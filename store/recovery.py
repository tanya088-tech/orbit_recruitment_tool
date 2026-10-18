"""Recover jobs that a collection saved to output/ but that never reached the history.

This happens when the dashboard is closed or interrupted (for example Ctrl+C in the Terminal window)
after the scraper saved its file but before the dashboard added it to the history.

Safe by design
  * only looks at output/jobs_*.json files saved at or after `since` (the start of the interrupted run)
  * skips a file when a normalized_jobs_*.json made from it was already ingested (matched by file hash
    against the history's run ledger), so nothing is ingested twice
  * ingestion uses the normal deduplicating store; existing vacancies are never replaced and
    recruiter state (saved / status / notes) is never touched
  * existing files are never modified or deleted; recovery only adds a new normalized_jobs_*.json
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from processing.pipeline import load_jobs, normalize_all, save_normalized
from store.base import JobHistoryStore
from store.ingest import ingest_filtered_file

log = logging.getLogger(__name__)


@dataclass
class RecoveryResult:
    files_found: int = 0
    files_recovered: int = 0
    jobs_in_files: int = 0
    new: int = 0
    existing: int = 0
    errors: list[str] = field(default_factory=list)
    recovered_files: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _already_processed_inputs(history: JobHistoryStore, output_dir: Path) -> set[str]:
    """Names of raw jobs files that already have an ingested normalized/filtered file."""
    ingested = {r.get("source_hash") for r in history.runs() if r.get("source_hash")}
    done: set[str] = set()
    for pattern in ("normalized_jobs_*.json", "filtered_jobs_*.json"):
        for path in output_dir.glob(pattern):
            try:
                if _sha256(path) not in ingested:
                    continue
                src = json.loads(path.read_text(encoding="utf-8")).get("input_file")
            except (OSError, ValueError):
                continue
            if src:
                done.add(Path(src).name)
    return done


def find_unprocessed(history: JobHistoryStore, output_dir: Path, since: Optional[datetime]) -> list[Path]:
    output_dir = Path(output_dir)
    if since is None or not output_dir.is_dir():
        return []
    cutoff = since.timestamp() - 2          # allow a little clock/rounding slack
    done = _already_processed_inputs(history, output_dir)
    files = [p for p in output_dir.glob("jobs_*_*.json")
             if p.stat().st_mtime >= cutoff and p.name not in done]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name))


def recover_unprocessed(history: JobHistoryStore, output_dir: Path, since: Optional[datetime]) -> RecoveryResult:
    result = RecoveryResult()
    output_dir = Path(output_dir)
    for path in find_unprocessed(history, output_dir, since):
        result.files_found += 1
        try:
            _, jobs = load_jobs(path)
            if not jobs:
                continue                      # nothing to recover from an empty file
            norm_path = save_normalized(normalize_all(jobs), output_dir, "linkedin", input_file=path)
            r = ingest_filtered_file(norm_path, history)
        except Exception as exc:              # leave the file alone so a later start can try again
            log.exception("could not recover %s", path)
            result.errors.append(f"{path.name}: {type(exc).__name__}: {exc}"[:240])
            continue
        result.files_recovered += 1
        result.jobs_in_files += len(jobs)
        result.new += r.new
        result.existing += r.existing
        result.recovered_files.append(path.name)
        log.info("Recovered %s: %d jobs, %d new, %d already existing", path.name, len(jobs), r.new, r.existing)
    return result
