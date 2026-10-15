#!/usr/bin/env python3
"""Command-line entry point for Phase 1 (collection only).

Examples
  python run_collect.py                                   # default test run
  python run_collect.py --keywords "investment bank" --locations "Pune, India" --days 3
  python run_collect.py --locations India --max-jobs-per-search 0 --days 7   # full India run
"""
import argparse
import logging

from collectors.collector import Collector
from collectors.registry import available_sources, get_source
from config import settings
from models.job import SearchParams
from utils.logging_setup import setup_logging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Collect public job postings (Phase 1).")
    p.add_argument("--source", default="linkedin", choices=available_sources())
    p.add_argument("--keywords", nargs="+", default=settings.DEFAULT_KEYWORDS,
                   help='One or more keyword searches, e.g. "bank" "GCC OR fintech"')
    p.add_argument("--locations", nargs="+", default=settings.DEFAULT_LOCATIONS,
                   help='e.g. "Pune, India" or just India')
    p.add_argument("--days", type=int, default=settings.DEFAULT_DAYS, help="Posted within the last N days")
    p.add_argument("--max-jobs-per-search", type=int, default=settings.DEFAULT_MAX_JOBS_PER_SEARCH,
                   help="Cap per keyword/location search. 0 = unlimited")
    p.add_argument("--max-pages", type=int, default=settings.DEFAULT_MAX_PAGES)
    p.add_argument("--output-dir", default=str(settings.OUTPUT_DIR))
    p.add_argument("--skip-ids-file", default=None,
                   help="Text file with one job ID per line. These jobs are not fetched again (default: skip nothing)")
    p.add_argument("--count-known", action="store_true",
                   help="With --max-jobs-per-search N: jobs listed in --skip-ids-file count toward N (the N most recent postings)")
    p.add_argument("--exclude-ids-file", default=None,
                   help="With --count-known: IDs already counted for this request (skipped without counting again)")
    p.add_argument("--log-level", default="INFO")
    return p


def main() -> int:
    args = build_parser().parse_args()
    log_file = setup_logging(args.log_level)
    log = logging.getLogger("run_collect")
    log.info("Logging to %s", log_file)

    exclude_ids = frozenset()
    if args.exclude_ids_file:
        with open(args.exclude_ids_file, encoding="utf-8") as fh:
            exclude_ids = frozenset(line.strip() for line in fh if line.strip())
    searches = [
        SearchParams(keywords=kw, location=loc, days=args.days,
                     max_jobs=args.max_jobs_per_search, max_pages=args.max_pages, count_known=args.count_known, exclude_ids=exclude_ids)
        for kw in args.keywords for loc in args.locations
    ]
    skip_ids = None
    if args.skip_ids_file:
        with open(args.skip_ids_file, encoding="utf-8") as fh:
            skip_ids = {line.strip() for line in fh if line.strip()}
        log.info("Skipping %d job IDs that are already collected", len(skip_ids))
    result = Collector(get_source(args.source)).run(searches, output_dir=args.output_dir, skip_ids=skip_ids)
    if result.stats.setup_error:
        return 3                      # this source cannot run here yet (see the SETUP REQUIRED line in the log)
    return 2 if result.stats.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
