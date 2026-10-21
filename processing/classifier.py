"""Strict GCC / BFSI eligibility (deterministic, no AI).

A job is eligible only when the EMPLOYER clearly is a GCC or a BFSI business, or (BFSI only) the job
itself is specific BFSI work. A generic word - HR, recruiter, talent acquisition, manager, analyst,
operations, technology, finance - is never evidence on its own. Recruitment / staffing employers,
agency postings ("our client ...") and employers that are not named are never eligible, because the
real employer is unknown. Not enough evidence means NOT eligible.

Returns potential_gcc, potential_bfsi (the dashboard labels), a human-readable reason and the signals
(which field and term triggered each). Same function for every source (LinkedIn, Naukri, ...).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from config import filter_rules as R
from config import settings


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_STAFF_IND = _compile(R.STAFFING_INDUSTRY_PATTERNS)
_STAFF_CO = _compile(R.STAFFING_COMPANY_PATTERNS)
_FOR_CLIENT = _compile(R.HIRING_FOR_CLIENT_PATTERNS)
_BFSI_IND = _compile(R.BFSI_STRICT_INDUSTRY_PATTERNS)
_BFSI_CO = _compile(R.BFSI_STRICT_COMPANY_PATTERNS)
_BFSI_CO_AMBIG = _compile(R.BFSI_AMBIGUOUS_COMPANY_PATTERNS)
_BFSI_KNOWN = _compile(R.KNOWN_BFSI_EMPLOYERS)
_BFSI_TITLE = _compile(R.BFSI_STRICT_TITLE_PATTERNS)
_BFSI_DESC = _compile(R.BFSI_DESCRIPTION_PATTERNS)
_HR_TITLE = _compile(R.HR_TITLE_PATTERNS)
_PAGE_SLUG = _compile(R.BFSI_PAGE_SLUG_PATTERNS)
_SLUG_BLOCK_IND = _compile(R.PAGE_SLUG_BLOCKING_INDUSTRY_PATTERNS)
_TITLE_BLOCK_IND = _compile(R.TITLE_ROUTE_BLOCKING_INDUSTRY_PATTERNS)
_COMPANY_PAGE = re.compile(r"/company/([^/?#]+)", re.IGNORECASE)
_GCC_SELF = _compile(R.GCC_SELF_DESCRIPTION_PATTERNS)
_GCC_CENTER = _compile(R.GCC_CENTER_PATTERNS)
_GCC_MNC = _compile(R.GCC_MNC_CUE_PATTERNS)
_GCC_COMPANY_ONLY = _compile(R.GCC_COMPANY_ONLY_PATTERNS)
_GCC_EMPLOYER_CUE = re.compile(R.GCC_EMPLOYER_CUE, re.IGNORECASE)
_GCC_TOKEN = re.compile(r"\bGCCs?\b")                      # case-sensitive on purpose
_GCC_NON_CAP = re.compile(R.GCC_TOKEN_NON_CAPABILITY_CONTEXT, re.IGNORECASE)

_FIELD_LABEL = {
    "industries": "industry", "company": "company name", "title": "job title",
    "description": "job description", "posted_by": "posted by",
}


_OVERSEAS_HQ = [(re.compile(p, re.IGNORECASE), c) for p, c in R.OVERSEAS_HQ_EMPLOYERS]
_GCC_KNOWN = [(re.compile(p, re.IGNORECASE), c) for p, c in R.KNOWN_GCC_EMPLOYERS]
_GCC_KNOWN_MIXED = [(re.compile(p, re.IGNORECASE), c) for p, c in R.KNOWN_GCC_MIXED_EMPLOYERS]
_GCC_CAPABILITY_TITLE = _compile(R.GCC_CAPABILITY_TITLE_PATTERNS)
_GCC_NAME_NOT_FOR_TITLE = _compile(R.GCC_NAME_NOT_FOR_TITLE_PATTERNS)
_INDIA_HQ = _compile(R.INDIA_HQ_EMPLOYERS)
_CARD_TITLE_SKIP = _compile(R.CARD_TITLE_SKIP_PATTERNS)
_HQ_STATEMENTS = _compile(R.HQ_STATEMENT_PATTERNS)
_HQ_ADJECTIVE = re.compile(R.HQ_ADJECTIVE_PATTERN, re.IGNORECASE)
_INDIA_PLACES = {x.lower() for x in R.INDIA_CITIES} | {x.lower() for x in R.INDIA_STATES} | {"india", "bharat"}
_FOREIGN_PLACES = ({x.lower() for x in R.FOREIGN_COUNTRIES} | {x.lower() for x in R.US_STATES} | {x.lower() for x in R.FOREIGN_PLACES}
                   | {x.lower() for x in R.HQ_FOREIGN_CITIES})
_ADJ_COUNTRY = {"us": "United States", "usa": "United States", "american": "United States", "uk": "United Kingdom", "british": "United Kingdom",
                "german": "Germany", "french": "France", "swiss": "Switzerland", "dutch": "Netherlands", "japanese": "Japan",
                "singapore": "Singapore", "singaporean": "Singapore", "canadian": "Canada", "australian": "Australia", "irish": "Ireland",
                "swedish": "Sweden", "spanish": "Spain", "italian": "Italy", "european": "Europe", "emirati": "United Arab Emirates",
                "korean": "South Korea", "chinese": "China"}


def _place_country(place: str) -> Optional[str]:
    """'India' / a foreign place name / None for the first place named in a headquarters statement ('Pune, India' -> India)."""
    first = re.split(r",|;|\band\b|\bwith\b|\bwhile\b|\bbut\b|\bwhere\b|\bwhich\b|\bwhose\b", place, maxsplit=1)[0]
    text = " " + re.sub(r"[^a-z ]+", " ", first.lower()) + " "
    text = " ".join(text.split())
    words = f" {text} "
    for name in _INDIA_PLACES:
        if f" {name} " in words:
            return "India"
    for name in sorted(_FOREIGN_PLACES, key=len, reverse=True):
        if f" {name} " in words:
            return name.title() if len(name) > 3 else name.upper()
    return None


def _headquarters(company: Optional[str], desc: str) -> tuple[Optional[str], str, str]:
    """Where the employer's group is headquartered, from reliable evidence only: ('overseas'|'india'|None, country, evidence text).
    1. a statement in the job description ('headquartered in New York'; 'a US-based bank')  2. the reference list of employers
    (India-headquartered first, then overseas). The company NAME alone, a BFSI word in it, or the job title is never used."""
    for p in _HQ_STATEMENTS:
        for m in p.finditer(desc or ""):
            where = _place_country(m.group("place"))
            if where == "India":
                return "india", "India", " ".join(m.group(0).split())[:90]
            if where:
                return "overseas", where, " ".join(m.group(0).split())[:90]
    m = _HQ_ADJECTIVE.search(desc or "")
    if m:
        key = re.sub(r"[^a-z]", "", m.group("c").lower())
        key = {"usa": "us"}.get(key, key)
        return "overseas", _ADJ_COUNTRY.get(key, m.group("c").title()), " ".join(m.group(0).split())[:60]
    name = " ".join(str(company or "").lower().split())
    if name and _hits(_INDIA_HQ, name):
        return "india", "India", "employer headquartered in India"
    for pat, country in _OVERSEAS_HQ + _GCC_KNOWN + _GCC_KNOWN_MIXED:
        if name and pat.search(name):
            return "overseas", country, f"known employer headquartered in {country}"
    return None, "", ""


def known_gcc_employer(company: Optional[str], title: Optional[str] = None) -> Optional[str]:
    """The matched name when the company is a known GCC employer (config/filter_rules.py), else None. A group that also runs an
    ordinary Indian business (KNOWN_GCC_MIXED_EMPLOYERS) matches only when `title` is capability-centre work."""
    name = " ".join(str(company or "").lower().split())
    if not name:
        return None
    for pat, _country in _GCC_KNOWN:
        m = pat.search(name)
        if m:
            return m.group(0)
    if _hits(_GCC_CAPABILITY_TITLE, title):
        for pat, _country in _GCC_KNOWN_MIXED:
            m = pat.search(name)
            if m:
                return m.group(0)
    return None

def headquarters_of(company: Optional[str], desc: Optional[str]) -> tuple[str, str, str]:
    """Parent-company headquarters for the dashboard filter: ('outside' | 'india' | 'unknown', country, evidence).
    Same evidence as the classifier uses (a statement in the posting, or the reference list of known employers) - never the
    job location, the job title or a word in the company name. 'unknown' = no reliable evidence, nothing is guessed."""
    status, country, why = _headquarters(company, desc or "")
    if status == "overseas":
        return "outside", country, why
    if status == "india":
        return "india", "India", why
    return "unknown", "", ""

@dataclass
class Signal:
    category: str       # "bfsi" | "gcc"
    field: str          # industries | company | title | description
    term: str           # what is shown in the reason
    strength: str       # "strong" | "weak"
    matched: Optional[str] = None


@dataclass
class Classification:
    potential_gcc: bool
    potential_bfsi: bool
    reason: str
    signals: list[Signal] = field(default_factory=list)
    excluded_because: Optional[str] = None     # set when the employer/posting is ruled out

    @property
    def eligible(self) -> bool:
        return self.potential_gcc or self.potential_bfsi

    def signals_as_dicts(self) -> list[dict]:
        return [asdict(s) for s in self.signals]


def _hits(patterns: list[re.Pattern], text: Optional[str]) -> list[str]:
    if not text:
        return []
    out = []
    for p in patterns:
        m = p.search(text)
        if m:
            out.append(" ".join(m.group(0).lower().split()))
    return out


def _gcc_token_hits(text: Optional[str], need_employer_cue: bool) -> list[str]:
    """Bare 'GCC' counts only when it is not the Gulf region / GNU compiler (and, in free text, about the employer)."""
    if not text:
        return []
    for m in _GCC_TOKEN.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 60]
        if _GCC_NON_CAP.search(window):
            continue
        if need_employer_cue and not _GCC_EMPLOYER_CUE.search(window):
            continue
        return [m.group(0)]
    return []


def _near_employer_cue(pattern_hit_text: str, description: str, patterns: list[re.Pattern]) -> bool:
    for p in patterns:
        for m in p.finditer(description):
            if _GCC_EMPLOYER_CUE.search(description[max(0, m.start() - 70): m.end() + 10]):
                return True
    return False


def _unclear_company(company: Optional[str]) -> bool:
    c = " ".join(str(company or "").lower().split()).strip(" .-")
    return (not c) or c in R.UNCLEAR_COMPANY_NAMES or c.startswith("confidential")


def employer_can_never_qualify(company: Optional[str]) -> bool:
    """True when the employer name alone already rules a vacancy out (recruitment/staffing firm, or no real employer named).
    Used to avoid downloading a detail page that could not change the outcome."""
    c = " ".join(str(company or "").lower().split()).strip(" .-")
    return bool(_hits(_STAFF_CO, company)) or _unclear_company(company) or c in R.PLACEHOLDER_COMPANY_NAMES


def _known_overseas_employer(name: str) -> bool:
    return any(pat.search(name) for pat, _c in _OVERSEAS_HQ + _GCC_KNOWN + _GCC_KNOWN_MIXED)


def is_known_overseas_employer(company: Optional[str]) -> bool:
    """True when the name is on one of the reference lists of overseas-headquartered / known GCC employers."""
    name = " ".join(str(company or "").lower().split())
    return bool(name) and _known_overseas_employer(name)


def skip_before_fetch_reason(company: Optional[str], title: Optional[str] = None) -> Optional[str]:
    """Why a search-result card can be passed over without opening its detail page, or None to open it. Besides the
    employers that can never qualify, with REQUIRE_OVERSEAS_HQ an employer on the India-headquartered list is skipped too
    (Axis Bank, IDFC FIRST Bank, Bajaj Finserv ...): such a vacancy is kept only in the rare case that its posting names an
    overseas headquarters, and opening every one of them is what makes a search slow."""
    if employer_can_never_qualify(company):
        return "can never qualify"
    name = " ".join(str(company or "").lower().split())
    if settings.REQUIRE_OVERSEAS_HQ and name and _hits(_INDIA_HQ, name):
        return "can never qualify (headquartered in India)"
    # title on the card (Naukri): clearly not GCC / BFSI work - unless the employer is a known GCC / overseas group
    hit = _hits(_CARD_TITLE_SKIP, title) if title else []
    if hit and not (name and _known_overseas_employer(name)):
        return f"is not a GCC / BFSI role (title: {hit[0]})"
    return None


def classify(
    company: Optional[str],
    title: Optional[str],
    description: Optional[str],
    industries: Optional[str],
    posted_by: Optional[str] = None,
    company_url: Optional[str] = None,
    location: Optional[str] = None,
) -> Classification:
    signals: list[Signal] = []
    desc = description or ""

    def done(excluded: Optional[str] = None) -> Classification:
        bfsi = [s for s in signals if s.category == "bfsi"]
        gcc = [s for s in signals if s.category == "gcc"]

        def describe(group: list[Signal]) -> str:
            return "; ".join(f"{_FIELD_LABEL[s.field]} '{s.term}'" for s in group[:4])

        hq = [s for s in signals if s.category == "hq"]
        if excluded:
            reason = f"Not eligible: {excluded}."
        elif bfsi or gcc:
            reason = (f"BFSI: {describe(bfsi) if bfsi else 'no evidence'}. "
                      f"GCC: {describe(gcc) if gcc else 'no evidence'}. "
                      + (f"Headquarters: {hq[0].term}. " if hq else "") + "Rule-based eligibility - not a verified company record.")
        else:
            reason = "Not eligible: no clear evidence that the employer is a GCC or a BFSI business."
        return Classification(bool(gcc and not excluded), bool(bfsi and not excluded), reason,
                              [] if excluded else signals, excluded_because=excluded)

    # ---- 0. The vacancy must be located in India (the client's scope) ------------------------------
    if location is not None and settings.REQUIRE_INDIA_LOCATION:
        from processing.location import check_location
        if check_location(location).country != "India":
            return done("the vacancy is not confidently located in India")

    # ---- 1. Employers that can never qualify -------------------------------------------------
    if _hits(_STAFF_IND, industries):
        return done(f"the employer's industry is '{industries.strip()}' (a recruitment/staffing business)")
    if _hits(_STAFF_CO, company):
        return done(f"'{(company or '').strip()}' is a recruitment/staffing business")
    if _hits(_FOR_CLIENT, desc):
        return done("the posting is an agency hiring for an unnamed client, so the real employer is unknown")
    if " ".join(str(company or "").lower().split()).strip(" .-") in R.PLACEHOLDER_COMPANY_NAMES:
        return done(f"'{(company or '').strip()}' is a placeholder, not a company name, so the employer is not named")
    unclear = _unclear_company(company)
    if unclear and _hits(_STAFF_CO, posted_by):
        return done(f"the employer is not named and the job was posted by '{(posted_by or '').strip()}' (a recruitment business)")

    ind_known = bool((industries or "").strip())
    ind_bfsi = _hits(_BFSI_IND, industries)
    ind_other = ind_known and not ind_bfsi          # a different industry is stated

    # ---- 2. BFSI ---------------------------------------------------------------------------------
    # Evidence = the employer's industry, a known BFSI employer, or a company name / job title backed by the description.
    # A word in the company name ("Bank", "Finance", "Insurance") or in the title is never enough by itself.
    desc_phrases = len(_hits(_BFSI_DESC, desc))
    if ind_bfsi:
        signals.append(Signal("bfsi", "industries", industries.strip(), "strong", matched=", ".join(ind_bfsi[:3])))
    elif not unclear and not ind_other:                      # no industry stated: look for other reliable evidence
        known = _hits(_BFSI_KNOWN, company)
        name = _hits(_BFSI_CO, company) or _hits(_BFSI_CO_AMBIG, company)
        if known:
            signals.append(Signal("bfsi", "company", company.strip(), "strong", matched=", ".join(known[:3])))
        elif name and desc_phrases >= R.BFSI_NAME_NEEDS_DESCRIPTION_PHRASES:
            signals.append(Signal("bfsi", "company", f"{company.strip()} (name + {desc_phrases} BFSI phrases in the description)",
                                  "strong", matched=", ".join(name[:3])))
    if not signals and not unclear and ind_other and company_url:
        # LinkedIn's industry label is sometimes wrong. The company's own page address (/company/oaknorth-bank) plus BFSI
        # wording in the posting is accepted instead - never for tech / consulting / education / staffing industries.
        m = _COMPANY_PAGE.search(company_url)
        slug = m.group(1) if m else ""
        if (slug and _hits(_PAGE_SLUG, slug) and not _hits(_SLUG_BLOCK_IND, industries)
                and desc_phrases >= R.BFSI_PAGE_SLUG_MIN_DESCRIPTION_PHRASES):
            signals.append(Signal("bfsi", "company", f"LinkedIn page '{slug}'", "strong", matched=slug))
    if not _hits(_HR_TITLE, title) and not signals and not _hits(_TITLE_BLOCK_IND, industries):
        t = _hits(_BFSI_TITLE, title)
        if t:
            need = R.OTHER_INDUSTRY_NEEDS_DESCRIPTION_PHRASES if ind_other else R.BFSI_TITLE_NEEDS_DESCRIPTION_PHRASES
            if desc_phrases >= need:
                signals.append(Signal("bfsi", "title", f"{t[0]} (+ {desc_phrases} BFSI phrases in the description)", "strong"))

    # ---- 3. GCC -------------------------------------------------------------------------------
    # Evidence = the posting describes the employer as a GCC / captive / in-house / shared-services centre. A GCC-style
    # company name ("... GCC", "... Global Tech", "... Technology Centre") counts only together with multinational-group
    # wording in the description; an industry label such as "IT & Software" says nothing about being a GCC.
    self_hits = _hits(_GCC_SELF, desc)
    if self_hits and _near_employer_cue("", desc, _GCC_SELF):
        signals.append(Signal("gcc", "description", self_hits[0], "strong"))
    elif _gcc_token_hits(desc, need_employer_cue=True):
        signals.append(Signal("gcc", "description", "GCC", "strong"))
    elif has_cue_center(desc):
        signals.append(Signal("gcc", "description", "centre of a multinational group", "weak"))
    if not unclear and not any(s.category == "gcc" for s in signals):
        name_terms = (_hits(_GCC_SELF, company)[:1] + _gcc_token_hits(company, need_employer_cue=False)
                      + _hits(_GCC_CENTER, company)[:1] + _hits(_GCC_COMPANY_ONLY, company)[:1])
        mnc = _hits(_GCC_MNC, desc)
        if name_terms and mnc:
            signals.append(Signal("gcc", "company", f"{name_terms[0]} (+ multinational wording in the description: {mnc[0]})", "weak"))
    if not unclear and not any(s.category == "gcc" for s in signals) and not _hits(_GCC_NAME_NOT_FOR_TITLE, title):
        if known_gcc_employer(company, title):
            signals.append(Signal("gcc", "company", f"{company.strip()} (known GCC employer)", "strong"))

    if unclear and signals and not ind_bfsi:
        signals = []
    if unclear and not ind_bfsi:
        return done("the employer is not named (confidential), so there is no employer evidence")
    # ---- 4. Headquarters: only employers headquartered OUTSIDE India qualify --------------------------
    if signals and settings.REQUIRE_OVERSEAS_HQ:
        status, country, why = _headquarters(company, desc)
        if status == "india":
            return done(f"the employer is headquartered in India ({why})")
        if status != "overseas":
            return done("there is no reliable evidence that the employer is headquartered outside India")
        signals.append(Signal("hq", "description" if "known employer" not in why else "company", f"{country} ({why})", "strong"))
    return done()


def has_cue_center(desc: str) -> bool:
    """'... our technology centre ... part of a multinational group': centre wording about the employer plus a multinational cue."""
    if not desc or not _hits(_GCC_MNC, desc):
        return False
    return _near_employer_cue("", desc, _GCC_CENTER)
