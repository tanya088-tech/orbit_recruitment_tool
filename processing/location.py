"""Decide whether a LinkedIn location string is in India, and name the country."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from config import filter_rules as R


def _phrase_regex(phrases: set[str]) -> re.Pattern:
    # longest first so "new delhi" wins over "delhi"
    alt = "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"\b(?:{alt})\b")


_INDIA_PLACES = _phrase_regex(R.INDIA_CITIES | R.INDIA_STATES)
_FOREIGN_COUNTRY = _phrase_regex(R.FOREIGN_COUNTRIES)
_FOREIGN_PLACE = _phrase_regex(R.FOREIGN_PLACES)
_US_STATE = _phrase_regex(R.US_STATES)
_INDIA_WORD = re.compile(r"\bindia\b")
_COUNTRY_CODE_IN = re.compile(r"(?:,|\s)IN\s*$")      # "Pune, MH, IN"
_REMOTE = re.compile(r"\b(remote|hybrid|work from home|wfh)\b")
_FULLY_REMOTE = re.compile(r"\b(remote|work from home|wfh)\b")      # "hybrid" is NOT fully remote


@dataclass
class LocationResult:
    is_india: bool
    country: Optional[str]       # "India", a foreign country/place name, or None if unknown
    code: str                    # ok | location_not_india | location_unavailable
    reason: str
    is_remote_or_hybrid: bool = False
    is_remote: bool = False      # remote / work-from-home named in the location (hybrid alone does not count)


def _pretty(name: str) -> str:
    return name.upper() if len(name) <= 3 else name.title()


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def check_location(location: Optional[str]) -> LocationResult:
    if not location or not str(location).strip():
        return LocationResult(False, None, "location_unavailable", "location unavailable")

    raw = str(location).strip()
    norm = _normalize(raw)
    remote = bool(_REMOTE.search(norm))
    fully_remote = bool(_FULLY_REMOTE.search(norm))

    if _INDIA_WORD.search(norm) or _COUNTRY_CODE_IN.search(raw):
        return LocationResult(True, "India", "ok", f"'{raw}' is in India", remote, fully_remote)

    # Country is normally the LAST part of a LinkedIn location, so take the last country match.
    countries = list(_FOREIGN_COUNTRY.finditer(norm))
    if countries:
        name = _pretty(countries[-1].group(0))
    elif _US_STATE.search(norm):
        name = "United States"
    else:
        place = _FOREIGN_PLACE.search(norm)
        name = _pretty(place.group(0)) if place else None
    if name:
        return LocationResult(False, name, "location_not_india",
                              f"location '{raw}' is outside India ({name})", remote, fully_remote)

    place = _INDIA_PLACES.search(norm)
    if place:
        return LocationResult(True, "India", "ok", f"'{raw}' matched Indian place '{place.group(0)}'", remote, fully_remote)

    why = "remote with no India mentioned" if remote else "no Indian city/state recognised"
    return LocationResult(False, None, "location_not_india", f"location '{raw}' not recognised as India ({why})", remote, fully_remote)
