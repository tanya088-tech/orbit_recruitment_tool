"""Date helpers for the formats LinkedIn shows.

IMPORTANT: LinkedIn's public pages give only
  * a calendar date (the <time datetime="2026-10-05"> attribute), and
  * a relative age ("17 minutes ago", "5 hours ago", "2 days ago").
Relative ages are rounded DOWN by LinkedIn ("2 days ago" = 2 to <3 days), so turning
one into a calendar date by subtraction can be off by a day. Prefer the datetime
attribute; use relative text only for sub-day precision or as a last resort.
All "today" calculations use UTC, never the machine's local date.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_RELATIVE = re.compile(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", re.I)
_DAYS_PER_UNIT = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
_UNIT_SECONDS = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000, "year": 31536000}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def parse_iso_datetime(value: object) -> Optional[datetime]:
    """'2026-10-06T08:30:00.000Z' -> aware UTC datetime. Date-only strings return None."""
    if not value:
        return None
    text = str(value).strip()
    if "T" not in text and " " not in text:
        return None
    text = re.sub(r"Z$", "+00:00", text)
    text = re.sub(r"\.(\d{1,6})\d*", lambda m: "." + m.group(1).ljust(6, "0"), text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_relative_age(value: object) -> Optional[tuple[int, str]]:
    """'17 minutes ago' -> (17, 'minute'); 'Just now' -> (0, 'minute'); unknown -> None."""
    if not value:
        return None
    low = str(value).strip().lower()
    if "just now" in low or low in {"today", "now"}:
        return (0, "minute")
    if "yesterday" in low:
        return (1, "day")
    m = _RELATIVE.search(low)
    if m:
        return (int(m[1]), m[2].lower())
    return None


def relative_age_seconds(age: tuple[int, str]) -> int:
    return age[0] * _UNIT_SECONDS[age[1]]


def parse_posted_date(value: object, today: Optional[date] = None) -> Optional[date]:
    """'2026-10-05', '2026-10-05T10:00:00Z' -> date. Relative text -> approximate date (last resort)."""
    if not value:
        return None
    text = str(value).strip()
    m = _ISO_DATE.match(text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    age = parse_relative_age(text)
    if age is None:
        return None
    today = today or utc_today()
    value_, unit = age
    return today - timedelta(days=value_ * _DAYS_PER_UNIT[unit])


def is_within_days(posted: Optional[date], days: int, today: Optional[date] = None) -> bool:
    """Unknown dates are kept (we can't prove they are too old)."""
    if posted is None:
        return True
    today = today or utc_today()
    return (today - posted).days <= days
