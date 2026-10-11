import json
from datetime import timedelta
from pathlib import Path

from tests.factories import NOW, make_record
from store.base import StoreError
from store.ingest import ingest_filtered_file, load_filtered_file
from store.json_store import JsonJobHistory

FIX = Path(__file__).parent / "fixtures"


def keys(history):
    return sorted(j["key"] for j in history.list_jobs())


def test_same_job_found_again_is_not_a_new_vacancy(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    a, b, c = make_record(1), make_record(2), make_record(3)

    r1 = h.ingest([a, b], now=NOW)
    assert (r1.new, r1.existing) == (2, 0)

    r2 = h.ingest([b, c], now=NOW + timedelta(hours=3))      # scraper ran again; B found again
    assert (r2.new, r2.existing) == (1, 1)
    assert r2.new_keys == ["linkedin-3"] and r2.existing_keys == ["linkedin-2"]

    assert keys(h) == ["linkedin-1", "linkedin-2", "linkedin-3"]          # no duplicate vacancy
    job_b = h.get_job("linkedin-2")
    assert job_b["times_seen"] == 2
    assert job_b["first_seen_run_id"] == r1.run_id and job_b["last_seen_run_id"] == r2.run_id
    assert h.get_job("linkedin-3")["first_seen_run_id"] == r2.run_id
    assert h.get_job("linkedin-1")["times_seen"] == 1


def test_three_runs_and_run_log(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    for day, ids in enumerate([[1, 2], [2, 3], [1, 3, 4]]):
        h.ingest([make_record(i) for i in ids], now=NOW + timedelta(days=day))
    assert len(keys(h)) == 4
    assert [(r["new"], r["existing"]) for r in h.runs()] == [(2, 0), (1, 1), (1, 2)]
    assert h.latest_run()["new_keys"] == ["linkedin-4"]
    assert h.get_job("linkedin-1")["times_seen"] == 2 and h.get_job("linkedin-3")["times_seen"] == 2


def test_duplicate_inside_one_file_counts_once(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    r = h.ingest([make_record(1), make_record(1), make_record(2)], now=NOW)
    assert (r.new, r.duplicates_in_file) == (2, 1) and len(keys(h)) == 2


def test_url_only_and_id_records_are_the_same_vacancy(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([make_record(4001111111)], now=NOW)
    no_id = make_record(4001111111, job_url="https://in.linkedin.com/jobs/view/some-title-4001111111?refId=x")
    no_id["job_id"] = None
    r = h.ingest([no_id], now=NOW + timedelta(hours=1))
    assert (r.new, r.existing) == (0, 1) and len(keys(h)) == 1


def test_unidentifiable_jobs_are_counted_not_fatal(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    r = h.ingest([make_record(1), {"source": "LinkedIn", "title": "No id or url"}], now=NOW)
    assert (r.new, r.unidentifiable) == (1, 1)


def test_first_record_is_kept_and_only_gaps_are_filled(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    first = make_record(1, posted="2026-10-08T09:33:46+00:00", precision="estimated_from_relative_minutes", description=None)
    later = make_record(1, posted="2026-10-08T10:26:56+00:00", precision="estimated_from_relative_hours", description="Now we have text")
    h.ingest([first], now=NOW)
    h.ingest([later], now=NOW + timedelta(hours=1))
    rec = h.get_job("linkedin-1")["record"]
    assert rec["posted_at"] == "2026-10-08T09:33:46+00:00"                    # not overwritten
    assert rec["posted_at_precision"] == "estimated_from_relative_minutes"
    assert rec["description"] == "Now we have text"                           # gap filled


def test_same_file_twice_is_skipped_and_does_not_add_a_run(tmp_path):
    f = tmp_path / "filtered.json"
    f.write_text(json.dumps({"jobs": [make_record(1), make_record(2)]}))
    h = JsonJobHistory(tmp_path / "h.json")
    first = ingest_filtered_file(f, h, now=NOW)
    second = ingest_filtered_file(f, h, now=NOW + timedelta(hours=1))
    assert first.new == 2 and second.skipped_already_ingested and len(h.runs()) == 1
    forced = ingest_filtered_file(f, h, force=True, now=NOW + timedelta(hours=2))
    assert (forced.new, forced.existing) == (0, 2) and len(h.runs()) == 2 and len(keys(h)) == 2


def test_history_survives_restart(tmp_path):
    path = tmp_path / "h.json"
    JsonJobHistory(path).ingest([make_record(1), make_record(2)], now=NOW)
    again = JsonJobHistory(path)                                   # new process / new object
    assert len(keys(again)) == 2
    r = again.ingest([make_record(2), make_record(3)], now=NOW + timedelta(hours=1))
    assert (r.new, r.existing) == (1, 1)


def test_corrupt_history_is_never_overwritten(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{ this is not json")
    h = JsonJobHistory(path)
    try:
        h.ingest([make_record(1)], now=NOW)
    except StoreError:
        pass
    else:
        raise AssertionError("expected StoreError")
    assert path.read_text() == "{ this is not json"


def test_real_scraper_outputs_dedupe_across_runs(tmp_path):
    """Two real Phase 2 files from 2026-10-08 both contain JPMorgan job 4438121997."""
    jobs1, _ = load_filtered_file(FIX / "phase2_real_run1.json")
    jobs2, _ = load_filtered_file(FIX / "phase2_real_run2.json")
    assert {j["job_id"] for j in jobs1} == {j["job_id"] for j in jobs2} == {"4438121997"}

    h = JsonJobHistory(tmp_path / "h.json")
    r1 = ingest_filtered_file(FIX / "phase2_real_run1.json", h, now=NOW)
    r2 = ingest_filtered_file(FIX / "phase2_real_run2.json", h, now=NOW + timedelta(hours=1))
    assert (r1.new, r1.existing) == (1, 0)
    assert (r2.new, r2.existing) == (0, 1)                        # found again: NOT a new vacancy
    assert len(keys(h)) == 1
    job = h.get_job("linkedin-4438121997")
    assert job["times_seen"] == 2
    assert job["record"]["posted_at"] == jobs1[0]["posted_at"]   # first, minute-precise estimate retained
    assert job["record"]["posted_at"] != jobs2[0]["posted_at"]


# ------------------------------------------------------------------ normalized (all jobs) file -> history
def test_normalized_file_ingests_all_jobs_and_dedupes_across_runs(tmp_path):
    import json
    from datetime import datetime, timezone
    from processing.pipeline import normalize_all, save_normalized
    from store.ingest import ingest_filtered_file, newest_normalized_file
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    mk = lambda i, **kw: {"source": "LinkedIn", "job_id": str(i), "title": f"Role {i}", "company": "Acme", "location": "Pune, Maharashtra, India",
                          "employment_type": "Full-time", "industries": "Financial Services", "job_url": f"https://www.linkedin.com/jobs/view/{i}",
                          "posted_age_text": "5 hours ago", "collected_at": "2026-10-08T11:00:00+00:00", **kw}
    day1 = [mk(1), mk(2, posted_age_text="9 days ago"), mk(3, industries="Retail", company="Shop")]
    day2 = [mk(2, posted_age_text="10 days ago"), mk(3, industries="Retail", company="Shop"), mk(4)]
    out = tmp_path / "output"
    p1 = save_normalized(normalize_all(day1, as_of=now), out, "linkedin")
    p2 = out / "normalized_jobs_linkedin_zz_second.json"
    p2.write_text(json.dumps({"jobs": normalize_all(day2, as_of=now).jobs}), encoding="utf-8")
    h = JsonJobHistory(tmp_path / "h.json")
    r1 = ingest_filtered_file(p1, h, now=now)
    assert (r1.new, r1.existing) == (3, 0)                              # old and non-GCC/BFSI jobs are all kept
    r2 = ingest_filtered_file(p2, h, now=now + timedelta(days=1))
    assert (r2.new, r2.existing) == (1, 2)                              # re-scraped jobs are not new
    assert len(keys(h)) == 4 and h.get_job("linkedin-2")["times_seen"] == 2
    assert newest_normalized_file(out) is not None and newest_normalized_file(tmp_path / "none") is None
