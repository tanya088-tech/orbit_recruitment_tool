"""HTTP client for public pages. The ONLY place that talks to the network.

Rules it follows:
  * waits a random few seconds between requests (never bursts)
  * retries temporary problems with growing waits (exponential backoff)
  * if the site says "too many requests" or sends us to a login wall, it gives
    up and raises BlockedError. It does NOT rotate IPs, fake logins, solve
    CAPTCHAs or otherwise get around the block.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, Optional

import requests

from collectors.errors import BlockedError, FetchError, NotFoundError
from config import settings

log = logging.getLogger(__name__)

_BLOCK_STATUSES = {401, 403, 429, 999}   # 999 is LinkedIn's own "go away" code
_LOGIN_WALL_MARKERS = ("/authwall", "/login", "/uas/login", "/checkpoint")


class HttpClient:
    def __init__(
        self,
        delay_min: float = settings.REQUEST_DELAY_MIN,
        delay_max: float = settings.REQUEST_DELAY_MAX,
        max_retries: int = settings.MAX_RETRIES,
        backoff_base: float = settings.BACKOFF_BASE,
        timeout: float = settings.REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.delay_min, self.delay_max = delay_min, delay_max
        self.max_retries, self.backoff_base, self.timeout = max_retries, backoff_base, timeout
        self._sleep = sleep
        self._last_request_at = 0.0
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        })

    # -- helpers -----------------------------------------------------------
    def _throttle(self) -> None:
        wait = random.uniform(self.delay_min, self.delay_max) - (time.monotonic() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)

    def _backoff(self, attempt: int, retry_after: Optional[str] = None) -> None:
        if retry_after and retry_after.isdigit():
            wait = min(float(retry_after), settings.BACKOFF_MAX)
        else:
            wait = min(self.backoff_base * (2 ** (attempt - 1)), settings.BACKOFF_MAX)
            wait += random.uniform(0, 1.5)
        log.warning("Backing off %.1fs before retry", wait)
        self._sleep(wait)

    # -- main entry point --------------------------------------------------
    def get(self, url: str, params: Optional[dict] = None) -> str:
        """Return page HTML or raise NotFoundError / BlockedError / FetchError."""
        return self._send(url, lambda: self.session.get(url, params=params, timeout=self.timeout))

    def _send(self, url: str, send: Callable) -> str:
        last_problem = "unknown error"
        blocked = False

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = send()
            except requests.RequestException as exc:
                last_problem, blocked = f"network error: {exc}", False
                log.warning("Attempt %d/%d failed for %s: %s", attempt, self.max_retries, url, last_problem)
                self._last_request_at = time.monotonic()
                if attempt < self.max_retries:
                    self._backoff(attempt)
                continue
            self._last_request_at = time.monotonic()

            if any(marker in resp.url for marker in _LOGIN_WALL_MARKERS):
                raise BlockedError(f"redirected to login wall ({resp.url})")

            status = resp.status_code
            if status == 200:
                return resp.text
            if status in (404, 410):
                raise NotFoundError(f"HTTP {status} (page not found / job removed)")

            if status in _BLOCK_STATUSES:
                last_problem, blocked = f"HTTP {status} (rate limited / blocked)", True
            elif status >= 500:
                last_problem, blocked = f"HTTP {status} (server error)", False
            else:
                raise FetchError(f"HTTP {status}")

            log.warning("Attempt %d/%d for %s -> %s", attempt, self.max_retries, url, last_problem)
            if attempt < self.max_retries:
                self._backoff(attempt, resp.headers.get("Retry-After"))

        if blocked:
            raise BlockedError(last_problem)
        raise FetchError(last_problem)
