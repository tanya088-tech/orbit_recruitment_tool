"""Parse an Indeed India search-results page (rendered HTML) into job 'stubs'.

The cards carry no posting date, so posted_date stays None here (never guessed); the window is enforced by the
`fromage` filter in the search URL and the exact date, when Indeed shows one, is read from the job page.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)
BASE = "https://in.indeed.com"


def _text(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def job_url(job_key: str) -> str:
    return f"{BASE}/viewjob?jk={job_key}"


def parse_search_results(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    stubs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in soup.select("div.job_seen_beacon, li div.cardOutline"):
        try:
            link = card.select_one("a.jcs-JobTitle, h2.jobTitle a")
            key = (link.get("data-jk") if link else None) or (card.select_one("[data-jk]") or {}).get("data-jk")
            if not key or key in seen:
                continue
            seen.add(key)
            title_node = link.select_one("span[title]") if link else None
            title = (title_node.get("title") if title_node else None) or _text(link)
            attrs = [t for t in (_text(li) for li in card.select("li[data-testid='attribute_snippet_testid']")) if t and "₹" not in t]
            salary = _text(card.select_one("li.salary-snippet-container span, [data-testid='attribute_snippet_testid'].salary-snippet-container"))
            stubs.append({
                "job_id": str(key),
                "job_url": job_url(str(key)),
                "title": title,
                "company": _text(card.select_one("[data-testid='company-name'], span.companyName")),
                "company_url": None,
                "location": _text(card.select_one("[data-testid='text-location'], div.companyLocation")),
                "salary": salary,
                "attributes": attrs,
                "snippet": _text(card.select_one(".underShelfFooter, .job-snippet")),
                "posted_age_text": None,
                "posted_date": None,
                "raw": str(card)[:4000],
            })
        except Exception as exc:
            log.warning("Skipping an Indeed card that could not be read: %s", exc)
    return stubs
