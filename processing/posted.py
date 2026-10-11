"""Posted-within-last-24-hours decision, with honest precision labels.

What LinkedIn's PUBLIC pages actually provide (no login):
  * the calendar date in <time datetime="YYYY-MM-DD">  - a date, never a time
  * a relative age such as "17 minutes ago" / "5 hours ago" / "2 days ago"
  * (rarely) an exact ISO timestamp in structured data - used when present

So an exact "24 hours" window is NOT knowable for most jobs. This module therefore:

  1. exact timestamp present          -> exact check              (certainty: confirmed)
  2. "N minutes/hours ago"            -> posted_at ~= collected_at - N; check age at the
                                         filter time <= 24h        (certainty: estimated, +/- 1 unit)
  3. "N days/weeks/... ago" (N >= 1)  -> LinkedIn rounds down, so the job is >= 24h old: FAIL
  4. calendar date only               -> same UTC date as the filter run: pass (estimated);
                                         previous date: AMBIGUOUS (fails unless
                                         include_ambiguous_date=True, then certainty "uncertain");
                                         older: fail
  5. nothing usable                   -> fail ("posting date unavailable")

`collected_at` is used ONLY as the clock the relative text was read against - it is never
treated as the posting date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup

from utils.dates import parse_iso_datetime, parse_posted_date, parse_relative_age, relative_age_seconds

WINDOW_HOURS = 24


@dataclass
class PostingEvidence:
    timestamp: Optional[datetime]
    age: Optional[tuple[int, str]]
    age_text: Optional[str]
    card_date: Optional[date]
    reference: Optional[datetime]       # when the relative text was read (collected_at)


@dataclass
class PostedResult:
    passed: bool
    code: str            # ok | posted_older_than_24h | posted_date_ambiguous | posted_unavailable
    reason: str
    posted_at: Optional[str]     # ISO datetime, or YYYY-MM-DD when only the date is known
    precision: str       # exact_timestamp | estimated_from_relative_minutes/hours | relative_days | date_only | unknown
    certainty: str       # confirmed | estimated | uncertain | unknown
    age_text: Optional[str]


def _card_time_from_raw(job: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Legacy support: pull (datetime attr, visible text) from the saved search-card HTML."""
    html = (job.get("raw") or {}).get("search_card_html")
    if not html:
        return None, None
    tag = BeautifulSoup(html, "lxml").select_one("time")
    if not tag:
        return None, None
    return tag.get("datetime"), " ".join(tag.get_text(" ", strip=True).split()) or None


def extract_evidence(job: dict[str, Any]) -> PostingEvidence:
    card_attr, card_text = _card_time_from_raw(job)
    age_text = job.get("posted_age_text") or card_text
    # The card's datetime attribute is LinkedIn's own date. Older Phase 1 files stored a
    # relative-text guess (sometimes a day off) in posted_date, so prefer the raw attribute.
    card_date = parse_posted_date(card_attr) if card_attr else None
    if card_date is None:
        card_date = parse_posted_date(job.get("posted_date")) if job.get("posted_date") else None
    return PostingEvidence(
        timestamp=parse_iso_datetime(job.get("posted_timestamp")),
        age=parse_relative_age(age_text),
        age_text=age_text,
        card_date=card_date,
        reference=parse_iso_datetime(job.get("collected_at")),
    )


def evaluate_posting(
    job: dict[str, Any],
    as_of: Optional[datetime] = None,
    include_ambiguous_date: bool = False,
    window_hours: int = WINDOW_HOURS,
) -> PostedResult:
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ev = extract_evidence(job)
    window = timedelta(hours=window_hours)

    # 1) exact timestamp
    if ev.timestamp:
        age = max(as_of - ev.timestamp, timedelta(0))
        ok = age <= window
        return PostedResult(ok, "ok" if ok else "posted_older_than_24h",
                            f"exact posting time {ev.timestamp.isoformat()} ({age.total_seconds()/3600:.1f}h old)",
                            ev.timestamp.isoformat(timespec="seconds"), "exact_timestamp", "confirmed", ev.age_text)

    # 2) / 3) relative age text
    if ev.age:
        n, unit = ev.age
        if unit in ("minute", "hour"):
            reference = ev.reference or as_of
            posted_at = reference - timedelta(seconds=relative_age_seconds(ev.age))
            age = max(as_of - posted_at, timedelta(0))
            ok = age <= window
            return PostedResult(
                ok, "ok" if ok else "posted_older_than_24h",
                f"'{ev.age_text}' at collection; estimated {age.total_seconds()/3600:.1f}h old at filter time (+/- 1 {unit})",
                posted_at.isoformat(timespec="seconds"), f"estimated_from_relative_{unit}s", "estimated", ev.age_text)
        # day or longer: LinkedIn rounds down, so >= 24h old
        if ev.card_date:
            posted_at, precision = ev.card_date.isoformat(), "date_only"
        else:
            posted_at = ((ev.reference or as_of) - timedelta(seconds=relative_age_seconds(ev.age))).date().isoformat()
            precision = "relative_days"
        return PostedResult(False, "posted_older_than_24h",
                            f"posted '{ev.age_text}' - at least 24h old (LinkedIn rounds relative ages down)",
                            posted_at, precision, "estimated", ev.age_text)

    # 4) calendar date only
    if ev.card_date:
        today = as_of.date()
        iso = ev.card_date.isoformat()
        if ev.card_date >= today:
            return PostedResult(True, "ok", f"only a calendar date ({iso}); same UTC day as filter run",
                                iso, "date_only", "estimated", ev.age_text)
        if ev.card_date == today - timedelta(days=1):
            if include_ambiguous_date:
                return PostedResult(True, "ok", f"only a calendar date ({iso}, yesterday); 24h cannot be confirmed - included by option",
                                    iso, "date_only", "uncertain", ev.age_text)
            return PostedResult(False, "posted_date_ambiguous",
                                f"only a calendar date ({iso}, yesterday) - cannot confirm it is within 24h",
                                iso, "date_only", "uncertain", ev.age_text)
        return PostedResult(False, "posted_older_than_24h", f"posted on {iso} (older than 24h)",
                            iso, "date_only", "estimated", ev.age_text)

    # 5) nothing
    return PostedResult(False, "posted_unavailable", "posting date unavailable", None, "unknown", "unknown", ev.age_text)
