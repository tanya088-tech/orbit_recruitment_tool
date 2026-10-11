"""Parse LinkedIn's public search-results HTML into lightweight job 'stubs'.

A stub has just enough to identify the job (ID, URL, title, company, card date).
The full description comes later from the detail page.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from utils.dates import parse_posted_date

log = logging.getLogger(__name__)

_URN_ID = re.compile(r"jobPosting:(\d+)")
_URL_ID = re.compile(r"(\d{6,})(?:\?|/|$)")


def clean_url(url: Optional[str]) -> Optional[str]:
    """Drop tracking query-strings so the same job always has the same URL."""
    return url.split("?")[0].strip() if url else None


def _text(card: Tag, selector: str) -> Optional[str]:
    node = card.select_one(selector)
    if not node:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _extract_job_id(card: Tag, href: Optional[str]) -> Optional[str]:
    for node in [card] + card.find_all(attrs={"data-entity-urn": True}):
        m = _URN_ID.search(node.get("data-entity-urn", ""))
        if m:
            return m.group(1)
    if href:
        m = _URL_ID.search(clean_url(href) or "")
        if m:
            return m.group(1)
    return None


def parse_search_results(html: str) -> list[dict[str, Any]]:
    """Return a list of stubs. A card that fails to parse is skipped, not fatal."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.base-card, div.base-search-card, div.job-search-card")
    if not cards:
        cards = soup.select("li div[data-entity-urn]")

    stubs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        try:
            link = card.select_one("a.base-card__full-link") or card.find("a", href=re.compile(r"/jobs/view/"))
            href = link.get("href") if link else None
            job_id = _extract_job_id(card, href)
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)

            company_link = card.select_one("h4.base-search-card__subtitle a, a.hidden-nested-link")
            time_tag = card.select_one("time")
            date_attr = time_tag.get("datetime") if time_tag else None   # LinkedIn's real calendar date
            age_text = " ".join(time_tag.get_text(" ", strip=True).split()) if time_tag else None

            stubs.append({
                "job_id": job_id,
                "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "title": _text(card, "h3.base-search-card__title, .base-search-card__title"),
                "company": _text(card, "h4.base-search-card__subtitle, .base-search-card__subtitle"),
                "company_url": clean_url(company_link.get("href")) if company_link else None,
                "location": _text(card, "span.job-search-card__location, .job-search-card__location"),
                "posted_date": parse_posted_date(date_attr) if date_attr else None,
                "posted_age_text": age_text or None,
                "raw": str(card),
            })
        except Exception as exc:   # one bad card must not break the page
            log.warning("Skipping unparseable search card: %s", exc)
    return stubs
