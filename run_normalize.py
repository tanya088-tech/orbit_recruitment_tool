#!/usr/bin/env python3
"""Phase 2 (normalization): classify and normalize EVERY collected job. Nothing is removed.

This is the step that feeds the dashboard. It uses exactly the same Phase 2 rules as
run_filter.py (GCC/BFSI, Permanent/Contract, India location, posting date), but keeps all jobs.
The dashboard filters then decide what is shown.

Examples
  python run_normalize.py                                  # newest output/jobs_*.json
  python run_normalize.py --input output/jobs_linkedin_20261008_152046.json
  python run_normalize.py --as-of 2026-10-08T10:00:00+00:00
"""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from processing.pipeline import load_jobs, normalize_all, save_normalized
from run_filter import newest_jobs_file
from utils.logging_setup import setup_logging


def main() -> int:
    p = argparse.ArgumentParser(description="Normalize all collected jobs for the dashboard (no jobs removed).")
    p.add_argument("--input", help="Phase 1 JSON file (default: newest in output/)")
    p.add_argument("--output-dir", default=str(settings.OUTPUT_DIR))
    p.add_argument("--as-of", help="Treat this ISO time as 'now' (default: current UTC time)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    log_file = setup_logging(args.log_level, prefix="normalize")
    log = logging.getLogger("run_normalize")
    log.info("Logging to %s", log_file)

    input_path = Path(args.input) if args.input else newest_jobs_file(Path(args.output_dir))
    _, jobs = load_jobs(input_path)
    log.info("Loaded %d jobs from %s", len(jobs), input_path)

    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    run = normalize_all(jobs, as_of=as_of)
    source = (jobs[0].get("source") or "linkedin").lower() if jobs else "linkedin"
    out = save_normalized(run, Path(args.output_dir), source, input_file=input_path)

    s = run.summary
    print("=" * 62)
    print(f"NORMALIZED  {input_path.name}")
    print(f"  Jobs collected              : {s['total_jobs_collected']}")
    print(f"  Normalized (all kept)       : {s['normalized_jobs']}")
    print(f"  Could not be processed      : {s['failed_to_process']}")
    print(f"  In India (dashboard scope)  : {s['in_india']}")
    print(f"  Outside India / no location : {s['outside_india_or_unknown_location']}")
    print(f"  Potential GCC / BFSI        : {s['potential_gcc']} / {s['potential_bfsi']}")
    print(f"  Permanent / Contract        : {s['permanent']} / {s['contract']}")
    print(f"  Saved to                    : {out}")
    print("  Next: python run_ingest.py")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
