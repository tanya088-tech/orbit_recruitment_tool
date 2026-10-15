"""Parse a Naukri job page (rendered HTML) into the fields the tool stores.

Order of trust:
  header (what a recruiter sees)  >  JSON-LD JobPosting  >  nothing.
The JSON-LD `experienceRequirements.monthsOfExperience` is NOT used: Naukri fills it with "1" for most jobs
(it does not match the visible "0 - 2 years"), so the visible header text is the only experience source.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from collectors.linkedin.detail_parser import html_to_text
from processing.description_sections import clean_description
from utils.dates import parse_iso_datetime, parse_posted_date

_EMPLOYMENT = {"full time": "Full-time", "part time": "Part-time", "contract": "Contract", "temporary": "Temporary",
               "internship": "Internship", "intern": "Internship", "freelance": "Contract"}
_NOT_DISCLOSED = {"not disclosed", "not disclosed by recruiter", "not available", ""}
# buttons that collapse the description / details; clicked before the page is read
EXPAND_SELECTORS = ["[class*='JDC__show-more']", "button:has-text('Read more')", "button:has-text('Show more')",
                    "span:has-text('View More')", "a:has-text('View More')"]
DESCRIPTION_SELECTOR = "[class*='JDC__dang-inner-html']"


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
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return {}


def employment_label(text: Optional[str]) -> Optional[str]:
    """'Full Time, Permanent' -> 'Full-time'; 'Full Time, Contractual' -> 'Contract'. Anything that rules a job out
    (part time, internship, temporary) wins over 'full time'. Unrecognised wording -> None (never assumed)."""
    if not text:
        return None
    low = text.lower()
    for key in ("intern", "part time", "temporary"):
        if key in low:
            return _EMPLOYMENT[key]
    if "contract" in low or "freelance" in low:
        return "Contract"
    if "permanent" in low or "full time" in low:
        return "Full-time"
    return None


def _details(soup) -> dict[str, str]:
    """Label/value pairs from the 'Role / Industry Type / Department / Employment Type ...' block."""
    out: dict[str, str] = {}
    for block in soup.select("[class*='other-details'] [class*='details']"):
        label = _t(block, "label")
        if not label:
            continue
        value = " ".join(block.get_text(" ", strip=True).split())
        value = value[len(label):].strip(" :") if value.startswith(label) else value
        value = re.sub(r"\s*,\s*", ", ", value).strip(" ,")      # the page puts a separate "," after each linked value
        if value:
            out[label.strip(" :").lower()] = value
    return out


_NOT_COMPANY_SITE = ("naukri.com", "naukrigulf.com", "ambitionbox.com", "naukimg.com", "linkedin.com", "facebook.com", "twitter.com", "x.com",
                     "instagram.com", "youtube.com", "glassdoor.com")


def company_website(soup) -> Optional[str]:
    """The 'X website' link in Naukri's 'About the company' block. Only that link counts: a link elsewhere on the page
    (reviews, social profiles, Naukri's own pages) is not the company's website."""
    for a in soup.select("[class*='about-company'] a[href]"):
        href = (a.get("href") or "").strip()
        if not re.match(r"https?://", href, re.I):
            continue
        host = re.sub(r"^https?://(www\.)?", "", href, flags=re.I).split("/")[0].split(":")[0].lower()
        if "website" in a.get_text(" ", strip=True).lower() and not any(host == d or host.endswith("." + d) for d in _NOT_COMPANY_SITE):
            return href
    return None


_REVIEWS = re.compile(r"(\d[\d,]*(?:\.\d+)?\s*[KkMm]?)\s*reviews?\b", re.IGNORECASE)
_RATING_BEFORE = re.compile(r"(?<![\d.,])([0-4](?:\.\d)?|5(?:\.0)?)[\s|/\u00b7\u2022-]*$")
_RATING_ONLY = re.compile(r"^\s*([0-4](?:\.\d)?|5(?:\.0)?)\s*$")
_COMPANY_RATING_SUFFIX = re.compile(r"\s+(?:[0-4](?:\.\d)?|5(?:\.0)?)\s+\d[\d,]*(?:\.\d+)?\s*[KkMm]?\s*reviews?\s*$", re.IGNORECASE)


def rating_and_reviews(text: Optional[str], rating_only_ok: bool = False) -> tuple[Optional[str], Optional[str]]:
    """The company rating ("3.7") and review count ("689", "6.6K") from text such as "3.7 689 Reviews".
    The rating must sit directly before the review count (or, when the text is only the rating box, be the whole text),
    and the count must be followed by the word "Reviews" - so applicants, openings, salaries or experience are never read as reviews."""
    t = " ".join(str(text or "").split())
    if not t:
        return None, None
    m = _REVIEWS.search(t)
    if m:
        reviews = m.group(1).replace(" ", "").upper()
        r = _RATING_BEFORE.search(t[: m.start()])
        return (r.group(1) if r else None), reviews
    if rating_only_ok:
        r = _RATING_ONLY.match(t)
        if r:
            return r.group(1), None
    return None, None


def company_rating(soup) -> tuple[Optional[str], Optional[str]]:
    """Company rating and review count shown beside the company name on a Naukri job page (None, None when absent)."""
    box = soup.select_one("[class*='rating-wrapper']")
    for text, only_ok in ((box.get_text(" ", strip=True) if box else "", True),
                          (" ".join(n.get_text(" ", strip=True) for n in soup.select("[class*='jd-header-comp-name']")), False)):
        rating, reviews = rating_and_reviews(text, only_ok)
        if rating or reviews:
            return rating, reviews
    return None, None


def parse_job_detail(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    ld = _ld(soup)
    org = ld.get("hiringOrganization") if isinstance(ld.get("hiringOrganization"), dict) else {}
    details = _details(soup)

    title = _t(soup, "h1[class*='jd-header-title'], h1") or ld.get("title")
    # the company NAME is the link text; the box around it also holds the rating and review count (never part of the name)
    company = _t(soup, "[class*='jd-header-comp-name'] a")
    if not company:
        company = _t(soup, "[class*='jd-header-comp-name']")
        company = _COMPANY_RATING_SUFFIX.sub("", company).strip() if company else company
    company = company or org.get("name")
    c_rating, c_reviews = company_rating(soup)
    exp = _t(soup, "[class*='jhc__exp__'] span")
    salary = _t(soup, "[class*='jhc__salary'] span")
    if salary and salary.lower().rstrip(".") in _NOT_DISCLOSED:
        salary = None
    locs = [t for t in (" ".join(a.get_text(" ", strip=True).split()) for a in soup.select("[class*='jhc__location'] a")) if t]
    location = ", ".join(dict.fromkeys(locs)) or None
    if not location:
        jl = ld.get("jobLocation")
        jl = jl if isinstance(jl, list) else [jl] if jl else []
        names = []
        for place in jl:
            addr = place.get("address") if isinstance(place, dict) else None
            if isinstance(addr, dict) and addr.get("addressLocality"):
                names.append(str(addr["addressLocality"]))
        location = ", ".join(dict.fromkeys(names)) or None

    stats = [" ".join(s.get_text(" ", strip=True).split()) for s in soup.select("[class*='jhc__stat']")]
    stat = lambda label: next((s.split(":", 1)[1].strip() for s in stats if s.lower().startswith(label) and ":" in s), None) or None
    posted_text, applicants, openings = stat("posted"), stat("applicants"), stat("openings")
    work_mode_text = _t(soup, "[class*='jhc__wfhmode'] span")
    posted_by = _t(soup, "[class*='consultant-posted-by'] a")
    if posted_by and posted_by.lower().startswith("posted by"):
        posted_by = posted_by[9:].strip()
    edu_lines = []
    for block in soup.select("[class*='education'] [class*='details']"):
        label, value = _t(block, "label"), " ".join(block.get_text(" ", strip=True).split())
        if label and value.startswith(label):
            value = value[len(label):].strip()
        if value:
            edu_lines.append(f"{label.strip(' :')}: {value}" if label else value)
    education = "; ".join(edu_lines) or None
    if not education and isinstance(ld.get("qualifications"), dict):
        education = ld["qualifications"].get("educationalLevel") or None
    posted_iso = ld.get("datePosted")
    posted_date = parse_posted_date(posted_iso) if posted_iso else parse_posted_date(posted_text)
    posted_ts = parse_iso_datetime(posted_iso)
    posted_ts_text = posted_ts.isoformat(timespec="seconds") if posted_ts else None

    skills = [t for t in (" ".join(c.get_text(" ", strip=True).split()) for c in soup.select("[class*='key-skill'] a span, [class*='key-skill'] a")) if t]
    skills = list(dict.fromkeys(skills))
    if not skills:
        raw_sk = ld.get("skills")
        if isinstance(raw_sk, str):
            skills = [s.strip() for s in re.split(r"[,\n]", raw_sk) if s.strip()]
        elif isinstance(raw_sk, list):
            skills = [str(s).strip() for s in raw_sk if str(s).strip()]

    node = soup.select_one(DESCRIPTION_SELECTOR)
    description = html_to_text(str(node)) if node is not None else None
    if not description and ld.get("description"):
        description = html_to_text(str(ld["description"]))

    emp_text = details.get("employment type") or (ld.get("employmentType") if isinstance(ld.get("employmentType"), str) else None)
    emp = employment_label(emp_text)
    return {
        "title": title, "company": company, "company_url": None, "location": location,
        "experience": exp, "salary": salary, "skills": skills,
        "description": clean_description(description) if description else None,
        "employment_type": emp, "employment_details": emp_text,
        "work_mode_text": work_mode_text, "openings": openings, "applicants": applicants,
        "company_website": company_website(soup),
        "company_rating": c_rating, "company_reviews": c_reviews,
        "education": education, "role_category": details.get("role category"), "posted_by": posted_by,
        "posted_date": posted_date, "posted_age_text": posted_text, "posted_timestamp": posted_ts_text,
        "job_function": details.get("department") or details.get("role category"),
        "industries": details.get("industry type"),
        "job_role": details.get("role"),
        "raw": {"applicants": applicants, "details": details,
                "role_category": details.get("role category"),
                "ld_valid_through": ld.get("validThrough")},
    }


# label shown on the page -> the Job field that should hold it. Used to cross-check a capture against the page itself.
PAGE_LABELS = {"Openings": "openings", "Applicants": "applicants", "Education": "education", "Key Skills": "skills",
               "Role Category": "role_category", "Employment Type": "employment_details", "Department": "job_function",
               "Industry Type": "industries", "Role": "job_role", "Posted": "posted_age_text"}


def completeness_gaps(html: str, job: dict[str, Any]) -> list[str]:
    """Labels the page SHOWS whose field came back empty, plus a description-length check against the page's own
    description block. An empty list means nothing visible was missed; it does not prove the page was read in full
    if the page itself hid content behind a button."""
    soup = BeautifulSoup(html, "lxml")
    gaps = []
    shown = {(" ".join(l.get_text(" ", strip=True).split())).rstrip(": ").strip() for l in soup.find_all("label")}
    shown |= {t.get_text(" ", strip=True).rstrip(": ") for t in soup.select("[class*='education'] [class*='heading'], [class*='key-skill'] [class*='heading']")}
    for label, field in PAGE_LABELS.items():
        if label in shown and not job.get(field):
            gaps.append(f"page shows '{label}' but {field} is empty")
    if soup.select_one("[class*='jhc__wfhmode']") and not job.get("work_mode_text"):
        gaps.append("page shows a work-mode badge but work_mode_text is empty")
    node = soup.select_one(DESCRIPTION_SELECTOR)
    if node is not None:
        page_len = len(" ".join(node.get_text(" ", strip=True).split()))
        got = len(" ".join((job.get("description") or "").split()))
        if got < page_len * 0.9:
            gaps.append(f"description on page is {page_len} characters but {got} were captured")
    return gaps
