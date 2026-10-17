import json
import logging
import os
import threading
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic

import httpx

from gambit.engine.client import check_request_active
from gambit.infrastructure.configuration import Configuration

HOSTS = {'lichess': 'https://lichess.org', 'explorer': 'https://explorer.lichess.org', 'tablebase': 'https://tablebase.lichess.ovh', 'chesscom': 'https://api.chess.com',}

class ProviderFailure(Exception,):
    def __init__(
        self,
        status: str,
        code: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code,)
        self.status = status
        self.code = code
        self.retry_after_seconds = retry_after_seconds

    def render(
        self,
        provider: str,
    ) -> dict:
        return {'status': self.status, 'provider': provider, 'reason_code': self.code, 'retry_after_seconds': self.retry_after_seconds,}

class ProviderHttp:
    def __init__(
        self,
        configuration: Configuration,
        transport=None,
    ) -> None:
        logging.getLogger("httpx",).setLevel(logging.WARNING,)
        self.configuration = configuration

        self.client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            headers={'User-Agent': 'Gambit/0.3 chess evidence', 'Accept': 'application/json',},
        )

        self.locks = {host: threading.Lock() for host in HOSTS}
        self.cooldowns = {}
        self.cache = OrderedDict()
        self.cache_lock = threading.Lock()

    def request(
        self,
        provider: str,
        path: str,
        params: dict | None = None,
        *,
        is_text: bool = False,
        should_cache: bool = True,
    ) -> dict | str:
        if provider not in HOSTS or not path.startswith('/',) or '?' in path:
            raise ValueError('Unsupported provider request.',)

        params = params or {}

        key = (3, provider, path, json.dumps(
            params,
            sort_keys=True,
        ), is_text)

        started = monotonic()
        deadline = started + self.configuration.api_timeout_seconds

        with self.cache_lock:
            cached = self.cache.get(key,) if should_cache else None

            if cached is not None and cached[0] > started:
                self.cache.move_to_end(key,)
                check_request_active()

                return deepcopy(cached[1],)

        lock = self.locks[provider]

        while not lock.acquire(timeout=0.025,):
            check_request_active()

            if monotonic() >= deadline:
                raise ProviderFailure(
                    'unavailable',
                    'provider_queue_timeout',
                )

        try:
            check_request_active()

            if self.cooldowns.get(
                provider,
                0,
            ) > monotonic():
                raise ProviderFailure(
                    'unavailable',
                    'rate_limited',
                    max(
                        1,
                        int(self.cooldowns[provider] - monotonic(),),
                    ),
                )

            with self.cache_lock:
                cached = self.cache.get(key,) if should_cache else None

                if cached is not None and cached[0] > monotonic():
                    return deepcopy(cached[1],)

            for attempt in range(2,):
                remaining = deadline - monotonic()

                if remaining <= 0:
                    raise ProviderFailure(
                        'unavailable',
                        'provider_timeout',
                    )

                try:
                    with self.client.stream(
                        'GET',
                        HOSTS[provider] + path,
                        params=params,
                        timeout=min(
                            2.0,
                            remaining,
                        ),
                        headers={**({'Authorization': 'Bearer ' + os.environ['GAMBIT_LICHESS_TOKEN'],} if provider == 'explorer' and os.environ.get('GAMBIT_LICHESS_TOKEN',) else {}), 'Accept': 'application/x-chess-pgn' if is_text else 'application/json',},
                    ) as response:
                        if response.status_code == 429:
                            retry = response.headers.get(
                                'Retry-After',
                                '60',
                            )

                            try:
                                seconds = max(
                                    1,
                                    int(retry,),
                                )
                            except ValueError:
                                try:
                                    seconds = max(
                                        1,
                                        int((parsedate_to_datetime(retry,) - datetime.now(UTC,)).total_seconds(),),
                                    )
                                except (ValueError, TypeError, OverflowError):
                                    seconds = 60

                            self.cooldowns[provider] = monotonic() + seconds

                            raise ProviderFailure(
                                'unavailable',
                                'rate_limited',
                                seconds,
                            )

                        if response.status_code == 404:
                            raise ProviderFailure(
                                'unavailable',
                                'not_found',
                            )

                        if response.status_code in (401, 403):
                            raise ProviderFailure(
                                'unavailable',
                                'provider_access_denied',
                            )

                        if response.status_code >= 500 and attempt == 0:
                            continue

                        if response.status_code != 200:
                            raise ProviderFailure(
                                'unavailable' if response.status_code >= 500 else 'failed',
                                'provider_http_error',
                            )

                        content = bytearray()

                        for chunk in response.iter_bytes():
                            check_request_active()

                            if monotonic() >= deadline:
                                raise ProviderFailure(
                                    'unavailable',
                                    'provider_timeout',
                                )

                            content.extend(chunk,)

                            if len(content,) > self.configuration.api_max_response_bytes:
                                raise ProviderFailure(
                                    'failed',
                                    'provider_response_too_large',
                                )

                        try:
                            result = content.decode('utf-8',) if is_text else json.loads(content,)
                        except (ValueError, UnicodeError):
                            raise ProviderFailure(
                                'failed',
                                'malformed_response',
                            ) from None

                        if not is_text and not isinstance(
                            result,
                            dict,
                        ):
                            raise ProviderFailure(
                                'failed',
                                'malformed_response',
                            )

                        if should_cache:
                            with self.cache_lock:
                                self.cache[key] = (monotonic() + 60, result)
                                self.cache.move_to_end(key,)

                                while len(self.cache,) > self.configuration.api_cache_capacity:
                                    self.cache.popitem(last=False,)

                        return deepcopy(result,)
                except httpx.TimeoutException:
                    raise ProviderFailure(
                        'unavailable',
                        'provider_timeout',
                    ) from None
                except httpx.RequestError:
                    if attempt:
                        raise ProviderFailure(
                            'unavailable',
                            'provider_network_error',
                        ) from None

            raise ProviderFailure(
                'unavailable',
                'provider_http_error',
            )
        finally:
            lock.release()

    def close(self,) -> None:
        self.client.close()

        with self.cache_lock:
            self.cache.clear()
