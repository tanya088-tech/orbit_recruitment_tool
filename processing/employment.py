"""Map LinkedIn employment types to the two we keep: Permanent and Contract."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from config import filter_rules as R


@dataclass
class EmploymentResult:
    normalized: Optional[str]    # "Permanent" | "Contract" | None
    passed: bool
    code: str                    # ok | employment_not_allowed | employment_unavailable
    reason: str


def map_employment_type(raw: Optional[str]) -> EmploymentResult:
    if raw is None or not str(raw).strip():
        # Never assume Permanent when LinkedIn gave us nothing.
        return EmploymentResult(None, False, "employment_unavailable",
                                "employment type unavailable (not assumed Permanent)")
    key = re.sub(r"[\s_\-/]+", " ", str(raw).strip().lower())
    if key in R.EMPLOYMENT_PERMANENT:
        return EmploymentResult("Permanent", True, "ok", f"'{raw}' -> Permanent")
    if key in R.EMPLOYMENT_CONTRACT or key.startswith("contract"):
        return EmploymentResult("Contract", True, "ok", f"'{raw}' -> Contract")
    if key in R.EMPLOYMENT_EXCLUDED:
        return EmploymentResult(None, False, "employment_not_allowed", f"employment type '{raw}' is not Permanent/Contract")
    return EmploymentResult(None, False, "employment_not_allowed", f"employment type '{raw}' not recognised as Permanent/Contract")
