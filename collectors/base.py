"""The contract every job source must follow.

To add Naukri or Indeed later: create collectors/naukri/source.py with a class
that subclasses JobSource, give it a `name`, implement `search()`, and register
it in collectors/registry.py. Nothing else in the project needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional

from models.job import Job, RunStats, SearchParams


class JobSource(ABC):
    name: str = ""   # short lowercase id, e.g. "linkedin"
    location_independent: bool = False   # True: the search ignores the keyword / city, so it is run once per collection

    @abstractmethod
    def search(
        self,
        params: SearchParams,
        stats: RunStats,
        skip_ids: Optional[set[str]] = None,
    ) -> Iterator[Job]:
        """Yield normalized Jobs for the search.

        Must: update `stats`, skip any job_id in `skip_ids` (already collected),
        isolate per-job failures (log + stats.record_failure, keep going), and
        let BlockedError propagate so the collector can stop the source.
        """
        raise NotImplementedError
