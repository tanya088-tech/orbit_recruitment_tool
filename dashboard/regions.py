"""Work out each job's State / location from the scraped location strings themselves.

Nothing is hard-coded: the dropdown is whatever regions appear in the data.

LinkedIn writes locations as "City, State, India". For each India location we drop the country
and any "Remote/Hybrid" words, then:
  * two or more place parts  -> the LAST place part is the region ("Pune, Maharashtra, India" -> Maharashtra)
  * a single place part      -> if the same name was seen as the city of a fuller location
                                ("Bengaluru, Karnataka, India" taught us Bengaluru -> Karnataka) use
                                that region, otherwise the place itself is the region ("Delhi")
  * "Greater Bengaluru Area" style names are matched on their core place (Bengaluru)
  * only "India"             -> no region (the job still appears under "All India")
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Iterable, Optional

_PARENS = re.compile(r"\([^)]*\)")
# words that describe the country or the work arrangement, not a place
_NOISE = re.compile(r"\b(india|remote|hybrid|work from home|wfh|on[- ]?site)\b", re.I)
_EDGE = re.compile(r"^[\s\-\u2013\u2014|/:]+|[\s\-\u2013\u2014|/:]+$")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _pretty(text: str) -> str:
    text = " ".join(text.split())
    return text.title() if text.islower() or text.isupper() else text


_AREA = re.compile(r"^(greater\s+)?(?P<core>.+?)(\s+(metropolitan\s+)?area)?$", re.I)


def _core(name: str) -> str:
    """LinkedIn writes some cities as 'Greater Bengaluru Area'; the core place is 'Bengaluru'."""
    m = _AREA.match(name.strip())
    return m.group("core") if m else name


def _place_parts(location: Optional[str]) -> list[str]:
    if not location:
        return []
    parts = [_EDGE.sub("", _NOISE.sub(" ", p)) for p in _PARENS.sub("", str(location)).split(",")]
    return [" ".join(p.split()) for p in parts if _norm(p) not in ("", "in")]


class RegionResolver:
    """location -> region (for the Location filter) and location -> state (for the details page)."""

    def __init__(self, india_locations: Iterable[Optional[str]]) -> None:
        self._city_to_region: dict[str, Counter] = {}
        self._spellings: dict[str, Counter] = {}
        self._states: set[str] = set()                  # names seen as the last part of a "City, State" location
        for loc in india_locations:
            parts = _place_parts(loc)
            for p in parts:
                self._spellings.setdefault(_norm(p), Counter())[_pretty(p)] += 1
            if len(parts) >= 2:
                self._city_to_region.setdefault(_norm(parts[0]), Counter())[_norm(parts[-1])] += 1
                self._states.add(_norm(parts[-1]))

    def _canonical(self, norm_name: str) -> str:
        c = self._spellings.get(norm_name)
        return c.most_common(1)[0][0] if c else _pretty(norm_name)

    def state(self, location: Optional[str]) -> str:
        """The state when the data shows one ('' when only a city is known)."""
        parts = _place_parts(location)
        if not parts:
            return ""
        if len(parts) >= 2:
            return self._canonical(_norm(parts[-1]))
        learned = self._city_to_region.get(_norm(parts[0])) or self._city_to_region.get(_norm(_core(parts[0])))
        if learned:
            return self._canonical(learned.most_common(1)[0][0])
        return self._canonical(_norm(parts[0])) if _norm(parts[0]) in self._states else ""

    def __call__(self, location: Optional[str]) -> str:
        """The Location-filter value: the state if known, otherwise the place itself."""
        parts = _place_parts(location)
        return self.state(location) or (self._canonical(_norm(parts[0])) if parts else "")


def build_region_resolver(india_locations: Iterable[Optional[str]]) -> RegionResolver:
    return RegionResolver(india_locations)


# ---------------------------------------------------------------- State filter
# Normalisation reference (NOT the dropdown): it only turns the spellings found in job locations into one official
# name. The State dropdown lists just the states that actually occur in the stored vacancies.
_STATE_NAMES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
)
_STATE_ALIASES = {
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry", "chattisgarh": "Chhattisgarh",
    "tamilnadu": "Tamil Nadu", "nct of delhi": "Delhi", "new delhi": "Delhi", "delhi ncr": "Delhi", "ncr": "Delhi",
    "national capital region": "Delhi", "j k": "Jammu and Kashmir", "jammu kashmir": "Jammu and Kashmir",
    "andaman nicobar islands": "Andaman and Nicobar Islands", "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu", "dadra nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "orrisa": "Odisha", "andhra": "Andhra Pradesh", "bengal": "West Bengal", "up": "Uttar Pradesh", "mp": "Madhya Pradesh",
}
# Cities that appear on their own ("Pune", "Greater Noida Area") with no state written next to them.
_CITY_STATE = {
    "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysuru": "Karnataka", "mysore": "Karnataka", "mangaluru": "Karnataka",
    "hubballi": "Karnataka", "belagavi": "Karnataka", "mumbai": "Maharashtra", "navi mumbai": "Maharashtra", "thane": "Maharashtra",
    "pune": "Maharashtra", "nagpur": "Maharashtra", "nashik": "Maharashtra", "aurangabad": "Maharashtra", "hyderabad": "Telangana",
    "secunderabad": "Telangana", "warangal": "Telangana", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "madurai": "Tamil Nadu",
    "tiruchirappalli": "Tamil Nadu", "salem": "Tamil Nadu", "gurugram": "Haryana", "gurgaon": "Haryana", "faridabad": "Haryana",
    "panipat": "Haryana", "noida": "Uttar Pradesh", "greater noida": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh", "lucknow": "Uttar Pradesh",
    "kanpur": "Uttar Pradesh", "agra": "Uttar Pradesh", "varanasi": "Uttar Pradesh", "prayagraj": "Uttar Pradesh", "kolkata": "West Bengal",
    "howrah": "West Bengal", "siliguri": "West Bengal", "ahmedabad": "Gujarat", "gandhinagar": "Gujarat", "surat": "Gujarat",
    "vadodara": "Gujarat", "rajkot": "Gujarat", "gift city": "Gujarat", "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan",
    "kochi": "Kerala", "cochin": "Kerala", "thiruvananthapuram": "Kerala", "trivandrum": "Kerala", "kozhikode": "Kerala",
    "visakhapatnam": "Andhra Pradesh", "vijayawada": "Andhra Pradesh", "amaravati": "Andhra Pradesh", "tirupati": "Andhra Pradesh",
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh", "bhubaneswar": "Odisha", "cuttack": "Odisha", "patna": "Bihar",
    "ranchi": "Jharkhand", "jamshedpur": "Jharkhand", "raipur": "Chhattisgarh", "bhilai": "Chhattisgarh", "dehradun": "Uttarakhand",
    "guwahati": "Assam", "panaji": "Goa", "margao": "Goa", "shimla": "Himachal Pradesh", "srinagar": "Jammu and Kashmir",
    "jammu": "Jammu and Kashmir", "mohali": "Punjab", "ludhiana": "Punjab", "amritsar": "Punjab", "jalandhar": "Punjab",
}
_STATE_BY_NORM = {_norm(n): n for n in _STATE_NAMES}
_STATE_BY_NORM.update({_norm(k): v for k, v in _STATE_ALIASES.items()})


def indian_state(location: Optional[str], learned_city_region: Optional[Callable[[str], str]] = None) -> str:
    """The official state / union territory named by an India location, or "" when it names none.

    Used only for locations already judged to be in India. A state written in the text wins (last part first); a lone
    well-known city maps to its state; a city learned from "City, State" locations in the data may also map.
    Missing or unrecognised text gives "" - it is never guessed."""
    parts = _place_parts(location)
    if not parts:
        return ""
    for p in reversed(parts):
        hit = _STATE_BY_NORM.get(_norm(p))
        if hit:
            return hit
    for p in parts:
        n = _norm(p)
        hit = _CITY_STATE.get(n) or _CITY_STATE.get(_norm(_core(p)))
        if hit:
            return hit
        if learned_city_region:
            learned = _STATE_BY_NORM.get(_norm(learned_city_region(p) or ""))
            if learned:
                return learned
    return ""
