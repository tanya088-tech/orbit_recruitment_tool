"""Industry category from the job source's own industry label (deterministic, no AI).

LinkedIn's public job page carries an "Industries" label such as "Financial Services" or
"IT Services and IT Consulting". We map that label to a small set of recruiter-friendly
categories with ordered keyword rules (first match wins).

  * label missing                       -> "Unknown"   (not enough data; nothing is guessed)
  * label present but matches no rule   -> "Other"     (the original label is still shown on the details page)

Only the industry label is used. The job title, company name and description are NOT used,
because a keyword in a title ("Bank Teller" at a software firm) says little about the employer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

UNKNOWN, OTHER = "Unknown", "Other"

# Order matters: more specific rules come before broader ones
# (e.g. "Pharmaceutical Manufacturing" must be Healthcare before "Manufacturing").
INDUSTRY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("IT & Software", ("it services", "information technology", "software", "technology information", "internet",
                       "computer", "data infrastructure", "cyber", "network security", "information services",
                       "it system", "semiconductor")),
    ("Healthcare & Pharma", ("hospital", "health care", "healthcare", "pharma", "biotech", "medical", "wellness and fitness",
                             "mental health", "veterinary", "life sciences")),
    ("Banking & Finance", ("bank", "financial", "insurance", "investment", "capital markets", "venture capital",
                           "private equity", "asset management", "wealth", "fintech", "mortgage", "credit", "payments",
                           "securities", "fund")),
    ("Consulting & Professional Services", ("consulting", "accounting", "legal", "law practice", "professional services",
                                            "outsourcing", "business services", "market research", "research services",
                                            "architecture and planning", "design services")),
    ("Staffing & Recruiting", ("staffing", "recruiting", "executive search", "human resources")),
    ("Retail & E-commerce", ("retail", "e commerce", "ecommerce", "wholesale", "consumer goods", "consumer services",
                             "apparel", "fashion", "food and beverage", "supermarket", "luxury goods")),
    ("Manufacturing & Industrial", ("manufacturing", "automotive", "motor vehicle", "machinery", "industrial", "chemical",
                                   "electrical", "aviation and aerospace", "aerospace", "defense", "mining", "metal",
                                   "steel", "textile", "packaging", "plastics", "paper")),
    ("Energy & Utilities", ("oil and gas", "oil energy", "utilities", "renewable", "energy", "power generation", "electric power")),
    ("Telecommunications", ("telecommunication", "wireless", "telecom")),
    ("Education", ("education", "e learning", "university", "school", "training")),
    ("Media & Entertainment", ("media", "entertainment", "publishing", "broadcast", "advertising", "marketing", "gaming",
                               "animation", "film", "music")),
    ("Real Estate & Construction", ("real estate", "construction", "civil engineering", "building", "facilities services")),
    ("Transport & Logistics", ("transportation", "logistics", "supply chain", "airlines", "shipping", "freight", "warehousing",
                               "maritime", "railroad", "trucking", "delivery")),
    ("Travel & Hospitality", ("hospitality", "hotel", "travel", "restaurants", "leisure", "tourism")),
    ("Government & Non-profit", ("government", "non profit", "nonprofit", "public policy", "civic", "public safety",
                                 "international affairs", "military")),
]
CATEGORIES = [name for name, _ in INDUSTRY_RULES] + [OTHER, UNKNOWN]


@dataclass(frozen=True)
class IndustryResult:
    category: str
    label: Optional[str]          # the source's own wording, kept for display


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def classify_industry(label: Any) -> IndustryResult:
    clean = " ".join(str(label).split()) if label not in (None, "") else ""
    if not clean:
        return IndustryResult(UNKNOWN, None)
    text = f" {_norm(clean)} "
    for category, terms in INDUSTRY_RULES:
        for term in terms:
            if re.search(rf"\b{re.escape(term)}", text):
                return IndustryResult(category, clean)
    return IndustryResult(OTHER, clean)
