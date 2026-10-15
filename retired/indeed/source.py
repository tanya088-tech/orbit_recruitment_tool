"""Indeed India source. Indeed shows a security check to automated visitors; when it appears the run for this source
stops (BlockedError) and keeps what it had. See README "Naukri and Indeed"."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

from collectors.browser_source import BrowserListSource
from collectors.indeed.detail_parser import DESCRIPTION_SELECTOR, EXPAND_SELECTORS, parse_job_detail
from collectors.indeed.search_parser import BASE, parse_search_results
from config import settings
from models.job import Job, SearchParams

log = logging.getLogger(__name__)
_FROMAGE = (1, 3, 7, 14)               # values Indeed's "date posted" filter offers


def fromage(days: int) -> int:
    return next((d for d in _FROMAGE if days <= d), _FROMAGE[-1])


def search_url(params: SearchParams, page: int) -> str:
    terms = [p.strip().strip('"') for p in re.split(r"\s+OR\s+|,", params.keywords, flags=re.I) if p.strip()] or [params.keywords]
    q = {"q": " OR ".join(f'"{t}"' if " " in t else t for t in terms),
         "l": "" if params.location.strip().lower() == "india" else params.location.split(",")[0].strip(),
         "fromage": fromage(params.days), "sort": "date"}
    if page:
        q["start"] = 10 * page
    return f"{BASE}/jobs?{urlencode(q)}"


class IndeedSource(BrowserListSource):
    name = "indeed"
    list_wait = "div.job_seen_beacon"
    detail_wait = DESCRIPTION_SELECTOR
    detail_expand = EXPAND_SELECTORS

    def effective_days(self, params: SearchParams) -> int:
        if params.days > settings.INDEED_MAX_DAYS:
            log.warning("Indeed only filters up to %d days; using %d instead of %d", settings.INDEED_MAX_DAYS,
                        settings.INDEED_MAX_DAYS, params.days)
        return min(params.days, settings.INDEED_MAX_DAYS)

    def search_url(self, params: SearchParams, page: int) -> str:
        return search_url(params, page)

    def parse_search(self, html: str):
        return parse_search_results(html)

    def parse_detail(self, html: str):
        return parse_job_detail(html)

    def build_job(self, stub: dict[str, Any], detail: dict[str, Any]) -> Job:
        return Job(
            source="Indeed", job_id=stub["job_id"],
            title=detail["title"] or stub["title"], company=detail["company"] or stub["company"],
            location=detail["location"] or stub["location"], job_url=stub["job_url"],
            description=detail["description"], employment_type=detail["employment_type"] or ", ".join(stub.get("attributes") or []) or None,
            posted_date=detail["posted_date"], posted_age_text=detail["posted_age_text"], posted_timestamp=detail["posted_timestamp"],
            salary=detail["salary"] or stub.get("salary"),
            raw={"search_card_html": stub["raw"], **detail["raw"]},
        )
