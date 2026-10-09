import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from gambit.api.contracts import ProgressiveStart, ProgressiveStatus
from gambit.game.assessment import build_board
from gambit.learning.training import validate_training_id

if TYPE_CHECKING:
    from gambit.engine.analysis import AnalysisService

@dataclass
class AnalysisRequest:
    request_id: str
    context_id: str
    fen: str
    history: list[str]
    cancellation: threading.Event
    status: str = "queued"
    evidence_id: str | None = None
    error: str | None = None
    future: Future | None = None

class ProgressiveAnalysis:
    def __init__(
        self,
        analysis: "AnalysisService",
    ) -> None:
        self.analysis = analysis
        self.lock = threading.RLock()
        self.requests: dict[
            str,
            AnalysisRequest,
        ] = {}
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="gambit-progressive",
        )

    def start(
        self,
        context_id: str,
        fen: str,
        history: list[str] | None = None,
    ) -> ProgressiveStart:
        validate_training_id(context_id,)
        board = build_board(
            fen,
            history,
        )

        with self.lock:
            for request in self.requests.values():
                if request.context_id == context_id:
                    request.cancellation.set()

            if len(self.requests,) >= 32:
                completed = [key for key, request in self.requests.items() if request.status in ("completed", "cancelled", "failed")]

                for key in completed:
                    del self.requests[key]

            if len(self.requests,) >= 32:
                raise RuntimeError("The progressive analysis queue is full.",)

            request = AnalysisRequest(
                str(uuid4(),),
                context_id,
                fen,
                history or [],
                threading.Event(),
                "preliminary",
            )
            self.requests[request.request_id] = request

        try:
            preliminary = self.analysis.evaluate(
                fen,
                "instant",
                history,
                request.cancellation,
            )
        except BaseException:
            with self.lock:
                request.status = "failed"

            raise

        with self.lock:
            if request.cancellation.is_set():
                request.status = "cancelled"
            else:
                request.status = "queued"
                request.future = self.executor.submit(
                    self.run,
                    request,
                )

        return {"schema_version": 1, "request_id": request.request_id, "context_id": context_id, "position_fen": board.fen(), "status": request.status, "preliminary": preliminary,}

    def run(
        self,
        request: AnalysisRequest,
    ) -> None:
        try:
            with self.lock:
                request.status = "running"

            evidence = self.analysis.evaluate(
                request.fen,
                "deep",
                request.history,
                request.cancellation,
                True,
            )

            with self.lock:
                request.status = "cancelled" if request.cancellation.is_set() else "completed"
                request.evidence_id = evidence["id"] if request.status == "completed" else None
        except InterruptedError:
            with self.lock:
                request.status = "cancelled"
        except Exception:
            logging.getLogger(__name__,).exception("Progressive analysis failed.",)

            with self.lock:
                request.status = "failed"
                request.error = "Progressive analysis failed. Check engine health and retry."

    def get_status(
        self,
        request_id: str,
        should_cancel: bool = False,
    ) -> ProgressiveStatus:
        with self.lock:
            request = self.requests.get(request_id,)

            if request is None:
                raise ValueError("The analysis request is unavailable or expired.",)

            if should_cancel:
                request.cancellation.set()

            is_stale = request.cancellation.is_set()

            return {"schema_version": 1, "request_id": request_id, "context_id": request.context_id, "status": "cancelled" if is_stale else request.status, "analysis_id": None if is_stale else request.evidence_id, "error": request.error,}

    def close(self,) -> None:
        with self.lock:
            for request in self.requests.values():
                request.cancellation.set()

        self.executor.shutdown(
            wait=True,
            cancel_futures=True,
        )
