import threading
import numpy as np
from datetime import datetime


MAX_COLLECTIONS = 20
CHANNELS = 8
PREALLOCATE = 1_000_000  # initial pre-allocated samples per channel


class DataManager:
    def __init__(self):
        self._live_buf = [np.empty(PREALLOCATE, dtype=np.float32) for _ in range(CHANNELS)]
        self._live_len = 0
        self.live_history_buf: list[list] = [[] for _ in range(CHANNELS)]
        self.collected_data: list[dict] = []
        self.history_lock = threading.Lock()
        self.is_collecting: bool = False
        self._collection_start_time: datetime | None = None

    @property
    def live_history(self) -> list[np.ndarray]:
        """O(1) views into the pre-allocated buffer up to current length."""
        return [self._live_buf[ch][:self._live_len] for ch in range(CHANNELS)]

    def flush_buf(self) -> int:
        """Append live_history_buf into pre-allocated array. O(1) amortized.
        Must be called under history_lock. Returns new total length."""
        buf0 = self.live_history_buf[0]
        if not buf0:
            return self._live_len
        n = len(buf0)
        end = self._live_len + n
        capacity = len(self._live_buf[0])
        if end > capacity:
            new_size = max(end, capacity * 2)
            for ch in range(CHANNELS):
                new_arr = np.empty(new_size, dtype=np.float32)
                new_arr[:self._live_len] = self._live_buf[ch][:self._live_len]
                self._live_buf[ch] = new_arr
        for ch in range(CHANNELS):
            self._live_buf[ch][self._live_len:end] = self.live_history_buf[ch]
            self.live_history_buf[ch].clear()
        self._live_len = end
        return end

    def start_collection(self):
        with self.history_lock:
            self._live_len = 0
            for buf in self.live_history_buf:
                buf.clear()
        self._collection_start_time = datetime.now()
        self.is_collecting = True

    def stop_collection(self) -> dict | None:
        """Stop collection, flush remaining buf, return record dict (or None if not collecting)."""
        if not self.is_collecting:
            return None
        end_time = datetime.now()
        self.is_collecting = False
        with self.history_lock:
            self.flush_buf()
            saved = [self._live_buf[ch][:self._live_len].copy() for ch in range(CHANNELS)]
        return {
            'data': saved,
            'start_time': self._collection_start_time,
            'end_time': end_time,
            'time_str': self._collection_start_time.strftime('%H:%M:%S') if self._collection_start_time else '',
        }

    def commit_record(self, record: dict, name: str):
        record['name'] = name
        self.collected_data.append(record)

    def overwrite_record(self, index: int, record: dict):
        existing = self.collected_data[index]
        existing['data'] = record['data']
        existing['start_time'] = record['start_time']
        existing['end_time'] = record['end_time']
        existing['time_str'] = record['time_str']
        existing['name'] = record.get('name', existing['name'])

    def clear_all(self):
        with self.history_lock:
            self.collected_data.clear()
            self._live_len = 0
            for buf in self.live_history_buf:
                buf.clear()
        self.is_collecting = False
