#!/usr/bin/env python3
"""Phase 2: filter the jobs collected in Phase 1 (pure Python rules, no AI).

Examples
  python run_filter.py                                   # newest output/jobs_*.json
  python run_filter.py --input output/jobs_linkedin_20261008_152046.json
  python run_filter.py --as-of 2026-10-08T10:00:00+00:00 # reproducible run for old files
  python run_filter.py --include-ambiguous-date          # also keep date-only "yesterday" jobs
"""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from processing.pipeline import load_jobs, run_filters, save_filtered, summary_lines
from utils.logging_setup import setup_logging


def newest_jobs_file(output_dir: Path) -> Path:
    files = sorted(output_dir.glob("jobs_*_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No jobs_*.json files found in {output_dir}. Run run_collect.py first.")
    return files[-1]


def main() -> int:
    p = argparse.ArgumentParser(description="Filter collected jobs (Phase 2).")
    p.add_argument("--input", help="Phase 1 JSON file (default: newest in output/)")
    p.add_argument("--output-dir", default=str(settings.OUTPUT_DIR))
    p.add_argument("--as-of", help="Treat this ISO time as 'now' (default: current UTC time)")
    p.add_argument("--include-ambiguous-date", action="store_true",
                   help="Keep jobs whose only date info is 'yesterday' (24h cannot be confirmed)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    log_file = setup_logging(args.log_level, prefix="filter")
    log = logging.getLogger("run_filter")
    log.info("Logging to %s", log_file)

    input_path = Path(args.input) if args.input else newest_jobs_file(Path(args.output_dir))
    _, jobs = load_jobs(input_path)
    log.info("Loaded %d jobs from %s", len(jobs), input_path)

    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    run = run_filters(jobs, as_of=as_of, include_ambiguous_date=args.include_ambiguous_date)
    source = (jobs[0].get("source") or "linkedin").lower() if jobs else "linkedin"
    out = save_filtered(run, Path(args.output_dir), source, input_file=input_path)
    for line in summary_lines(run):
        log.info(line)
    log.info("Saved %d filtered jobs to %s", len(run.final_jobs), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
