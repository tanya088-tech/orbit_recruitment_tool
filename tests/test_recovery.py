"""Recovering jobs saved by an interrupted collection, without duplicates and without touching existing data."""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

from dashboard.collection import FAILED, PARTIAL, RUNNING, CollectionManager
from processing.pipeline import load_jobs, normalize_all, save_normalized
from store.ingest import ingest_filtered_file
from store.json_store import JsonJobHistory, JsonRecruiterState
from store.recovery import find_unprocessed, recover_unprocessed
from tests.factories import NOW
from tests.test_collection_and_controls import raw_job

START = datetime.now(timezone.utc) - timedelta(minutes=30)       # when the interrupted run "started"


def write_jobs(out, name, jobs):
    path = out / name
    path.write_text(json.dumps({"run": {}, "jobs": jobs}), encoding="utf-8")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    return out, JsonJobHistory(tmp_path / "job_history.json")


def test_unprocessed_file_is_recovered_once(tmp_path):
    out, h = setup(tmp_path)
    raw = write_jobs(out, "jobs_linkedin_20261010_190744.json", [raw_job(1), raw_job(2, location="Jaipur, Rajasthan, India")])
    before = digest(raw)
    r = recover_unprocessed(h, out, START)
    assert (r.files_found, r.files_recovered, r.jobs_in_files, r.new, r.existing) == (1, 1, 2, 2, 0)
    assert len(h.list_jobs()) == 2 and digest(raw) == before          # the original file is untouched
    assert len(list(out.glob("normalized_jobs_*.json"))) == 1
    again = recover_unprocessed(h, out, START)                         # a second start does nothing
    assert again.files_found == 0 and len(h.list_jobs()) == 2 and len(list(out.glob("normalized_jobs_*.json"))) == 1


def test_existing_history_and_recruiter_state_are_preserved_and_not_duplicated(tmp_path):
    out, h = setup(tmp_path)
    state = JsonRecruiterState(tmp_path / "recruiter_state.json", now_fn=lambda: NOW)
    h.ingest([{"source": "LinkedIn", "job_id": "7000000001", "title": "Original title", "company": "Acme Bank"}], now=NOW)
    state.set_saved("linkedin-7000000001", True); state.add_note("linkedin-7000000001", "keep me")
    state_before = (tmp_path / "recruiter_state.json").read_text()
    write_jobs(out, "jobs_linkedin_20261010_190744.json", [raw_job(1, title="Different title"), raw_job(2)])
    r = recover_unprocessed(h, out, START)
    assert r.new == 1 and r.existing == 1 and len(h.list_jobs()) == 2
    assert h.get_job("linkedin-7000000001")["record"]["title"] == "Original title"      # first record wins
    assert h.get_job("linkedin-7000000001")["times_seen"] == 2
    assert (tmp_path / "recruiter_state.json").read_text() == state_before


def test_files_already_ingested_old_or_out_of_scope_are_not_recovered(tmp_path):
    out, h = setup(tmp_path)
    done = write_jobs(out, "jobs_linkedin_20261010_100000.json", [raw_job(1)])
    _, jobs = load_jobs(done)
    ingest_filtered_file(save_normalized(normalize_all(jobs), out, "linkedin", input_file=done), h)   # processed the normal way
    old = write_jobs(out, "jobs_linkedin_20261001_100000.json", [raw_job(2)])
    os.utime(old, (time.time() - 86400 * 9, time.time() - 86400 * 9))
    fresh = write_jobs(out, "jobs_linkedin_20261010_190744.json", [raw_job(3)])
    (out / "notes.txt").write_text("not a jobs file")
    assert [p.name for p in find_unprocessed(h, out, START)] == [fresh.name]
    assert find_unprocessed(h, out, None) == []                           # no known interrupted run: touch nothing
    recover_unprocessed(h, out, START)
    assert {j["key"] for j in h.list_jobs()} == {"linkedin-7000000001", "linkedin-7000000003"}


def test_a_broken_file_does_not_stop_the_others(tmp_path):
    out, h = setup(tmp_path)
    (out / "jobs_linkedin_20261010_180000.json").write_text("{ broken")
    write_jobs(out, "jobs_linkedin_20261010_190744.json", [raw_job(1)])
    write_jobs(out, "jobs_linkedin_20261010_200000.json", [])             # an empty file is skipped quietly
    r = recover_unprocessed(h, out, START)
    assert r.files_recovered == 1 and len(r.errors) == 1 and "20261010_180000" in r.errors[0] and len(h.list_jobs()) == 1


# ------------------------------------------------------------------ the dashboard's own startup
def manager(tmp_path, out):
    return CollectionManager(JsonJobHistory(tmp_path / "job_history.json"), tmp_path, output_dir=out, now_fn=lambda: NOW, background=False)


def test_startup_after_an_interrupted_run_recovers_saved_jobs_and_is_not_stuck_on_running(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    write_jobs(out, "jobs_linkedin_20261010_190744.json", [raw_job(i) for i in range(1, 4)])
    (tmp_path / "collection.lock").write_text(json.dumps({"pid": 2 ** 22 + 777}))          # left behind by the dead app
    (tmp_path / "collection_status.json").write_text(json.dumps(
        {"state": "running", "scope": "india", "started_at": START.isoformat(timespec="seconds"), "search_done": 0, "search_total": 38}))
    m = manager(tmp_path, out)
    st = m.status()
    assert st["state"] == PARTIAL and not m.running and "Recovered 3 saved jobs: 3 new" in st["message"]
    assert st["last_summary"]["new"] == 3 and len(m.history.list_jobs()) == 3 and st["last_success_at"] is None
    assert not (tmp_path / "collection.lock").exists()
    again = manager(tmp_path, out)                                      # restarting again re-ingests nothing
    assert len(again.history.list_jobs()) == 3 and len(list(out.glob("normalized_jobs_*.json"))) == 1


def test_interrupt_with_nothing_saved_just_reports_interrupted(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    (tmp_path / "collection_status.json").write_text(json.dumps({"state": "running", "started_at": START.isoformat()}))
    m = manager(tmp_path, out)
    assert m.status()["state"] == FAILED and "interrupted" in m.status()["last_error"] and not m.running


def test_clean_shutdown_marks_interrupted_and_next_start_recovers(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    m = manager(tmp_path, out)
    m._acquire_lock()                                                   # a run in progress holds the lock
    m._s.update(state=RUNNING, started_at=START.isoformat(timespec="seconds"))
    m.mark_interrupted()
    st = json.loads((tmp_path / "collection_status.json").read_text())
    assert st["state"] == FAILED and st["pending_recovery_since"] and not (tmp_path / "collection.lock").exists()
    write_jobs(out, "jobs_linkedin_20261010_190744.json", [raw_job(1)])     # the scraper saved its file as it was interrupted
    m2 = manager(tmp_path, out)
    assert len(m2.history.list_jobs()) == 1 and m2.status()["state"] == PARTIAL
    assert "pending_recovery_since" not in json.loads((tmp_path / "collection_status.json").read_text())


def test_a_stale_lock_with_a_reused_process_id_does_not_block_a_new_run(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    lock = tmp_path / "collection.lock"
    lock.write_text(json.dumps({"pid": os.getppid()}))                  # a pid that IS alive (a different program now)
    old = time.time() - 3600
    os.utime(lock, (old, old))
    m = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, output_dir=out, now_fn=lambda: NOW, background=False,
                          runner=lambda *a, **k: 1)
    assert m.start("india")[0]                                          # not refused: nobody refreshed the lock for an hour
    fresh = tmp_path / "collection.lock"
    fresh.write_text(json.dumps({"pid": os.getppid()}))
    m2 = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, output_dir=out, now_fn=lambda: NOW, background=False)
    assert not m2.start("india")[0]                                     # a fresh lock from a live process still blocks
