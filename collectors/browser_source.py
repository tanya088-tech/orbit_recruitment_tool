"""Shared search loop for sources that need a real browser (Naukri, Indeed).

Same behaviour as the LinkedIn source: newest first, one page at a time, one job at a time, polite delays, the
"N most recent" counting (count_known), per-job failures isolated, a security check / block stops the source.
A subclass supplies only what differs: URLs, the two parsers and how a Job is assembled.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

from collectors.base import JobSource
from collectors.browser_client import BrowserClient
from collectors.errors import BlockedError, LocalBrowserError, NotFoundError
from config import settings
from models.job import Job, RunStats, SearchParams
from processing.classifier import skip_before_fetch_reason
from utils.dates import is_within_days

log = logging.getLogger(__name__)


class BrowserListSource(JobSource):
    list_wait: Optional[str] = None        # CSS selector that appears when the result list has rendered
    detail_wait: Optional[str] = None
    detail_expand: list[str] = []          # "Read more" style buttons to click before reading a detail page

    def __init__(self, client: Optional[BrowserClient] = None) -> None:
        self.client = client or BrowserClient()

    # -- supplied by the subclass --------------------------------------------
    def search_url(self, params: SearchParams, page: int) -> str:
        raise NotImplementedError

    def parse_search(self, html: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def detail_url(self, stub: dict[str, Any]) -> str:
        return stub["job_url"]

    def parse_detail(self, html: str) -> dict[str, Any]:
        raise NotImplementedError

    def build_job(self, stub: dict[str, Any], detail: dict[str, Any]) -> Job:
        raise NotImplementedError

    def effective_days(self, params: SearchParams) -> int:
        return params.days

    def card_skip_reason(self, stub: dict[str, Any], params: SearchParams) -> Optional[str]:
        """A source-specific reason to leave a search card unopened (None = open it)."""
        return None

    # -- the loop --------------------------------------------------------------
    def search(self, params: SearchParams, stats: RunStats, skip_ids: Optional[set[str]] = None) -> Iterator[Job]:
        skip_ids = skip_ids if skip_ids is not None else set()
        seen_this_search: set[str] = set()
        collected_here = 0
        consecutive_failures = 0
        browser_failures = 0          # pages in a row that failed because OUR browser failed (never counted as the site blocking us)
        days = self.effective_days(params)
        try:
            for page in range(params.max_pages):
                url = self.search_url(params, page)
                try:
                    html = self.client.get(url, wait_for=self.list_wait)
                except BlockedError:
                    raise
                except Exception as exc:
                    if exc.__class__.__name__ == "SetupError":
                        raise
                    log.error("Search page %d failed (%s): %s", page + 1, params.label(), exc)
                    stats.record_failure(f"{url} [{params.label()}]", exc)
                    return
                stubs = self.parse_search(html)
                log.info("[%s] search page %d: %d listings", self.name, page + 1, len(stubs))
                if not stubs or all(s["job_id"] in seen_this_search for s in stubs):
                    return

                for stub in stubs:
                    job_id = stub["job_id"]
                    if job_id in seen_this_search:
                        continue
                    seen_this_search.add(job_id)
                    stats.found += 1

                    if job_id in skip_ids:
                        stats.skipped_duplicate += 1
                        if params.count_known and params.max_jobs and job_id not in params.exclude_ids:
                            stats.latest_ids.append(job_id)
                            collected_here += 1
                            if collected_here >= params.max_jobs:
                                return
                        continue
                    if not is_within_days(stub.get("posted_date"), days):
                        stats.skipped_out_of_range += 1
                        continue
                    why = (skip_before_fetch_reason(stub.get("company"), stub.get("title"))
                           if (settings.COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH and (stub.get("company") or stub.get("title"))) else None)
                    why = why or self.card_skip_reason(stub, params)
                    if why:       # same as LinkedIn: opening a page in the browser is the slow part, so skip what cannot qualify
                        log.info("Not opening %s: %s %s", stub["job_url"], stub.get("company") or "(no company)", why)
                        continue
                    try:
                        job = self._collect_one(stub)
                    except BlockedError:
                        raise
                    except NotFoundError as exc:
                        log.warning("Job removed or missing: %s (%s)", stub["job_url"], exc)
                        stats.record_failure(stub["job_url"], exc)
                        continue
                    except LocalBrowserError as exc:
                        log.error("Failed to collect %s: %s", stub["job_url"], exc)
                        stats.record_failure(stub["job_url"], exc)
                        browser_failures += 1
                        if browser_failures >= settings.MAX_CONSECUTIVE_BROWSER_FAILURES:
                            log.error("The browser keeps failing (%d pages in a row, even after re-opening it). Skipping the rest of "
                                      "this place. This is a problem on this computer, not the site refusing us.", browser_failures)
                            return
                        continue
                    except Exception as exc:
                        if exc.__class__.__name__ == "SetupError":
                            raise
                        log.error("Failed to collect %s: %s", stub["job_url"], exc)
                        stats.record_failure(stub["job_url"], exc)
                        consecutive_failures += 1
                        if consecutive_failures >= settings.MAX_CONSECUTIVE_FAILURES:
                            raise BlockedError(f"{consecutive_failures} failures in a row - stopping to avoid hammering {self.name}")
                        continue
                    consecutive_failures = 0
                    browser_failures = 0
                    if not is_within_days(job.posted_date, days):     # the exact date from the job page overrides the card's estimate
                        stats.skipped_out_of_range += 1
                        continue
                    stats.collected += 1
                    collected_here += 1
                    if params.count_known:
                        stats.latest_ids.append(job_id)
                    yield job
                    if params.max_jobs and collected_here >= params.max_jobs:
                        return
        finally:
            pass

    def _collect_one(self, stub: dict[str, Any]) -> Job:
        html = self.client.get(self.detail_url(stub), wait_for=self.detail_wait, expand=self.detail_expand)
        return self.build_job(stub, self.parse_detail(html))
