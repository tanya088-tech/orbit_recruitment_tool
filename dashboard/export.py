"""CSV export of every eligible vacancy with every field the View Details page shows.

* Rows are exactly the dashboard's eligible vacancies (the same strict rules), all of them - not only the visible page.
* Newest posting first; vacancies whose posting date is unknown come after those with a known date.
* UTF-8 with a byte-order mark and CRLF line ends, so Excel / Numbers / Google Sheets show accents and line breaks correctly.
* Text that a spreadsheet could read as a formula (=, @, or +/- followed by non-digits) is prefixed with an apostrophe.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Callable

from dashboard import viewmodel as vm
from dashboard.viewmodel import Row
from processing.description_sections import clean_description, extract_sections

_SAFE_NUMBER = re.compile(r"^[+-]?[\d\s().-]+$")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(x) for x in value if str(x).strip())
    text = str(value)
    if text and (text[0] in "=@\t\r" or (text[0] in "+-" and not _SAFE_NUMBER.match(text))):
        text = "'" + text
    return text


def _iso(p: vm.Posted) -> str:
    if p.moment:
        return p.moment.astimezone(vm.UTC).strftime("%Y-%m-%d %H:%M UTC")
    return p.day.isoformat() if p.day else ""


def _bullets(items: Any) -> str:
    return "\n".join(f"- {x}" for x in (items or []))


def _also(r: Row) -> str:
    return "; ".join(f"{a.get('source', '')} {a.get('job_id', '')} {a.get('job_url', '')}".strip() for a in r.also_listed_on if isinstance(a, dict))


def _notes(r: Row) -> str:
    return "\n".join(str(n.get("text", "")) for n in r.notes)


# header -> value; mirrors the View Details page (Vacancy, Posting, Description, Requirements, Contact) plus the list columns
def _columns() -> list[tuple[str, Callable[[Row, Any], Any]]]:
    sec = lambda r: extract_sections(r.description or "")
    return [
        ("Company name", lambda r, s: r.company),
        ("Company website", lambda r, s: r.company_website),
        ("Company LinkedIn page", lambda r, s: r.company_linkedin or r.company_url),
        ("Company rating", lambda r, s: r.company_rating),
        ("Company reviews", lambda r, s: r.company_reviews),
        ("Job title", lambda r, s: r.title),
        ("Designation", lambda r, s: r.designation),
        ("Job poster (shown on posting)", lambda r, s: r.poster.name if r.poster else None),
        ("Job poster LinkedIn", lambda r, s: r.poster.linkedin_url if r.poster else None),
        ("Suggested recruiters (not confirmed posters)", lambda r, s: "; ".join(
            f"{c.name}" + (f" ({c.designation})" if c.designation else "") + (f" {c.linkedin_url}" if c.linkedin_url else "") for c in r.suggested_contacts) or None),
        ("Original vacancy / post link", lambda r, s: r.job_url),
        ("Industry Type", lambda r, s: r.industry),
        ("Parent company headquarters", lambda r, s: {"outside": "Outside India", "india": "India"}.get(r.hq_status, "Unknown")),
        ("Headquarters country", lambda r, s: r.hq_country),
        ("Headquarters evidence", lambda r, s: r.hq_evidence),
        ("Industry (source label)", lambda r, s: r.industry_label),
        ("Location", lambda r, s: r.location),
        ("State", lambda r, s: r.state_name),
        ("Country", lambda r, s: r.country),
        ("Work mode", lambda r, s: r.work_mode),
        ("Employment type", lambda r, s: r.employment_type),
        ("Employment details (source)", lambda r, s: r.employment_details),
        ("Role category", lambda r, s: r.role_category),
        ("Job role", lambda r, s: r.job_role),
        ("Openings", lambda r, s: r.openings),
        ("Applicants so far", lambda r, s: r.applicants),
        ("Posted by", lambda r, s: r.posted_by),
        ("Posting date", lambda r, s: _iso(r.posted)),
        ("Posting date (as shown)", lambda r, s: vm.format_moment(r.posted) if r.posted.known else ""),
        ("Posting date is estimated", lambda r, s: r.posted.estimated),
        ("Source", lambda r, s: r.source),
        ("Job ID", lambda r, s: r.job_id),
        ("Original job URL", lambda r, s: r.job_url),
        ("Also listed on", lambda r, s: _also(r)),
        ("First found by the tool", lambda r, s: r.first_ingested_at),
        ("Last seen", lambda r, s: r.last_seen_at),
        ("Times seen", lambda r, s: r.times_seen),
        ("Salary", lambda r, s: r.salary),
        ("Job summary", lambda r, s: s.summary),
        ("Full job description", lambda r, s: clean_description(r.description) if r.description else ""),
        ("Key responsibilities", lambda r, s: _bullets(s.responsibilities)),
        ("Required qualifications and skills", lambda r, s: _bullets(s.qualifications)),
        ("Education (source)", lambda r, s: r.education_structured or r.education),
        ("Experience required", lambda r, s: _bullets(s.experience) or r.experience_structured or r.experience_text),
        ("Key skills", lambda r, s: r.skills),
        ("Contact details available", lambda r, s: r.contact_direct),
        ("Contact name", lambda r, s: r.recruiter_name),
        ("Contact phone", lambda r, s: r.contact_phones),
        ("Contact email", lambda r, s: r.contact_emails),
        ("Contact LinkedIn profile", lambda r, s: r.contact_linkedin),
        ("Contact URL", lambda r, s: r.contact_urls),
        ("Why it qualifies", lambda r, s: r.category_reason),
        ("Recruitment status", lambda r, s: r.status),
        ("Saved", lambda r, s: r.saved),
        ("Notes", lambda r, s: _notes(r)),
        ("Vacancy key", lambda r, s: r.key),
    ]


def sort_for_export(rows: list[Row]) -> list[Row]:
    """Newest posting first; unknown posting dates after every known one (then by when the tool first found them)."""
    known = [r for r in rows if r.posted.known]
    unknown = [r for r in rows if not r.posted.known]
    known.sort(key=lambda r: (vm.posted_sort_key(r.posted), r.first_ingested_at or "", r.key), reverse=True)
    unknown.sort(key=lambda r: (r.first_ingested_at or "", r.key), reverse=True)
    return known + unknown


def build_csv(rows: list[Row]) -> bytes:
    cols = _columns()
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow([name for name, _ in cols])
    for r in sort_for_export(rows):
        s = extract_sections(r.description or "")
        w.writerow([_cell(fn(r, s)) for _, fn in cols])
    return ("﻿" + buf.getvalue()).encode("utf-8")
