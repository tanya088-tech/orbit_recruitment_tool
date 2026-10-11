"""Deterministic GCC / BFSI potential classification (no AI).

Returns potential_gcc, potential_bfsi, a human-readable classification_reason and the
list of signals (which field and term triggered each). This is keyword evidence only -
it never confirms that a company IS a GCC or a BFSI firm.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from config import filter_rules as R


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_BFSI_INDUSTRY = _compile(R.BFSI_INDUSTRY_PATTERNS)
_BFSI_COMPANY = _compile(R.BFSI_COMPANY_PATTERNS)
_BFSI_TITLE = _compile(R.BFSI_TITLE_PATTERNS)
_BFSI_DESC = _compile(R.BFSI_DESCRIPTION_PATTERNS)
_GCC_EXPLICIT = _compile(R.GCC_EXPLICIT_PATTERNS)
_GCC_CENTER = _compile(R.GCC_CENTER_PATTERNS)
_GCC_MNC = _compile(R.GCC_MNC_CUE_PATTERNS)
_GCC_COMPANY_ONLY = _compile(R.GCC_COMPANY_ONLY_PATTERNS)
_GCC_TOKEN = re.compile(r"\bGCCs?\b")                      # case-sensitive on purpose
_GCC_NON_CAP = re.compile(R.GCC_TOKEN_NON_CAPABILITY_CONTEXT, re.IGNORECASE)

_FIELD_LABEL = {
    "industries": "LinkedIn industry", "company": "company name",
    "title": "job title", "description": "job description",
}


@dataclass
class Signal:
    category: str       # "bfsi" | "gcc"
    field: str          # industries | company | title | description
    term: str           # what is shown in the reason (full field value for industry/company)
    strength: str       # "strong" | "weak"
    matched: Optional[str] = None   # the keyword fragment that actually matched


@dataclass
class Classification:
    potential_gcc: bool
    potential_bfsi: bool
    reason: str
    signals: list[Signal] = field(default_factory=list)

    def signals_as_dicts(self) -> list[dict]:
        return [asdict(s) for s in self.signals]


def _first_hits(patterns: list[re.Pattern], text: Optional[str]) -> list[str]:
    """One matched string per pattern that hits (distinct patterns, in order)."""
    if not text:
        return []
    hits = []
    for p in patterns:
        m = p.search(text)
        if m:
            hits.append(" ".join(m.group(0).lower().split()))
    return hits


def _gcc_token_hits(text: Optional[str]) -> list[str]:
    """Bare 'GCC' counts only when it is not clearly the Gulf region or the GNU compiler."""
    if not text:
        return []
    out = []
    for m in _GCC_TOKEN.finditer(text):
        window = text[max(0, m.start() - 40): m.end() + 40]
        if not _GCC_NON_CAP.search(window):
            out.append(m.group(0))
    return out[:1]


def classify(
    company: Optional[str],
    title: Optional[str],
    description: Optional[str],
    industries: Optional[str],
) -> Classification:
    signals: list[Signal] = []

    # ---------------- BFSI ----------------
    ind_hits = _first_hits(_BFSI_INDUSTRY, industries)
    if ind_hits:
        signals.append(Signal("bfsi", "industries", industries.strip(), "strong", matched=", ".join(ind_hits[:3])))
    comp_hits = _first_hits(_BFSI_COMPANY, company)
    if comp_hits:
        signals.append(Signal("bfsi", "company", company.strip(), "strong", matched=", ".join(comp_hits[:3])))
    for term in _first_hits(_BFSI_TITLE, title)[:2]:
        signals.append(Signal("bfsi", "title", term, "strong"))

    desc_terms = _first_hits(_BFSI_DESC, description)
    if len(desc_terms) >= R.BFSI_DESCRIPTION_MIN_DISTINCT:
        signals.append(Signal("bfsi", "description", ", ".join(desc_terms[:5]), "weak"))

    # ---------------- GCC ----------------
    for fname, text in (("company", company), ("title", title), ("description", description)):
        for term in _first_hits(_GCC_EXPLICIT, text)[:1]:
            signals.append(Signal("gcc", fname, term, "strong"))
        for term in _gcc_token_hits(text):
            signals.append(Signal("gcc", fname, term, "strong"))

    for fname, text in (("company", company), ("title", title)):
        for term in _first_hits(_GCC_CENTER, text)[:1]:
            signals.append(Signal("gcc", fname, term, "weak"))
    for term in _first_hits(_GCC_COMPANY_ONLY, company)[:1]:
        signals.append(Signal("gcc", "company", term, "weak"))

    desc_center = _first_hits(_GCC_CENTER, description)
    if desc_center:
        cues = _first_hits(_GCC_MNC, f"{company or ''}\n{description or ''}")
        if cues:
            signals.append(Signal("gcc", "description", f"{desc_center[0]} (+ multinational cue: {cues[0]})", "weak"))

    bfsi = [s for s in signals if s.category == "bfsi"]
    gcc = [s for s in signals if s.category == "gcc"]

    def describe(group: list[Signal]) -> str:
        return "; ".join(f"{_FIELD_LABEL[s.field]} '{s.term}'" for s in group[:4])

    reason = (
        f"Potential BFSI: {describe(bfsi) if bfsi else 'no BFSI signals found'}. "
        f"Potential GCC: {describe(gcc) if gcc else 'no GCC signals found'}. "
        "Keyword-based indication only - not a confirmed GCC/BFSI classification."
    )
    return Classification(potential_gcc=bool(gcc), potential_bfsi=bool(bfsi), reason=reason, signals=signals)
