"""Naukri source: the search pages and job pages are built with JavaScript, so they are read through BrowserClient."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import replace
from typing import Any, Iterator, Optional

from collectors.browser_source import BrowserListSource
from config import settings
from collectors.naukri.detail_parser import DESCRIPTION_SELECTOR, EXPAND_SELECTORS, parse_job_detail
from collectors.naukri.search_parser import parse_search_results
from models.job import Job, RunStats, SearchParams
from processing.classifier import is_known_overseas_employer

log = logging.getLogger(__name__)

BASE = "https://www.naukri.com"
_AGE_CHOICES = (1, 3, 7, 15, 30)        # values Naukri's "freshness" filter accepts


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def age_filter(days: int) -> int:
    return next((d for d in _AGE_CHOICES if days <= d), _AGE_CHOICES[-1])


def keyword_terms(keywords: str) -> list[str]:
    """'bank OR fintech' -> ['bank', 'fintech'] (Naukri takes the alternatives comma-separated)."""
    parts = [p.strip().strip('"') for p in re.split(r"\s+OR\s+|,", keywords, flags=re.I) if p.strip()]
    return parts or [keywords.strip()]


def naukri_location(text: Optional[str]) -> Optional[str]:
    """Naukri is an Indian job site and writes Indian places without the country, often small towns the place lists do not
    know ("Kotputli, Bhiwadi", "Sonipat( Kundli )"). When the text names no foreign country or place and no known Indian one,
    ", India" is added so the vacancy is not dropped as 'not located in India'. Text that names a foreign country or place
    ("Saudi Arabia", "Doha, Gulf") or is already recognised is returned unchanged."""
    from processing.location import check_location
    if not text or not text.strip():
        return text
    if check_location(text).country is None:
        return f"{text.strip()}, India"
    return text


def search_url(params: SearchParams, page: int) -> str:
    """URL for ONE keyword. Naukri turns a comma list (k=a,b,c) into a different page (/a-b-c-jobs) that silently drops
    the freshness and sort settings, so several keywords are searched one at a time (see NaukriSource.search)."""
    terms = keyword_terms(params.keywords)[:1]
    place = params.location.split(",")[0].strip()
    nationwide = place.lower() in {"", "india"}
    path = f"{_slug(terms[0])}-jobs" + ("" if nationwide else f"-in-{_slug(place)}")
    if page:
        path += f"-{page + 1}"
    query = f"k={','.join(t.replace(' ', '%20') for t in terms)}"
    if not nationwide:
        query += f"&l={_slug(place)}"
    query += f"&jobAge={age_filter(params.days)}&sort=f"      # sort=f is Naukri's "most recent first"
    return f"{BASE}/{path}?{query}"


class NaukriSource(BrowserListSource):
    name = "naukri"
    list_wait = "div.srp-jobtuple-wrapper"
    detail_wait = DESCRIPTION_SELECTOR
    detail_expand = EXPAND_SELECTORS

    def search_url(self, params: SearchParams, page: int) -> str:
        return search_url(params, page)

    def card_skip_reason(self, stub: dict[str, Any], params: SearchParams) -> Optional[str]:
        """A search for an employer's name (e.g. "Barclays") also lists other companies' jobs, mostly when the employer has
        posted little in the chosen period (in the last 24 hours, 'Barclays' gave two cards, both from a staffing firm).
        For such a search only cards from an employer on the reference lists are opened. Role-term searches are unaffected."""
        if not is_known_overseas_employer(params.keywords):
            return None
        if is_known_overseas_employer(stub.get("company")):
            return None
        return f"is not one of the listed employers (searched for '{params.keywords}')"

    def search(self, params: SearchParams, stats: RunStats, skip_ids: Optional[set[str]] = None) -> Iterator[Job]:
        """One search per keyword ("GCC OR bank OR financial services" = three searches), results merged newest-first-ish
        (round robin over the keywords, since each is newest first), a vacancy found by several keywords counted once.
        If Naukri blocks part-way, what was already collected is still returned before the block is reported."""
        terms = keyword_terms(params.keywords)
        if len(terms) == 1:
            yield from super().search(replace(params, keywords=terms[0]), stats, skip_ids)
            return
        known = set(skip_ids) if skip_ids is not None else set()
        per_term: list[tuple[list[Job], list[str]]] = []
        stop: Optional[Exception] = None
        # With a cap of N, the merged list takes about N / keywords from each keyword (round robin below), so opening N
        # postings for EVERY keyword mostly fetched pages that were then left out. Each keyword now gets its share
        # (x NAUKRI_KEYWORD_SHARE_FACTOR, so a keyword with few results is made up by the others).
        share = params.max_jobs
        factor = float(settings.NAUKRI_KEYWORD_SHARE_FACTOR or 0)
        if params.max_jobs and factor > 0:
            share = min(params.max_jobs, max(1, math.ceil(params.max_jobs * factor / len(terms))))
        pages = min(params.max_pages, int(settings.NAUKRI_MAX_PAGES_PER_KEYWORD or params.max_pages))
        for term in terms:
            sub = RunStats()
            jobs: list[Job] = []
            try:
                for job in super().search(replace(params, keywords=term, max_jobs=share, max_pages=pages), sub, set(known)):
                    jobs.append(job)
                    if job.job_id:
                        known.add(str(job.job_id))
            except KeyboardInterrupt as exc:    # the Stop button: keep what was fetched so far (it is saved), then stop
                stop = exc
            except Exception as exc:            # BlockedError / SetupError: keep the earlier terms, then report it
                if exc.__class__.__name__ not in ("BlockedError", "SetupError"):
                    raise
                stop = exc
            for f in ("found", "failed", "skipped_duplicate", "skipped_out_of_range"):
                setattr(stats, f, getattr(stats, f) + getattr(sub, f))
            stats.failures.extend(sub.failures)
            per_term.append((jobs, sub.latest_ids))
            if stop is not None:
                break
        seen_jobs: set[str] = set()
        for rank in range(max((len(j) for j, _ in per_term), default=0)):
            for jobs, _ in per_term:
                if rank < len(jobs) and jobs[rank].job_id not in seen_jobs:
                    seen_jobs.add(jobs[rank].job_id)
                    stats.collected += 1
                    yield jobs[rank]
        merged: list[str] = []
        for rank in range(max((len(l) for _, l in per_term), default=0)):
            for _, latest in per_term:
                if rank < len(latest) and latest[rank] not in merged:
                    merged.append(latest[rank])
        stats.latest_ids.extend(merged[: params.max_jobs] if params.max_jobs else merged)
        if stop is not None:
            raise stop

    def parse_search(self, html: str):
        return parse_search_results(html)

    def parse_detail(self, html: str):
        return parse_job_detail(html)

    def build_job(self, stub: dict[str, Any], detail: dict[str, Any]) -> Job:
        age_text = detail["posted_age_text"] or stub["posted_age_text"]
        return Job(
            source="Naukri", job_id=stub["job_id"],
            title=detail["title"] or stub["title"], company=detail["company"] or stub["company"],
            location=naukri_location(detail["location"] or stub["location"]), job_url=stub["job_url"],
            description=detail["description"], employment_type=detail["employment_type"],
            posted_date=detail["posted_date"] or stub["posted_date"], posted_age_text=age_text,
            posted_timestamp=detail["posted_timestamp"], company_url=stub.get("company_url"),
            job_function=detail["job_function"], industries=detail["industries"], job_role=detail["job_role"],
            experience=detail["experience"] or stub.get("experience"),
            salary=detail["salary"] or stub.get("salary"),
            skills=detail["skills"] or stub.get("skills") or [],
            work_mode_text=detail["work_mode_text"], openings=detail["openings"], applicants=detail["applicants"],
            education=detail["education"], role_category=detail["role_category"], posted_by=detail["posted_by"],
            employment_details=detail["employment_details"], company_website=detail["company_website"],
            company_rating=detail.get("company_rating") or stub.get("company_rating"),
            company_reviews=detail.get("company_reviews") or stub.get("company_reviews"),
            raw={"search_card_html": stub["raw"], **detail["raw"]},
        )
