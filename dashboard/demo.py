"""Synthetic vacancies for trying the dashboard. Stored in data_demo/, never in data/.

Everything here is made up (company names start with "Demo", job IDs start with 9000).
Three simulated scraper runs show how New / already-existing works:
  run 1 (2 days ago), run 2 (5 hours ago, re-finds one old job), run 3 (25 minutes ago, re-finds three).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from processing.work_mode import classify_work_mode
from store.json_store import JsonJobHistory, JsonRecruiterState

DEMO_BANNER = "Demo data. These vacancies are made up so you can try the dashboard. Nothing here is a real job."
_TEXT = ("This is a made-up vacancy created to preview the Ace Talent Consulting dashboard.\n\n"
         "It exists only so you can try filters, sorting, saving, statuses and notes.")


def _job(n: int, title: Optional[str], company: str, location: Optional[str], emp: Optional[str],
         gcc: bool, bfsi: bool, posted: Any, now: datetime, industries: str = "Financial Services", **over) -> dict[str, Any]:
    job_id = str(9000000000 + n)
    if isinstance(posted, timedelta):
        posted_at, precision = (now - posted).isoformat(timespec="seconds"), "estimated_from_relative_minutes"
    elif isinstance(posted, tuple) and posted[0] == "days_ago":      # LinkedIn gave only a calendar date
        posted_at, precision = (now - timedelta(days=posted[1])).date().isoformat(), "date_only"
    elif posted == "today":
        posted_at, precision = now.date().isoformat(), "date_only"
    else:
        posted_at, precision = None, "unknown"
    signals = []
    if bfsi:
        signals.append({"category": "bfsi", "field": "industries", "term": industries, "strength": "strong", "matched": "financial"})
    if gcc:
        signals.append({"category": "gcc", "field": "company", "term": "global services", "strength": "weak"})
    reason = (f"Potential BFSI: LinkedIn industry '{industries}'. " if bfsi else "Potential BFSI: no BFSI signals found. ") + \
             ("Potential GCC: company name 'global services'. " if gcc else "Potential GCC: no GCC signals found. ") + \
             "Keyword-based indication only - not a confirmed GCC/BFSI classification."
    rec = {
        "source": "LinkedIn", "job_id": job_id, "title": title, "company": company, "company_url": f"https://www.linkedin.com/company/demo-{n}",
        "description": _TEXT, "location": location, "country": "India" if location else None, "potential_gcc": gcc,
        "potential_bfsi": bfsi, "classification_reason": reason, "classification_signals": signals, "employment_type": emp,
        "employment_type_raw": {"Permanent": "Full-time", "Contract": "Contract"}.get(emp or ""), "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
        "work_mode": classify_work_mode(location).mode,
        "posted_at": posted_at, "posted_at_precision": precision, "first_seen_at": now.isoformat(timespec="seconds"),
        "industries": industries, "raw_data": {},
    }
    rec.update(over)
    return rec


def build_demo(data_dir: Any, now: Optional[datetime] = None) -> None:
    now = now or datetime.now(timezone.utc)
    h = lambda **kw: timedelta(**kw)
    t = lambda n, *a, **kw: _job(n, *a, now=now, **kw)

    # --- run 1: two days ago
    old = [
        t(1, "Credit Risk Analyst", "Demo Bank India", "Mumbai, Maharashtra, India", "Permanent", False, True, h(hours=52)),
        t(2, "Treasury Operations Associate", "Demo Capital Markets", "Bengaluru, Karnataka, India", "Permanent", True, True, h(hours=58)),
        t(3, "Insurance Claims Analyst", "Demo Insurance Group", "Pune, Maharashtra, India", "Contract", False, True, h(hours=70), industries="Insurance"),
        t(4, "Regulatory Reporting Analyst", "Demo Bank India", "Chennai, Tamil Nadu, India", "Permanent", False, True, h(hours=120)),
        t(5, "Shared Services Finance Associate", "Demo Global Services Centre", "Hyderabad, Telangana, India", "Contract", True, False, h(hours=140), industries="Business Consulting and Services"),
    ]
    # --- run 2: five hours ago (also re-finds job 3)
    mid = [
        old[2],
        t(6, "Wealth Management Associate", "Demo Asset Management", "Mumbai, Maharashtra, India", "Permanent", False, True, h(hours=14)),
        t(7, "Underwriting Specialist", "Demo Insurance Group", "Gurugram, Haryana, India", "Permanent", False, True, h(hours=13), industries="Insurance"),
        t(8, "Technology Lead, Global Capability Centre", "Demo Global Services Centre", "Bengaluru, Karnataka, India", "Permanent", True, False, h(hours=11), industries="IT Services and IT Consulting"),
        t(9, "KYC Operations Analyst", "Demo Bank India", "Hyderabad, Telangana, India", "Contract", True, True, h(hours=9)),
        t(10, "Fixed Income Operations Analyst", "Demo Capital Markets", "Pune, Maharashtra, India", "Permanent", False, True, h(hours=8)),
    ]
    # --- run 3: 25 minutes ago (re-finds 3 earlier jobs, adds 5 new, one with missing data)
    new = [
        mid[1], mid[4], mid[5],
        t(11, "Payments Product Analyst", "Demo Payments Ltd", "Remote - India", "Permanent", False, True, h(minutes=8)),
        t(12, "AML Investigator", "Demo Bank India", "Bengaluru, Karnataka, India", "Permanent", True, True, h(minutes=24)),
        t(13, "Data Analyst, Retail Banking", "Demo Bank India", "Chennai, Tamil Nadu, India", "Contract", False, True, h(hours=1, minutes=10)),
        t(14, "Cards Risk Analyst", "Demo Payments Ltd", "Mumbai, Maharashtra, India", "Permanent", False, True, h(hours=3)),
        t(15, None, "Demo Asset Management", None, None, False, True, None, description=None, company_url=None, job_url=None,
          classification_reason=None, classification_signals=[]),    # deliberately incomplete
    ]
    # --- older jobs and jobs outside the original filters: these are in the dashboard too
    new += [
        t(16, "Compliance Officer", "Demo Bank India", "Bengaluru, India", "Permanent", False, True, ("days_ago", 10)),
        t(17, "Marketing Manager", "Demo Retail Co", "Mumbai, Maharashtra, India", "Permanent", False, False, ("days_ago", 20), industries="Retail"),
        t(18, "Backend Engineer", "Demo Payments Ltd", "Remote, India", "Contract", False, True, ("days_ago", 3)),
        t(19, "Treasury Analyst", "Demo Capital Markets", "Kolkata, West Bengal, India", "Permanent", False, True, ("days_ago", 40)),
        t(20, "Credit Analyst", "Demo Bank UK", "London, England, United Kingdom", "Permanent", False, True, h(hours=2),
          country="United Kingdom"),                                    # outside India: kept in history, not listed
    ]
    # --- work modes and contact details (the contact details are made up, like everything in demo mode)
    new += [
        t(21, "Risk Analytics Manager", "Demo Bank India", "Pune, Maharashtra, India (Hybrid)", "Permanent", False, True, h(hours=6)),
        t(22, "Operations Lead", "Demo Global Services Centre", "Hyderabad, Telangana, India (On-site)", "Contract", True, False, ("days_ago", 2),
          industries="Business Consulting and Services"),
        t(23, "Fund Accounting Associate", "Demo Asset Management", "Mumbai, Maharashtra, India (Hybrid)", "Contract", False, True, ("days_ago", 5),
          designation="Associate", job_role="Finance", recruiter_name="Demo Recruiter", recruiter_email="demo.recruiter@example.com",
          recruiter_phone="+00 000 000 0000", contact_url="https://example.com/demo-contact"),
    ]
    # --- other industries, outside India, and a description with headings (so the details page can show sections)
    structured = ("Demo Software builds made-up products for a made-up market.\n\n"
                  "Responsibilities:\n- Design and build backend services\n- Review code written by teammates\n\n"
                  "Requirements:\n- Experience with Python and SQL\n- Clear written English\n\n"
                  "You will have 5+ years of experience in software engineering.")
    new += [
        t(24, "Senior Software Engineer", "Demo Software Pvt Ltd", "Bangalore, Karnataka, India", "Permanent", False, False, h(hours=4),
          industries="Software Development", description=structured),
        t(25, "Clinical Data Manager", "Demo Health Sciences", "Ahmedabad, Gujarat, India", "Permanent", False, False, h(hours=30),
          industries="Hospitals and Health Care"),
        t(26, "Plant Maintenance Engineer", "Demo Manufacturing Works", "Chennai, Tamil Nadu, India", "Contract", False, False, ("days_ago", 12),
          industries="Machinery Manufacturing"),
        t(27, "Relationship Manager", "Demo Gulf Bank", "Dubai, United Arab Emirates", "Permanent", False, True, h(hours=20),
          country="United Arab Emirates"),
        t(28, "Platform Engineer", "Demo Software Pvt Ltd", "Singapore", "Contract", False, False, ("days_ago", 6),
          industries="Software Development", country="Singapore", description=structured),
        t(29, "Store Operations Lead", "Demo Retail Co", "Jaipur, Rajasthan, India", "Permanent", False, False, h(hours=70),
          industries="Retail"),
        t(30, "Product Analyst", "Demo Retail Co", None, "Permanent", False, False, h(hours=9), industries=None,
          country=None),                                                # no location and no industry: shown as Unknown
    ]
    data_dir = Path(data_dir)
    history = JsonJobHistory(data_dir / "job_history.json")
    history.ingest(old, source_file="demo_run_1", now=now - timedelta(days=2))
    history.ingest(mid, source_file="demo_run_2", now=now - timedelta(hours=5))
    history.ingest(new, source_file="demo_run_3", now=now - timedelta(minutes=25))

    state = JsonRecruiterState(data_dir / "recruiter_state.json")
    state.set_saved("linkedin-9000000009", True)
    state.set_saved("linkedin-9000000002", True)
    state.set_status("linkedin-9000000009", "Candidate Search Started")
    state.set_status("linkedin-9000000002", "Reviewing")
    state.set_status("linkedin-9000000004", "Not Relevant")
    state.add_note("linkedin-9000000009", "Demo note: asked the hiring team to confirm the target start date.")
