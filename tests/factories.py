"""Shared builders for Phase 3 tests (Phase 2-shaped job records)."""
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
DEFAULT = object()


def ago(**delta) -> str:
    return (NOW - timedelta(**delta)).isoformat(timespec="seconds")


def make_record(job_id, title="Credit Risk Analyst", company="Acme Bank", location="Pune, Maharashtra, India",
                employment="Permanent", gcc=False, bfsi=True, posted=DEFAULT, precision="estimated_from_relative_minutes",
                **over):
    rec = {
        "source": "LinkedIn", "job_id": str(job_id), "title": title, "company": company,
        "company_url": "https://www.linkedin.com/company/acme", "description": f"Description of {title}.",
        "location": location, "country": "India" if location else None, "potential_gcc": gcc, "potential_bfsi": bfsi,
        "classification_reason": "Potential BFSI: LinkedIn industry 'Financial Services'. Potential GCC: no GCC signals found. "
                                 "Keyword-based indication only - not a confirmed GCC/BFSI classification.",
        "classification_signals": [{"category": "bfsi", "field": "industries", "term": "Financial Services", "strength": "strong"}],
        "employment_type": employment, "employment_type_raw": "Full-time",
        "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
        "posted_at": ago(minutes=30) if posted is DEFAULT else posted, "posted_at_precision": precision,
        "first_seen_at": ago(minutes=5), "industries": "Financial Services", "raw_data": {"k": "v"},
    }
    rec.update(over)
    return rec


def entry(job_id, run="run_1", **kw):
    """A stored history entry (what JobHistoryStore.list_jobs() returns)."""
    rec = make_record(job_id, **kw)
    return {"key": f"linkedin-{job_id}", "first_seen_run_id": run, "first_ingested_at": ago(hours=1),
            "last_seen_run_id": run, "last_seen_at": ago(hours=1), "times_seen": 1, "record": rec}


def standard_records():
    """Six jobs used by the server tests. Expected newest-first order: A, B, E, C, D, F."""
    return {
        "A": make_record(1001, "Credit Risk Analyst", "Acme Bank", "Pune, Maharashtra, India", "Permanent", False, True,
                         posted=ago(minutes=20), description="Line 1 of the description.\nLine 2 about <b>risk</b> models."),
        "B": make_record(1002, "Technology Lead GCC", "Globex Global Services", "Bengaluru, Karnataka, India", "Permanent", True, False,
                         posted=ago(hours=5)),
        "C": make_record(1003, "KYC Analyst", "Acme Bank", "Hyderabad, Telangana, India", "Contract", True, True, posted=ago(hours=30)),
        "D": make_record(1004, "Insurance Underwriter", "Shield Insurance", "Mumbai, Maharashtra, India", "Contract", False, True,
                         posted=ago(days=4)),
        "E": make_record(1005, "Payments Associate", "Payco", "Remote - India", "Permanent", False, True,
                         posted="2026-10-08", precision="date_only"),
        "F": make_record(1006, "Treasury Analyst", "Acme Bank", "Pune, Maharashtra, India", "Permanent", False, True,
                         posted=None, precision="unknown"),
    }
