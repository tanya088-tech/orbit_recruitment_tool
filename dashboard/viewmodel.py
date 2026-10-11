"""Dashboard logic with NO HTML: turns stored vacancies into rows, applies filters, sorts,
counts and paginates. Everything shown comes from the Phase 2 record - nothing is invented.

Posting time honesty
  Phase 2 stores `posted_at` as either an ISO datetime (exact or estimated from LinkedIn's
  relative text) or a bare YYYY-MM-DD (LinkedIn gave only a calendar date). We keep that
  distinction: a date-only job is never shown as if it had a time.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlencode, urlsplit

from config import settings
from dashboard.regions import build_region_resolver
from processing.description_sections import extract_designation
from processing.industry import classify_industry
from processing.normalize import clean_company, clean_location
from processing.work_mode import FILTER_WORK_MODES, UNKNOWN, work_mode_for   # Phase 2 work-mode rules (reused)
from store.base import DEFAULT_STATUS, STATUSES
from utils.dates import parse_iso_datetime

UTC = timezone.utc
POSTED_OPTIONS: dict[str, Optional[int]] = {"24h": 24, "3d": 72, "7d": 168, "15d": 360, "1m": 720, "all": None}
POSTED_LABELS = {"24h": "Last 24 hours", "3d": "Last 3 days", "7d": "Last 7 days",
                 "15d": "Last 15 days", "1m": "Last 1 month", "all": "All"}
SCOPE_OPTIONS = ["india", "outside", "all"]
SCOPE_LABELS = {"india": "Within India", "outside": "Outside India", "all": "All locations"}
EMPLOYMENT_OPTIONS = ["all", "Permanent", "Contract"]
EMPLOYMENT_LABELS = {"all": "All", "Permanent": "Permanent", "Contract": "Contract"}
WORK_MODE_OPTIONS = ["all"] + FILTER_WORK_MODES           # All, On-site, Hybrid, Remote (Unknown jobs show under All)
WORK_MODE_LABELS = {"all": "All", **{m: m for m in FILTER_WORK_MODES}}
SORT_LABELS = {
    "recent": "Most recently posted", "oldest": "Oldest posted",
    "title": "Job title A to Z", "company": "Company A to Z",
}
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RING_WINDOW_HOURS = 24


# ---------------------------------------------------------------- posting time
@dataclass(frozen=True)
class Posted:
    moment: Optional[datetime]     # an instant (exact, or estimated from relative text), UTC
    day: Optional[date]            # set instead when LinkedIn gave only a calendar date
    precision: str                 # exact_timestamp | estimated_from_relative_* | date_only | ... | unknown

    @property
    def known(self) -> bool:
        return self.moment is not None or self.day is not None

    @property
    def estimated(self) -> bool:
        return self.precision.startswith("estimated")


def parse_posted(record: Mapping[str, Any]) -> Posted:
    raw = record.get("posted_at")
    precision = str(record.get("posted_at_precision") or "unknown")
    if not raw:
        return Posted(None, None, precision)
    text = str(raw).strip()
    if _DATE_ONLY.match(text):
        try:
            return Posted(None, date.fromisoformat(text), precision)
        except ValueError:
            return Posted(None, None, precision)
    moment = parse_iso_datetime(text)
    return Posted(moment, None, precision) if moment else Posted(None, None, precision)


def posted_sort_key(p: Posted) -> datetime:
    if p.moment:
        return p.moment
    if p.day:
        return datetime.combine(p.day, time.min, tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def age_hours(p: Posted, now: datetime) -> Optional[float]:
    if not p.moment:
        return None
    return max((now - p.moment).total_seconds() / 3600.0, 0.0)


def is_within(p: Posted, now: datetime, hours: int) -> bool:
    """True only when the job is certainly inside the window.

    For a date-only job the post could be anywhere on that UTC day, so it counts as inside
    a window of `hours` only if even the end of that day is still inside the window.
    """
    if p.moment:
        return age_hours(p, now) <= hours
    if p.day:
        return (now.date() - p.day).days <= hours / 24 - 1
    return False


def freshness(p: Posted, now: datetime) -> str:
    """just_posted (<1h) | fresh (<6h) | today (<24h) | recent (<72h) | older | unknown"""
    h = age_hours(p, now)
    if h is not None:
        return "just_posted" if h < 1 else "fresh" if h < 6 else "today" if h < 24 else "recent" if h < 72 else "older"
    if p.day:
        days = (now.date() - p.day).days
        return "today" if days <= 0 else "recent" if days <= 2 else "older"
    return "unknown"


def ring_fraction(p: Posted, now: datetime) -> float:
    """0..1 for the freshness ring: full = just posted, empty = 24h or more. Date-only -> 0."""
    h = age_hours(p, now)
    if h is None:
        return 0.0
    return round(max(0.0, 1.0 - h / RING_WINDOW_HOURS), 3)


def to_display_tz(dt: datetime) -> datetime:
    return dt.astimezone(timezone(timedelta(minutes=settings.DISPLAY_UTC_OFFSET_MINUTES)))


def format_age(p: Posted, now: datetime) -> str:
    h = age_hours(p, now)
    if h is not None:
        minutes = int(h * 60)
        plural = lambda n, unit: f"{n} {unit}{'' if n == 1 else 's'} ago"
        if minutes < 1:
            text = "just now"
        elif minutes < 60:
            text = plural(minutes, "minute")
        elif h < 48:
            text = plural(int(h), "hour")
        else:
            text = plural(int(h // 24), "day")
        return ("about " + text) if (p.estimated and minutes >= 1) else text
    if p.day:
        return f"{p.day.day} {p.day:%b %Y}"
    return "Not available"


def format_precision(p: Posted) -> str:
    if p.moment and p.precision == "exact_timestamp":
        return "exact time"
    if p.moment:
        return "estimated time"
    if p.day:
        return "date only"
    return ""


def format_moment(p: Posted) -> str:
    """Full local timestamp for the details page, e.g. '8 Oct 2026, 15:03 IST'."""
    if p.moment:
        local = to_display_tz(p.moment)
        return f"{local.day} {local:%b %Y, %H:%M} {settings.DISPLAY_TZ_LABEL}"
    if p.day:
        return f"{p.day.day} {p.day:%b %Y} (no time available)"
    return "Not available"


def safe_http_url(url: Any) -> Optional[str]:
    """Only http(s) links are ever rendered as links (blocks javascript: and similar)."""
    if not url:
        return None
    text = str(url).strip()
    parts = urlsplit(text)
    return text if parts.scheme.lower() in ("http", "https") and parts.netloc else None


# ---------------------------------------------------------------- rows
@dataclass
class Row:
    key: str
    title: Optional[str]
    company: Optional[str]
    company_url: Optional[str]
    location: Optional[str]
    state: str                     # the state, only when the data shows one
    country: Optional[str]
    industry: str                  # category from the source's industry label, or Unknown / Other
    industry_label: Optional[str]  # the source's own wording
    employment_type: Optional[str]
    work_mode: str                 # On-site | Hybrid | Remote | Unknown
    posted: Posted
    source: Optional[str]
    job_id: Optional[str]
    job_url: Optional[str]
    description: Optional[str]
    designation: Optional[str]
    designation_from_seniority: bool
    job_role: Optional[str]
    recruiter_name: Optional[str]
    recruiter_email: Optional[str]
    recruiter_phone: Optional[str]
    contact_url: Optional[str]
    is_new: bool
    status: str
    saved: bool
    notes: list[dict[str, Any]]
    first_ingested_at: Optional[str]
    last_seen_at: Optional[str]
    times_seen: int
    designation_source: str = ""             # source | description | seniority | "" (not available)
    experience_structured: Optional[str] = None   # JSON-LD experienceRequirements, when the page had it
    education_structured: Optional[str] = None

    @property
    def in_india(self) -> bool:
        return self.country == "India"

    @property
    def display_title(self) -> str:
        return self.title or "Untitled vacancy"

    @property
    def scope(self) -> str:
        """india | outside | unknown (the location was missing or not recognised)."""
        return "india" if self.country == "India" else "outside" if self.country else "unknown"


def _clean(value: Any) -> Optional[str]:
    text = " ".join(str(value).split()) if value not in (None, "") else ""
    return text or None


def _seniority(value: Any) -> Optional[str]:
    """LinkedIn's 'Seniority level' stands in for the designation; its 'Not Applicable' filler is not a value."""
    text = _clean(value)
    return None if text is None or text.lower() in ("not applicable", "n/a", "none") else text


def build_rows(jobs: list[dict[str, Any]], states: Mapping[str, Mapping[str, Any]],
               latest_run_id: Optional[str]) -> list[Row]:
    rows = []
    # Learn state names only from India jobs (a "Hyderabad, Sindh, Pakistan" must not teach Hyderabad -> Sindh).
    resolve_region = build_region_resolver(
        clean_location((e.get("record") or {}).get("location")) for e in jobs if (e.get("record") or {}).get("country") == "India")
    for entry in jobs:
        rec = entry.get("record") or {}
        st = states.get(entry.get("key"), {})
        status = st.get("status") if st.get("status") in STATUSES else DEFAULT_STATUS
        location = clean_location(rec.get("location"))
        industry = classify_industry(rec.get("industries"))
        # Designation: the source's own field, else the "Designation:" / "Role/Job Title:" line of the posting,
        # else LinkedIn's seniority level (its "Not Applicable" filler is not a value).
        d_source, d_desc, d_sen = _clean(rec.get("designation")), extract_designation(rec.get("description")), _seniority(rec.get("seniority_level"))
        designation, d_from = (d_source, "source") if d_source else (d_desc, "description") if d_desc else (d_sen, "seniority") if d_sen else (None, "")
        rows.append(Row(
            key=entry["key"], title=(rec.get("title") or "").strip() or None,
            company=clean_company(rec.get("company")),
            company_url=safe_http_url(rec.get("company_url")), location=location,
            state=resolve_region.state(location) if rec.get("country") == "India" else "", country=rec.get("country"),
            industry=industry.category, industry_label=industry.label,
            employment_type=rec.get("employment_type") or None,
            work_mode=work_mode_for(rec),
            posted=parse_posted(rec),
            source=rec.get("source") or None, job_id=str(rec["job_id"]) if rec.get("job_id") else None,
            job_url=safe_http_url(rec.get("job_url")), description=(rec.get("description") or "").strip() or None,
            designation=designation, designation_from_seniority=d_from == "seniority", designation_source=d_from,
            experience_structured=_clean(rec.get("experience_requirements")),
            education_structured=_clean(rec.get("education_requirements")),
            job_role=_clean(rec.get("job_role")) or _clean(rec.get("job_function")),
            recruiter_name=_clean(rec.get("recruiter_name")), recruiter_email=_clean(rec.get("recruiter_email")),
            recruiter_phone=_clean(rec.get("recruiter_phone")), contact_url=_clean(rec.get("contact_url")),
            is_new=bool(latest_run_id) and entry.get("first_seen_run_id") == latest_run_id,
            status=status, saved=bool(st.get("saved")), notes=list(st.get("notes") or []),
            first_ingested_at=entry.get("first_ingested_at"), last_seen_at=entry.get("last_seen_at"),
            times_seen=int(entry.get("times_seen") or 1),
        ))
    return rows


# ---------------------------------------------------------------- filters
@dataclass
class Filters:
    scope: str = "india"
    employment: str = "all"
    source: str = ""
    posted: str = "all"
    work_mode: str = "all"
    sort: str = "recent"
    page: int = 1
    view: str = "latest"          # "latest" = only the vacancies from the last "N vacancies" request (when there is one); "all" = everything

    @classmethod
    def from_query(cls, params: Mapping[str, Any]) -> "Filters":
        def first(name: str) -> str:
            v = params.get(name, "")
            if isinstance(v, (list, tuple)):
                v = v[0] if v else ""
            return " ".join(str(v).split())[:100]

        f = cls()
        f.scope = first("scope") if first("scope") in SCOPE_OPTIONS else "india"
        f.employment = first("employment") if first("employment") in EMPLOYMENT_OPTIONS else "all"
        f.source = first("source")
        f.posted = first("posted") if first("posted") in POSTED_OPTIONS else "all"
        f.work_mode = first("work_mode") if first("work_mode") in WORK_MODE_OPTIONS else "all"
        f.sort = first("sort") if first("sort") in SORT_LABELS else "recent"
        f.view = "all" if first("view") == "all" else "latest"
        try:
            f.page = max(1, int(first("page") or 1))
        except ValueError:
            f.page = 1
        return f

    def to_query(self, **overrides: Any) -> str:
        """Query string holding only non-default values (so URLs stay short)."""
        merged = {**self.__dict__, **overrides}
        defaults = Filters().__dict__
        pairs = [(k, str(v)) for k, v in merged.items() if v != defaults[k]]
        return urlencode(pairs)

    @property
    def active_count(self) -> int:
        d = Filters().__dict__
        return sum(1 for k in ("scope", "employment", "source", "posted", "work_mode") if getattr(self, k) != d[k])


def apply_filters(rows: list[Row], f: Filters, now: datetime) -> list[Row]:
    out = []
    for r in rows:
        if f.scope == "india" and r.scope != "india":
            continue
        if f.scope == "outside" and r.scope != "outside":
            continue
        if f.employment != "all" and r.employment_type != f.employment:
            continue
        if f.source and (r.source or "").lower() != f.source.lower():
            continue
        if f.posted != "all" and not is_within(r.posted, now, POSTED_OPTIONS[f.posted]):
            continue
        if f.work_mode != "all" and r.work_mode != f.work_mode:
            continue
        out.append(r)
    return out


def sort_rows(rows: list[Row], sort: str) -> list[Row]:
    by_title = lambda r: (r.title or "").lower()
    if sort == "oldest":
        known = sorted([r for r in rows if r.posted.known], key=lambda r: (posted_sort_key(r.posted), by_title(r)))
        return known + sorted([r for r in rows if not r.posted.known], key=by_title)
    if sort in ("title", "company"):
        getter = by_title if sort == "title" else (lambda r: (r.company or "").lower())
        present = sorted([r for r in rows if getter(r)], key=lambda r: (getter(r), by_title(r)))
        return present + [r for r in rows if not getter(r)]
    # recent (default): newest posting first; unknown posting time last; ties -> newest discovered
    return sorted(rows, key=lambda r: (posted_sort_key(r.posted), r.first_ingested_at or "", by_title(r)), reverse=True)


def summary_cards(rows: list[Row]) -> dict[str, int]:
    """Counted from the SAME rows the current filters matched, so every card follows the filters."""
    return {
        "total": len(rows),
        "permanent": sum(r.employment_type == "Permanent" for r in rows),
        "contract": sum(r.employment_type == "Contract" for r in rows),
    }


def filter_options(rows: list[Row]) -> dict[str, list[str]]:
    """Source choices come from the data, so a newly added source appears without any dashboard change."""
    seen: dict[str, str] = {}
    for r in rows:
        if r.source:
            seen.setdefault(r.source.lower(), r.source)
    return {"sources": sorted(seen.values(), key=str.lower)}


@dataclass
class Page:
    rows: list[Row]
    page: int
    pages: int
    total: int
    start: int = 0
    end: int = 0


def paginate(rows: list[Row], page: int, size: int = 0) -> Page:
    size = size or settings.DASHBOARD_PAGE_SIZE
    total = len(rows)
    pages = max(1, math.ceil(total / size))
    page = min(max(1, page), pages)
    chunk = rows[(page - 1) * size: page * size]
    return Page(chunk, page, pages, total, (page - 1) * size + 1 if chunk else 0, (page - 1) * size + len(chunk))
