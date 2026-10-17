import hashlib
import json
import os
import shutil
import threading
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from queue import Empty, LifoQueue
from time import monotonic
from uuid import uuid4

import chess

from gambit.api.contracts import AnalysisMetrics, EngineIdentity, GameJob, PositionEvidence
from gambit.engine.client import (
    REQUEST_CONTEXT,
    RequestContext,
    StockfishClient,
    check_request_active,
    get_request_cancellation,
    parse_board,
    parse_move,
)
from gambit.game.service import analyze_board, analyze_game, review_game
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.tablebases import Tablebases

PROFILES = {"instant": (12000, 1), "quick": (100000, 3), "deep": (1000000, 3),}
SPOKEN_VARIATION_PLIES = 4

class BackgroundExecutor:
    def __init__(
        self,
        configuration: Configuration,
    ) -> None:
        self.configuration = configuration

        self.executor = ThreadPoolExecutor(
            max_workers=configuration.max_jobs + 2,
            thread_name_prefix="gambit-background",
        )

        self.slots = threading.BoundedSemaphore(configuration.max_jobs + 2,)
        self.anticipation_slots = threading.BoundedSemaphore(2,)
        self.lock = threading.Lock()
        self.cancellations: set[threading.Event] = set()

    def submit(
        self,
        operation,
        *args,
        cancellation: threading.Event | None = None,
        is_automatic: bool = False,
        is_anticipation: bool = False,
        **kwargs,
    ) -> Future:
        if is_automatic and self.configuration.worker_count == 1:
            raise RuntimeError("Automatic background analysis requires an available background worker.",)

        if not self.slots.acquire(blocking=False,):
            raise RuntimeError("The background analysis queue is full.",)

        has_anticipation_slot = False

        if is_anticipation:
            has_anticipation_slot = self.anticipation_slots.acquire(blocking=False,)

            if not has_anticipation_slot:
                self.slots.release()

                raise RuntimeError("At most two anticipated branches may be queued or running.",)

        cancellation = cancellation if cancellation is not None else threading.Event()

        with self.lock:
            self.cancellations.add(cancellation,)

        def run_operation():
            context_token = REQUEST_CONTEXT.set(RequestContext(
                cancellation,
                is_background=True,
            ),)

            try:
                check_request_active()

                return operation(
                    *args,
                    **kwargs,
                )
            finally:
                REQUEST_CONTEXT.reset(context_token,)

        def release_slot(completed,):
            with self.lock:
                self.cancellations.discard(cancellation,)

            self.slots.release()

            if has_anticipation_slot:
                self.anticipation_slots.release()

        try:
            future = self.executor.submit(run_operation,)
        except RuntimeError:
            release_slot(None,)

            raise

        future.add_done_callback(release_slot,)

        return future

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        with self.lock:
            for cancellation in self.cancellations:
                cancellation.set()

        self.executor.shutdown(
            wait=wait,
            cancel_futures=cancel_futures,
        )

def compact_position_evidence(evidence: PositionEvidence,) -> PositionEvidence:
    return {
        **evidence,
        "is_compact": True,
        "principal_variations": [
            {
                **variation,
                "moves_uci": variation["moves_uci"][:SPOKEN_VARIATION_PLIES],
                "moves_san": variation["moves_san"][:SPOKEN_VARIATION_PLIES],
            }
            for variation in evidence["principal_variations"]
        ],
    }

class EnginePool:
    def __init__(
        self,
        configuration: Configuration,
    ) -> None:
        self.configuration = configuration
        self.clients = [StockfishClient(configuration,) for _ in range(configuration.worker_count,)]
        self.available: LifoQueue[StockfishClient] = LifoQueue(configuration.worker_count,)
        self.lock = threading.Lock()

        self.cache: OrderedDict[
            tuple,
            list,
        ] = OrderedDict()

        self.pending: dict[
            tuple,
            threading.Event,
        ] = {}

        self.name = "Stockfish"
        self.version = None
        self.is_closed = False
        self.background_condition = threading.Condition()
        self.background_waiters = deque()
        self.active_background_searches = 0
        self.samples = deque(maxlen=512,)
        self.cache_hits = 0
        self.search_count = 0

        for client in self.clients:
            self.available.put(client,)

    def analyze(
        self,
        board: chess.Board,
        multipv: int,
        nodes: int,
        *,
        root_moves: tuple[
            str,
            ...,
        ] = (),
        cancellation: threading.Event | None = None,
        is_background: bool = False,
    ) -> list:
        context = REQUEST_CONTEXT.get()
        is_background = is_background or (context is not None and context.is_background)
        cancellation_identity = (id(cancellation,) if cancellation is not None else None, id(context,) if context is not None else None)
        cancellation = get_request_cancellation(cancellation,)
        key = (board.root().fen(), board.fen(), tuple((move.uci() for move in board.move_stack),), multipv, nodes, root_moves)
        pending_key = (key, cancellation_identity)
        started = monotonic()

        with self.lock:
            if cancellation is not None and cancellation.is_set():
                raise InterruptedError("Analysis was cancelled.",)

            if self.is_closed:
                raise RuntimeError("The engine pool is closed.",)

            if key in self.cache:
                self.cache_hits += 1
                self.cache.move_to_end(key,)

                return self.cache[key]

            if pending_key in self.pending:
                event = self.pending[pending_key]
                is_owner = False
            else:
                if len(self.pending,) >= 32:
                    raise RuntimeError("The engine request queue is full.",)

                event = threading.Event()
                self.pending[pending_key] = event
                is_owner = True

        if not is_owner:
            while not event.wait(0.05,):
                if cancellation is not None and cancellation.is_set():
                    raise InterruptedError("Analysis was cancelled.",)

                if monotonic() - started > 65:
                    raise TimeoutError("The shared engine search timed out.",)

            with self.lock:
                if key not in self.cache:
                    raise RuntimeError("The shared engine search failed.",)

                return self.cache[key]

        client = None
        has_background_slot = False

        try:
            if is_background:
                self.acquire_background_slot(
                    cancellation,
                    started,
                )

                has_background_slot = True

            while client is None:
                if cancellation is not None and cancellation.is_set():
                    raise InterruptedError("Analysis was cancelled.",)

                if monotonic() - started >= 30:
                    raise TimeoutError("No engine worker became available within 30 seconds.",)

                try:
                    client = self.available.get(timeout=0.05,)
                except Empty:
                    continue

            queue_ms = (monotonic() - started) * 1000

            if root_moves or cancellation is not None:
                lines = client.analyze(
                    board,
                    multipv,
                    nodes,
                    root_moves=root_moves,
                    cancellation=cancellation,
                )
            else:
                lines = client.analyze(
                    board,
                    multipv,
                    nodes,
                )

            with self.lock:
                self.search_count += 1
                self.samples.append((queue_ms, (monotonic() - started) * 1000),)
                self.name = client.name
                self.version = client.version
                self.cache[key] = lines

                while len(self.cache,) > self.configuration.cache_capacity:
                    self.cache.popitem(last=False,)

            return lines
        except Empty as exception:
            raise TimeoutError("No engine worker became available within 30 seconds.",) from exception
        finally:
            if client is not None:
                self.available.put(client,)

            if has_background_slot:
                with self.background_condition:
                    self.active_background_searches -= 1
                    self.background_condition.notify_all()

            with self.lock:
                self.pending.pop(
                    pending_key,
                    None,
                )

                event.set()

    def acquire_background_slot(
        self,
        cancellation,
        started: float,
    ) -> None:
        waiter = object()

        background_limit = max(
            1,
            self.configuration.worker_count - 1,
        )

        with self.background_condition:
            self.background_waiters.append(waiter,)
            self.background_condition.notify_all()

            try:
                while True:
                    if cancellation.is_set():
                        raise InterruptedError("Analysis was cancelled.",)

                    if monotonic() - started > 30:
                        raise TimeoutError("The background analysis queue timed out.",)

                    if self.background_waiters[0] is waiter and self.active_background_searches < background_limit:
                        self.background_waiters.popleft()
                        self.active_background_searches += 1
                        self.background_condition.notify_all()

                        return

                    self.background_condition.wait(timeout=0.025,)
            finally:
                if waiter in self.background_waiters:
                    self.background_waiters.remove(waiter,)
                    self.background_condition.notify_all()

    def get_metrics(self,) -> AnalysisMetrics:
        with self.lock:
            latencies = sorted((sample[1] for sample in self.samples),)
            queues = sorted((sample[0] for sample in self.samples),)

            return {
                "schema_version": 1,
                "search_count": self.search_count,
                "cache_hits": self.cache_hits,
                "pending_count": len(self.pending,),
                "sample_count": len(latencies,),
                "latency_p50_ms": latencies[len(latencies,) // 2] if latencies else None,
                "latency_p95_ms": latencies[min(
                    len(latencies,) - 1,
                    int(len(latencies,) * 0.95,),
                )] if latencies else None,
                "queue_p95_ms": queues[min(
                    len(queues,) - 1,
                    int(len(queues,) * 0.95,),
                )] if queues else None,
                "has_reserved_interactive_capacity": self.configuration.worker_count > 1,
            }

    def analyze_candidates(
        self,
        board: chess.Board,
        moves: list[str],
        nodes: int,
        *,
        cancellation: threading.Event | None = None,
    ) -> dict:
        candidates = [parse_move(
            board,
            move,
        ).uci() for move in moves]

        best = self.analyze(
            board,
            1,
            nodes,
            cancellation=cancellation,
        )[0]

        lines = {best["pv"][0].uci(): best,}

        for move in candidates:
            check_request_active(cancellation,)

            if move not in lines:
                lines[move] = self.analyze(
                    board,
                    1,
                    nodes,
                    root_moves=(move,),
                    cancellation=cancellation,
                )[0]

        return {"best": best, "candidates": {move: lines[move] for move in candidates},}

    def get_metadata(self,) -> EngineIdentity:
        return {
            "name": self.name,
            "version": self.version,
            "binary_sha256": next(
                (client.binary_digest for client in self.clients if client.binary_digest),
                None,
            ),
            "worker_count": len(self.clients,),
            "threads_per_worker": self.configuration.threads_per_worker,
            "hash_mb_per_worker": self.configuration.hash_mb_per_worker,
            "is_reproducible": self.configuration.is_reproducible,
        }

    def warm_up(self,) -> None:
        def start_client(client: StockfishClient,) -> None:
            with client.lock:
                if client.process is None:
                    try:
                        client.start()
                    except BaseException:
                        client.stop()

                        raise

        with ThreadPoolExecutor(max_workers=len(self.clients,),) as executor:
            futures = [executor.submit(
                start_client,
                client,
            ) for client in self.clients]

            for future in futures:
                future.result()

    def close(self,) -> None:
        with self.lock:
            self.is_closed = True

        for client in self.clients:
            client.close()

class AnalysisService:
    def __init__(
        self,
        configuration: Configuration,
        store: Store,
        engine: EnginePool | None = None,
    ) -> None:
        self.configuration = configuration
        self.store = store
        self.engine = engine or EnginePool(configuration,)
        self.should_close_engine = engine is None
        self.tablebases = Tablebases(configuration.syzygy_path,)
        self.background_executor = BackgroundExecutor(configuration,)
        self.executor = self.background_executor
        self.lock = threading.Lock()

        self.evidence_ids: OrderedDict[
            tuple,
            str,
        ] = OrderedDict()

        self.evidence_pending: dict[
            tuple,
            threading.Event,
        ] = {}

        self.engine_fingerprint: str | None = None

        self.jobs: dict[
            str,
            tuple,
        ] = {}

        self.interrupted_jobs: set[str] = set()

        with store.lock:
            rows = store.connection.execute("""
                SELECT payload FROM record
                WHERE collection = 'job' AND json_extract(payload, '$.status') IN ('queued', 'running', 'interrupted')

                ORDER BY id
                LIMIT 1000
            """,).fetchall()

        for row in rows:
            job = json.loads(row[0],)

            if job["status"] in ("queued", "running"):
                job.update(
                    status="interrupted",
                    error="The previous server stopped before completion.",
                )

                store.put(
                    "job",
                    job["id"],
                    job,
                )

            if "pgn" in job and len(self.jobs,) < configuration.max_jobs:
                self.resume_job(job["id"],)

    def submit_background(
        self,
        operation,
        *args,
        **kwargs,
    ) -> Future:
        return self.background_executor.submit(
            operation,
            *args,
            **kwargs,
        )

    def get_engine_fingerprint(self,) -> str:
        with self.lock:
            if self.engine_fingerprint is not None:
                return self.engine_fingerprint

            executable = shutil.which(self.configuration.engine_path,)
            binary_digest = self.engine.get_metadata().get("binary_sha256",)

            if executable is not None and binary_digest is None:
                with Path(executable,).open("rb",) as binary_file:
                    binary_digest = hashlib.file_digest(
                        binary_file,
                        "sha256",
                    ).hexdigest()

            settings = {
                name: getattr(
                    self.configuration,
                    name,
                )
                for name in (
                    "engine_path", "threads_per_worker", "hash_mb_per_worker", "is_reproducible",
                    "syzygy_path", "instant_nodes", "quick_nodes", "deep_nodes", "candidate_count",
                    "instant_search_time_ms", "quick_search_time_ms", "search_time_ms", "search_depth",
                )
            }

            tablebase_files = []

            for directory in self.configuration.syzygy_path.split(os.pathsep,):
                path = Path(directory,).expanduser()

                if not directory or not path.is_dir():
                    continue

                for tablebase in path.iterdir():
                    if tablebase.suffix in (".rtbw", ".rtbz"):
                        metadata = tablebase.stat()
                        tablebase_files.append((str(tablebase,), metadata.st_size, metadata.st_mtime_ns),)

            identity = {"schema_version": 2, "binary_sha256": binary_digest, "configuration": settings, "tablebases": sorted(tablebase_files,),}

            self.engine_fingerprint = hashlib.sha256(json.dumps(
                identity,
                sort_keys=True,
            ).encode(),).hexdigest()

            return self.engine_fingerprint

    def evaluate(
        self,
        fen: str,
        profile: str = "instant",
        moves: list[str] | None = None,
        cancellation: threading.Event | None = None,
        is_background: bool = False,
    ) -> PositionEvidence:
        check_request_active(cancellation,)

        fingerprint = hashlib.sha256(json.dumps(
            [self.get_engine_fingerprint(), fen, moves, profile,],
            sort_keys=True,
        ).encode(),).hexdigest()

        while True:
            cached = self.store.get_analysis_cache(fingerprint,)

            if cached is not None:
                check_request_active(cancellation,)

                return cached

            with self.lock:
                pending = self.evidence_pending.get(fingerprint,)

                if pending is None:
                    pending = threading.Event()
                    self.evidence_pending[fingerprint] = pending
                    is_owner = True
                else:
                    is_owner = False

            if is_owner:
                break

            while not pending.wait(0.025,):
                check_request_active(cancellation,)

        try:
            cached = self.store.get_analysis_cache(fingerprint,)

            if cached is not None:
                check_request_active(cancellation,)

                return cached

            evidence = self.create_evidence(
                fen,
                profile,
                moves,
                cancellation,
                is_background,
            )

            check_request_active(cancellation,)

            return self.store.put_analysis_cache(
                fingerprint,
                evidence,
                before_commit=lambda: check_request_active(cancellation,),
            )
        finally:
            with self.lock:
                self.evidence_pending.pop(
                    fingerprint,
                    None,
                )

                pending.set()

    def create_evidence(
        self,
        fen: str,
        profile: str = "instant",
        moves: list[str] | None = None,
        cancellation: threading.Event | None = None,
        is_background: bool = False,
    ) -> PositionEvidence:
        if profile not in PROFILES:
            raise ValueError("Analysis profile must be instant, quick, or deep.",)

        board = parse_board(fen,)

        if len(moves or [],) > 1024:
            raise ValueError("A position history may contain at most 1024 moves.",)

        for move in moves or []:
            board.push(parse_move(
                board,
                move,
            ),)

        nodes = getattr(
            self.configuration,
            profile + "_nodes",
        )

        multipv = 1 if profile == "instant" else self.configuration.candidate_count
        started = monotonic()
        pool = self.engine
        evidence_key = (fen, tuple(moves or [],), moves is not None, profile)

        if cancellation is not None and cancellation.is_set():
            raise InterruptedError("Analysis was cancelled.",)

        with self.lock:
            evidence_id = self.evidence_ids.get(evidence_key,)

            if evidence_id is not None:
                cached = self.store.get(
                    "analysis",
                    evidence_id,
                )

                if cached is not None:
                    self.evidence_ids.move_to_end(evidence_key,)

                    return cached

                del self.evidence_ids[evidence_key]

        class RequestEngine:
            def analyze(
                self,
                board,
                multipv,
                nodes,
            ):
                return pool.analyze(
                    board,
                    multipv,
                    nodes,
                    cancellation=cancellation,
                    is_background=is_background,
                )

        if cancellation is not None and cancellation.is_set():
            raise InterruptedError("Analysis was cancelled.",)

        analysis = asdict(analyze_board(
            board,
            RequestEngine() if cancellation is not None or is_background else self.engine,
            nodes,
            multipv,
        ),)

        analysis.update({
            "id": str(uuid4(),),
            "schema_version": 1,
            "evidence_status": "preliminary" if profile != "deep" else "deeper search",
            "profile": profile,
            "score_perspective": "white",
            "configured_nodes": nodes,
            "elapsed_ms": round(
                (monotonic() - started) * 1000,
                2,
            ),
            "engine": self.engine.get_metadata(),
            "has_complete_history": moves is not None and fen == chess.STARTING_FEN,
            "history_scope": "from supplied root" if moves is not None else "position only",
        },)

        check_request_active(cancellation,)

        with self.lock:
            self.evidence_ids[evidence_key] = analysis["id"]
            self.evidence_ids.move_to_end(evidence_key,)

            while len(self.evidence_ids,) > self.configuration.cache_capacity:
                self.evidence_ids.popitem(last=False,)

        return analysis

    def evaluate_move(
        self,
        fen: str,
        move: str,
        profile: str = "instant",
        history: list[str] | None = None,
    ) -> dict:
        from gambit.game.assessment import assess_move, build_board

        board = build_board(
            fen,
            history,
        )

        candidate = parse_move(
            board,
            move,
        )

        san = board.san(candidate,)

        before = self.evaluate(
            fen,
            profile,
            history,
        )

        after = self.evaluate(
            fen,
            profile,
            [*(history or []), candidate.uci(),],
        )

        before_cp = before["evaluation"]["centipawns"]
        after_cp = after["evaluation"]["centipawns"]
        loss = None

        if before_cp is not None and after_cp is not None:
            loss = max(
                0,
                (before_cp - after_cp) * (1 if board.turn else -1),
            )

        return {
            "move": {"san": san, "uci": candidate.uci(),},
            "before": before,
            "after": after,
            "centipawn_loss": loss,
            "schema_version": 1,
            "assessment": asdict(assess_move(
                self.engine,
                fen,
                move,
                history,
                profile=profile,
            ),),
        }

    def start_job(
        self,
        pgn: str,
        should_review: bool = True,
    ) -> GameJob:
        from gambit.game.service import parse_game
        parse_game(pgn,)

        with self.lock:
            active_count = sum((not future.done() for future, _ in self.jobs.values()),)

            if active_count >= self.configuration.max_jobs:
                raise RuntimeError("The analysis job queue is full.",)

            self.jobs = {key: pair for key, pair in self.jobs.items() if not pair[0].done()}
            job_id = str(uuid4(),)
            cancellation = threading.Event()
            job = {"id": job_id, "status": "queued", "completed_searches": 0, "pgn": pgn, "should_review": should_review, "schema_version": 1,}

            self.store.put(
                "job",
                job_id,
                job,
            )

            future = self.executor.submit(
                self.run_job,
                job_id,
                pgn,
                should_review,
                cancellation,
            )

            self.jobs[job_id] = (future, cancellation)

        return job

    def resume_job(
        self,
        job_id: str,
    ) -> GameJob:
        with self.lock:
            job = self.store.get(
                "job",
                job_id,
            )

            if job is None or job["status"] not in ("interrupted", "failed", "cancelled") or "pgn" not in job:
                raise ValueError("The job has no resumable input or is already active.",)

            if sum((not future.done() for future, _ in self.jobs.values()),) >= self.configuration.max_jobs:
                raise RuntimeError("The analysis job queue is full.",)

            cancellation = threading.Event()

            job.update(
                status="queued",
                error=None,
            )

            self.store.put(
                "job",
                job_id,
                job,
            )

            future = self.executor.submit(
                self.run_job,
                job_id,
                job["pgn"],
                job["should_review"],
                cancellation,
            )

            self.jobs[job_id] = (future, cancellation)

        return job

    def run_job(
        self,
        job_id: str,
        pgn: str,
        should_review: bool,
        cancellation: threading.Event,
    ) -> None:
        job = {"id": job_id, "status": "running", "completed_searches": 0, "pgn": pgn, "should_review": should_review, "schema_version": 1, "reused_searches": 0,}

        self.store.put(
            "job",
            job_id,
            job,
        )

        service = self
        executable = shutil.which(self.configuration.engine_path,)
        binary_digest = "unavailable"

        if executable:
            try:
                with Path(executable,).open("rb",) as engine_file:
                    binary_digest = hashlib.file_digest(
                        engine_file,
                        "sha256",
                    ).hexdigest()
            except OSError as exception:
                job.update(
                    status="failed",
                    error=f"The engine executable could not be fingerprinted: {exception}.",
                )

                self.store.put(
                    "job",
                    job_id,
                    job,
                )

                return

        fingerprint = json.dumps(
            {"engine": binary_digest, "configuration": asdict(self.configuration,),},
            sort_keys=True,
        )

        engine_metadata = self.engine.get_metadata()

        class JobEngine:
            name = "Stockfish"
            version = None
            configuration = service.configuration

            def analyze(
                self,
                board,
                multipv,
                nodes,
            ):
                if cancellation.is_set():
                    raise InterruptedError("Analysis was cancelled.",)

                position_identity = [board.root().fen(), board.fen(), [move.uci() for move in board.move_stack], multipv, nodes,]
                checkpoint_key = hashlib.sha256(json.dumps(["game search", evidence_fingerprint, *position_identity,],).encode(),).hexdigest()

                checkpoint = service.store.get(
                    "checkpoint",
                    checkpoint_key,
                )

                if checkpoint is None:
                    legacy_key = hashlib.sha256(json.dumps([job_id, fingerprint, *position_identity,],).encode(),).hexdigest()

                    checkpoint = service.store.get(
                        "checkpoint",
                        legacy_key,
                    )

                if checkpoint is not None:
                    engine_metadata.update(checkpoint.get(
                        "engine",
                        {},
                    ),)

                    lines = [{**line, "pv": [chess.Move.from_uci(move,) for move in line["pv"]],} for line in checkpoint["lines"]]
                    job["reused_searches"] += 1
                else:
                    lines = service.engine.analyze(
                        board,
                        multipv,
                        nodes,
                        cancellation=cancellation,
                        is_background=True,
                    )

                    engine_metadata.update(service.engine.get_metadata(),)

                    service.store.put(
                        "checkpoint",
                        checkpoint_key,
                        {
                            "id": checkpoint_key,
                            "job_id": job_id,
                            "engine": engine_metadata,
                            "lines": [{**line, "pv": [move.uci() for move in line["pv"]],} for line in lines],
                        },
                        is_immutable=True,
                    )

                self.name = engine_metadata["name"]
                self.version = engine_metadata["version"]
                job["completed_searches"] += 1

                service.store.put(
                    "job",
                    job_id,
                    job,
                )

                return lines

        try:
            evidence_fingerprint = self.get_engine_fingerprint()
            operation = review_game if should_review else analyze_game

            report = asdict(operation(
                pgn,
                JobEngine(),
            ),)

            if cancellation.is_set():
                raise InterruptedError("Analysis was cancelled.",)

            report["engine"].update(engine_metadata,)

            self.store.put(
                "analysis",
                job_id,
                report,
                is_immutable=True,
            )

            job.update(
                status="completed",
                analysis_id=job_id,
            )
        except InterruptedError:
            job.update(status="interrupted" if job_id in self.interrupted_jobs else "cancelled",)
        except Exception as exception:
            job.update(
                status="failed",
                error=str(exception,),
            )
        finally:
            self.store.put(
                "job",
                job_id,
                job,
            )

    def cancel_job(
        self,
        job_id: str,
    ) -> dict:
        with self.lock:
            pair = self.jobs.get(job_id,)

            if pair:
                pair[1].set()

        job = self.store.get(
            "job",
            job_id,
        )

        if job is None:
            raise ValueError("The analysis job does not exist.",)

        return job

    def close(self,) -> None:
        with self.lock:
            for job_id, (future, cancellation) in self.jobs.items():
                if not future.done() and not cancellation.is_set():
                    self.interrupted_jobs.add(job_id,)
                    cancellation.set()

        self.executor.shutdown(
            wait=True,
            cancel_futures=False,
        )

        if self.should_close_engine:
            self.engine.close()

        self.tablebases.close()
