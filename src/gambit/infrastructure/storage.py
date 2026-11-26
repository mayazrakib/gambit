import json
import threading
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy

COLLECTIONS = frozenset({'analysis', 'job', 'checkpoint', 'live_game',},)

class Store:
    def __init__(
        self,
        capacity: int = 512,
        max_record_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if type(capacity,) is not int or not 1 <= capacity <= 10000:
            raise ValueError('State capacity must be between 1 and 10000.',)

        self.capacity = capacity
        self.max_record_bytes = max_record_bytes
        self.lock = threading.RLock()
        self.records = {name: OrderedDict() for name in COLLECTIONS}
        self.analysis_cache = OrderedDict()
        self.record_sizes = OrderedDict()
        self.total_bytes = 0
        self.max_total_bytes = 32 * 1024 * 1024

    @contextmanager
    def acquire_write(self,):
        with self.lock:
            yield

    def get(
        self,
        collection: str,
        record_id: str,
    ) -> dict | None:
        with self.lock:
            value = self.records[collection].get(record_id,)

            if value is not None:
                self.records[collection].move_to_end(record_id,)

            return deepcopy(value,)

    def put(
        self,
        collection: str,
        record_id: str,
        payload: dict,
        *,
        is_immutable: bool = False,
    ) -> dict:
        if collection not in COLLECTIONS or not record_id:
            raise ValueError('Unsupported temporary state collection or identity.',)

        size = len(json.dumps(
            payload,
            allow_nan=False,
        ).encode(),)

        if size > self.max_record_bytes:
            raise ValueError('The temporary record exceeds its size limit.',)

        with self.lock:
            records = self.records[collection]

            if is_immutable and record_id in records:
                return deepcopy(records[record_id],)

            key = (collection, record_id)

            self.total_bytes -= self.record_sizes.pop(
                key,
                0,
            )

            self.record_sizes[key] = size
            self.total_bytes += size
            records[record_id] = deepcopy(payload,)
            records.move_to_end(record_id,)
            limit = 1 if collection == 'live_game' else self.capacity

            while len(records,) > limit:
                removed_id, _ = records.popitem(last=False,)

                self.total_bytes -= self.record_sizes.pop(
                    (collection, removed_id),
                    0,
                )

            while self.total_bytes > self.max_total_bytes:
                oldest = next(
                    (item for item in self.record_sizes if item[0] != 'live_game'),
                    None,
                )

                if oldest is None:
                    break

                self.total_bytes -= self.record_sizes.pop(oldest,)

                self.records[oldest[0]].pop(
                    oldest[1],
                    None,
                )

        return payload

    def get_analysis_cache(
        self,
        fingerprint: str,
    ) -> dict | None:
        with self.lock:
            identifier = self.analysis_cache.get(fingerprint,)

            return self.get(
                'analysis',
                identifier,
            ) if identifier else None

    def put_analysis_cache(
        self,
        fingerprint: str,
        payload: dict,
        *,
        before_commit=None,
    ) -> dict:
        with self.lock:
            if before_commit is not None:
                before_commit()

            cached = self.get_analysis_cache(fingerprint,)

            if cached is not None:
                return cached

            self.put(
                'analysis',
                payload['id'],
                payload,
            )

            self.analysis_cache[fingerprint] = payload['id']
            self.analysis_cache.move_to_end(fingerprint,)

            while len(self.analysis_cache,) > self.capacity:
                self.analysis_cache.popitem(last=False,)

            return payload

    def close(self,) -> None:
        with self.lock:
            for records in self.records.values():
                records.clear()

            self.analysis_cache.clear()
            self.record_sizes.clear()
            self.total_bytes = 0
