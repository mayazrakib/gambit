import hashlib
import json
import shutil
import threading
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from queue import Empty, LifoQueue
from time import monotonic
from uuid import uuid4

import chess

from gambit.configuration import Configuration
from gambit.contracts import AnalysisMetrics, EngineIdentity, GameJob, PositionEvidence
from gambit.engine import StockfishClient, parse_board, parse_move
from gambit.games import analyze_board, analyze_game, review_game
from gambit.storage import Store
from gambit.tablebases import Tablebases

PROFILES = {"instant": (12000, 1), "quick": (100000, 3), "deep": (1000000, 3),}

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
        self.background_slots = threading.BoundedSemaphore(max(
            1,
            configuration.worker_count - 1,
        ),)
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
        key = (board.root().fen(), board.fen(), tuple((move.uci() for move in board.move_stack),), multipv, nodes, root_moves)
        pending_key = (key, id(cancellation,) if cancellation is not None else None)
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
                while not self.background_slots.acquire(timeout=0.05,):
                    if cancellation is not None and cancellation.is_set():
                        raise InterruptedError("Analysis was cancelled.",)

                    if monotonic() - started > 30:
                        raise TimeoutError("The background analysis queue timed out.",)

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
                self.background_slots.release()

            with self.lock:
                self.pending.pop(
                    pending_key,
                    None,
                )
                event.set()

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
        self.executor = ThreadPoolExecutor(max_workers=2,)
        self.lock = threading.Lock()
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

    def evaluate(
        self,
        fen: str,
        profile: str = "quick",
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
        self.store.put(
            "analysis",
            analysis["id"],
            analysis,
            is_immutable=True,
        )

        return analysis

    def evaluate_move(
        self,
        fen: str,
        move: str,
        profile: str = "quick",
        history: list[str] | None = None,
    ) -> dict:
        from gambit.assessment import assess_move, build_board

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
            ),),
        }

    def start_job(
        self,
        pgn: str,
        should_review: bool = True,
    ) -> GameJob:
        from gambit.games import parse_game
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

                checkpoint_key = hashlib.sha256(json.dumps([job_id, fingerprint, board.root().fen(), board.fen(), [move.uci() for move in board.move_stack], multipv, nodes,],).encode(),).hexdigest()
                checkpoint = service.store.get(
                    "checkpoint",
                    checkpoint_key,
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
