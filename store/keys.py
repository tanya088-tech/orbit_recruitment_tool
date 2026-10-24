"""Deduplication keys: how we decide two scraped postings are the SAME vacancy.

Preferred identifier: the source's own job_id  ->  "linkedin-4438121997"
Fallback (no job_id):  the normalized job URL  ->  "linkedin-url-<12 hex chars>"
The key is URL-safe, so it is also used in dashboard links (/job/<key>).
"""
from __future__ import annotations

import difflib
import hashlib
import re
from typing import Any, Optional
from urllib.parse import urlsplit

_LINKEDIN_VIEW_ID = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})(?:[/?#]|$)")


def normalize_job_url(url: Any) -> Optional[str]:
    """Strip tracking noise so the same posting always yields the same URL string.

    in.linkedin.com / uk.linkedin.com -> www.linkedin.com; query string, fragment and
    trailing slash dropped; /jobs/view/<slug>-<id> collapsed to /jobs/view/<id>.
    """
    if not url or not str(url).strip():
        return None
    parts = urlsplit(str(url).strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        host = "www.linkedin.com"
        m = _LINKEDIN_VIEW_ID.search(parts.path)
        if m:
            return f"https://{host}/jobs/view/{m.group(1)}"
    return f"https://{host}{parts.path.rstrip('/')}"


def lane(source: Any) -> str:
    """Company Careers vacancies have their own page and are a separate lane: they are only ever matched with each other.
    Everything else (LinkedIn, Naukri, ...) is the "main" lane and is matched exactly as before."""
    return "careers" if str(source or "").strip().lower() == "company careers" else "main"


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower()) or "unknown"


def extract_job_id(record: dict[str, Any]) -> Optional[str]:
    raw = record.get("job_id")
    if raw is not None:
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "", str(raw))
        if cleaned:
            return cleaned
    m = _LINKEDIN_VIEW_ID.search(normalize_job_url(record.get("job_url")) or "")
    return m.group(1) if m else None


def job_key(record: dict[str, Any]) -> str:
    """Return the dedupe key for a Phase 2 job record. Raises ValueError if unidentifiable."""
    source = _slug(record.get("source") or "unknown")
    job_id = extract_job_id(record)
    if job_id:
        return f"{source}-{job_id}"
    normalized = normalize_job_url(record.get("job_url"))
    if normalized:
        return f"{source}-url-{hashlib.sha1(normalized.encode()).hexdigest()[:12]}"
    raise ValueError("job has neither a job_id nor a usable job_url")


def match_url(record: dict[str, Any]) -> Optional[str]:
    """A normalized URL precise enough to prove two postings (even from different sources) are the same job.

    Needs a real path (a bare site address or a search page proves nothing), so those return None.
    """
    url = normalize_job_url(record.get("job_url"))
    if not url:
        return None
    parts = urlsplit(url)
    path = parts.path.strip("/")
    if not path or path.lower() in ("jobs", "search", "careers", "jobs/search"):
        return None
    return url


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


_COMPANY_NOISE = re.compile(r"\b(pvt|private|ltd|limited|inc|llp|llc|corp|corporation|india|co)\b")


def vacancy_fingerprint(record: dict[str, Any]) -> Optional[str]:
    """company + title + city, normalised. Used ONLY to recognise the same opening listed on two DIFFERENT sources.

    All three parts must be present, otherwise None (never match on partial information). It is a heuristic:
    two genuinely separate openings with identical company, title and city on different sites are merged into one
    row, and both source links are kept on that row so nothing is lost.
    """
    company = _COMPANY_NOISE.sub(" ", _norm(record.get("company")))
    company = " ".join(company.split())
    title = _norm(record.get("title"))
    city = _norm(str(record.get("location") or "").split(",")[0].split("(")[0])
    if not (company and title and city) or city in ("india", "remote"):
        return None
    return f"{company}|{title}|{city}"


REPOST_SIMILARITY = 0.9          # descriptions at least this similar (0-1) make a re-posted vacancy on the SAME source
REPOST_MIN_DESCRIPTION = 200     # characters; shorter descriptions prove nothing, so they are never treated as reposts


def _desc(rec: dict[str, Any]) -> str:
    return " ".join(_norm(rec.get("description")).split())[:4000]


def is_repost(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when b is the same opening as a, posted again on the SAME source under a new job id (e.g. LinkedIn
    reposts): same company + title + city, same source, and nearly the same description (both at least
    REPOST_MIN_DESCRIPTION characters). Two openings with the same title but different descriptions stay separate."""
    fp = vacancy_fingerprint(a)
    if not fp or fp != vacancy_fingerprint(b):
        return False
    if str(a.get("source") or "").strip().lower() != str(b.get("source") or "").strip().lower():
        return False
    da, db = _desc(a), _desc(b)
    if len(da) < REPOST_MIN_DESCRIPTION or len(db) < REPOST_MIN_DESCRIPTION:
        return False
    if da == db:
        return True
    m = difflib.SequenceMatcher(None, da, db, autojunk=False)
    return m.real_quick_ratio() >= REPOST_SIMILARITY and m.quick_ratio() >= REPOST_SIMILARITY and m.ratio() >= REPOST_SIMILARITY
