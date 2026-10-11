#!/usr/bin/env python3
"""Check how LinkedIn's public search offset ("start") behaves. Makes only THREE polite requests.

Run once on your Mac:   python verify_pagination.py
It fetches the first results page with start=0, start=10 and start=25 for one search and compares the job IDs, then tells
you whether config/settings.py should use LINKEDIN_PAGINATION = "fixed" or "returned". It does not collect or save jobs.
"""
import sys

from collectors.linkedin.client import HttpClient
from collectors.linkedin.search_parser import parse_search_results
from collectors.linkedin.source import SEARCH_URL, date_filter_code


def ids_at(client, start):
    html = client.get(SEARCH_URL, params={"keywords": "bank", "location": "India", "f_TPR": date_filter_code(7),
                                          "sortBy": "DD", "start": start})
    return [s["job_id"] for s in parse_search_results(html)]


def main() -> int:
    client = HttpClient()
    pages = {start: ids_at(client, start) for start in (0, 10, 25)}
    for start, ids in pages.items():
        print(f"start={start:<3} -> {len(ids)} listings: {ids[:4]}...")
    n0 = len(pages[0])
    overlap_10 = len(set(pages[0]) & set(pages[10]))
    print()
    if n0 >= 25:
        print("Each page returns 25 listings, so the current setting (LINKEDIN_PAGINATION = \"fixed\") is correct.")
    elif n0 and pages[10] and overlap_10 == 0 and set(pages[25]).isdisjoint(pages[10]):
        print(f"Each page returns only {n0} listings, and start behaves as a result offset (start=10 continues from page 1).")
        print("With start=page*25, listings between those offsets are skipped. Set LINKEDIN_PAGINATION = \"returned\" in config/settings.py.")
    else:
        print("The result is not clear-cut (overlapping or empty pages). Leave LINKEDIN_PAGINATION = \"fixed\" and send me this output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
