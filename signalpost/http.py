"""Small stdlib HTTP client with a hard outbound-request budget, retries and a disk cache.

Every network call goes through `Client.get`, so the request counter is the single
source of truth for the 2,000-requests-per-run limit.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import USER_AGENT


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Response:
    url: str
    status: int
    body: bytes
    content_type: str
    fetched_at: str  # ISO-8601 UTC
    from_cache: bool = False

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def text(self, limit: int = 2_000_000) -> str:
        return self.body[:limit].decode("utf-8", errors="replace")


def utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Client:
    def __init__(
        self,
        max_requests: int = 1900,
        cache_dir: Path | None = None,
        cache_ttl_s: int = 6 * 3600,
        timeout_s: float = 15.0,
        min_interval_s: float = 0.02,
    ):
        self.max_requests = max_requests
        self.requests_made = 0
        self.cache_dir = cache_dir
        self.cache_ttl_s = cache_ttl_s
        self.timeout_s = timeout_s
        self.min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def _cache_get(self, url: str) -> Response | None:
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl_s:
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return Response(d["url"], d["status"], d["body"].encode("utf-8"), d["content_type"], d["fetched_at"], True)

    def _cache_put(self, r: Response) -> None:
        path = self._cache_path(r.url)
        if path and r.status in (200, 404, 410):
            path.write_text(json.dumps({
                "url": r.url, "status": r.status, "content_type": r.content_type,
                "fetched_at": r.fetched_at, "body": r.body.decode("utf-8", errors="replace"),
            }), encoding="utf-8")

    # -- fetch ---------------------------------------------------------------
    def _reserve(self) -> None:
        with self._lock:
            if self.requests_made >= self.max_requests:
                raise BudgetExceeded(f"outbound request budget of {self.max_requests} reached")
            self.requests_made += 1
            wait = self._last + self.min_interval_s - time.monotonic()
            self._last = max(time.monotonic(), self._last + self.min_interval_s)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, accept: str = "application/json", retries: int = 1, use_cache: bool = True) -> Response:
        if use_cache and (cached := self._cache_get(url)):
            return cached
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._reserve()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    r = Response(url, resp.status, resp.read(5_000_000), resp.headers.get("Content-Type", ""), utcnow_iso())
            except urllib.error.HTTPError as e:
                r = Response(url, e.code, e.read() or b"", e.headers.get("Content-Type", "") if e.headers else "", utcnow_iso())
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exc = e
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            if use_cache:
                self._cache_put(r)
            return r
        raise ConnectionError(f"GET {url} failed: {last_exc}")
