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
