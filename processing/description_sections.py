"""Pull a summary, responsibilities, qualifications and experience lines out of a job description.

Deterministic and conservative. Everything returned is the vacancy's OWN wording, copied
(bullets removed) from the description. Nothing is written, rephrased or inferred:
  * summary          - the opening text of the description, cut at a sentence end
  * responsibilities - lines under a heading such as "Key Responsibilities" / "What you will do"
  * qualifications   - lines under a heading such as "Qualifications" / "Requirements" / "Skills"
  * experience       - lines under an "Experience" heading, plus lines that state a number / range of years
  * designation      - the value of a "Designation:" / "Role/Job Title:" line, when the posting has one
Anything not found stays empty and the page shows "Not available".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# A heading is a short line with no bullet and no closing full stop whose first two words contain one of
# these stems ("Key Responsibilities", "Required qualifications, capabilities, and skills", "What you will do:").
_RESP_STEMS = re.compile(r"responsibilit|accountabilit|\bduties\b|what you(?:'ll| will)(?: be)? do|\byour role\b|day to day|in this role")
_QUAL_STEMS = re.compile(r"qualification|requirement|\bskills?\b|what you bring|looking for|who you are|must[- ]have|ideal candidate|your profile|education and experience")
OTHER_HEADINGS = (
    "about us", "about the company", "about the role", "about the job", "job description", "overview",
    "benefits", "what we offer", "why join us", "equal opportunity", "how to apply", "location", "company description",
    "about the team", "diversity", "compensation", "perks", "preferred", "nice to have", "bonus points",
)

_BULLET = re.compile(r"^\s*(?:[-*•·▪●○◦►–—]+|\d{1,2}[.)])\s*")
_NUM = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty)"
_YEARS = re.compile(rf"\b{_NUM}\s*(?:\+|\s*[-–—]\s*{_NUM}|\s*(?:to|and)\s*{_NUM})?\s*\+?\s*(?:years?|yrs?)\b", re.I)
# "Experience" as a heading of its own ("Experience:", "Total Experience", "Years of experience required:").
_EXP_HEADING = re.compile(
    r"^(?:(?:total|work|relevant|minimum|min|required|overall|professional|industry|banking)\s+)*"
    r"(?:years?\s+of\s+)?(?:experience|exp)(?:\s+(?:required|level|range|needed))?$")
_REQ_CUE = re.compile(r"\b(?:minimum|min\.?|at least|atleast|up ?to|required|requires|preferred|candidate|you (?:have|bring|will have))\b", re.I)
_HISTORY = re.compile(r"\b(?:history|founded|established|since\s+\d{4}|(?:for|with) (?:more than|over|almost|nearly)\s+\d+\s+years)\b", re.I)
_EDU_WORDS = re.compile(r"\b(?:bachelor|master|diploma|degree|b\.?sc|b\.?tech|mba)\b", re.I)
# LinkedIn's "Show more" / "Show less" buttons end up in the text of every description.
_UI_LINE = re.compile(r"^\s*(?:(?:show|see|read)\s+(?:more|less)\s*)+$", re.I)
_TITLE_LABEL = re.compile(
    r"^\s*(?:[-*•·▪●]\s*)?(?:role\s*/\s*job\s*title|job\s*title|designation|position\s*title|role\s*title)\s*:\s*(.*)$", re.I)
MAX_LINES = 25
MAX_LINE_CHARS = 400


@dataclass
class DescriptionSections:
    summary: Optional[str] = None
    responsibilities: list[str] = field(default_factory=list)
    qualifications: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    designation: Optional[str] = None


def clean_description(text: Optional[str]) -> Optional[str]:
    """Drop the page-furniture lines ("Show more", "Show less") and tidy blank lines. Wording is untouched."""
    if not text or not str(text).strip():
        return None
    lines = [ln.rstrip() for ln in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n") if not _UI_LINE.match(ln)]
    out = re.sub(r"\n\s*\n+", "\n\n", "\n".join(lines)).strip()
    return out or None


def _clean_heading(line: str) -> str:
    return re.sub(r"[\s:–—-]+$", "", _BULLET.sub("", line.strip()).replace("’", "'")).lower()


def _kind(line: str) -> Optional[str]:
    """'resp' / 'qual' / 'exp' when the line is a responsibilities / qualifications / experience heading, else None."""
    text = line.strip()
    if not text or len(text) > 80 or _BULLET.match(text) or not text[0].isupper():
        return None
    words = _clean_heading(text).split()
    if _EXP_HEADING.match(" ".join(words)):
        return "exp"
    if len(words) > 10 or (text.endswith(".") and not text.endswith(":")):
        return None
    head = " ".join(words[:4]) if text.endswith(":") else " ".join(words[:2])
    if _RESP_STEMS.search(head):
        return "resp"
    if _QUAL_STEMS.search(head):
        return "qual"
    return None


def _is_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 80 or _BULLET.match(text) or text.endswith("."):
        return False
    if _kind(text) or _clean_heading(text) in OTHER_HEADINGS:
        return True
    return text.endswith(":") or (text.isupper() and len(text) > 3)


def _tidy(line: str) -> str:
    return " ".join(_BULLET.sub("", line).split())[:MAX_LINE_CHARS]


def _collect(lines: list[str], kind: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines) and len(out) < MAX_LINES:
        raw = lines[i].strip()
        rest = ""
        found = False
        if raw and len(raw) <= 400:
            m = re.match(r"^(.{3,80}?)\s*:\s*(.+)$", raw)
            if m and _kind(m.group(1) + ":") == kind:
                found, rest = True, m.group(2)
            elif _is_heading(raw) and _kind(raw) == kind:
                found = True
        if not found:
            i += 1
            continue
        if rest and _tidy(rest):
            out.append(_tidy(rest))
        i += 1
        last_was_bullet = False
        gap = False
        got = bool(rest and _tidy(rest))
        while i < len(lines) and len(out) < MAX_LINES:
            nxt = lines[i].strip()
            if not nxt:
                # experience values are short: a blank line after the first value ends the section
                gap = gap or bool(last_was_bullet) or (kind == "exp" and got)
                i += 1
                continue
            if _is_heading(nxt):
                break
            is_bullet = bool(_BULLET.match(nxt))
            if gap and not is_bullet:
                break                      # a bullet list ended; the paragraph after it is not part of it
            gap = False
            last_was_bullet = is_bullet
            got = True
            if kind == "exp" and len(nxt) > 200:
                break                      # a paragraph, not an experience value
            out.append(_tidy(nxt))
            i += 1
    return [x for x in out if x]


def _summary(text: str) -> Optional[str]:
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(block.split())
        if len(block) < 40 or _is_heading(block) or _clean_heading(block) in OTHER_HEADINGS:
            continue
        if len(block) <= 420:
            return block
        cut = block[:420]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        return (cut[:end + 1] if end > 120 else cut.rsplit(" ", 1)[0] + "...")
    return None


def _years_line(line: str) -> bool:
    """A line that states a number or range of years as a requirement (not company history, not an education list)."""
    if not _YEARS.search(line):
        return False
    has_exp = bool(re.search(r"experience|\bexp\b", line, re.I))
    cue = bool(_REQ_CUE.search(line))
    if _HISTORY.search(line) and not (cue or has_exp):
        return False
    if _EDU_WORDS.search(line) and not has_exp:
        return False
    if has_exp or cue:
        return True
    # a short stand-alone line that starts with the years: "0-2 years", "8+ years in credit operations"
    return len(line) <= 160 and bool(re.match(rf"^{_NUM}\s*(?:\+|[-–—]|to\b)", line, re.I)) or bool(re.match(rf"^{_NUM}\s*(?:years?|yrs?)\b", line, re.I))


def _experience(text: str, lines: list[str]) -> list[str]:
    found: list[str] = []

    def add(line: str) -> None:
        line = _tidy(line)
        if line and line.lower() not in (x.lower() for x in found) and len(found) < 6:
            found.append(line)

    for line in _collect(lines, "exp")[:4]:          # "Experience:" heading, then its value / bullets
        add(line)
    for raw in re.split(r"\n+|(?<=[.;])\s+", text):
        if _years_line(_tidy(raw)):
            add(raw)
    return found


def extract_designation(description: Optional[str]) -> Optional[str]:
    """The designation exactly as the posting labels it ("Designation: ...", "Role/Job Title: ..."), else None."""
    lines = (clean_description(description) or "").split("\n")
    for i, raw in enumerate(lines):
        m = _TITLE_LABEL.match(raw)
        if not m:
            continue
        value = m.group(1).strip()
        if not value:      # value on the next non-empty line
            for nxt in lines[i + 1:i + 4]:
                if nxt.strip():
                    value = nxt.strip()
                    break
        value = " ".join(_BULLET.sub("", value).split()).rstrip(".;,")
        if value and len(value) <= 100 and not value.endswith(":") and not _is_heading(value):
            return value
    return None


def extract_sections(description: Optional[str]) -> DescriptionSections:
    if not description or not str(description).strip():
        return DescriptionSections()
    text = clean_description(description) or ""
    if not text:
        return DescriptionSections()
    lines = text.split("\n")
    return DescriptionSections(
        summary=_summary(text),
        responsibilities=_collect(lines, "resp"),
        qualifications=_collect(lines, "qual"),
        experience=_experience(text, lines),
        designation=extract_designation(text),
    )
