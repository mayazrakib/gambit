import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import chess
import pytest

from gambit.engine.analysis import AnalysisService, BackgroundExecutor, EnginePool
from gambit.engine.client import (
    REQUEST_CONTEXT,
    RequestContext,
    check_request_active,
    execute_engine_request,
)
from gambit.game.assessment import assess_move
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store

class CountingPool(EnginePool,):
    def __init__(
        self,
        configuration,
    ):
        super().__init__(configuration,)
        self.searches = 0

    def analyze(
        self,
        board,
        multipv,
        nodes,
        **options,
    ):
        check_request_active(options.get("cancellation",),)
        self.searches += 1
        move = next(iter(board.legal_moves,),)

        if options.get("root_moves",):
            move = chess.Move.from_uci(options["root_moves"][0],)

        return [{"centipawns": 20, "mate_in": None, "pv": [move,], "depth": 10, "actual_nodes": nodes,},]

def test_durable_evidence_survives_restart_and_separates_history(tmp_path,):
    database_path = str(tmp_path / "evidence.sqlite3",)
    configuration = Configuration()
    store = Store(database_path,)
    pool = CountingPool(configuration,)

    first_service = AnalysisService(
        configuration,
        store,
        pool,
    )

    first = first_service.evaluate(chess.STARTING_FEN,)
    first_service.close()
    store.close()
    store = Store(database_path,)

    second_service = AnalysisService(
        configuration,
        store,
        pool,
    )

    try:
        second = second_service.evaluate(chess.STARTING_FEN,)
        assert second["id"] == first["id"]
        assert pool.searches == 1

        historical = second_service.evaluate(
            chess.STARTING_FEN,
            moves=[],
        )

        assert historical["id"] != first["id"]
        assert historical["has_complete_history"]
        assert store.count_records("analysis",) == 2
    finally:
        second_service.close()
        store.close()
        pool.close()

def test_changed_engine_configuration_cannot_reuse_evidence(tmp_path,):
    store = Store(str(tmp_path / "evidence.sqlite3",),)
    first_configuration = Configuration(instant_nodes=100,)
    second_configuration = Configuration(instant_nodes=200,)
    first_pool = CountingPool(first_configuration,)
    second_pool = CountingPool(second_configuration,)

    first_service = AnalysisService(
        first_configuration,
        store,
        first_pool,
    )

    second_service = AnalysisService(
        second_configuration,
        store,
        second_pool,
    )

    try:
        first = first_service.evaluate(chess.STARTING_FEN,)
        second = second_service.evaluate(chess.STARTING_FEN,)
        assert first["id"] != second["id"]
        assert first_pool.searches == second_pool.searches == 1
    finally:
        first_service.close()
        second_service.close()
        first_pool.close()
        second_pool.close()
        store.close()

def test_concurrent_evidence_publishes_once():
    store = Store(":memory:",)
    configuration = Configuration()
    pool = CountingPool(configuration,)

    service = AnalysisService(
        configuration,
        store,
        pool,
    )

    try:
        with ThreadPoolExecutor(max_workers=8,) as executor:
            futures = [executor.submit(
                service.evaluate,
                chess.STARTING_FEN,
            ) for _ in range(8,)]

            results = [future.result(timeout=5,) for future in futures]

        assert len({result["id"] for result in results},) == 1
        assert pool.searches == 1
        assert store.count_records("analysis",) == 1
    finally:
        service.close()
        pool.close()
        store.close()

@pytest.mark.asyncio
async def test_cancelled_async_request_stops_running_operation():
    entered = threading.Event()
    exited = threading.Event()

    def run_operation():
        context = REQUEST_CONTEXT.get()
        entered.set()

        try:
            assert context.cancellation.wait(5,)
            check_request_active()
        finally:
            exited.set()

    task = asyncio.create_task(execute_engine_request(run_operation,),)

    assert await asyncio.to_thread(
        entered.wait,
        3,
    )

    task.cancel()

    with pytest.raises(asyncio.CancelledError,):
        await task

    assert await asyncio.to_thread(
        exited.wait,
        1,
    )

@pytest.mark.asyncio
async def test_expired_deadline_starts_no_search():
    token = REQUEST_CONTEXT.set(RequestContext(
        threading.Event(),
        monotonic() - 1,
    ),)

    invoked = threading.Event()

    try:
        with pytest.raises(
            TimeoutError,
            match="deadline",
        ):
            await execute_engine_request(invoked.set,)

        assert not invoked.is_set()
    finally:
        REQUEST_CONTEXT.reset(token,)

def test_automatic_background_disabled_for_one_worker():
    executor = BackgroundExecutor(Configuration(worker_count=1,),)

    try:
        with pytest.raises(
            RuntimeError,
            match="background worker",
        ):
            executor.submit(
                lambda: 1,
                is_automatic=True,
            )

        assert executor.submit(lambda: 2,).result(timeout=1,) == 2
    finally:
        executor.shutdown()

def test_anticipation_is_bounded_and_cancels_before_publishing():
    executor = BackgroundExecutor(Configuration(worker_count=2,),)
    entered = threading.Barrier(3,)
    release = threading.Event()
    was_invoked = threading.Event()
    cancellation = threading.Event()

    def occupy_worker(should_publish,):
        entered.wait(timeout=3,)
        assert release.wait(5,)
        check_request_active()

        if should_publish:
            was_invoked.set()

    first = executor.submit(
        occupy_worker,
        False,
        is_anticipation=True,
    )

    second = executor.submit(
        occupy_worker,
        True,
        cancellation=cancellation,
        is_anticipation=True,
    )

    entered.wait(timeout=3,)

    try:
        with pytest.raises(
            RuntimeError,
            match="two anticipated",
        ):
            executor.submit(
                lambda: None,
                is_anticipation=True,
            )

        cancellation.set()
        release.set()
        first.result(timeout=1,)

        with pytest.raises(InterruptedError,):
            second.result(timeout=1,)

        assert not was_invoked.is_set()
    finally:
        release.set()
        executor.shutdown()

def test_shared_candidate_searches_feed_assessment_without_extra_work():
    configuration = Configuration()
    pool = CountingPool(configuration,)

    try:
        board = chess.Board()

        evidence = pool.analyze_candidates(
            board,
            ["e4", "d4", "e4",],
            configuration.instant_nodes,
        )

        searches = pool.searches

        assessment = assess_move(
            pool,
            chess.STARTING_FEN,
            "e4",
            baseline_lines={configuration.instant_nodes: evidence["best"],},
            candidate_lines={configuration.instant_nodes: evidence["candidates"]["e2e4"],},
        )

        assert assessment.verified.move_uci == "e2e4"
        assert pool.searches == searches
        assert searches <= 3
    finally:
        pool.close()

def test_deadline_stops_and_drains_engine_before_reuse(monkeypatch,):
    from gambit.engine.client import StockfishClient

    engine = StockfishClient(Configuration(),)
    original_send = engine.send

    context = RequestContext(
        threading.Event(),
        monotonic() + 30,
    )

    token = REQUEST_CONTEXT.set(context,)

    def send_and_expire(command,):
        original_send(command,)

        if command.startswith("go ",):
            object.__setattr__(
                context,
                "deadline",
                monotonic() - 1,
            )

    monkeypatch.setattr(
        engine,
        "send",
        send_and_expire,
    )

    try:
        with pytest.raises(
            TimeoutError,
            match="deadline",
        ):
            engine.analyze(
                chess.Board(),
                1,
                100000,
            )
    finally:
        REQUEST_CONTEXT.reset(token,)

        monkeypatch.setattr(
            engine,
            "send",
            original_send,
        )

    try:
        assert engine.analyze(
            chess.Board(),
            1,
            1000,
        )
    finally:
        engine.close()

def test_background_search_admission_yields_between_game_positions():
    configuration = Configuration(worker_count=2,)
    pool = EnginePool(configuration,)
    executor = BackgroundExecutor(configuration,)
    entered = threading.Event()
    release = threading.Event()
    searched_nodes = []

    class OrderedClient:
        name = "Ordered test engine"
        version = "test"

        def analyze(
            self,
            board,
            multipv,
            nodes,
            **options,
        ):
            if nodes == 10:
                entered.set()
                assert release.wait(5,)

            searched_nodes.append(nodes,)

            return [{"centipawns": 0, "mate_in": None, "pv": [next(iter(board.legal_moves,),),],},]

        def close(self,):
            return None

    pool.clients = [OrderedClient(), OrderedClient(),]

    while not pool.available.empty():
        pool.available.get_nowait()

    for client in pool.clients:
        pool.available.put(client,)

    def review_two_positions():
        pool.analyze(
            chess.Board(),
            1,
            10,
        )

        pool.analyze(
            chess.Board(),
            1,
            30,
        )

    game = executor.submit(review_two_positions,)
    assert entered.wait(2,)

    refinement = executor.submit(
        pool.analyze,
        chess.Board(),
        1,
        20,
    )

    try:
        with pool.background_condition:
            assert pool.background_condition.wait_for(
                lambda: len(pool.background_waiters,) == 1,
                timeout=2,
            )

        release.set()
        game.result(timeout=3,)
        refinement.result(timeout=3,)
        assert searched_nodes == [10, 20, 30,]
    finally:
        release.set()
        executor.shutdown()
        pool.close()

def test_cancelled_search_cannot_publish_durable_evidence():
    store = Store(":memory:",)
    configuration = Configuration()
    entered = threading.Event()
    release = threading.Event()
    cancellation = threading.Event()

    class PausedPool(CountingPool,):
        def analyze(
            self,
            board,
            multipv,
            nodes,
            **options,
        ):
            entered.set()
            assert release.wait(3,)

            return super().analyze(
                board,
                multipv,
                nodes,
                **options,
            )

    pool = PausedPool(configuration,)

    service = AnalysisService(
        configuration,
        store,
        pool,
    )

    try:
        with ThreadPoolExecutor(max_workers=1,) as executor:
            future = executor.submit(
                service.evaluate,
                chess.STARTING_FEN,
                cancellation=cancellation,
            )

            assert entered.wait(2,)
            cancellation.set()
            release.set()

            with pytest.raises(InterruptedError,):
                future.result(timeout=2,)

        assert store.count_records("analysis",) == 0
        assert not service.evidence_pending
    finally:
        release.set()
        service.close()
        pool.close()
        store.close()

def test_whole_game_reviews_reuse_matching_searches_across_jobs_and_restart(tmp_path,):
    database_path = str(tmp_path / "games.sqlite3",)
    configuration = Configuration()
    pool = CountingPool(configuration,)
    store = Store(database_path,)

    service = AnalysisService(
        configuration,
        store,
        pool,
    )

    try:
        first = service.start_job("1. e4 e5 *",)
        service.jobs[first["id"]][0].result(timeout=30,)

        assert store.get(
            "job",
            first["id"],
        )["status"] == "completed"

        searches = pool.searches
        assert searches > 0
        service.close()
        store.close()
        store = Store(database_path,)

        service = AnalysisService(
            configuration,
            store,
            pool,
        )

        second = service.start_job("1. e4 e5 *",)
        service.jobs[second["id"]][0].result(timeout=30,)

        report = store.get(
            "job",
            second["id"],
        )

        assert report["status"] == "completed"
        assert report["reused_searches"] == report["completed_searches"]
        assert pool.searches == searches
        changed = service.start_job("1. d4 d5 *",)
        service.jobs[changed["id"]][0].result(timeout=30,)

        assert store.get(
            "job",
            changed["id"],
        )["status"] == "completed"

        assert pool.searches > searches
    finally:
        service.close()
        store.close()
        pool.close()
