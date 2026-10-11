"""Orchestrator: runs searches against ONE source and gathers the results.

It only collects. It does not decide which jobs are relevant (GCC/BFSI etc.) -
that belongs to a later filtering phase that will consume the Job objects.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from collectors.base import JobSource
from collectors.errors import BlockedError
from models.job import Job, RunStats, SearchParams

log = logging.getLogger(__name__)


@dataclass
class CollectionResult:
    jobs: list[Job] = field(default_factory=list)
    stats: RunStats = field(default_factory=RunStats)
    output_file: Optional[Path] = None


class Collector:
    def __init__(self, source: JobSource) -> None:
        self.source = source

    def run(self, searches: list[SearchParams], output_dir: Optional[Path] = None,
            skip_ids: Optional[set[str]] = None) -> CollectionResult:
        """skip_ids: job IDs to leave alone (already collected before). None = skip nothing (the original behaviour)."""
        result = CollectionResult()
        seen_ids: set[str] = set(skip_ids or ())

        try:
            for i, params in enumerate(searches, start=1):
                result.stats.searches_run += 1
                log.info("[%s] Search %d/%d: %s", self.source.name, i, len(searches), params.label())
                try:
                    for job in self.source.search(params, result.stats, skip_ids=seen_ids):
                        if job.job_id:
                            seen_ids.add(job.job_id)
                        result.jobs.append(job)
                except BlockedError as exc:
                    result.stats.blocked = True
                    log.error("SOURCE BLOCKED US - stopping run. Reason: %s", exc)
                    break
                except Exception as exc:    # a whole search failing must not kill the other searches
                    log.exception("Search failed: %s", params.label())
                    result.stats.record_failure(f"search: {params.label()}", exc)
        except KeyboardInterrupt:
            log.warning("Interrupted by user - saving what was collected so far")
        finally:
            if output_dir is not None:
                result.output_file = self._save(result, Path(output_dir))
            for line in result.stats.summary_lines():
                log.info(line)
            if result.output_file:
                log.info("Saved %d jobs to %s", len(result.jobs), result.output_file)
        return result

    def _save(self, result: CollectionResult, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"jobs_{self.source.name}_{datetime.now():%Y%m%d_%H%M%S}.json"
        payload = {"run": result.stats.to_dict(), "jobs": [j.to_dict() for j in result.jobs]}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
