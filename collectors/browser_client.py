"""Fetch fully rendered pages with a real browser engine, for sources that build their pages with JavaScript.

Used by Naukri and Indeed (a plain HTTP request to Naukri returns an empty shell with no jobs).
It follows the same rules as collectors/linkedin/client.py:
  * waits a random few seconds between page loads (never bursts)
  * if the site shows a security check / CAPTCHA / "access denied", or answers 403 / 429, it raises BlockedError
    and the run for that source stops. It does NOT solve CAPTCHAs, wait them out, rotate IPs, fake logins
    or hide that it is automated.
  * "Read more" / "Show more" style buttons can be expanded before the page is read (expand=[css selectors]),
    so a collapsed description is read in full.
Playwright is optional: if it is not installed a SetupError explains how to install it.
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
from typing import Any, Callable, Optional
from urllib.parse import urlencode, urlsplit

from collectors.errors import BlockedError, FetchError, LocalBrowserError, NotFoundError, SetupError
from config import settings

log = logging.getLogger(__name__)

INSTALL_HELP = ("Browser support is not installed. In the project folder run:  pip install playwright  and then  "
                "playwright install chromium   (about 150 MB, once). Then start the collection again.")
# A challenge page announces itself in its TITLE; the page body is only checked for markers no real job text contains.
# (A bank job may legitimately say "background and security check" or "captcha" in its description.)
TITLE_MARKERS = ("security check", "just a moment", "verify you are human", "verify you're human", "captcha",
                 "access denied", "unusual traffic", "are you a robot", "pardon our interruption", "attention required")
BODY_MARKERS = ("cf_chl", "cf-challenge", "challenge-platform", "verify you are human", "verify you're human",
                "unusual traffic from your")


def looks_blocked(title: str, html: str) -> bool:
    t = (title or "").lower()
    if any(m in t for m in TITLE_MARKERS):
        return True
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if m and any(k in m.group(1).lower() for k in TITLE_MARKERS):
        return True
    head = (html or "")[:20000].lower()
    return any(k in head for k in BODY_MARKERS)


_GATE_PATH = re.compile(r"/(auth|login|nlogin|signin|sign-in|authwall|captcha|challenge|verify|checkpoint)(?:[/;?]|$)", re.I)


_CRASH_MARKERS = ("page crashed", "target closed", "targetclosederror", "has been closed", "frame was detached",
                   "browser has disconnected", "execution context was destroyed")
_NETWORK_MARKERS = ("err_network_changed", "err_internet_disconnected", "err_network_io_suspended")


def local_failure_kind(exc: BaseException) -> Optional[str]:
    """'crash' / 'network' when a failed page load was caused by OUR browser or connection (not by the site); else None.
    Only clear local symptoms count. Resets, timeouts and HTTP errors still go through the normal failure path."""
    text = f"{type(exc).__name__} {exc}".lower()
    if any(m in text for m in _NETWORK_MARKERS):
        return "network"
    if any(m in text for m in _CRASH_MARKERS):
        return "crash"
    return None


def redirected_to_gate(requested: str, final: str) -> bool:
    """True when the browser ended on a different page whose path is a sign-in / session / challenge endpoint."""
    if not final or final == requested:
        return False
    r, f = urlsplit(requested), urlsplit(final)
    if f.path == r.path and f.netloc == r.netloc:
        return False
    return bool(_GATE_PATH.search(f.path)) and not _GATE_PATH.search(r.path)


class BrowserClient:
    """get(url) -> rendered HTML. `page_factory` lets tests supply a fake page; the default starts Playwright."""

    def __init__(self, delay_min: float = settings.REQUEST_DELAY_MIN, delay_max: float = settings.REQUEST_DELAY_MAX,
                 wait_ms: int = settings.BROWSER_WAIT_MS, page_factory: Optional[Callable[[], Any]] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.delay_min, self.delay_max, self.wait_ms = delay_min, delay_max, wait_ms
        self._page_factory = page_factory
        self._page: Any = None
        self._pw: Any = None
        self._ctx: Any = None
        self._sleep = sleep
        self._last = 0.0
        self._shared = False              # connected to the browser the tool started for the whole run (never closed from here)

    # -- browser lifecycle ---------------------------------------------------
    def _open(self) -> Any:
        if self._page is not None:
            return self._page
        if self._page_factory is not None:
            self._page = self._page_factory()
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SetupError(INSTALL_HELP) from exc
        cdp = os.environ.get("ORBIT_BROWSER_CDP")
        if cdp:                                          # the collection started one browser for the whole run: use it
            try:
                self._pw = sync_playwright().start()
                browser = self._pw.chromium.connect_over_cdp(cdp)
                self._ctx = browser.contexts[0] if browser.contexts else browser.new_context(locale="en-IN")
                self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
                self._shared = True
                self._skip_heavy(self._page)
                if settings.BROWSER_MINIMIZE_WINDOW and not settings.BROWSER_HEADLESS:
                    self._minimize(self._page)
                return self._page
            except Exception as exc:
                log.info("could not use the shared browser (%s); starting one instead", type(exc).__name__)
                self.close()
                self._shared = False
        try:
            settings.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(settings.BROWSER_PROFILE_DIR), headless=settings.BROWSER_HEADLESS, locale="en-IN",
                viewport={"width": 1366, "height": 900},
                # keep a minimized / covered window rendering normally (otherwise Chrome pauses its pages)
                args=["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                      "--disable-background-timer-throttling"])
            self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            self._skip_heavy(self._page)
            if settings.BROWSER_MINIMIZE_WINDOW and not settings.BROWSER_HEADLESS:
                self._minimize(self._page)
        except Exception as exc:                     # chromium missing, profile locked by another window, ...
            self.close()
            raise SetupError(f"{INSTALL_HELP} (details: {type(exc).__name__}: {str(exc)[:160]})") from exc
        return self._page

    def _recover_page(self) -> None:
        """Replace a crashed / closed page with a fresh one in the same browser (same profile and cookies).
        If the browser itself is gone, drop it so the next _open() starts it again. Never touches the site."""
        old, self._page = self._page, None
        try:
            if old is not None and hasattr(old, "close"):
                old.close()
        except Exception:
            pass
        if self._ctx is not None:
            try:
                self._page = self._ctx.new_page()
                self._skip_heavy(self._page)
                if settings.BROWSER_MINIMIZE_WINDOW and not settings.BROWSER_HEADLESS:
                    self._minimize(self._page)
                return
            except Exception as exc:
                log.warning("could not open a new page in the browser (%s); restarting the browser", type(exc).__name__)
                self.close()

    @staticmethod
    def _skip_heavy(page: Any) -> None:
        """Do not download images, video or fonts (settings.BROWSER_SKIP_RESOURCE_TYPES): the tool reads only the page's
        text and HTML, so this makes each page load lighter without changing anything that is read. Best effort."""
        types = frozenset(settings.BROWSER_SKIP_RESOURCE_TYPES or ())
        if not types or not hasattr(page, "route"):
            return

        def handle(route: Any) -> None:
            if route.request.resource_type in types:
                route.abort()
            else:
                route.fallback()
        try:
            page.route("**/*", handle)
        except Exception as exc:
            log.debug("could not skip images/fonts: %s", exc)

    def _minimize(self, page: Any) -> None:
        """Minimize the collection window so it does not open in front of the dashboard. Best effort: if the browser
        refuses, the window simply stays where it is. It is still an ordinary browser window - nothing is hidden from the site."""
        try:
            session = page.context.new_cdp_session(page)
            window = session.send("Browser.getWindowForTarget")
            session.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "minimized"}})
        except Exception as exc:
            log.debug("could not minimize the browser window: %s", exc)

    def close(self) -> None:
        for obj, method in (((None if self._shared else self._ctx), "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, method)()
            except Exception:
                pass
        self._page = self._ctx = self._pw = None
        self._shared = False

    @staticmethod
    def describe_page(page: Any) -> str:
        """Page title plus the first words of its visible text, so a refusal can be understood (never used to get past it)."""
        try:
            title = (page.title() or "").strip()
        except Exception:
            title = ""
        try:
            body = page.inner_text("body")[:200] if hasattr(page, "inner_text") else ""
        except Exception:
            body = ""
        text = " ".join(f"{title} | {body}".split()).strip(" |")
        return text[:240] or "(no readable text)"

    # -- politeness ----------------------------------------------------------
    def _throttle(self) -> None:
        wait = random.uniform(self.delay_min, self.delay_max) - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)

    # -- main entry point ----------------------------------------------------
    def diagnose(self, page: Any, requested: str, status: Any = None, resp: Any = None) -> str:
        """One line that shows what happened: the URL asked for, the URL the browser ended on, the status,
        the redirect chain and what the page said. For understanding a refusal only - never used to get past one."""
        final = getattr(page, "url", None) or requested
        chain = []
        try:
            req = getattr(resp, "request", None)
            while req is not None and getattr(req, "redirected_from", None) is not None:
                req = req.redirected_from
                chain.append(f"{getattr(req, 'url', '?')}")
        except Exception:
            pass
        bits = [f"requested={requested}", f"final={final}"]
        if status is not None:
            bits.append(f"status={status}")
        if chain:
            bits.append("redirected_from=" + " <- ".join(reversed(chain)))
        bits.append(f"page={self.describe_page(page)!r}")
        return "; ".join(bits)

    def get(self, url: str, params: Optional[dict] = None, wait_for: Optional[str] = None,
            expand: Optional[list[str]] = None) -> str:
        """Load `url`, wait for `wait_for` (a CSS selector) if given, click every `expand` button, return the HTML."""
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
        local_failures = 0
        while True:
            page = self._open()
            self._throttle()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=self.wait_ms * 2)
                break
            except Exception as exc:
                self._last = time.monotonic()
                kind = local_failure_kind(exc)
                if kind is None:
                    raise FetchError(f"could not load {url}: {type(exc).__name__}: {str(exc)[:160]}; "
                                     f"{self.diagnose(page, url)}") from exc
                # Our own browser crashed or lost its network: that is not the site refusing us. Open a fresh page and
                # load the same URL again (a couple of times, slowly); if it still fails it is reported as a local problem.
                local_failures += 1
                if local_failures > settings.BROWSER_RECOVERY_RETRIES:
                    raise LocalBrowserError(f"the browser on this computer failed ({kind}); the site did not refuse anything. "
                                            f"{url}: {type(exc).__name__}: {str(exc)[:120]}") from exc
                wait = settings.BROWSER_RECOVERY_WAIT * (local_failures * 3 if kind == "network" else 1)
                log.warning("Browser %s while loading a page (%s); re-opening it and trying again in %.0fs (%d/%d)",
                            kind, type(exc).__name__, wait, local_failures, settings.BROWSER_RECOVERY_RETRIES)
                self._sleep(wait)
                if kind == "crash":
                    self._recover_page()
        self._last = time.monotonic()
        status = getattr(resp, "status", 200) if resp is not None else 200
        if status in (404, 410):
            raise NotFoundError(f"HTTP {status} (page not found / job removed)")
        if status in (401, 403, 429):
            # a 403 page may still be a challenge page; either way we stop and never work around it
            raise BlockedError(f"HTTP {status}: the site refused the request (rate limit, security check or login wall). "
                               + self.diagnose(page, url, status, resp))
        if status >= 400:
            raise FetchError(f"HTTP {status}; " + self.diagnose(page, url, status, resp))
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=self.wait_ms)
            except Exception:
                pass                                    # no list on the page: the caller decides whether that means "no results"
        # A page can answer 200 and then move the browser somewhere else with JavaScript (e.g. to a sign-in or
        # session endpoint). That is the site declining to show the page to this session: stop, do not follow it on.
        final = getattr(page, "url", None) or url
        if redirected_to_gate(url, final):
            raise BlockedError("the site sent the browser to a sign-in / session page instead of the page asked for. "
                               "The tool does not sign in or work around it. " + self.diagnose(page, url, status, resp))
        for selector in expand or []:
            try:
                for el in page.query_selector_all(selector):
                    try:
                        el.click(timeout=2000)
                    except Exception:
                        pass
            except Exception:
                pass
        html = page.content()
        if looks_blocked(page.title() if hasattr(page, "title") else "", html):
            raise BlockedError("the site is showing a security check; The tool does not try to get past it. "
                               + self.diagnose(page, url, status, resp))
        return html
