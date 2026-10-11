#!/usr/bin/env python3
"""Phase 3, step 1: add the jobs from a Phase 2 normalized file to the vacancy history.

A job already in history is NOT added again - it is counted as "already existing".

Examples
  python run_ingest.py                                # newest output/normalized_jobs_*.json (from run_normalize.py)
  python run_ingest.py --input output/normalized_jobs_linkedin_<ts>.json   (a filtered_jobs_*.json also works)
  python run_ingest.py --force                        # ingest a file even if it was ingested before
"""
import argparse
from pathlib import Path

from config import settings
from store.ingest import ingest_filtered_file, newest_normalized_file
from store.json_store import JsonJobHistory


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest normalized jobs into the vacancy history.")
    p.add_argument("--input", help="Phase 2 normalized JSON (default: newest normalized_jobs_*.json in output/)")
    p.add_argument("--output-dir", default=str(settings.OUTPUT_DIR))
    p.add_argument("--data-dir", default=str(settings.DATA_DIR))
    p.add_argument("--force", action="store_true", help="Ingest even if this exact file was ingested before")
    args = p.parse_args()

    path = Path(args.input) if args.input else newest_normalized_file(args.output_dir)
    if not path or not path.exists():
        raise SystemExit("No normalized_jobs_*.json found. Run run_collect.py and run_normalize.py first.")

    history = JsonJobHistory(Path(args.data_dir) / "job_history.json")
    r = ingest_filtered_file(path, history, force=args.force)

    print("=" * 62)
    print(f"INGEST  {path.name}")
    if r.skipped_already_ingested:
        print("  This exact file was already ingested - nothing changed.")
        print("  (Use --force to ingest it again as a new run.)")
    else:
        print(f"  Run id                  : {r.run_id}")
        print(f"  Jobs in file            : {r.total_in_file}")
        print(f"  NEW vacancies           : {r.new}")
        print(f"  Already existing        : {r.existing}")
        print(f"  Duplicates inside file  : {r.duplicates_in_file}")
        print(f"  Could not identify      : {r.unidentifiable}")
    print(f"  Total vacancies in history: {len(history.list_jobs())}")
    for key in r.new_keys:
        job = history.get_job(key)["record"]
        print(f"    + {job.get('company')} | {job.get('title')}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
