"""LinkedIn source: search public listings, then fetch each job's detail page."""
from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

from collectors.base import JobSource
from collectors.errors import BlockedError, NotFoundError
from collectors.linkedin.client import HttpClient
from collectors.linkedin.detail_parser import parse_job_detail
from collectors.linkedin.search_parser import parse_search_results
from config import settings
from models.job import Job, RunStats, SearchParams
from utils.dates import is_within_days, parse_posted_date

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
PAGE_SIZE = 25


def date_filter_code(days: int) -> str:
    """LinkedIn only supports 24h / week / month windows; we then trim exactly in code."""
    if days <= 1:
        return "r86400"
    if days <= 7:
        return "r604800"
    return "r2592000"


class LinkedInSource(JobSource):
    name = "linkedin"

    def __init__(self, client: Optional[HttpClient] = None) -> None:
        self.client = client or HttpClient()

    def search(
        self,
        params: SearchParams,
        stats: RunStats,
        skip_ids: Optional[set[str]] = None,
    ) -> Iterator[Job]:
        skip_ids = skip_ids if skip_ids is not None else set()
        seen_this_search: set[str] = set()
        collected_here = 0
        consecutive_failures = 0

        start = 0
        for page in range(params.max_pages):
            if page and settings.LINKEDIN_PAGINATION == "fixed":
                start = page * PAGE_SIZE
            query = {
                "keywords": params.keywords,
                "location": params.location,
                "f_TPR": date_filter_code(params.days),
                "sortBy": "DD",          # most recent first
                "start": start,
            }
            try:
                html = self.client.get(SEARCH_URL, params=query)
            except BlockedError:
                raise
            except Exception as exc:
                log.error("Search page %d failed (%s): %s", page + 1, params.label(), exc)
                stats.record_failure(f"{SEARCH_URL}?start={start} [{params.label()}]", exc)
                return

            stubs = parse_search_results(html)
            log.info("Search page %d: %d listings", page + 1, len(stubs))
            if not stubs:
                return   # no more results
            if settings.LINKEDIN_PAGINATION == "returned":
                if all(stub["job_id"] in seen_this_search for stub in stubs):
                    return   # the offset did not move us forward: stop rather than loop
                start += len(stubs)

            for stub in stubs:
                job_id = stub["job_id"]
                if job_id in seen_this_search:
                    continue
                seen_this_search.add(job_id)
                stats.found += 1

                if job_id in skip_ids:
                    stats.skipped_duplicate += 1
                    if params.count_known and params.max_jobs and job_id not in params.exclude_ids:
                        # "the N most recent": a vacancy we already hold is one of the N, it just is not fetched again
                        stats.latest_ids.append(job_id)
                        collected_here += 1
                        if collected_here >= params.max_jobs:
                            log.info("Reached max_jobs=%d for this search", params.max_jobs)
                            return
                    continue
                if not is_within_days(stub["posted_date"], params.days):
                    stats.skipped_out_of_range += 1
                    continue

                try:
                    job = self._collect_one(stub)
                except BlockedError:
                    raise
                except NotFoundError as exc:
                    log.warning("Job removed or missing: %s (%s)", stub["job_url"], exc)
                    stats.record_failure(stub["job_url"], exc)   # not a block: don't count toward breaker
                    continue
                except Exception as exc:
                    log.error("Failed to collect %s: %s", stub["job_url"], exc)
                    stats.record_failure(stub["job_url"], exc)
                    consecutive_failures += 1
                    if consecutive_failures >= settings.MAX_CONSECUTIVE_FAILURES:
                        raise BlockedError(
                            f"{consecutive_failures} failures in a row - stopping to avoid hammering LinkedIn"
                        )
                    continue

                consecutive_failures = 0
                stats.collected += 1
                collected_here += 1
                if params.count_known:
                    stats.latest_ids.append(job_id)
                yield job

                if params.max_jobs and collected_here >= params.max_jobs:
                    log.info("Reached max_jobs=%d for this search", params.max_jobs)
                    return

    def _collect_one(self, stub: dict[str, Any]) -> Job:
        html = self.client.get(DETAIL_URL.format(job_id=stub["job_id"]))
        detail = parse_job_detail(html)
        age_text = detail["posted_age_text"] or stub["posted_age_text"]
        # Date priority: structured-data date > card's datetime attribute > (last resort) guess from relative text
        posted_date = detail["posted_date"] or stub["posted_date"] or parse_posted_date(age_text)
        return Job(
            source="LinkedIn",
            job_id=stub["job_id"],
            title=detail["title"] or stub["title"],
            company=detail["company"] or stub["company"],
            location=detail["location"] or stub["location"],
            job_url=stub["job_url"],
            description=detail["description"],
            employment_type=detail["employment_type"],
            posted_date=posted_date,
            posted_age_text=age_text,
            posted_timestamp=detail["posted_timestamp"],
            company_url=detail["company_url"] or stub["company_url"],
            seniority_level=detail["seniority_level"],
            job_function=detail["job_function"],
            industries=detail["industries"],
            raw={"search_card_html": stub["raw"], **detail["raw"]},
        )
