"""Move jobs from a Phase 2 file (normalized_jobs_*.json, or a filtered_jobs_*.json) into the history store (with deduplication)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from store.base import IngestResult, JobHistoryStore


def load_filtered_file(path: Any) -> tuple[list[dict[str, Any]], str]:
    """Return (jobs, sha256 of the file bytes). Accepts the Phase 2 format or a bare list."""
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    return jobs, hashlib.sha256(raw).hexdigest()


def ingest_filtered_file(path: Any, store: JobHistoryStore, force: bool = False, now: Any = None) -> IngestResult:
    jobs, digest = load_filtered_file(path)
    return store.ingest(jobs, source_file=Path(path).name, source_hash=digest, now=now, force=force)


def newest_filtered_file(output_dir: Any) -> Optional[Path]:
    files = sorted(Path(output_dir).glob("filtered_jobs_*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    return files[-1] if files else None


def newest_normalized_file(output_dir: Any) -> Optional[Path]:
    """The newest output/normalized_jobs_*.json (every collected job, written by run_normalize.py)."""
    files = sorted(Path(output_dir).glob("normalized_jobs_*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    return files[-1] if files else None
