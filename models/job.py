"""Data models shared by all sources.

Job          - one normalized job posting (same shape whatever the source)
SearchParams - what to search for (keywords, location, date range, limits)
RunStats     - counters + failures, used for logging and the JSON output
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional


@dataclass
class SearchParams:
    keywords: str
    location: str = "India"
    days: int = 7                    # only jobs posted in the last N days
    max_jobs: Optional[int] = None   # cap per search (None / 0 = unlimited)
    max_pages: int = 40
    count_known: bool = False        # True: jobs already collected (skip_ids) still count toward max_jobs ("latest N")
    exclude_ids: frozenset = frozenset()   # with count_known: IDs already taken for this request; skipped, NOT counted again

    def __post_init__(self) -> None:
        if not self.keywords or not self.keywords.strip():
            raise ValueError("keywords must not be empty")
        if self.days < 1:
            raise ValueError("days must be >= 1")
        if not self.max_jobs:
            self.max_jobs = None

    def label(self) -> str:
        return f"'{self.keywords}' in '{self.location}' (last {self.days}d)"


@dataclass
class Job:
    source: str                          # e.g. "LinkedIn"
    job_id: Optional[str]                # the source's own ID
    title: Optional[str]
    company: Optional[str]
    location: Optional[str]
    job_url: str
    description: Optional[str] = None
    employment_type: Optional[str] = None    # "Full-time", "Contract", ...
    posted_date: Optional[date] = None       # calendar date only (LinkedIn gives no time on public pages)
    posted_age_text: Optional[str] = None    # LinkedIn's relative text exactly as shown, e.g. '2 days ago'
    posted_timestamp: Optional[str] = None   # exact ISO timestamp, only if the page's structured data has one
    company_url: Optional[str] = None
    seniority_level: Optional[str] = None
    job_function: Optional[str] = None
    industries: Optional[str] = None
    # Optional detail fields. LinkedIn's public pages do not provide these, so they stay None unless a source does.
    designation: Optional[str] = None
    job_role: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    recruiter_phone: Optional[str] = None
    contact_url: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)   # untouched source data
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["posted_date"] = self.posted_date.isoformat() if self.posted_date else None
        return data


@dataclass
class RunStats:
    searches_run: int = 0
    found: int = 0                    # unique job listings seen in search results
    collected: int = 0                # successfully turned into a Job
    failed: int = 0
    skipped_duplicate: int = 0
    skipped_out_of_range: int = 0
    blocked: bool = False             # True if the site started refusing us
    latest_ids: list[str] = field(default_factory=list)   # job IDs taken, newest first (only filled with count_known)
    failures: list[dict[str, str]] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def record_failure(self, url: str, error: object) -> None:
        self.failed += 1
        self.failures.append({"url": url, "error": f"{type(error).__name__}: {error}"})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_lines(self) -> list[str]:
        lines = [
            "=" * 60,
            "RUN SUMMARY",
            f"  Searches run          : {self.searches_run}",
            f"  Jobs found            : {self.found}",
            f"  Successfully collected: {self.collected}",
            f"  Failed                : {self.failed}",
            f"  Skipped (duplicate)   : {self.skipped_duplicate}",
            f"  Skipped (out of range): {self.skipped_out_of_range}",
            f"  Blocked by source     : {'YES - run was stopped early' if self.blocked else 'no'}",
        ]
        if self.failures:
            lines.append("  Failed URLs:")
            for item in self.failures:
                lines.append(f"    - {item['url']}  ->  {item['error']}")
        lines.append("=" * 60)
        return lines
