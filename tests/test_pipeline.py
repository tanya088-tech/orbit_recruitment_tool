import json
from datetime import datetime, timezone
from pathlib import Path

from processing.pipeline import FILTER_ORDER, load_jobs, run_filters, save_filtered, summary_lines

AS_OF = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
FIX = Path(__file__).parent / "fixtures"


def make(**kw):
    base = {
        "source": "LinkedIn", "job_id": "1", "title": "Credit Risk Analyst", "company": "Acme Bank",
        "location": "Pune, Maharashtra, India", "job_url": "https://www.linkedin.com/jobs/view/1",
        "description": "desc", "employment_type": "Full-time", "industries": "Banking",
        "posted_age_text": "2 hours ago", "collected_at": "2026-10-08T09:50:00+00:00", "raw": {"k": "v"},
    }
    base.update(kw)
    return base


def test_good_job_passes_with_required_output_fields():
    run = run_filters([make()], AS_OF)
    assert run.summary["final_jobs"] == 1
    j = run.final_jobs[0]
    for key in ["title", "company", "description", "location", "country", "potential_gcc", "potential_bfsi",
                "classification_reason", "employment_type", "source", "job_url", "posted_at",
                "first_seen_at", "raw_data"]:
        assert key in j, key
    assert j["country"] == "India" and j["employment_type"] == "Permanent" and j["potential_bfsi"] is True
    assert j["first_seen_at"] == "2026-10-08T09:50:00+00:00"
    assert j["raw_data"] == {"k": "v"}


def test_each_filter_excludes_with_its_reason():
    jobs = [
        make(job_id="ok"),
        make(job_id="notfin", company="Sunrise Pharma", title="Chemist", industries="Pharma"),
        make(job_id="parttime", employment_type="Part-time"),
        make(job_id="noemp", employment_type=None),
        make(job_id="abroad", location="London, United Kingdom"),
        make(job_id="old", posted_age_text="3 days ago"),
    ]
    run = run_filters(jobs, AS_OF)
    s = run.summary
    assert s["total_jobs_collected"] == 6 and s["final_jobs"] == 1 and s["excluded_jobs"] == 5
    assert s["passed_each_filter_independently"] == {
        "gcc_bfsi": 5, "employment_type": 4, "india_location": 5, "posted_24h": 5}
    assert [step["remaining"] for step in s["cumulative_funnel"]] == [5, 3, 2, 1]
    assert [step["filter"] for step in s["cumulative_funnel"]] == FILTER_ORDER
    codes = s["excluded_by_reason"]
    assert codes["not_gcc_or_bfsi"] == 1 and codes["employment_not_allowed"] == 1
    assert codes["employment_unavailable"] == 1 and codes["location_not_india"] == 1
    assert codes["posted_older_than_24h"] == 1
    assert {e["job_id"] for e in run.excluded} == {"notfin", "parttime", "noemp", "abroad", "old"}


def test_job_failing_several_filters_lists_all_reasons():
    run = run_filters([make(employment_type="Internship", location="Austin, Texas, United States")], AS_OF)
    e = run.excluded[0]
    assert set(e["failed_filters"]) == {"employment_type", "india_location"}
    assert len(e["reasons"]) == 2


def test_ambiguous_date_option():
    j = make(posted_age_text=None, posted_date="2026-10-07")
    assert run_filters([j], AS_OF).summary["final_jobs"] == 0
    run = run_filters([j], AS_OF, include_ambiguous_date=True)
    assert run.summary["final_jobs"] == 1
    assert run.final_jobs[0]["posted_within_24h_certainty"] == "uncertain"


def test_malformed_job_does_not_stop_the_run():
    bad = make(job_id="bad", description=["not", "a", "string"])
    run = run_filters([bad, make(job_id="ok")], AS_OF)
    assert run.summary["final_jobs"] == 1
    assert any(e["reason_codes"] == ["processing_error"] for e in run.excluded)


def test_save_and_summary_text(tmp_path):
    run = run_filters([make(), make(job_id="2", employment_type="Internship")], AS_OF)
    path = save_filtered(run, tmp_path, "linkedin")
    assert path.name.startswith("filtered_jobs_linkedin_") and path.suffix == ".json"
    data = json.loads(path.read_text())
    assert set(data) == {"input_file", "summary", "jobs", "excluded"}
    text = "\n".join(summary_lines(run))
    assert "FINAL JOBS" in text and "employment_not_allowed" in text


def test_real_phase1_output_regression():
    """Real LinkedIn run from 2026-10-08: JPMorgan job is 17 min old; both Goldman jobs are days old."""
    _, jobs = load_jobs(FIX / "phase1_real_sample.json")
    run = run_filters(jobs, AS_OF)
    assert run.summary["total_jobs_collected"] == 3
    assert [j["company"] for j in run.final_jobs] == ["JPMorganChase"]
    by_id = {e["job_id"]: e for e in run.excluded}
    assert set(by_id) == {"4474609165", "4443262848"}
    assert all(e["reason_codes"] == ["posted_older_than_24h"] for e in by_id.values())
    # the one-day bug: Phase 1 had saved 2026-10-06 / 2026-10-03; LinkedIn's own dates are 10-05 / 10-02
    full = {j["job_id"]: j for j in jobs}
    from processing.pipeline import evaluate_job
    assert evaluate_job(full["4474609165"], AS_OF).record["posted_at"] == "2026-10-05"
    assert evaluate_job(full["4443262848"], AS_OF).record["posted_at"] == "2026-10-02"


# ------------------------------------------------------------------ normalize ALL jobs (feeds the dashboard)
def test_normalize_all_keeps_every_job_and_reuses_phase2_fields(tmp_path):
    from datetime import datetime, timezone
    from processing.pipeline import normalize_all, run_filters, save_normalized
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    mk = lambda i, **kw: {"source": "LinkedIn", "job_id": str(i), "title": "Role", "company": "Acme", "location": "Pune, Maharashtra, India",
                          "employment_type": "Full-time", "industries": "Financial Services", "job_url": f"https://www.linkedin.com/jobs/view/{i}",
                          "posted_age_text": "5 hours ago", "collected_at": "2026-10-08T11:00:00+00:00", **kw}
    jobs = [mk(1), mk(2, posted_age_text="3 days ago"), mk(3, industries="Retail", title="Cashier", company="Shop"),
            mk(4, location="London, England, United Kingdom"), mk(5, employment_type="Internship"), mk(6, location="Remote, India")]
    norm = normalize_all(jobs, as_of=now)
    strict = run_filters(jobs, as_of=now)
    assert len(norm.jobs) == 6 and norm.failed == [] and len(strict.final_jobs) == 2       # strict filtering drops 4; normalizing drops none
    by = {r["job_id"]: r for r in norm.jobs}
    assert by["1"] == strict.final_jobs[0]                                                  # identical Phase 2 record for a passing job
    assert by["2"]["posted_at_precision"] != "unknown" and by["2"]["posted_at"]             # old job keeps its posting date
    assert by["3"]["potential_gcc"] is False and by["3"]["potential_bfsi"] is False         # not GCC/BFSI, still present
    assert by["4"]["country"] == "United Kingdom" and by["5"]["employment_type"] is None
    assert by["6"]["is_remote"] is True and by["1"]["is_remote"] is False
    assert norm.summary["normalized_jobs"] == 6 and norm.summary["in_india"] == 5 and norm.summary["outside_india_or_unknown_location"] == 1
    path = save_normalized(norm, tmp_path, "linkedin")
    assert path.name.startswith("normalized_jobs_linkedin_") and path.exists()


def test_normalize_all_survives_a_malformed_job():
    from processing.pipeline import normalize_all
    norm = normalize_all([{"job_id": "1", "title": "ok", "location": "Pune, India"}, {"job_id": "2", "description": 123, "title": ["x"]}])
    assert len(norm.jobs) + len(norm.failed) == 2 and len(norm.jobs) >= 1
