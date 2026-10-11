"""Consistent company and location text (display only; stored history is never rewritten)."""
from __future__ import annotations

import html
import re
from typing import Any, Optional

_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")

# Well-known official renames of Indian cities. One spelling is used everywhere so the same
# city is not counted twice ("Bangalore" and "Bengaluru").
CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengalooru": "Bengaluru", "bombay": "Mumbai", "calcutta": "Kolkata",
    "madras": "Chennai", "gurgaon": "Gurugram", "poona": "Pune", "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram", "mysore": "Mysuru", "vizag": "Visakhapatnam",
    "baroda": "Vadodara", "pondicherry": "Puducherry", "orissa": "Odisha",
}
_ALIAS_RE = re.compile(r"\b(" + "|".join(sorted(CITY_ALIASES, key=len, reverse=True)) + r")\b", re.I)
_LEGAL_SUFFIX = re.compile(
    r"\b(pvt|private|ltd|limited|llp|llc|inc|incorporated|corp|corporation|co|company|plc|gmbh|sa|ag|bv|pte)\b\.?", re.I)


def _tidy(text: Any) -> str:
    out = html.unescape(_ZERO_WIDTH.sub("", str(text or "")))
    return " ".join(out.split())


def clean_company(name: Any) -> Optional[str]:
    text = _tidy(name).strip(" ,;|-")
    return text or None


def company_key(name: Any) -> str:
    """Comparison key: 'Acme Pvt. Ltd.' and 'ACME Private Limited' give the same key."""
    text = _LEGAL_SUFFIX.sub(" ", _tidy(name).lower().replace("&", " and "))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def clean_location(location: Any) -> Optional[str]:
    text = _tidy(location)
    if not text:
        return None
    text = _ALIAS_RE.sub(lambda m: CITY_ALIASES[m.group(1).lower()], text)
    parts = [p.strip() for p in text.split(",")]
    deduped = [p for i, p in enumerate(parts) if p and (i == 0 or p.lower() != parts[i - 1].lower())]
    return ", ".join(deduped) or None
