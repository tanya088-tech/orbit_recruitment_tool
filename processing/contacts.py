"""Contact details a job posting itself publishes - and nothing else.

extract_contacts / poster_contacts read ONLY what the posting text (or the stored record) states: e-mail addresses,
phone numbers, a name written next to them, a LinkedIn profile link and apply / contact links. Nothing is guessed,
looked up or invented, and company-process lines (accommodation, accessibility, help desk) are not the poster's contact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_BAD_EMAIL_END = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf")
_BAD_EMAIL_NAMES = {"example", "sample", "yourname", "name", "email", "user", "xyz", "abc"}
# 10-digit Indian mobile (optionally +91 / 0 / 91 first), also written "98765 43210"; and 1-800 / international style numbers.
_MOBILE = re.compile(r"(?<![\d.])(?:\+?91[\s-]?|0)?([6-9]\d{4}[\s-]?\d{5})(?![\d])")
_INTL = re.compile(r"(?<![\d.])(\+\d{1,3}[\s-]?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{2,4}|1[\s-]?800[\s-]?\d{3}[\s-]?\d{4})(?![\d])")
_MONEY_BEFORE = re.compile(r"(?:₹|rs\.?|inr|ctc|salary|lpa|usd|\$)\s*$", re.I)
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_URL_CUE = re.compile(r"(apply|contact|career|register|walk[- ]?in|resume|cv|submit|connect)", re.I)
_LI_PROFILE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9_%\-.]{2,100}/?", re.I)
# Boilerplate that is about the company's process, not the person who posted the job: accommodation / accessibility /
# privacy / technical-help lines and mailboxes. These are not "the job poster's contact details".
_BOILER_CTX = re.compile(r"accommodat|accessib|disabilit|assistive|reasonable adjustment|e-?verify|privacy|data protection|grievance|"
                         r"complaint|unsubscribe|technical (?:issue|difficult|problem)|trouble (?:applying|accessing)|difficulty (?:applying|accessing)|"
                         r"employee assistance|hr service center|helpdesk|help desk", re.I)
_BOILER_LOCAL = re.compile(r"accommodat|accessib|no-?reply|do-?not-?reply|privacy|legal|compliance|helpdesk|hrhelp|grievance|"
                           r"unsubscribe|ombuds|support$|abuse|security@?", re.I)
_SKIP_HOSTS = ("facebook.com", "twitter.com", "instagram.com", "youtube.com", "play.google.com", "apps.apple.com")

_STOP_NAMES = {"capital", "one", "contact", "email", "mail", "recruiting", "recruitment", "please", "hr", "team", "human", "resources",
               "service", "center", "careers", "talent", "acquisition", "call", "phone", "mobile", "number", "details", "id", "for",
               "the", "our", "us", "now", "more", "apply", "send", "share", "cv", "resume", "us", "at", "on", "via", "direct", "directly"}
_NAME = r"([A-Z][a-z]{1,20}(?:\s[A-Z][a-z]{1,20}){0,2})"
_NAME_BEFORE_EMAIL = re.compile(_NAME + r"\s*\(\s*(?:e-?mail[:\s]*)?$")                       # "Swati Pal (swati@x.com)"
_NAME_AFTER_CUE = re.compile(r"(?:\b[Hh][Rr]\b|recruiter|contact(?: person)?|call|ask for|talk to|reach out to|connect with|attention|Mr\.?|Ms\.?|Mrs\.?)"
                             r"\s*[:\-]?\s*(?:Mr\.?\s*|Ms\.?\s*|Mrs\.?\s*)?" + _NAME + r"\s*[:\-(,]?\s*(?:\+?\d|e-?mail|\(|[A-Za-z0-9._%+-]+@|$)")


def _boiler_near(body: str, start: int, end: int) -> bool:
    """True when the SAME sentence is about accommodation / accessibility / help-desk style matters."""
    left = max(body.rfind(". ", 0, start), body.rfind("\n", 0, start), start - 160) + 1
    nxt = [i for i in (body.find(". ", end), body.find("\n", end)) if i != -1]
    right = min(nxt + [end + 60])
    return bool(_BOILER_CTX.search(body[left:right]))


@dataclass
class Contacts:
    name: Optional[str] = None
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)          # apply / contact links (shown, but not "contact details")
    linkedin: Optional[str] = None                         # a LinkedIn PROFILE link written in the posting (never looked up)

    @property
    def direct(self) -> bool:
        """The poster's contact details are stated: an e-mail, a phone number or a LinkedIn profile (a lone name or an apply link is not enough)."""
        return bool(self.phones or self.emails or self.linkedin)


def _uniq(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _clean_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    words = raw.split()
    while words and words[-1].lower() in _STOP_NAMES:
        words.pop()
    if not words or any(w.lower() in _STOP_NAMES for w in words):
        return None
    return " ".join(words)


def _digits_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw)
    return f"{d[:5]} {d[5:]}" if len(d) == 10 else raw.strip()


def extract_contacts(text: Optional[str]) -> Contacts:
    """Contact details written in a posting. Returns empty Contacts when the posting states none."""
    out = Contacts()
    if not text or not isinstance(text, str):
        return out
    body = text
    first_email_pos = None
    for m in _EMAIL.finditer(body):
        mail = m.group(0).rstrip(".,;:").lower()
        if mail.endswith(_BAD_EMAIL_END) or mail.split("@")[0] in _BAD_EMAIL_NAMES:
            continue
        if _BOILER_LOCAL.search(mail.split("@")[0]) or _boiler_near(body, m.start(), m.end()):
            continue
        out.emails.append(mail)
        if first_email_pos is None:
            first_email_pos = m.start()
        nm = _NAME_BEFORE_EMAIL.search(body[max(0, m.start() - 60):m.start()])
        if nm and not out.name:
            out.name = _clean_name(nm.group(1))
    for m in _MOBILE.finditer(body):
        if _MONEY_BEFORE.search(body[max(0, m.start() - 12):m.start()]) or _boiler_near(body, m.start(), m.end()):
            continue
        out.phones.append(_digits_phone(m.group(1)))
    for m in _INTL.finditer(body):
        if _MONEY_BEFORE.search(body[max(0, m.start() - 12):m.start()]) or _boiler_near(body, m.start(), m.end()):
            continue
        digits = re.sub(r"\D", "", m.group(1))
        if 10 <= len(digits) <= 13 and not any(digits.endswith(re.sub(r"\D", "", p)) for p in out.phones):
            out.phones.append(m.group(1).strip())
    for m in _LI_PROFILE.finditer(body):
        out.linkedin = m.group(0).rstrip("/.,;:")
        break
    for m in _URL.finditer(body):
        url = m.group(0).rstrip(".,;:")
        if any(h in url.lower() for h in _SKIP_HOSTS) or _LI_PROFILE.match(url):
            continue
        if _URL_CUE.search(body[max(0, m.start() - 50):m.start()]):
            out.urls.append(url)
    if not out.name:
        for m in _NAME_AFTER_CUE.finditer(body):
            name = _clean_name(m.group(1))
            if name:
                out.name = name
                break
    out.emails, out.phones, out.urls = _uniq(out.emails)[:5], _uniq(out.phones)[:5], _uniq(out.urls)[:3]
    return out


def poster_contacts(description: Optional[str], email: Optional[str] = None, phone: Optional[str] = None,
                    name: Optional[str] = None, contact_url: Optional[str] = None) -> Contacts:
    """The job poster's contact details: what the posting text states plus any values stored on the record itself.

    Company mailboxes of other postings and suggestions are NOT included - this is only what this posting states."""
    c = extract_contacts(description)
    if email and str(email).strip():
        c.emails.insert(0, str(email).strip())
    if phone and str(phone).strip():
        c.phones.insert(0, str(phone).strip())
    if name and str(name).strip() and not c.name:
        c.name = str(name).strip()
    if contact_url and _LI_PROFILE.match(str(contact_url).strip()):
        c.linkedin = str(contact_url).strip().rstrip("/")
    elif contact_url and str(contact_url).strip():
        c.urls.insert(0, str(contact_url).strip())
    c.emails, c.phones, c.urls = _uniq(c.emails)[:5], _uniq(c.phones)[:5], _uniq(c.urls)[:3]
    return c
