#!/usr/bin/env python3
"""Read-only report: how many saved jobs pass the strict GCC/BFSI rules, and why the others do not.

Changes nothing. The dashboard already hides jobs that fail the rules (settings.DISPLAY_ONLY_GCC_BFSI), so the history
file never needs to be rewritten or reclassified.

    python check_history.py            # counts per source + the reason for every hidden job
    python check_history.py --list     # also lists the visible ones
"""
import argparse
import collections
import sys

from config import settings
from dashboard.viewmodel import assess_record
from store.json_store import JsonJobHistory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="also list the jobs that stay visible")
    args = ap.parse_args()
    entries = JsonJobHistory(settings.DATA_DIR / "job_history.json").list_jobs()
    shown = collections.Counter(); hidden = collections.Counter(); why = collections.Counter()
    for e in entries:
        rec = e.get("record") or {}
        src = rec.get("source") or "?"
        v = assess_record(rec)
        if v.eligible:
            shown[src] += 1
            label = " + ".join(n for n, on in (("GCC", v.potential_gcc), ("BFSI", v.potential_bfsi)) if on)
            if args.list:
                print(f"  SHOWN  [{src}] {label:9} {rec.get('company')} - {rec.get('title')}")
        else:
            hidden[src] += 1
            why[v.reason] += 1
            print(f"  HIDDEN [{src}] {rec.get('company')} - {rec.get('title')}\n         {v.reason}")
    print(f"\nSaved jobs: {len(entries)}  (nothing is deleted or changed)")
    for src in sorted(set(shown) | set(hidden)):
        print(f"  {src:10} shown {shown[src]:4}   hidden {hidden[src]:4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
