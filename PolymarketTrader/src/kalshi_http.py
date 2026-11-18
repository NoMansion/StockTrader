"""A small, patient HTTP client for Kalshi's public market-data API (no account, no key, read-only).

Used by the Kalshi venue adapter and by the research downloader. It paces requests, waits out HTTP 429 (the
API rate-limits bursts and asks for a pause), retries timeouts and 5xx a few times, and never raises on a single
slow answer. Nothing here can place an order: only GET requests are made, and no credentials exist.
"""
from __future__ import annotations

import time

BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiError(RuntimeError):
    def __init__(self, status: int, path: str, text: str = ""):
        super().__init__(f"Kalshi {status} on {path}: {' '.join(text.split())[:160]}")
        self.status_code = status


class KalshiHTTP:
    def __init__(self, min_interval: float = 0.25, base: str = BASE, timeout: float = 40.0, max_wait: float = 90.0,
                 user_agent: str = "paper-research-client/0.1", client=None):
        self.base, self.min_interval, self.max_wait = base, float(min_interval), float(max_wait)
        if client is None:
            import httpx                                    # arrives with the polymarket-us SDK
            client = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})
        self.client = client
        self._last = 0.0
        self.requests = 0
        self.rate_limited = 0

    def _pace(self) -> None:
        wait = self._last + self.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def get(self, path: str, tries: int = 6, **params) -> dict:
        """GET base+path. 404 raises KalshiError(404); 429 and 5xx are waited out (5 s, 15 s, 45 s, then 90 s)
        up to `tries` attempts, after which KalshiError carries the status."""
        params = {k: v for k, v in params.items() if v is not None}
        pause = 5.0
        for attempt in range(tries):
            self._pace()
            self.requests += 1
            try:
                r = self.client.get(self.base + path, params=params)
            except Exception:                                # timeouts, connection resets
                if attempt == tries - 1:
                    raise
                time.sleep(min(pause, self.max_wait))
                pause *= 3
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                if r.status_code == 429:
                    self.rate_limited += 1
                    self.min_interval = min(self.min_interval * 1.5 + 0.05, 2.0)   # slow down for good
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else pause
                except ValueError:
                    wait = pause
                if attempt == tries - 1:
                    raise KalshiError(r.status_code, path, r.text)
                time.sleep(min(max(wait, 1.0), self.max_wait))
                pause *= 3
                continue
            raise KalshiError(r.status_code, path, r.text)
        raise KalshiError(599, path, "gave up")

    def pages(self, path: str, key: str, limit: int = 1000, max_pages: int = 10000, tries: int = 6, **params):
        """Yield every item of a cursor-paginated listing, one page in memory at a time."""
        cursor = None
        for _ in range(max_pages):
            d = self.get(path, tries=tries, limit=limit, cursor=cursor, **params)
            items = d.get(key) or []
            yield from items
            cursor = d.get("cursor")
            if not cursor or not items:
                return
