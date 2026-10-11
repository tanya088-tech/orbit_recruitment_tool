"""Phase 2 pipeline:  Phase 1 jobs  ->  normalize  ->  4 filters  ->  filtered jobs + summary.

Every job is evaluated against ALL four filters (no early exit) so the summary can list
every reason a job was excluded. A job is kept only if all four pass.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from processing.classifier import classify
from processing.employment import map_employment_type
from processing.location import check_location
from processing.posted import evaluate_posting
from processing.work_mode import classify_work_mode, source_work_mode_texts

log = logging.getLogger(__name__)

# Order matters only for the cumulative "funnel" in the summary.
FILTER_ORDER = ["gcc_bfsi", "employment_type", "india_location", "posted_24h"]
FILTER_LABELS = {
    "gcc_bfsi": "Potential GCC or BFSI",
    "employment_type": "Employment type (Permanent/Contract)",
    "india_location": "India location",
    "posted_24h": "Posted within last 24 hours",
}


@dataclass
class EvaluatedJob:
    record: dict[str, Any]
    outcomes: dict[str, dict[str, Any]]      # filter -> {passed, code, reason}

    @property
    def passed_all(self) -> bool:
        return all(o["passed"] for o in self.outcomes.values())


@dataclass
class FilterRun:
    final_jobs: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def evaluate_job(job: dict[str, Any], as_of: datetime, include_ambiguous_date: bool = False) -> EvaluatedJob:
    cls = classify(job.get("company"), job.get("title"), job.get("description"), job.get("industries"))
    emp = map_employment_type(job.get("employment_type"))
    loc = check_location(job.get("location"))
    posted = evaluate_posting(job, as_of=as_of, include_ambiguous_date=include_ambiguous_date)
    work_mode = classify_work_mode(*source_work_mode_texts(job))

    gcc_bfsi_ok = cls.potential_gcc or cls.potential_bfsi
    outcomes = {
        "gcc_bfsi": {
            "passed": gcc_bfsi_ok,
            "code": "ok" if gcc_bfsi_ok else "not_gcc_or_bfsi",
            "reason": cls.reason if gcc_bfsi_ok else "no potential GCC or BFSI signals found",
        },
        "employment_type": {"passed": emp.passed, "code": emp.code, "reason": emp.reason},
        "india_location": {"passed": loc.is_india, "code": loc.code, "reason": loc.reason},
        "posted_24h": {"passed": posted.passed, "code": posted.code, "reason": posted.reason},
    }

    record = {
        "source": job.get("source") or "LinkedIn",
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "company_url": job.get("company_url"),
        "description": job.get("description"),
        "location": job.get("location"),
        "country": loc.country,
        "is_remote": loc.is_remote,
        "work_mode": work_mode.mode,                  # On-site | Hybrid | Remote | Unknown (explicit wording only)
        "potential_gcc": cls.potential_gcc,
        "potential_bfsi": cls.potential_bfsi,
        "classification_reason": cls.reason,
        "classification_signals": cls.signals_as_dicts(),
        "employment_type": emp.normalized,
        "employment_type_raw": job.get("employment_type"),
        "job_url": job.get("job_url"),
        "posted_at": posted.posted_at,
        "posted_at_precision": posted.precision,
        "posted_within_24h_certainty": posted.certainty,
        "posted_age_text": posted.age_text,
        "first_seen_at": job.get("collected_at"),   # no database yet: first seen == this collection
        "industries": job.get("industries"),
        "seniority_level": job.get("seniority_level"),
        "job_function": job.get("job_function"),
        # Detail-page fields. None unless the source actually provided them - never guessed.
        "designation": job.get("designation"),
        "job_role": job.get("job_role") or job.get("job_function"),
        "experience_requirements": (job.get("raw") or {}).get("experience_requirements"),   # JSON-LD only; None when the page has none
        "education_requirements": (job.get("raw") or {}).get("education_requirements"),
        "recruiter_name": job.get("recruiter_name"),
        "recruiter_email": job.get("recruiter_email"),
        "recruiter_phone": job.get("recruiter_phone"),
        "contact_url": job.get("contact_url"),
        "filter_results": outcomes,
        "raw_data": job.get("raw"),
    }
    return EvaluatedJob(record, outcomes)


def run_filters(
    jobs: list[dict[str, Any]],
    as_of: Optional[datetime] = None,
    include_ambiguous_date: bool = False,
) -> FilterRun:
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evaluated: list[EvaluatedJob] = []
    for job in jobs:
        try:
            evaluated.append(evaluate_job(job, as_of, include_ambiguous_date))
        except Exception as exc:        # one malformed job must not stop the run
            log.error("Could not evaluate job %s: %s", job.get("job_url") or job.get("job_id"), exc)
            evaluated.append(EvaluatedJob(
                {"job_id": job.get("job_id"), "title": job.get("title"), "company": job.get("company"),
                 "job_url": job.get("job_url")},
                {"processing": {"passed": False, "code": "processing_error", "reason": f"{type(exc).__name__}: {exc}"}},
            ))

    run = FilterRun()
    passed_each = {name: 0 for name in FILTER_ORDER}
    funnel, remaining = [], list(evaluated)
    reason_counts: Counter = Counter()
    failed_filter_counts: Counter = Counter()

    for ev in evaluated:
        for name in FILTER_ORDER:
            if ev.outcomes.get(name, {}).get("passed"):
                passed_each[name] += 1

    for name in FILTER_ORDER:
        remaining = [e for e in remaining if e.outcomes.get(name, {}).get("passed")]
        funnel.append({"filter": name, "label": FILTER_LABELS[name], "remaining": len(remaining)})

    for ev in evaluated:
        if ev.passed_all:
            run.final_jobs.append(ev.record)
            continue
        failed = {n: o for n, o in ev.outcomes.items() if not o["passed"]}
        for name, o in failed.items():
            reason_counts[o["code"]] += 1
            failed_filter_counts[name] += 1
        r = ev.record
        run.excluded.append({
            "job_id": r.get("job_id"), "title": r.get("title"), "company": r.get("company"),
            "job_url": r.get("job_url"), "location": r.get("location"),
            "employment_type_raw": r.get("employment_type_raw"), "posted_age_text": r.get("posted_age_text"),
            "failed_filters": list(failed),
            "reason_codes": [o["code"] for o in failed.values()],
            "reasons": [f"{FILTER_LABELS.get(n, n)}: {o['reason']}" for n, o in failed.items()],
        })

    run.summary = {
        "as_of": as_of.isoformat(timespec="seconds"),
        "include_ambiguous_date": include_ambiguous_date,
        "total_jobs_collected": len(evaluated),
        "passed_each_filter_independently": {
            "gcc_bfsi": passed_each["gcc_bfsi"],
            "employment_type": passed_each["employment_type"],
            "india_location": passed_each["india_location"],
            "posted_24h": passed_each["posted_24h"],
        },
        "cumulative_funnel": funnel,
        "final_jobs": len(run.final_jobs),
        "excluded_jobs": len(run.excluded),
        "excluded_by_filter": dict(failed_filter_counts),
        "excluded_by_reason": dict(reason_counts),
        "notes": [
            "GCC/BFSI is a keyword-based POTENTIAL classification, not a confirmation.",
            "LinkedIn public pages give a calendar date and a relative age, not an exact posting time; "
            "see posted_at_precision / posted_within_24h_certainty on each job.",
            "first_seen_at is the Phase 1 collected_at (no database yet).",
        ],
    }
    return run


# ----------------------------------------------------------------------------- normalize ALL jobs
@dataclass
class NormalizedRun:
    """Every successfully evaluated job, with NO filter applied. The dashboard filters these."""
    jobs: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)      # jobs that could not be processed
    summary: dict[str, Any] = field(default_factory=dict)


def normalize_all(jobs: list[dict[str, Any]], as_of: Optional[datetime] = None) -> NormalizedRun:
    """Run the same Phase 2 normalization/classification on every job and keep them all.

    Uses evaluate_job() unchanged. The only difference from run_filters() is that jobs which
    fail a filter are kept (their filter_results still say what failed) instead of dropped.
    """
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run = NormalizedRun()
    for job in jobs:
        try:
            run.jobs.append(evaluate_job(job, as_of).record)
        except Exception as exc:        # one malformed job must not stop the run
            log.error("Could not normalize job %s: %s", job.get("job_url") or job.get("job_id"), exc)
            run.failed.append({"job_id": job.get("job_id"), "title": job.get("title"),
                               "job_url": job.get("job_url"), "error": f"{type(exc).__name__}: {exc}"})
    india = sum(1 for r in run.jobs if r.get("country") == "India")
    run.summary = {
        "as_of": as_of.isoformat(timespec="seconds"),
        "total_jobs_collected": len(jobs),
        "normalized_jobs": len(run.jobs),
        "failed_to_process": len(run.failed),
        "in_india": india,
        "outside_india_or_unknown_location": len(run.jobs) - india,
        "potential_gcc": sum(1 for r in run.jobs if r.get("potential_gcc")),
        "potential_bfsi": sum(1 for r in run.jobs if r.get("potential_bfsi")),
        "permanent": sum(1 for r in run.jobs if r.get("employment_type") == "Permanent"),
        "contract": sum(1 for r in run.jobs if r.get("employment_type") == "Contract"),
        "notes": [
            "No job was removed. Filtering (location, posted date, GCC/BFSI, job type) happens in the dashboard.",
            "GCC/BFSI is a keyword-based POTENTIAL classification, not a confirmation.",
            "first_seen_at is the Phase 1 collected_at; the history store records when Orbit first found each job.",
        ],
    }
    return run


def save_normalized(run: NormalizedRun, output_dir: Path, source: str, input_file: Optional[Path] = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"normalized_jobs_{source}_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {"input_file": str(input_file) if input_file else None, "summary": run.summary,
               "jobs": run.jobs, "failed": run.failed}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def summary_lines(run: FilterRun) -> list[str]:
    s = run.summary
    lines = ["=" * 64, "FILTERING SUMMARY", f"  Filter run time (UTC)   : {s['as_of']}",
             f"  Total jobs collected    : {s['total_jobs_collected']}", "  Passed each filter on its own:"]
    for name in FILTER_ORDER:
        lines.append(f"    - {FILTER_LABELS[name]:<40}: {s['passed_each_filter_independently'][name]}")
    lines.append("  Cumulative funnel (in order):")
    for step in s["cumulative_funnel"]:
        lines.append(f"    -> after {step['label']:<40}: {step['remaining']}")
    lines.append(f"  FINAL JOBS              : {s['final_jobs']}")
    lines.append(f"  Excluded                : {s['excluded_jobs']}")
    for code, n in sorted(s["excluded_by_reason"].items(), key=lambda kv: -kv[1]):
        lines.append(f"    - {code}: {n}")
    for e in run.excluded:
        lines.append(f"  x {e['company']} | {e['title']}")
        for reason in e["reasons"]:
            lines.append(f"      {reason}")
    lines.append("=" * 64)
    return lines


# ----------------------------------------------------------------------------- I/O
def load_jobs(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {}, data
    return data.get("run", {}), data.get("jobs", [])


def save_filtered(run: FilterRun, output_dir: Path, source: str, input_file: Optional[Path] = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"filtered_jobs_{source}_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {
        "input_file": str(input_file) if input_file else None,
        "summary": run.summary,
        "jobs": run.final_jobs,
        "excluded": run.excluded,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
