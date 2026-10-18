"""Hiring contacts: the job poster (only when the posting itself publicly shows them) and Suggested Recruiters.

Two kinds, never mixed up:
  * "Job Poster"          - name / designation / LinkedIn profile that the original posting page publicly displayed and the collector
                            read from the page it already downloads (no login, no extra request, no personalised recommendations).
  * "Suggested Recruiter" - a recruiter / talent-acquisition person at the same company taken from a CONTACT DIRECTORY the team
                            controls (data/hiring_contacts.json), filled from an authorised source (a licensed export, an official API,
                            a provider the client has a contract with). Each entry carries its source. A suggestion is never presented
                            as the person who posted the job.
Nothing here visits LinkedIn, guesses a profile, or looks a person up."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from config import settings
from processing.normalize import company_key

JOB_POSTER = "Job Poster"
SUGGESTED = "Suggested Recruiter"
TEAM_POSTER = "Job Poster (added by your team)"
_PROFILE = re.compile(r"^https?://(?:[a-z]{2,3}\.|www\.)?linkedin\.com/in/[A-Za-z0-9%_\-]{2,100}/?$", re.I)
_EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")
_ROLE_WORDS = ("recruit", "talent acquisition", "talent partner", "hiring", "hr ", "human resources", "people partner", "staffing")


@dataclass
class HiringContact:
    kind: str                           # JOB_POSTER | SUGGESTED
    name: Optional[str] = None
    designation: Optional[str] = None
    company: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    source: str = ""                    # where the information came from
    note: str = ""
    entered_by: Optional[str] = None
    entered_at: Optional[str] = None


def clean_profile_url(url: Any) -> Optional[str]:
    """A public LinkedIn PERSON profile link, with query / fragment dropped; anything else is rejected."""
    text = str(url or "").strip().split("#")[0].split("?")[0]
    return text.rstrip("/") if _PROFILE.match(text) else None


def _txt(value: Any, limit: int = 120) -> Optional[str]:
    t = " ".join(str(value or "").split())
    return t[:limit] or None


def poster_from_record(raw_data: Any, company: Optional[str]) -> Optional[HiringContact]:
    """The poster the posting page itself displayed (stored by the collector in raw_data['poster'])."""
    p = (raw_data or {}).get("poster") if isinstance(raw_data, dict) else None
    if not isinstance(p, dict):
        return None
    url = clean_profile_url(p.get("profile_url"))
    name = _txt(p.get("name"))
    if not (url or name):
        return None
    return HiringContact(JOB_POSTER, name, _txt(p.get("designation")), company, url, source="Shown on the original LinkedIn job posting")


def team_poster_from_entry(e: Any, company: Optional[str]) -> Optional[HiringContact]:
    """A poster the team confirmed on LinkedIn ('Meet the hiring team') and typed in; see store.json_store.JsonPosterEntries."""
    if not isinstance(e, dict):
        return None
    url, name = clean_profile_url(e.get("profile_url")), _txt(e.get("name"))
    if not (url and name and e.get("confirmed") is True and e.get("entered_by")):
        return None
    return HiringContact(TEAM_POSTER, name, _txt(e.get("designation")), company, url, source="Seen on the LinkedIn posting by your team",
                         entered_by=_txt(e.get("entered_by"), 80), entered_at=e.get("entered_at"))


def valid_entry(e: Any) -> Optional[dict[str, Any]]:
    """A directory entry is usable only with a company, a name, a source, and (if given) a proper LinkedIn /in/ link."""
    if not isinstance(e, dict):
        return None
    company, name, source = _txt(e.get("company")), _txt(e.get("name")), _txt(e.get("source"), 200)
    if not (company and name and source):
        return None
    url = clean_profile_url(e.get("linkedin_url")) if e.get("linkedin_url") else None
    if e.get("linkedin_url") and not url:
        return None
    email = _txt(e.get("email"), 200)
    if email and not _EMAIL.match(email):
        email = None
    phone = _txt(e.get("phone"), 40)
    return {"company": company, "name": name, "designation": _txt(e.get("designation")), "linkedin_url": url, "email": email,
            "phone": phone, "location": _txt(e.get("location")), "source": source, "retrieved_at": _txt(e.get("retrieved_at"), 40)}


class ContactDirectory:
    def __init__(self, entries: Iterable[Any] = ()) -> None:
        self.by_company: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            v = valid_entry(e)
            if v:
                self.by_company.setdefault(company_key(v["company"]), []).append(v)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ContactDirectory":
        path = Path(path or settings.HIRING_CONTACTS_FILE)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(data.get("contacts", []) if isinstance(data, dict) else data if isinstance(data, list) else [])

    def suggest(self, company: Optional[str], location: Optional[str] = None, title: Optional[str] = None, limit: int = 3) -> list[HiringContact]:
        """Recruiters at the SAME company, those in the job's city / state first, then those whose designation is a hiring role.
        Never claimed to be the poster."""
        key = company_key(company)
        if not key:
            return []
        loc = (location or "").lower()
        city = loc.split(",")[0].strip()

        def rank(e: dict[str, Any]) -> tuple:
            where = (e.get("location") or "").lower()
            return (0 if city and city in where else 1,
                    0 if any(w in (e.get("designation") or "").lower() + " " for w in _ROLE_WORDS) else 1,
                    e["name"].lower())

        out = []
        for e in sorted(self.by_company.get(key, []), key=rank)[:limit]:
            out.append(HiringContact(SUGGESTED, e["name"], e["designation"], e["company"], e["linkedin_url"], e["email"], e["phone"],
                                     e["location"], e["source"], "Suggested from the company's recruiters - not confirmed as the person who posted this job"))
        return out


def import_csv(csv_path: Path, directory_path: Optional[Path] = None) -> dict[str, int]:
    """Add rows of an authorised export (columns: company, name, designation, linkedin_url, location, email, phone, source,
    retrieved_at) to the directory file. Rows without company / name / source, or with a bad LinkedIn link, are rejected.
    Existing entries are kept; the same person (company + name + link) is not added twice."""
    directory_path = Path(directory_path or settings.HIRING_CONTACTS_FILE)
    try:
        current = json.loads(directory_path.read_text(encoding="utf-8")).get("contacts", [])
    except (OSError, ValueError, AttributeError):
        current = []
    seen = {(company_key(c.get("company")), (c.get("name") or "").lower(), c.get("linkedin_url") or "") for c in current}
    added = rejected = duplicate = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            v = valid_entry({k.strip().lower(): val for k, val in row.items() if k})
            if not v:
                rejected += 1
                continue
            sig = (company_key(v["company"]), v["name"].lower(), v["linkedin_url"] or "")
            if sig in seen:
                duplicate += 1
                continue
            seen.add(sig)
            current.append(v)
            added += 1
    tmp = directory_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"contacts": current}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(directory_path)
    return {"added": added, "rejected": rejected, "duplicate": duplicate, "total": len(current)}


def linkedin_people_search_url(company: Optional[str]) -> Optional[str]:
    """A plain LinkedIn people-search link the PERSON clicks and uses in their own session. Not a contact, and never fetched by the tool."""
    from urllib.parse import quote_plus
    c = _txt(company, 80)
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(c + ' talent acquisition recruiter')}" if c else None
