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
    ("Pharmaceuticals & Life Sciences", ("pharma", "biotech", "life sciences", "medical device", "medical equipment", "biopharma",
                                         "clinical research", "drug")),
    ("Hospitality, Travel & Tourism", ("hospitality", "hotel", "travel", "restaurants", "leisure", "tourism")),
    ("Healthcare & Hospitals", ("hospital", "health care", "healthcare", "medical", "wellness and fitness", "wellness",
                                "mental health", "veterinary", "diagnostic", "nursing")),
    ("Automotive & Auto Components", ("automotive", "motor vehicle", "auto component", "automobile", "vehicle", "two wheeler", "tyre", "tire")),
    ("Oil, Gas & Energy", ("oil and gas", "oil energy", "petroleum", "utilities", "renewable", "energy", "power generation",
                           "electric power", "solar")),
    ("IT & Software Services", ("it services", "information technology", "software", "technology information", "internet",
                                "computer", "data infrastructure", "cyber", "network security", "information services",
                                "it system", "semiconductor")),
    ("Banking, Financial Services & Insurance (BFSI)", ("bank", "financial", "insurance", "investment", "capital markets",
                                                         "venture capital", "private equity", "asset management", "wealth",
                                                         "fintech", "mortgage", "credit", "payments", "securities", "fund")),
    ("Professional Services & Consulting", ("consulting", "accounting", "legal", "law practice", "professional services",
                                            "outsourcing", "business services", "market research", "research services",
                                            "architecture and planning", "design services", "bpm", "bpo")),
    ("FMCG & Consumer Goods", ("consumer goods", "fmcg", "food and beverage", "food production", "beverage", "personal care",
                               "cosmetics", "household", "packaged", "tobacco")),
    ("Retail & E-commerce", ("retail", "e commerce", "ecommerce", "wholesale", "consumer services", "apparel", "fashion",
                             "supermarket", "luxury goods")),
    ("Infrastructure, Construction & Real Estate", ("real estate", "construction", "civil engineering", "infrastructure", "building",
                                                    "facilities services")),
    ("Logistics, Supply Chain & Transportation", ("transportation", "logistics", "supply chain", "airlines", "shipping", "freight",
                                                  "warehousing", "maritime", "railroad", "trucking", "delivery", "courier")),
    ("Education & EdTech", ("education", "edtech", "e learning", "university", "school", "training")),
    ("Manufacturing & Industrial Engineering", ("manufacturing", "machinery", "industrial", "chemical", "electrical",
                                                "aviation and aerospace", "aerospace", "defense", "mining", "metal", "steel",
                                                "textile", "packaging", "plastics", "paper", "engineering")),
]
# The industries the client works with, in the order the Industry Type filter lists them. A label that fits none is "Other".
CLIENT_INDUSTRIES = [
    "IT & Software Services", "Banking, Financial Services & Insurance (BFSI)", "Manufacturing & Industrial Engineering",
    "Healthcare & Hospitals", "Pharmaceuticals & Life Sciences", "FMCG & Consumer Goods", "Retail & E-commerce",
    "Infrastructure, Construction & Real Estate", "Logistics, Supply Chain & Transportation", "Automotive & Auto Components",
    "Oil, Gas & Energy", "Professional Services & Consulting", "Education & EdTech", "Hospitality, Travel & Tourism",
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
    exact = next((c for c in CLIENT_INDUSTRIES if c.lower() == clean.lower()), None)
    if exact:                                               # an industry already given in the client's own wording
        return IndustryResult(exact, clean)
    text = f" {_norm(clean)} "
    for category, terms in INDUSTRY_RULES:
        for term in terms:
            if re.search(rf"\b{re.escape(term)}", text):
                return IndustryResult(category, clean)
    return IndustryResult(OTHER, clean)
