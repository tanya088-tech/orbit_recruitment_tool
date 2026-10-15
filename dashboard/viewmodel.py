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
from dashboard.regions import build_region_resolver, indian_state
from processing.description_sections import extract_designation
from processing.classifier import classify
from processing.contacts import poster_contacts
from processing.industry import classify_industry
from processing.location import check_location
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
CONTACT_OPTIONS = ["all", "yes", "no"]
CONTACT_LABELS = {"all": "All", "yes": "Yes", "no": "No"}
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
    """How long ago, the same way for every source: "Just now" or "N hours ago" inside 24 hours, then "1 day ago",
    "2 days ago"... Worked out from the actual posting time when there is one; a date-only posting is counted in whole
    calendar days ("Today" when the date is today, because no hour can be known)."""
    plural = lambda n, unit: f"{n} {unit}{'' if n == 1 else 's'} ago"
    h = age_hours(p, now)
    if h is not None:
        if h < 1:
            return "Just now"
        if h < 24:
            return plural(int(h), "hour")
        return plural(int(h // 24), "day")
    if p.day:
        days = (now.date() - p.day).days
        return "Today" if days <= 0 else plural(days, "day")
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
    contact_phones: list = field(default_factory=list)    # phone numbers the posting (or the stored record) states
    contact_emails: list = field(default_factory=list)
    contact_urls: list = field(default_factory=list)
    contact_linkedin: Optional[str] = None                # LinkedIn profile link written in the posting
    contact_direct: bool = False                          # True = a way to reach someone is stated in the posting itself
    state_name: str = ""                     # official Indian state / UT of a confidently-India location ("" = none shown)
    designation_source: str = ""             # source | description | seniority | "" (not available)
    also_listed_on: list = field(default_factory=list)   # [{"source","job_id","job_url"}] the same vacancy on other sources
    salary: Optional[str] = None
    skills: list = field(default_factory=list)
    experience_text: Optional[str] = None      # the source's own experience field (e.g. Naukri "5-10 Yrs")
    openings: Optional[str] = None
    applicants: Optional[str] = None
    education: Optional[str] = None
    role_category: Optional[str] = None
    posted_by: Optional[str] = None
    employment_details: Optional[str] = None
    company_website: Optional[str] = None      # Naukri: the company's official website, as Naukri states it
    company_linkedin: Optional[str] = None     # LinkedIn: the company's LinkedIn page (verified /company/ link)
    company_link_note: str = ""                # "" = from this job's own posting; otherwise where it was taken from
    experience_structured: Optional[str] = None   # JSON-LD experienceRequirements, when the page had it
    education_structured: Optional[str] = None
    company_rating: Optional[str] = None       # Naukri only; blank for LinkedIn and for records collected before this existed
    company_reviews: Optional[str] = None
    potential_gcc: bool = False                # strict GCC evidence (processing/classifier.py)
    potential_bfsi: bool = False               # strict BFSI evidence
    category_reason: str = ""

    @property
    def category(self) -> str:
        return " + ".join(n for n, on in (("GCC", self.potential_gcc), ("BFSI", self.potential_bfsi)) if on)

    @property
    def all_sources(self) -> list[str]:
        """Every source this vacancy was found on, the first one that recorded it first."""
        out: list[str] = []
        for name in [self.source] + [a.get("source") for a in self.also_listed_on if isinstance(a, dict)]:
            if name and name.lower() not in [x.lower() for x in out]:
                out.append(name)
        return out

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


_RATING_OK = re.compile(r"^(?:[0-4](?:\.\d)?|5(?:\.0)?)$")
_REVIEWS_OK = re.compile(r"^\d[\d,]*(?:\.\d+)?[KkMm]?$")


def _valid_rating(value: Any) -> Optional[str]:
    text = _clean(value)
    return text if text and _RATING_OK.match(text) else None


def _valid_reviews(value: Any) -> Optional[str]:
    text = _clean(value)
    return text.upper() if text and _REVIEWS_OK.match(text) else None


def format_company_reviews(rating: Optional[str], reviews: Optional[str]) -> str:
    """"3.7 ★ (689 reviews)"; only what the source gave is shown; "" when it gave neither (LinkedIn, older records)."""
    if rating and reviews:
        return f"{rating} \u2605 ({reviews} review{'' if reviews == '1' else 's'})"
    if rating:
        return f"{rating} \u2605"
    if reviews:
        return f"{reviews} review{'' if reviews == '1' else 's'}"
    return ""


def _seniority(value: Any) -> Optional[str]:
    """LinkedIn's 'Seniority level' stands in for the designation; its 'Not Applicable' filler is not a value."""
    text = _clean(value)
    return None if text is None or text.lower() in ("not applicable", "n/a", "none") else text


_NO_SHARING = {"", "confidential", "confidential company", "undisclosed", "not disclosed", "company confidential"}
_LI_COMPANY = re.compile(r"^/company/([A-Za-z0-9][A-Za-z0-9._%~-]{0,99})/?$")


def _company_key(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _site_key(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.lower()).split("?")[0].split("#")[0].rstrip("/")


def linkedin_company_page(url: Any) -> Optional[str]:
    """Canonical https://www.linkedin.com/company/<slug> for a LinkedIn company page, else None.

    Only a real company page counts: not a person (/in/), school, showcase page, job search or any other site. Regional hosts
    (in., uk., sg. ...) and tracking parameters are dropped so the same company always gives the same link."""
    safe = safe_http_url(url)
    if not safe:
        return None
    parts = urlsplit(safe)
    host = parts.netloc.lower().split(":")[0]
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    m = _LI_COMPANY.match(parts.path)
    return f"https://www.linkedin.com/company/{m.group(1).lower()}" if m else None


def _share_company_links(rows: list["Row"]) -> None:
    """Fill the company link only from what a source itself stated, and only when it is unambiguous.

    LinkedIn jobs: the page is the company link LinkedIn put on the posting (checked to be a real /company/ page).
      A job without one reuses it from another LinkedIn job of the SAME company name, and only if every LinkedIn job of
      that company names the same page. If they disagree, none is shown.
    Naukri jobs: the website Naukri states; reused across Naukri jobs of the same company name only if they all agree.
    A confidential or blank company name never borrows anything. Nothing is ever guessed or searched for."""
    li: dict[str, set[str]] = {}
    web: dict[str, set[str]] = {}
    for r in rows:
        key = _company_key(r.company)
        if key in _NO_SHARING:
            continue
        if (r.source or "").lower() == "linkedin" and r.company_linkedin:
            li.setdefault(key, set()).add(r.company_linkedin)
        if (r.source or "").lower() != "linkedin" and r.company_website:
            web.setdefault(key, set()).add(r.company_website)
    for r in rows:
        key = _company_key(r.company)
        if key in _NO_SHARING:
            continue
        if (r.source or "").lower() == "linkedin":
            if r.company_linkedin and len(li.get(key, ())) > 1:
                r.company_linkedin, r.company_link_note = None, ""             # LinkedIn jobs of this company name disagree: unverified
            elif not r.company_linkedin and len(li.get(key, ())) == 1:
                r.company_linkedin, r.company_link_note = next(iter(li[key])), "Taken from another LinkedIn job of this company"
        elif not r.company_website and len(web.get(key, ())) == 1:
            r.company_website, r.company_link_note = next(iter(web[key])), "Taken from another listing of this company"


def assess_record(rec: Mapping[str, Any]):
    """The strict GCC/BFSI verdict for one stored record (same rules as collection)."""
    return classify(rec.get("company"), rec.get("title"), rec.get("description"), rec.get("industries"),
                    posted_by=rec.get("posted_by"), company_url=rec.get("company_url"))


def build_rows(jobs: list[dict[str, Any]], states: Mapping[str, Mapping[str, Any]],
               latest_run_id: Optional[str], only_gcc_bfsi: Optional[bool] = None) -> list[Row]:
    """Rows for the dashboard. With only_gcc_bfsi (default: settings.DISPLAY_ONLY_GCC_BFSI) a stored job that
    does not pass the strict rules is left out of the view - it stays in the history file untouched."""
    if only_gcc_bfsi is None:
        only_gcc_bfsi = settings.DISPLAY_ONLY_GCC_BFSI
    rows = []
    # Learn state names only from India jobs (a "Hyderabad, Sindh, Pakistan" must not teach Hyderabad -> Sindh).
    resolve_region = build_region_resolver(
        clean_location((e.get("record") or {}).get("location")) for e in jobs if (e.get("record") or {}).get("country") == "India")
    for entry in jobs:
        rec = entry.get("record") or {}
        verdict = assess_record(rec)
        if only_gcc_bfsi and not verdict.eligible:
            continue
        st = states.get(entry.get("key"), {})
        status = st.get("status") if st.get("status") in STATUSES else DEFAULT_STATUS
        location = clean_location(rec.get("location"))
        # India / outside India is decided from the job's own location text each time (never from the company's head office);
        # a missing, unrecognised or two-country location is "unknown" and appears under neither India nor Outside India.
        country = check_location(location).country if location else None
        industry = classify_industry(rec.get("industries"))
        # Designation: the source's own field, else the "Designation:" / "Role/Job Title:" line of the posting,
        # else LinkedIn's seniority level (its "Not Applicable" filler is not a value).
        d_source, d_desc, d_sen = _clean(rec.get("designation")), extract_designation(rec.get("description")), _seniority(rec.get("seniority_level"))
        designation, d_from = (d_source, "source") if d_source else (d_desc, "description") if d_desc else (d_sen, "seniority") if d_sen else (None, "")
        rows.append(Row(
            key=entry["key"], title=(rec.get("title") or "").strip() or None,
            company=clean_company(rec.get("company")),
            company_url=safe_http_url(rec.get("company_url")), location=location,
            state=resolve_region.state(location) if country == "India" else "", country=country,
            state_name=indian_state(location, resolve_region.state) if country == "India" else "",
            industry=industry.category, industry_label=industry.label,
            employment_type=rec.get("employment_type") or None,
            work_mode=work_mode_for(rec),
            posted=parse_posted(rec),
            source=rec.get("source") or None, job_id=str(rec["job_id"]) if rec.get("job_id") else None,
            job_url=safe_http_url(rec.get("job_url")), description=(rec.get("description") or "").strip() or None,
            also_listed_on=[a for a in (rec.get("also_listed_on") or []) if isinstance(a, dict)],
            salary=_clean(rec.get("salary")),
            skills=[str(x).strip() for x in (rec.get("skills") or []) if str(x).strip()][:40] if isinstance(rec.get("skills"), (list, tuple)) else [],
            experience_text=_clean(rec.get("experience")),
            openings=_clean(rec.get("openings")), applicants=_clean(rec.get("applicants")), education=_clean(rec.get("education")),
            role_category=_clean(rec.get("role_category")), posted_by=_clean(rec.get("posted_by")),
            employment_details=_clean(rec.get("employment_details")), company_website=safe_http_url(rec.get("company_website")),
            company_linkedin=linkedin_company_page(rec.get("company_url")),
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
            company_rating=_valid_rating(rec.get("company_rating")), company_reviews=_valid_reviews(rec.get("company_reviews")),
            potential_gcc=verdict.potential_gcc, potential_bfsi=verdict.potential_bfsi, category_reason=verdict.reason,
        ))
    for r_ in rows:
        _fill_contacts(r_)
    _share_company_links(rows)
    return rows


# ---------------------------------------------------------------- filters
@dataclass
class Filters:
    scope: str = "india"
    employment: str = "all"
    source: str = ""
    posted: str = "all"
    work_mode: str = "all"
    contact: str = "all"          # Contact Details Available: all | yes | no (what the posting itself states)
    state: str = ""               # "" = All states; otherwise an official state / UT name taken from the stored vacancies
    sort: str = "recent"
    page: int = 1
    scope_explicit: bool = field(default=False, repr=False, compare=False)   # the URL named a scope (kept in links)
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
        f.scope_explicit = first("scope") in SCOPE_OPTIONS
        f.employment = first("employment") if first("employment") in EMPLOYMENT_OPTIONS else "all"
        # Source and Job posted are chosen in the collection panel; old links carrying them are ignored (never a hidden filter).
        f.state = first("state")
        f.contact = first("contact") if first("contact") in CONTACT_OPTIONS else "all"
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
        explicit = self.scope_explicit or "scope" in overrides
        pairs = [(k, str(v)) for k, v in merged.items()
                 if k != "scope_explicit" and (v != defaults[k] or (k == "scope" and explicit))]
        return urlencode(pairs)

    @property
    def active_count(self) -> int:
        d = Filters().__dict__
        return sum(1 for k in ("scope", "employment", "state", "work_mode", "contact") if getattr(self, k) != d[k])


def apply_filters(rows: list[Row], f: Filters, now: datetime) -> list[Row]:
    out = []
    for r in rows:
        if f.scope == "india" and r.scope != "india":
            continue
        if f.scope == "outside" and r.scope != "outside":
            continue
        if f.employment != "all" and r.employment_type != f.employment:
            continue
        if f.source and f.source.lower() not in [s.lower() for s in r.all_sources]:
            continue
        if f.posted != "all" and not is_within(r.posted, now, POSTED_OPTIONS[f.posted]):
            continue
        if f.work_mode != "all" and r.work_mode != f.work_mode:
            continue
        if f.state and r.state_name.lower() != f.state.lower():
            continue
        if f.contact == "yes" and not r.contact_direct:
            continue
        if f.contact == "no" and r.contact_direct:
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
    # recent (default): newest posting first; unknown posting time last. Postings from the same recency window
    # (settings.COLLECTION_RECENCY_TOLERANCE_HOURS) show the ones that state the poster's contact details first - the same
    # rule the collection uses - then the newest. A newer window is always listed before an older one.
    tol = max(float(settings.COLLECTION_RECENCY_TOLERANCE_HOURS), 0.01) * 3600.0

    def recent_key(r: Row):
        when = posted_sort_key(r.posted)
        known = r.posted.known
        bucket = int(when.timestamp() // tol) if known else -1
        return (bucket, r.contact_direct if known else False, when, r.first_ingested_at or "", by_title(r))
    return sorted(rows, key=recent_key, reverse=True)


def summary_cards(rows: list[Row]) -> dict[str, int]:
    """Counted from the SAME rows the current filters matched, so every card follows the filters."""
    return {
        "total": len(rows),
        "permanent": sum(r.employment_type == "Permanent" for r in rows),
        "contract": sum(r.employment_type == "Contract" for r in rows),
    }


def filter_options(rows: list[Row]) -> dict[str, list[str]]:
    """Source choices come from the data, so a newly added source appears without any dashboard change."""
    seen: dict[str, str] = {s.lower(): s for s in settings.SUPPORTED_SOURCES}    # every supported source is selectable
    for r in rows:
        for name in r.all_sources:
            seen.setdefault(name.lower(), name)
    states = {r.state_name for r in rows if r.state_name}      # only states that occur in the stored vacancies
    return {"sources": sorted(seen.values(), key=str.lower), "states": sorted(states, key=str.lower)}


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


# ---------------------------------------------------------------- recruiter / contact details
# ---------------------------------------------------------------- fetch-time filters
FETCH_FILTER_KEYS = ("employment", "work_mode", "state", "contact")


def all_indian_states() -> list[str]:
    from dashboard.regions import _STATE_NAMES
    return sorted(_STATE_NAMES)


def clean_fetch_filters(raw: Optional[Mapping[str, Any]]) -> dict[str, str]:
    """Only the filters that actually narrow the collection (anything left at All / blank is dropped)."""
    raw = raw or {}
    out: dict[str, str] = {}
    emp, mode, contact = str(raw.get("employment") or ""), str(raw.get("work_mode") or ""), str(raw.get("contact") or "")
    if emp in EMPLOYMENT_OPTIONS and emp != "all":
        out["employment"] = emp
    if mode in WORK_MODE_OPTIONS and mode != "all":
        out["work_mode"] = mode
    if contact in CONTACT_OPTIONS and contact != "all":
        out["contact"] = contact
    state = " ".join(str(raw.get("state") or "").split())[:60]
    if state:
        out["state"] = state
    return out


def fetch_filter_matches(records: list[dict[str, Any]], filters: Optional[Mapping[str, str]],
                         max_age_hours: Optional[float] = None) -> list[bool]:
    """For each stored/normalized record: does it satisfy the collection filters? Uses the dashboard's own row building and
    filter rules, so a collected vacancy is shown under the same filter it was collected with."""
    if not filters and max_age_hours is None:
        return [True] * len(records)
    filters = filters or {}
    rows = build_rows([{"key": str(i), "record": rec} for i, rec in enumerate(records)], {}, None, only_gcc_bfsi=False)
    f = Filters(employment=filters.get("employment", "all"), work_mode=filters.get("work_mode", "all"),
                state=filters.get("state", ""), contact=filters.get("contact", "all"), scope="all")   # location scope is the collection's own gate
    now = datetime.now(timezone.utc)
    kept = {r.key for r in apply_filters(rows, f, now)}
    if max_age_hours is not None:                    # a posting whose own date shows it is older than the window is not a match
        for r in rows:
            if r.posted.moment and age_hours(r.posted, now) > max_age_hours + 1:
                kept.discard(r.key)
            elif not r.posted.moment and r.posted.day and (now.date() - r.posted.day).days > max_age_hours / 24:
                kept.discard(r.key)
    return [str(i) in kept for i in range(len(records))]


def saved_vacancies(entries: list[dict[str, Any]], scope: str, sources: list[str], window_hours: float,
                    filters: Optional[Mapping[str, str]], limit: Optional[int]) -> list[Row]:
    """The vacancies already stored that match a collection request: GCC/BFSI only, the chosen location scope and sources,
    certainly posted inside the window, and the same State / Employment / Work mode / Contact filters. Newest first, with
    poster-contact postings first inside the same recency window (the dashboard's own order)."""
    now = datetime.now(timezone.utc)
    rows = build_rows(entries, {}, None)
    want = {x.lower() for x in sources}
    out = []
    for r in rows:
        if scope == "india" and r.scope != "india":
            continue
        if scope == "international" and r.scope != "outside":
            continue
        if want and not (want & {x.lower() for x in r.all_sources}):
            continue
        if not is_within(r.posted, now, int(window_hours)):
            continue
        out.append(r)
    f = Filters(employment=(filters or {}).get("employment", "all"), work_mode=(filters or {}).get("work_mode", "all"),
                state=(filters or {}).get("state", ""), contact=(filters or {}).get("contact", "all"), scope="both")
    out = sort_rows(apply_filters(out, f, now), "recent")
    return out[:limit] if limit else out


def _fill_contacts(r: Row) -> None:
    """The poster's contact details as the posting itself states them (or the stored record holds). Never guessed or looked up."""
    c = poster_contacts(r.description, r.recruiter_email, r.recruiter_phone, r.recruiter_name, r.contact_url)
    r.contact_phones, r.contact_emails = list(c.phones), list(c.emails)
    r.contact_urls = list(dict.fromkeys(safe_http_url(u) for u in c.urls if safe_http_url(u)))[:3]
    r.contact_linkedin = safe_http_url(c.linkedin)
    if not r.recruiter_name and c.name:
        r.recruiter_name = c.name
    r.contact_direct = c.direct
