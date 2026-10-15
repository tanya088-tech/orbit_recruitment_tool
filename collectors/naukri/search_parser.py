"""Parse a Naukri search-results page (the HTML AFTER the browser has rendered it) into job 'stubs'.

Every value is read from the card exactly as shown. A value the card does not carry stays None - nothing is guessed.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from utils.dates import parse_posted_date

log = logging.getLogger(__name__)

_ID_IN_URL = re.compile(r"-(\d{9,})(?:\?|$)")


def _text(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def _clean_job_url(href: Optional[str]) -> Optional[str]:
    return href.split("?")[0].strip() if href else None


def _salary(card: Tag) -> Optional[str]:
    node = card.select_one(".sal-wrap span[title], .sal-wrap span")
    value = _text(node)
    if value and value.lower().replace(".", "") in {"not disclosed", "not disclosed by recruiter"}:
        return None
    return value


def _card_rating(card: Tag) -> tuple[Optional[str], Optional[str]]:
    from collectors.naukri.detail_parser import rating_and_reviews
    text = " ".join(n.get_text(" ", strip=True) for n in card.select("a.rating, a.review, span.rating, [class*='rating-wrap']"))
    return rating_and_reviews(text, rating_only_ok=True)


def parse_search_results(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    stubs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in soup.select("div.srp-jobtuple-wrapper, div.cust-job-tuple[data-job-id], article.jobTuple"):
        try:
            link = card.select_one("a.title")
            href = _clean_job_url(link.get("href") if link else None)
            job_id = card.get("data-job-id") or (card.select_one("[data-job-id]") or {}).get("data-job-id")
            if not job_id and href:
                m = _ID_IN_URL.search(href)
                job_id = m.group(1) if m else None
            if not job_id or not href or job_id in seen:
                continue
            seen.add(job_id)
            age_text = _text(card.select_one(".job-post-day"))
            tags = [t for t in (_text(li) for li in card.select("ul.tags-gt li")) if t]
            stubs.append({
                "job_id": str(job_id),
                "job_url": href,
                "title": (link.get("title") or _text(link)) if link else None,
                "company": _text(card.select_one("a.comp-name")),
                "company_rating": _card_rating(card)[0], "company_reviews": _card_rating(card)[1],
                "company_url": _clean_job_url((card.select_one("a.comp-name") or {}).get("href")),
                "location": _text(card.select_one(".loc-wrap .locWdth, .loc-wrap span")),
                "experience": _text(card.select_one(".exp-wrap .expwdth, .exp-wrap span")),
                "salary": _salary(card),
                "snippet": _text(card.select_one(".job-desc")),
                "skills": tags,
                "posted_age_text": age_text,
                "posted_date": parse_posted_date(age_text),
                "raw": str(card)[:4000],
            })
        except Exception as exc:     # one odd card must not lose the page
            log.warning("Skipping a Naukri card that could not be read: %s", exc)
    return stubs


def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    nxt = soup.select_one("a.styles_btn-secondary__2AsIP, [class*='pagination'] a[class*='next'], a[rel='next']")
    if nxt is not None and "disabled" not in " ".join(nxt.get("class") or []):
        return True
    return False
