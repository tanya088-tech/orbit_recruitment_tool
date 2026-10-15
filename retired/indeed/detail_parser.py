"""Parse an Indeed job page (/viewjob) into the fields Orbit stores.

NOTE: Indeed shows a security check to automated visitors, so these selectors could not be checked against a
live job page from the build environment. They follow Indeed's published markup (`#jobDescriptionText`,
`data-testid="jobsearch-JobInfoHeader-title"`, ...) and are tested against a fixture of that structure. If Indeed
changes its markup, fields come back as None ("Not available" in the dashboard) rather than wrong.
Run verify_sources.py on a machine where Indeed opens normally to confirm.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from collectors.linkedin.detail_parser import html_to_text
from processing.description_sections import clean_description
from utils.dates import parse_iso_datetime, parse_posted_date

DESCRIPTION_SELECTOR = "#jobDescriptionText"
EXPAND_SELECTORS = ["button:has-text('Show more')", "button:has-text('Read more')", "button:has-text('View More')"]
_JOB_TYPES = ("Full-time", "Part-time", "Permanent", "Contract", "Temporary", "Internship", "Fresher", "Freelance", "Apprenticeship")


def _t(soup, selector: str) -> Optional[str]:
    node = soup.select_one(selector)
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def _ld(soup) -> dict[str, Any]:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        for it in (data if isinstance(data, list) else [data]):
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return {}


def _job_type(soup, ld) -> Optional[str]:
    found = []
    for node in soup.select("#salaryInfoAndJobType span, [data-testid='jobsearch-OtherJobDetailsContainer'] li, "
                            "[aria-label='Job type'] ~ div, [data-testid='Job-Type']"):
        text = " ".join(node.get_text(" ", strip=True).split())
        for jt in _JOB_TYPES:
            if jt.lower() in text.lower() and jt not in found:
                found.append(jt)
    if not found and isinstance(ld.get("employmentType"), str):
        found.append(ld["employmentType"].replace("_", " ").title())
    return ", ".join(found) or None


def parse_job_detail(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    ld = _ld(soup)
    org = ld.get("hiringOrganization") if isinstance(ld.get("hiringOrganization"), dict) else {}

    title = _t(soup, "h1[data-testid='jobsearch-JobInfoHeader-title'], h1.jobsearch-JobInfoHeader-title") or ld.get("title")
    if title:
        title = re.sub(r"\s*-\s*job post\s*$", "", title, flags=re.I)
    company = _t(soup, "[data-testid='inlineHeader-companyName'] a, [data-testid='inlineHeader-companyName']") or org.get("name")
    location = _t(soup, "[data-testid='inlineHeader-companyLocation'], [data-testid='job-location']")
    salary = _t(soup, "#salaryInfoAndJobType .css-19j1a75, [data-testid='jobsearch-OtherJobDetailsContainer'] [aria-label='Pay'] ~ div, "
                      "#salaryInfoAndJobType span:first-child")
    if salary and not re.search(r"\d", salary):
        salary = None

    posted_text = None
    footer = _t(soup, "[class*='JobMetadataFooter'], [data-testid='jobsearch-JobMetadataFooter']")
    if footer:
        m = re.search(r"\bPosted\s+((?:\d+\+?\s+\w+\s+ago)|today|just posted)", footer, re.I)
        if m:
            posted_text = m.group(1)
    posted_iso = ld.get("datePosted")
    posted_date = parse_posted_date(posted_iso) if posted_iso else parse_posted_date(posted_text)
    posted_ts = parse_iso_datetime(posted_iso)

    node = soup.select_one(DESCRIPTION_SELECTOR)
    description = html_to_text(str(node)) if node is not None else None
    if not description and ld.get("description"):
        description = html_to_text(str(ld["description"]))
    job_type = _job_type(soup, ld)
    return {
        "title": title, "company": company, "location": location, "salary": salary,
        "description": clean_description(description) if description else None,
        "employment_type": job_type, "posted_date": posted_date, "posted_age_text": posted_text,
        "posted_timestamp": posted_ts.isoformat(timespec="seconds") if posted_ts else None,
        "raw": {"job_type_text": job_type},
    }
