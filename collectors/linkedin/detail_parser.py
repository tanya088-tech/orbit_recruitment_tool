"""Parse a LinkedIn public job-detail page/fragment into normalized fields.

Strategy:
  1. Prefer the embedded JSON-LD 'JobPosting' block (structured, stable).
  2. Fall back to the visible HTML elements for anything still missing.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from collectors.errors import ParseError
from collectors.linkedin.search_parser import clean_url
from processing.description_sections import clean_description
from utils.dates import parse_iso_datetime, parse_posted_date

_EMPLOYMENT_TYPES = {
    "FULL_TIME": "Full-time", "PART_TIME": "Part-time", "CONTRACTOR": "Contract",
    "CONTRACT": "Contract", "TEMPORARY": "Temporary", "INTERN": "Internship",
    "VOLUNTEER": "Volunteer", "PER_DIEM": "Per diem", "OTHER": "Other",
}


_COUNTRY_NAMES = {"IN": "India", "IND": "India"}   # LinkedIn gives ISO codes; cards say "India"


def html_to_text(fragment: Optional[str]) -> Optional[str]:
    """Convert an HTML description to readable plain text."""
    if not fragment:
        return None
    if "<" not in fragment and "&lt;" in fragment:   # double-escaped HTML
        fragment = html_lib.unescape(fragment)
    soup = BeautifulSoup(fragment, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for block in soup.find_all(["p", "div", "ul", "ol", "h1", "h2", "h3", "h4"]):
        block.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return clean_description(text)        # drops LinkedIn's "Show more" / "Show less" button text


def _ld_experience(ld: dict[str, Any]) -> Optional[str]:
    """JobPosting.experienceRequirements as text (months -> years), when the page carries it. Never guessed."""
    req = ld.get("experienceRequirements")
    items = req if isinstance(req, list) else [req]
    out = []
    for it in items:
        if isinstance(it, str) and it.strip():
            out.append(" ".join(it.split()))
        elif isinstance(it, dict):
            months = it.get("monthsOfExperience")
            try:
                m = int(float(months))
            except (TypeError, ValueError):
                m = 0
            if m > 0:
                out.append(f"{m // 12} years" if m % 12 == 0 else f"{m} months")
            elif isinstance(it.get("description"), str) and it["description"].strip():
                out.append(" ".join(it["description"].split()))
    return "; ".join(dict.fromkeys(out)) or None


def _ld_education(ld: dict[str, Any]) -> Optional[str]:
    req = ld.get("educationRequirements")
    items = req if isinstance(req, list) else [req]
    out = []
    for it in items:
        if isinstance(it, str) and it.strip():
            out.append(" ".join(it.split()))
        elif isinstance(it, dict):
            val = it.get("credentialCategory") or it.get("name") or it.get("description")
            if isinstance(val, str) and val.strip():
                out.append(" ".join(val.split()))
    return "; ".join(dict.fromkeys(out)) or None


def _normalize_employment(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.strip().upper().replace("-", "_").replace(" ", "_")
    return _EMPLOYMENT_TYPES.get(key, value.strip())


def _find_job_posting_ld(soup: BeautifulSoup) -> Optional[dict[str, Any]]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _ld_location(ld: dict[str, Any]) -> Optional[str]:
    loc = ld.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    address = (loc or {}).get("address") if isinstance(loc, dict) else None
    if not isinstance(address, dict):
        return None
    country = address.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    if isinstance(country, str):
        country = _COUNTRY_NAMES.get(country.strip().upper(), country)
    parts = [address.get("addressLocality"), address.get("addressRegion"), country]
    return ", ".join(p for p in parts if p) or None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    node = soup.select_one(selector)
    text = node.get_text(" ", strip=True) if node else None
    return text or None


def _criteria(soup: BeautifulSoup) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in soup.select("li.description__job-criteria-item"):
        header = item.select_one(".description__job-criteria-subheader")
        value = item.select_one(".description__job-criteria-text")
        if header and value:
            out[header.get_text(strip=True).lower()] = value.get_text(" ", strip=True)
    return out


def parse_job_detail(html: str) -> dict[str, Any]:
    """Return normalized detail fields. Raises ParseError if nothing usable found."""
    soup = BeautifulSoup(html, "lxml")
    ld = _find_job_posting_ld(soup) or {}
    criteria = _criteria(soup)

    org = ld.get("hiringOrganization") if isinstance(ld.get("hiringOrganization"), dict) else {}
    company_link = soup.select_one("a.topcard__org-name-link, .topcard__org-name-link")

    title = ld.get("title") or _text(soup, "h1, h2.top-card-layout__title, .top-card-layout__title, .topcard__title")
    company = org.get("name") or _text(soup, "a.topcard__org-name-link, .topcard__org-name-link, span.topcard__flavor")
    company_url = clean_url(org.get("sameAs") or org.get("url") or (company_link.get("href") if company_link else None))
    location = _ld_location(ld) or _text(soup, "span.topcard__flavor--bullet")

    description = html_to_text(ld.get("description")) or html_to_text(
        str(soup.select_one("div.show-more-less-html__markup, div.description__text") or "")
    )

    # Only trust a real date from structured data. Relative text is returned as-is
    # (posted_age_text) and NOT converted to a date here - that guess can be a day off.
    posted = parse_posted_date(ld.get("datePosted"))
    posted_dt = parse_iso_datetime(ld.get("datePosted"))
    age_text = _text(soup, "span.posted-time-ago__text, .posted-time-ago__text")
    employment = _normalize_employment(criteria.get("employment type") or ld.get("employmentType"))

    if not title and not description:
        raise ParseError("no title or description found (login wall or changed page layout?)")

    return {
        "title": title,
        "company": company,
        "company_url": company_url,
        "location": location,
        "employment_type": employment,
        "seniority_level": criteria.get("seniority level"),
        "job_function": criteria.get("job function"),
        "industries": criteria.get("industries"),
        "description": description,
        "posted_date": posted,
        "posted_age_text": age_text,
        "posted_timestamp": posted_dt.isoformat(timespec="seconds") if posted_dt else None,
        "raw": {"json_ld": ld or None, "criteria": criteria or None,
                "experience_requirements": _ld_experience(ld), "education_requirements": _ld_education(ld)},
    }
