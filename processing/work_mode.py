"""Work mode (On-site / Hybrid / Remote / Unknown) from explicit wording only.

Deterministic, no AI. A mode is reported only when the source text actually says it:
  * "Hybrid"                                   -> Hybrid
  * "Remote", "Work from home", "WFH",
    "Telecommute"                              -> Remote
  * "On-site", "Onsite", "In office",
    "Work from office"                         -> On-site
  * anything else (including a plain city, or no location at all) -> Unknown

If more than one appears, Hybrid wins (it names a mix), then Remote, then On-site.
Nothing is inferred from the city, from a missing location, or from the job description.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

ON_SITE, HYBRID, REMOTE, UNKNOWN = "On-site", "Hybrid", "Remote", "Unknown"
WORK_MODES = [ON_SITE, HYBRID, REMOTE, UNKNOWN]
FILTER_WORK_MODES = [ON_SITE, HYBRID, REMOTE]          # what the dashboard filter offers (Unknown shows under All)

_HYBRID = re.compile(r"\bhybrid\b")
_REMOTE = re.compile(r"\b(remote|work from home|wfh|telecommute|telecommuting|work from anywhere)\b")
_ONSITE = re.compile(r"\b(on site|onsite|in office|work from office|office based)\b")


@dataclass(frozen=True)
class WorkModeResult:
    mode: str
    evidence: Optional[str]      # the exact words that decided it


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def classify_work_mode(*texts: Any) -> WorkModeResult:
    """texts: the source's own location / workplace-type strings (None and blanks are ignored)."""
    joined = " | ".join(_norm(t) for t in texts if t and str(t).strip())
    for mode, pattern in ((HYBRID, _HYBRID), (REMOTE, _REMOTE), (ON_SITE, _ONSITE)):
        m = pattern.search(joined)
        if m:
            return WorkModeResult(mode, m.group(0))
    return WorkModeResult(UNKNOWN, None)


def source_work_mode_texts(job: Mapping[str, Any]) -> list[Any]:
    """The places a source can state work mode: the location, an explicit workplace-type field,
    and schema.org `jobLocationType` (TELECOMMUTE) when LinkedIn included it in the page data."""
    raw = job.get("raw") or job.get("raw_data") or {}
    json_ld = raw.get("json_ld") if isinstance(raw, Mapping) else None
    return [job.get("location"), job.get("workplace_type"), job.get("work_mode_text"),
            json_ld.get("jobLocationType") if isinstance(json_ld, Mapping) else None]


def work_mode_for(job: Mapping[str, Any]) -> str:
    """Stored `work_mode` if valid, otherwise worked out from the record (older history files have none)."""
    stored = job.get("work_mode")
    if stored in WORK_MODES:
        return stored
    return classify_work_mode(*source_work_mode_texts(job)).mode
