#!/usr/bin/env python3
"""Check Naukri on THIS computer: loads one search page and one job page per source and prints what was read.

Nothing is saved to your job history. It follows the same rules as the collector: slow, one page at a time, and it
stops if the site shows a security check (it never tries to get past one).

  python verify_sources.py                    # Naukri
  python verify_sources.py naukri             # one source
  python verify_sources.py naukri --visible   # keep the browser window open so you can look at it
"""
import argparse
import os
import sys
import threading

from collectors.browser_client import BrowserClient
from collectors.errors import BlockedError, SetupError
from collectors.registry import get_source
from collectors.naukri.detail_parser import completeness_gaps
from config import settings
from models.job import SearchParams

FIELDS = ("title", "company", "location", "employment_type", "posted_date", "experience", "salary", "skills", "job_url")


def check(name: str, client: BrowserClient) -> bool:
    src = get_source(name, client=client)
    params = SearchParams("bank", "India", days=7)
    print(f"\n=== {name.title()} ===")
    try:
        html = client.get(src.search_url(params, 0), wait_for=src.list_wait)
        stubs = src.parse_search(html)
        print(f"search page: {len(stubs)} listings read")
        if not stubs:
            print("  no listings were found. The page layout may have changed or the search has no results.")
            return False
        stub = stubs[0]
        print(f"  first card: {stub.get('title')!r} at {stub.get('company')!r} ({stub.get('location')!r})")
        detail_html = client.get(src.detail_url(stub), wait_for=src.detail_wait, expand=src.detail_expand)
        job = src.build_job(stub, src.parse_detail(detail_html))
        gaps = completeness_gaps(detail_html, job.to_dict()) if name == "naukri" else None
    except SetupError as exc:
        print(f"SETUP NEEDED: {exc}")
        return False
    except BlockedError as exc:
        print(f"BLOCKED: {exc}\n  The tool stops here and does not try to get past it. Re-run with --visible to see what the site shows.")
        return False
    data = job.to_dict()
    missing = []
    for f in FIELDS:
        value = data.get(f)
        shown = "Not available" if value in (None, "", []) else value
        if shown == "Not available":
            missing.append(f)
        print(f"  {f:16}: {shown}")
    desc = data.get("description") or ""
    print(f"  {'description':16}: {len(desc)} characters" + ("" if desc else "  <- Not available"))
    if not desc:
        missing.append("description")
    print("  empty fields        : " + (", ".join(missing) if missing else "none"))
    for f in ("work_mode_text", "openings", "applicants", "education", "role_category", "employment_details", "posted_by"):
        if data.get(f):
            print(f"  {f:16}: {data[f]}")
    if gaps is None:
        print("  cross-check vs page : not available for this source - compare the values above with the page by eye")
    elif gaps:
        print("  CROSS-CHECK FAILED  : " + "; ".join(gaps))
        return False
    else:
        print("  cross-check vs page : every label the page shows was captured (still compare by eye: this cannot see content the page hides)")
    return bool(desc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", default=["naukri"], choices=["naukri", "linkedin"])
    ap.add_argument("--visible", action="store_true", help="show the browser window")
    args = ap.parse_args()
    if args.visible:
        settings.BROWSER_HEADLESS = False
    client = BrowserClient()
    results = {}
    try:
        results = {s: check(s, client) for s in args.sources if s != "linkedin"}
        print("\nSummary: " + ", ".join(f"{k}: {'OK' if v else 'needs attention'}" for k, v in results.items()))
        if args.visible and sys.stdin.isatty():
            input("\nThe browser window is still open so you can look at it. The script is waiting for you, it has not hung. "
                  "Press Enter to close it... ")
    finally:
        print("Closing the browser...", flush=True)
        closer = threading.Thread(target=client.close, daemon=True)
        closer.start()
        closer.join(timeout=10)                      # never wait forever on the browser shutting down
        print("Done." if not closer.is_alive() else "Done (the browser was still shutting down; it will close by itself).", flush=True)
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)           # leave at once even if a browser helper process lingers
