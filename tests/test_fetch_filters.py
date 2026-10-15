"""The dashboard filters (State, Employment type, Work mode, Contact details) also apply while vacancies are fetched."""
import json
from pathlib import Path

from config import settings
from dashboard import viewmodel as vm
from dashboard.collection import CollectionManager
from store.json_store import JsonJobHistory

DESC = "Credit risk role at a bank. Send your CV to talent.hiring@acmebank.example for this opening."
JOBS = [  # id, title, location, description, employment
    ("1", "Credit Risk Analyst", "Pune, Maharashtra, India", DESC, "Full-time"),
    ("2", "Treasury Analyst", "Pune, Maharashtra, India", "Banking role with no contact stated.", "Full-time"),
    ("3", "Compliance Analyst", "Chennai, Tamil Nadu, India", DESC, "Full-time"),
    ("4", "Audit Associate", "Chennai, Tamil Nadu, India", "Banking role.", "Contract"),
]


def runner(cmd, on_line, cwd, timeout):
    out = Path(cmd[cmd.index("--output-dir") + 1]); out.mkdir(parents=True, exist_ok=True)
    jobs = [{"source": "LinkedIn", "job_id": i, "title": t, "company": "Acme Bank", "location": loc,
             "job_url": f"https://linkedin.example/{i}", "description": d, "industries": "Banking",
             "posted_date": "2026-10-12", "employment_type": e} for i, t, loc, d, e in JOBS]
    path = out / "jobs_linkedin_20261012_000000.json"
    path.write_text(json.dumps({"run": {"latest_ids": [j["job_id"] for j in jobs]}, "jobs": jobs}), encoding="utf-8")
    on_line(f"Saved {len(jobs)} jobs to {path}")
    return 0


def collect(tmp_path, filters, target=10):
    h = JsonJobHistory(tmp_path / "h.json")
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=runner, background=False)
    ok, msg = m.start("india", target=target, window=settings.COLLECTION_DEFAULT_WINDOW, sources=["LinkedIn"], filters=filters)
    assert ok, msg
    return h, m.status()


def ids(h):
    return {j["record"]["job_id"] for j in h.list_jobs()}


def test_clean_fetch_filters_drops_all_and_unknown_values():
    assert vm.clean_fetch_filters({"employment": "all", "work_mode": "", "state": "", "contact": "all"}) == {}
    assert vm.clean_fetch_filters({"employment": "Bogus", "contact": "yes", "state": " Tamil  Nadu "}) == {"contact": "yes", "state": "Tamil Nadu"}


def test_contact_filter_collects_only_vacancies_with_poster_contact(tmp_path):
    h, st = collect(tmp_path, {"contact": "yes"})
    assert ids(h) == {"1", "3"} and st["collected_unique"] == 2
    assert st["skipped_filters"] == 2 and st["fetch_filters"] == {"contact": "yes"}


def test_state_filter_collects_only_that_state(tmp_path):
    h, st = collect(tmp_path, {"state": "Tamil Nadu"})
    assert ids(h) == {"3", "4"}


def test_filters_combine_and_the_target_counts_only_matching_vacancies(tmp_path):
    h, st = collect(tmp_path, {"state": "Tamil Nadu", "contact": "yes"})
    assert ids(h) == {"3"} and st["collected_unique"] == 1
    h2, st2 = collect(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, {"contact": "no"})
    assert ids(h2) == {"2", "4"}


def test_no_filters_collects_everything_as_before(tmp_path):
    h, st = collect(tmp_path, {})
    assert ids(h) == {"1", "2", "3", "4"} and st["skipped_filters"] == 0


def test_the_collection_panel_offers_the_filters_and_the_server_passes_them(tmp_path):
    from dashboard import views
    from datetime import datetime, timezone
    h = JsonJobHistory(tmp_path / "h.json")
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=runner, background=False)
    html = views._collection_panel({"status": m.status(), "enabled": True, "default_scope": "india"}, "/", datetime.now(timezone.utc))
    for name in ("f_state", "f_employment", "f_work_mode", "f_contact"):
        assert f'name="{name}"' in html
    assert "Tamil Nadu" in html


# ---- showing the saved vacancies (no search) and the strict posted-within window ----------------------------
from datetime import datetime, timedelta, timezone


def _stored(tmp_path):
    """History with vacancies posted 2h, 5h, 30h ago and 4 days ago; some state a contact, some do not."""
    h = JsonJobHistory(tmp_path / "h.json")
    now = datetime.now(timezone.utc)
    spec = [("a", 2, DESC, "Pune, Maharashtra, India"), ("b", 5, "Banking role.", "Pune, Maharashtra, India"),
            ("c", 30, DESC, "Pune, Maharashtra, India"), ("d", 96, DESC, "Pune, Maharashtra, India"),
            ("e", 3, DESC, "Chennai, Tamil Nadu, India"), ("f", 1, DESC, "London, United Kingdom")]
    jobs = [{"source": "LinkedIn", "job_id": i, "title": "Credit Risk Analyst " + i, "company": "Acme Bank", "location": loc,
             "job_url": f"https://linkedin.example/{i}", "description": d, "industries": "Banking",
             "posted_age_text": f"{hrs} hours ago", "collected_at": now.isoformat(),
             "employment_type": "Full-time"} for i, hrs, d, loc in spec]
    from processing.pipeline import normalize_all
    from store.ingest import ingest_filtered_file
    run = normalize_all(jobs)
    p = tmp_path / "n.json"
    p.write_text(json.dumps({"input_file": None, "summary": run.summary, "jobs": run.jobs, "failed": run.failed}), encoding="utf-8")
    ingest_filtered_file(p, h)
    return h


def test_show_saved_lists_only_matching_recent_vacancies_with_contacts_and_changes_nothing(tmp_path):
    h = _stored(tmp_path)
    before = json.dumps(h.list_jobs(), sort_keys=True)
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=lambda *a: 1, background=False)
    ok, msg = m.show_saved("india", 10, "24h", ["LinkedIn"], {"contact": "yes"})
    st = m.status()
    assert ok and st["stop_reason"] == "saved" and "no new search" in st["message"]
    got = [e["record"]["job_id"] for e in h.list_jobs() if e["key"] in st["result_keys"]]
    assert set(got) == {"a", "e"}                          # <=24h, in India, with a contact; not b (no contact), c/d (too old), f (UK)
    assert json.dumps(h.list_jobs(), sort_keys=True) == before
    ok, _ = m.show_saved("india", 1, "24h", ["LinkedIn"], {"contact": "yes", "state": "Tamil Nadu"})
    assert [e["record"]["job_id"] for e in h.list_jobs() if e["key"] in m.status()["result_keys"]] == ["e"]


def test_show_saved_says_so_when_fewer_than_requested_match(tmp_path):
    h = _stored(tmp_path)
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=lambda *a: 1, background=False)
    ok, msg = m.show_saved("india", 10, "24h", ["LinkedIn"], {"contact": "yes"})
    assert "Only 2 of the 10 requested match" in msg


def test_live_collection_with_a_window_drops_postings_older_than_the_window(tmp_path):
    h = _stored(tmp_path)
    recs = [e["record"] for e in h.list_jobs()]
    flags = vm.fetch_filter_matches(recs, {"contact": "yes"}, max_age_hours=24)
    ok_ids = {r["job_id"] for r, f in zip(recs, flags) if f}
    assert ok_ids == {"a", "e", "f"}                       # c (30h) and d (96h) are outside 24h; f is only excluded by the scope gate


def test_the_collection_panel_defaults_the_contact_filter_to_yes_and_offers_show_saved(tmp_path):
    from dashboard import views
    h = JsonJobHistory(tmp_path / "h.json")
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=runner, background=False)
    html = views._collection_panel({"status": m.status(), "enabled": True, "default_scope": "india"}, "/", datetime.now(timezone.utc))
    assert 'formaction="/collection/saved"' in html and "Show saved vacancies" in html
    assert '<option value="yes" selected>' in html


def test_a_live_run_with_the_24h_window_does_not_keep_older_postings(tmp_path):
    h = _stored(tmp_path)
    old = [e["record"] for e in h.list_jobs() if e["record"]["job_id"] in ("c", "d")]
    settings.COLLECTION_STRICT_WINDOW = True
    try:
        assert vm.fetch_filter_matches(old, {}, max_age_hours=24) == [False, False]
    finally:
        settings.COLLECTION_STRICT_WINDOW = False
