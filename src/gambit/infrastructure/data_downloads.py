import argparse
import hashlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from gambit.infrastructure.data_capacity import RuntimeCapacity
from gambit.infrastructure.data_lock import acquire_file_lock

DATABASE_URL = "https://database.lichess.org/"

TABLEBASE_URL = "https://tablebase.lichess.ovh/tables/standard/"

CHUNK_BYTES = 1_048_576

SOURCE_LICENSES = {"puzzles": "CC0-1.0", "broadcast": "CC-BY-SA-4.0", "syzygy": "Syzygy tablebase data", "personal": "Chess.com public game archive",}

def open_request(
    url: str,
    headers: dict | None = None,
    method: str = "GET",
):
    request_headers = {"User-Agent": "Gambit/0.1 (personal chess tutoring)",}
    request_headers.update(headers or {},)

    return urllib.request.urlopen(
        urllib.request.Request(
            url,
            headers=request_headers,
            method=method,
        ),
        timeout=60,
    )

def read_metadata(url: str,) -> bytes:
    with open_request(url,) as response:
        content = response.read(4 * CHUNK_BYTES + 1,)

    if len(content,) > 4 * CHUNK_BYTES:
        raise ValueError("Dataset metadata exceeds its supported size.",)

    return content

def discover_sources(
    username: str = "mayazrakib",
    personal_sources: list[dict] | None = None,
) -> list[dict]:
    sources = [{"key": "puzzles", "kind": "puzzles", "url": DATABASE_URL + "lichess_db_puzzle.csv.zst", "filename": "lichess_db_puzzle.csv.zst",},]
    current_date = datetime.now(UTC,)
    month_index = current_date.year * 12 + current_date.month - 1

    for offset in range(
        1,
        13,
    ):
        year, month_zero = divmod(
            month_index - offset,
            12,
        )

        month = f"{year:04d}-{month_zero + 1:02d}"

        filename = f"lichess_db_broadcast_{month}.pgn.zst"

        sources.append({"key": f"broadcast-{month}", "kind": "broadcast", "url": DATABASE_URL + "broadcast/" + filename, "filename": filename,},)

    manifest = read_metadata(TABLEBASE_URL + "sha256",).decode()

    checksums = {line.split()[1]: line.split()[0] for line in manifest.splitlines() if len(line.split(),) == 2}

    for folder, suffix in (("3-4-5-wdl", "rtbw"), ("3-4-5-dtz", "rtbz")):
        listing = read_metadata(TABLEBASE_URL + folder + "/",).decode()

        filenames = sorted(set(re.findall(
            r'href="([A-Za-z0-9]+\.' + suffix + r')"',
            listing,
        ),),)

        if len(filenames,) != 145:
            raise RuntimeError("The expected complete three-to-five-piece Syzygy listing is unavailable.",)

        for filename in filenames:
            sources.append({"key": filename, "kind": "syzygy", "url": TABLEBASE_URL + folder + "/" + filename, "filename": filename, "sha256": checksums[filename],},)

    sources.extend(personal_sources if personal_sources is not None else discover_personal_sources(username,),)

    return sources

def discover_personal_sources(
    username: str,
    content: dict | None = None,
) -> list[dict]:
    username = username.lower()

    if not re.fullmatch(
        r"[a-z0-9_-]{1,100}",
        username,
    ):
        raise ValueError("The chess account name is invalid.",)

    prefix = "https://api.chess.com/pub/player/" + username + "/games/"
    archives = content if content is not None else json.loads(read_metadata(prefix + "archives",),)
    sources = []

    for url in archives["archives"]:
        if not isinstance(
            url,
            str,
        ) or not re.fullmatch(
            re.escape(prefix,) + r"[0-9]{4}/(?:0[1-9]|1[0-2])",
            url,
        ):
            raise ValueError("An archive URL has an unexpected origin or month.",)

        month = "-".join(url.split("/",)[-2:],)
        sources.append({"key": f"personal-{username}-{month}", "kind": "personal", "url": url, "filename": f"{username}-{month}.json",},)

    return sources

class DatasetDownloads:
    def __init__(
        self,
        directory: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.directory = Path(directory,).resolve()
        self.download_directory = self.directory / "downloads"

        self.download_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.capacity = RuntimeCapacity(self.directory,)

        self.manifest_path = self.directory / "datasets.json"

        self.lock = threading.Lock()

        self.cancel_event = cancel_event or threading.Event()

        self.manifest = json.loads(self.manifest_path.read_text(),) if self.manifest_path.exists() else {}

    def record_source(
        self,
        key: str,
        report: dict,
    ) -> None:
        with self.lock:
            self.manifest[key] = report
            temporary_path = self.manifest_path.with_suffix(".next",)

            temporary_path.write_text(json.dumps(
                self.manifest,
                sort_keys=True,
                indent=2,
            ) + "\n",)

            os.replace(
                temporary_path,
                self.manifest_path,
            )

    def download_personal_source(
        self,
        source: dict,
        destination: Path,
        existing: dict,
    ) -> dict:
        headers = {}
        has_cached_source = destination.is_file() and existing.get("status",) == "complete"

        if has_cached_source:
            if existing.get("etag",):
                headers["If-None-Match"] = existing["etag"]

            if existing.get("modified_at",):
                headers["If-Modified-Since"] = existing["modified_at"]

        try:
            response = open_request(
                source["url"],
                headers=headers,
            )
        except urllib.error.HTTPError as error:
            if error.code != 304 or not has_cached_source:
                raise

            error.close()
            report = {**existing, "checked_at": datetime.now(UTC,).isoformat(),}

            self.record_source(
                source["key"],
                report,
            )

            return report

        temporary_path = destination.with_suffix(destination.suffix + ".part",)
        reservation = None

        try:
            reservation = self.capacity.reserve_bytes(0,)

            with response, temporary_path.open("wb",) as stream:
                while content := response.read(CHUNK_BYTES,):
                    if self.cancel_event.is_set():
                        raise InterruptedError("The data download was cancelled.",)

                    self.capacity.write_chunk(
                        reservation,
                        stream,
                        content,
                    )

            payload = json.loads(temporary_path.read_text(),)
            records = payload.get("archives" if source.get("is_metadata",) else "games",)

            if not isinstance(
                records,
                list,
            ):
                raise ValueError("The Chess.com archive has an invalid format.",)

            with temporary_path.open("rb",) as stream:
                digest = hashlib.file_digest(
                    stream,
                    "sha256",
                ).hexdigest()

            report = {**source, "status": "complete", "etag": response.headers.get("ETag",), "modified_at": response.headers.get("Last-Modified",), "license": SOURCE_LICENSES["personal"], "bytes": temporary_path.stat().st_size, "sha256": digest, "path": str(destination,), "completed_at": datetime.now(UTC,).isoformat(), "checked_at": datetime.now(UTC,).isoformat(),}

            os.replace(
                temporary_path,
                destination,
            )

            self.record_source(
                source["key"],
                report,
            )

            return report
        finally:
            response.close()
            temporary_path.unlink(missing_ok=True,)

            if reservation is not None:
                self.capacity.release_bytes(reservation,)

    def get_personal_sources(
        self,
        username: str,
    ) -> list[dict]:
        username = username.lower()

        discover_personal_sources(
            username,
            {"archives": [],},
        )

        source = {"key": f"personal-{username}-index", "kind": "personal", "is_metadata": True, "url": f"https://api.chess.com/pub/player/{username}/games/archives", "filename": f"{username}-archives.json",}

        report = self.download_with_retries(
            source,
            True,
        )

        if report["status"] != "complete":
            raise RuntimeError(f"The Chess.com archive index could not be synchronized: {report.get(
                'error',
                'cancelled',
            )}.",)

        return discover_personal_sources(
            username,
            json.loads(Path(report["path"],).read_text(),),
        )

    def sync_personal_sources(
        self,
        username: str = "mayazrakib",
        should_refresh: bool = False,
    ) -> dict:
        with (self.directory / "download.lock").open("a+b",) as lock_stream, acquire_file_lock(
            lock_stream,
            self.cancel_event,
        ):
            self.manifest = json.loads(self.manifest_path.read_text(),) if self.manifest_path.exists() else {}

            reports = self.sync_personal_months(
                self.get_personal_sources(username,),
                should_refresh,
            )

        return {"complete": sum((report["status"] == "complete" for report in reports),), "incomplete": [report for report in reports if report["status"] != "complete"], **self.capacity.get_status(),}

    def sync_personal_months(
        self,
        sources: list[dict],
        should_refresh: bool,
    ) -> list[dict]:
        current_date = datetime.now(UTC,)
        month_index = current_date.year * 12 + current_date.month - 1
        reports = []

        for source in sources:
            year, month = (int(value,) for value in source["url"].split("/",)[-2:])
            is_recent_month = year * 12 + month - 1 >= month_index - 1

            reports.append(self.download_with_retries(
                source,
                should_refresh or is_recent_month,
            ),)

        return reports

    def download_source(
        self,
        source: dict,
        should_refresh: bool = False,
    ) -> dict:
        if self.cancel_event.is_set():
            raise InterruptedError("The data download was cancelled.",)

        filename = source["filename"]

        parent = self.directory / "syzygy" if source["kind"] == "syzygy" else self.download_directory

        parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = parent / filename

        existing = self.manifest.get(
            source["key"],
            {},
        )

        if destination.is_file() and existing.get("status",) == "complete" and not should_refresh:
            return existing

        if source["kind"] == "personal":
            return self.download_personal_source(
                source,
                destination,
                existing,
            )

        temporary_path = destination.with_suffix(destination.suffix + ".part",)

        with open_request(
            source["url"],
            method="HEAD",
        ) as response:
            expected_bytes = int(response.headers.get(
                "Content-Length",
                "0",
            ),)

            etag = response.headers.get("ETag",)

            modified_at = response.headers.get("Last-Modified",)

        if destination.is_file() and existing.get("status",) == "complete" and etag and existing.get("etag",) == etag:
            return existing

        if temporary_path.exists() and existing.get("etag",) != etag:
            temporary_path.unlink()

        offset_bytes = temporary_path.stat().st_size if temporary_path.exists() else 0

        reservation = self.capacity.reserve_bytes(max(
            0,
            expected_bytes - offset_bytes,
        ),)

        report = {**source, "status": "downloading", "etag": etag, "modified_at": modified_at, "license": SOURCE_LICENSES[source["kind"]], "expected_bytes": expected_bytes,}

        self.record_source(
            source["key"],
            report,
        )

        try:
            headers = {"Range": f"bytes={offset_bytes}-", "If-Range": etag,} if offset_bytes and etag else {}

            if not (expected_bytes and offset_bytes == expected_bytes):
                with open_request(
                    source["url"],
                    headers=headers,
                ) as response:
                    if offset_bytes and response.status == 206 and not response.headers.get(
                        "Content-Range",
                        "",
                    ).startswith(f"bytes {offset_bytes}-",):
                        raise RuntimeError("The resumed dataset response has an unexpected byte range.",)

                    if offset_bytes and response.status != 206:
                        offset_bytes = 0

                    with temporary_path.open("ab" if offset_bytes else "wb",) as stream:
                        while content := response.read(CHUNK_BYTES,):
                            if self.cancel_event.is_set():
                                raise InterruptedError("The data download was cancelled.",)

                            self.capacity.write_chunk(
                                reservation,
                                stream,
                                content,
                            )

            actual_bytes = temporary_path.stat().st_size

            if not actual_bytes or expected_bytes and actual_bytes != expected_bytes:
                raise RuntimeError("A dataset download has an unexpected byte count.",)

            with temporary_path.open("rb",) as stream:
                digest = hashlib.file_digest(
                    stream,
                    "sha256",
                ).hexdigest()

            if source.get("sha256",) and digest != source["sha256"]:
                temporary_path.unlink()
                raise RuntimeError("A dataset checksum does not match the published manifest.",)

            os.replace(
                temporary_path,
                destination,
            )

            report.update(
                status="complete",
                bytes=actual_bytes,
                sha256=digest,
                path=str(destination,),
                completed_at=datetime.now(UTC,).isoformat(),
            )

            self.record_source(
                source["key"],
                report,
            )

            print(
                json.dumps({"dataset": source["key"], "status": "complete", "bytes": actual_bytes,},),
                flush=True,
                file=sys.stderr,
            )

            return report
        except BaseException as exception:
            report.update(
                status="incomplete",
                error=str(exception,),
            )

            self.record_source(
                source["key"],
                report,
            )

            raise
        finally:
            self.capacity.release_bytes(reservation,)

    def download_with_retries(
        self,
        source: dict,
        should_refresh: bool = False,
    ) -> dict:
        for attempt in range(4,):
            try:
                return self.download_source(
                    source,
                    should_refresh,
                )
            except (OSError, urllib.error.URLError, RuntimeError) as exception:
                if self.cancel_event.is_set():
                    return {"key": source["key"], "status": "cancelled",}

                if attempt == 3:
                    return {"key": source["key"], "status": "incomplete", "error": str(exception,),}

                delay_seconds = min(
                    2 ** attempt,
                    8,
                )

                if isinstance(
                    exception,
                    urllib.error.HTTPError,
                ) and exception.headers.get("Retry-After",):
                    retry_after = exception.headers["Retry-After"]

                    try:
                        delay_seconds = max(
                            delay_seconds,
                            int(retry_after,),
                        )
                    except ValueError:
                        delay_seconds = max(
                            delay_seconds,
                            (parsedate_to_datetime(retry_after,) - datetime.now(UTC,)).total_seconds(),
                        )

                self.cancel_event.wait(min(
                    delay_seconds,
                    60,
                ),)

        raise RuntimeError("Dataset retries were exhausted.",)

    def sync_sources(
        self,
        username: str = "mayazrakib",
        should_refresh: bool = False,
    ) -> dict:
        with (self.directory / "download.lock").open("a+b",) as lock_stream, acquire_file_lock(
            lock_stream,
            self.cancel_event,
        ):
            return self.sync_locked_sources(
                username,
                should_refresh,
            )

    def sync_locked_sources(
        self,
        username: str,
        should_refresh: bool,
    ) -> dict:
        self.manifest = json.loads(self.manifest_path.read_text(),) if self.manifest_path.exists() else {}
        personal_sources = self.get_personal_sources(username,)

        sources = discover_sources(
            username,
            personal_sources,
        )

        personal_sources = [source for source in sources if source["kind"] == "personal"]
        bulk_sources = [source for source in sources if source["kind"] != "personal"]
        reports = []

        with ThreadPoolExecutor(max_workers=3,) as executor:
            futures = [executor.submit(
                self.download_with_retries,
                source,
                should_refresh,
            ) for source in bulk_sources]

            reports.extend(self.sync_personal_months(
                personal_sources,
                should_refresh,
            ),)

            for future in as_completed(futures,):
                reports.append(future.result(),)

        return {"complete": sum((report.get("status",) == "complete" for report in reports),), "incomplete": [report for report in reports if report.get("status",) != "complete"], **self.capacity.get_status(),}

def main() -> None:
    parser = argparse.ArgumentParser(description="Download the local Gambit teaching datasets.",)

    parser.add_argument(
        "--directory",
        default="runtime",
    )

    parser.add_argument(
        "--username",
        default="mayazrakib",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
    )

    arguments = parser.parse_args()

    print(
        json.dumps(DatasetDownloads(arguments.directory,).sync_sources(
            arguments.username,
            arguments.refresh,
        ),),
        flush=True,
    )

if __name__ == "__main__":
    main()
