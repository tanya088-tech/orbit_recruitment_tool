"""The Groxa AI logo for the dashboard header.

The official logo lives on the Groxa AI website. The dashboard downloads it once, on the computer
running the dashboard, and keeps a local copy in dashboard/static/. If the download is not possible
(no internet, site unreachable, not a PNG) the header shows a text-only "Powered by Groxa AI".

Only the fixed address below is ever requested - never anything typed into the dashboard.
"""
from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)
LOGO_URL = "https://www.groxaai.com/GLogo-cropped.png"
SITE_URL = "https://www.groxaai.com/"
LOGO_FILE = "groxa-logo.png"
MAX_BYTES = 2_000_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AceTalentJobRadar/1.0 (logo fetch)"})
    with urllib.request.urlopen(req, timeout=8) as resp:            # noqa: S310 - fixed https URL
        return resp.read(MAX_BYTES + 1)


def logo_path(static_dir: Path) -> Path:
    return Path(static_dir) / LOGO_FILE


def logo_available(static_dir: Path) -> bool:
    p = logo_path(static_dir)
    try:
        return p.is_file() and p.stat().st_size > 0 and p.read_bytes()[:8] == PNG_MAGIC
    except OSError:
        return False


def ensure_logo(static_dir: Path, fetch: Callable[[str], bytes] = _download, url: str = LOGO_URL) -> Optional[Path]:
    """Make sure a local copy exists. Returns its path, or None when it could not be fetched."""
    target = logo_path(static_dir)
    if logo_available(static_dir):
        return target
    try:
        data = fetch(url)
        if not data.startswith(PNG_MAGIC) or len(data) > MAX_BYTES:
            raise ValueError("the downloaded file is not a PNG image of a sensible size")
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        log.info("Saved the Groxa AI logo to %s", target)
        return target
    except Exception as exc:                                         # offline etc.: fall back to the text mark
        log.info("Groxa AI logo not available (%s). The header will show text only.", exc)
        return None
