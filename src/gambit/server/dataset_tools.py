import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from uuid import uuid4

class DatasetJobs:
    def __init__(
        self,
        runtime,
    ) -> None:
        self.runtime = runtime

        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="gambit-data",
        )

        self.lock = threading.RLock()
        self.job = None
        self.future = None

    def get_status(self,) -> dict[
        str,
        object,
    ]:
        with self.lock:
            return {"schema_version": 1, "job": dict(self.job,) if self.job else None,}

    def start_job(
        self,
        username: str,
        should_refresh: bool,
        should_download: bool,
        kinds: list[str] | None,
    ) -> dict[
        str,
        object,
    ]:
        if not username or len(username,) > 100 or not all((character.isalnum() or character in "_-" for character in username),):
            raise ValueError("The chess account name is invalid.",)

        with self.lock:
            if self.future is not None and not self.future.done():
                raise ValueError("A dataset job is already active. Read its status or cancel it.",)

            self.job = {"id": str(uuid4(),), "status": "queued", "username": username,}
            self.runtime.get_datasets().cancel_event.clear()

            self.future = self.executor.submit(
                self.run_job,
                username,
                should_refresh,
                should_download,
                kinds,
            )

            return self.get_status()

    def run_job(
        self,
        username: str,
        should_refresh: bool,
        should_download: bool,
        kinds: list[str] | None,
    ) -> None:
        with self.lock:
            if self.job["status"] == "cancellation requested":
                self.job["status"] = "cancelled"

                return

            self.job["status"] = "running"

        try:
            service = self.runtime.get_datasets()

            if should_download and kinds == ["personal",]:
                report = service.sync_games(
                    username,
                    should_refresh,
                )
            elif should_download:
                report = service.sync_data(
                    username,
                    should_refresh,
                )
            else:
                report = service.import_sources(
                    username,
                    kinds,
                )

            with self.lock:
                if self.job["status"] != "cancellation requested":
                    self.job.update(
                        status="completed",
                        result=report,
                    )
                else:
                    self.job["status"] = "cancelled"
        except Exception as error:
            with self.lock:
                self.job.update(
                    status="cancelled" if self.job["status"] == "cancellation requested" else "failed",
                    error=str(error,),
                )

    def cancel_job(self,) -> dict[
        str,
        object,
    ]:
        with self.lock:
            if self.future is not None and not self.future.done():
                self.job["status"] = "cancellation requested"
                self.runtime.get_datasets().cancel_data()

            return self.get_status()

    def close(self,) -> None:
        self.cancel_job()

        self.executor.shutdown(
            wait=True,
            cancel_futures=True,
        )

def register_dataset_tools(
    server,
    owner,
) -> None:
    @server.tool(description="Start, import, inspect, or cancel bounded local chess data synchronization. Downloads run outside tutoring workers.",)
    def manage_chess_data(
        action: Literal[
            "status",
            "sync",
            "sync_games",
            "import",
            "cancel",
        ] = "status",
        username: str = "mayazrakib",
        should_refresh: bool = False,
        kinds: list[str] | None = None,
    ) -> dict[
        str,
        object,
    ]:
        runtime = owner.get_runtime()

        if action == "status":
            return {**runtime.data_jobs.get_status(), **runtime.get_datasets().get_status(),}

        if action in ("sync", "sync_games", "import"):
            return runtime.data_jobs.start_job(
                username,
                should_refresh,
                action != "import",
                ["personal",] if action == "sync_games" else kinds,
            )

        if action == "cancel":
            return runtime.data_jobs.cancel_job()

        raise ValueError("Data action must be status, sync, sync_games, import, or cancel.",)

    @server.tool(description="Retrieve one attributed local game and its PGN after selecting a search result.",)
    def get_chess_game(game_id: str,) -> dict[
        str,
        object,
    ]:
        game = owner.get_runtime().get_corpus().get_game(game_id,)

        if game is None:
            raise ValueError("The local chess game is unavailable.",)

        return game
