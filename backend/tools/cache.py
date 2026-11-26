"""Tiny helpers shared by the tools: a TTL cache (no duplicate searches / fetches) and a rate limiter."""

import threading
import time


class TTLCache:
    """Thread-safe in-memory cache. Entries expire after `ttl` seconds."""

    def __init__(self, ttl: float = 6 * 3600, max_items: int = 500):
        self.ttl, self.max_items = ttl, max_items
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item and time.time() - item[0] < self.ttl:
                return item[1]
            self._data.pop(key, None)
            return None

    def set(self, key, value):
        with self._lock:
            if len(self._data) >= self.max_items:  # drop the oldest entry
                self._data.pop(min(self._data, key=lambda k: self._data[k][0]), None)
            self._data[key] = (time.time(), value)


class RateLimiter:
    """Guarantees at least `min_interval` seconds between calls (shared across threads)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            delay = self._next - now
            self._next = max(now, self._next) + self.min_interval
        if delay > 0:
            time.sleep(delay)


def normalize_query(q: str) -> str:
    return " ".join(str(q).lower().split())


def normalize_url(url: str) -> str:
    """Canonical form used to detect duplicate pages (drops #fragment, trailing slash, scheme case)."""
    url = str(url or "").strip().split("#")[0].rstrip("/")
    return url.lower() if url.lower().startswith(("http://", "https://")) else url
