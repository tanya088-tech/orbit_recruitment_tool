"""One browser window for a whole collection run.

Without this, every place that is searched starts its own browser (several seconds each, and a window that pops up
every time). With it, the tool starts the browser ONCE, the per-place collectors connect to it, and it is closed when the run
ends. It is the same kind of ordinary, visible browser window as before (Naukri needs one) - started with the same profile
folder, so cookies are kept exactly as they were. Nothing here hides the automation or gets past a block.

If anything goes wrong (browser not installed, profile already in use, no answer in time) start() returns None and the
collection falls back to starting a browser per place, as before.
"""
from __future__ import annotations

import logging
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

ENV_VAR = "ORBIT_BROWSER_CDP"
CHROME_ARGS = ("--no-first-run", "--no-default-browser-check", "--lang=en-IN", "--window-size=1366,900",
               "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
               "--disable-background-timer-throttling")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium_path() -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return p.chromium.executable_path


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/json/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


class BrowserHost:
    """start() -> "http://127.0.0.1:PORT" (the address the collectors connect to) or None; stop() closes the browser."""

    def __init__(self, profile_dir: Path, wait_seconds: float = 20.0,
                 find_binary: Callable[[], str] = _chromium_path,
                 popen: Callable[..., Any] = subprocess.Popen,
                 answers: Callable[[str], bool] = _answers,
                 port_fn: Callable[[], int] = _free_port) -> None:
        self.profile_dir, self.wait_seconds = Path(profile_dir), wait_seconds
        self._find, self._popen, self._answers, self._port = find_binary, popen, answers, port_fn
        self.proc: Any = None
        self.url: Optional[str] = None

    def start(self) -> Optional[str]:
        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            exe, port = self._find(), self._port()
            self.proc = self._popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={self.profile_dir}", *CHROME_ARGS, "about:blank"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + self.wait_seconds
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:             # it quit (e.g. the profile is open in another window)
                    break
                if self._answers(url):
                    self.url = url
                    return url
                time.sleep(0.25)
        except Exception as exc:                              # not installed, no permission, ...
            log.info("shared browser not started: %s: %s", type(exc).__name__, str(exc)[:160])
        self.stop()
        return None

    def stop(self) -> None:
        proc, self.proc, self.url = self.proc, None, None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass
