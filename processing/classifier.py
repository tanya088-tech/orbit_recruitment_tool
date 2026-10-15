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


def classify(
    company: Optional[str],
    title: Optional[str],
    description: Optional[str],
    industries: Optional[str],
    posted_by: Optional[str] = None,
    company_url: Optional[str] = None,
) -> Classification:
    signals: list[Signal] = []
    desc = description or ""

    def done(excluded: Optional[str] = None) -> Classification:
        bfsi = [s for s in signals if s.category == "bfsi"]
        gcc = [s for s in signals if s.category == "gcc"]

        def describe(group: list[Signal]) -> str:
            return "; ".join(f"{_FIELD_LABEL[s.field]} '{s.term}'" for s in group[:4])

        if excluded:
            reason = f"Not eligible: {excluded}."
        elif bfsi or gcc:
            reason = (f"BFSI: {describe(bfsi) if bfsi else 'no evidence'}. "
                      f"GCC: {describe(gcc) if gcc else 'no evidence'}. Rule-based eligibility - not a verified company record.")
        else:
            reason = "Not eligible: no clear evidence that the employer is a GCC or a BFSI business."
        return Classification(bool(gcc and not excluded), bool(bfsi and not excluded), reason,
                              [] if excluded else signals, excluded_because=excluded)

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

    if unclear and signals and not ind_bfsi:
        signals = []
    if unclear and not ind_bfsi:
        return done("the employer is not named (confidential), so there is no employer evidence")
    return done()


def has_cue_center(desc: str) -> bool:
    """'... our technology centre ... part of a multinational group': centre wording about the employer plus a multinational cue."""
    if not desc or not _hits(_GCC_MNC, desc):
        return False
    return _near_employer_cue("", desc, _GCC_CENTER)
