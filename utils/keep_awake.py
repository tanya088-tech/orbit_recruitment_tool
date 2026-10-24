"""Keep the computer from going to sleep while a collection runs (the screen may still turn off).

Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) on the thread that runs the collection, reset when it ends.
macOS:   `caffeinate -i -w <this process>` while it runs (it also ends by itself if this process ends).
Elsewhere nothing is done. This cannot prevent sleep forced by a critical battery or by closing the lid.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Callable, Iterator, Optional

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _windows_set_state() -> Optional[Callable[[int], Any]]:
    try:
        import ctypes
        return ctypes.windll.kernel32.SetThreadExecutionState
    except Exception:
        return None


@contextlib.contextmanager
def keep_awake(enabled: bool = True, platform: Optional[str] = None,
               set_state: Optional[Callable[[int], Any]] = None,
               popen: Callable[..., Any] = subprocess.Popen,
               which: Callable[[str], Optional[str]] = shutil.which) -> Iterator[bool]:
    """Yields True when sleep is being held off. Never raises because of the operating system; the block always runs."""
    platform = platform or sys.platform
    held, proc = False, None
    if enabled and platform == "win32":
        fn = set_state or _windows_set_state()
        try:
            held = bool(fn and fn(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
        except Exception as exc:
            log.debug("could not keep the computer awake: %s", exc)
    elif enabled and platform == "darwin":
        exe = which("caffeinate")
        if exe:
            try:
                proc = popen([exe, "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                held = True
            except Exception as exc:
                log.debug("could not start caffeinate: %s", exc)
    if held:
        log.info("Keeping the computer awake while the collection runs (a critical battery or a closed lid can still put it to sleep)")
    try:
        yield held
    finally:
        if held and platform == "win32":
            try:
                (set_state or _windows_set_state())(ES_CONTINUOUS)          # back to normal: the computer may sleep again
            except Exception:
                pass
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
