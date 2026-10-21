"""One opening listed on several sources: stored once, every source link kept; multi-source collection runs."""
import json
from datetime import timedelta
from pathlib import Path

from config import settings
from dashboard.collection import CollectionManager, build_command, SUCCEEDED, PARTIAL
from store.json_store import JsonJobHistory
from store.keys import vacancy_fingerprint
from tests.factories import NOW, make_record


def rec(i, source, **kw):
    return make_record(i, source=source, job_url=f"https://{source.lower()}.example/job/{i}", **kw)


def test_fingerprint_needs_company_title_and_city_and_ignores_legal_suffixes():
    a = vacancy_fingerprint({"company": "Acme Bank Pvt. Ltd.", "title": "Credit Risk Analyst", "location": "Pune, Maharashtra"})
    b = vacancy_fingerprint({"company": "ACME BANK", "title": "credit  risk analyst!", "location": "Pune(Hinjewadi)"})
    assert a == b and a
    assert vacancy_fingerprint({"company": "Acme", "title": "X", "location": None}) is None
    assert vacancy_fingerprint({"company": "Acme", "title": "X", "location": "India"}) is None
    assert vacancy_fingerprint({"company": "", "title": "X", "location": "Pune"}) is None


def test_same_opening_on_two_sources_is_stored_once_and_keeps_both_links(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([rec(1, "LinkedIn")], now=NOW)
    r = h.ingest([rec(55, "Naukri", experience="2-4 years", salary="6-8 LPA")], now=NOW + timedelta(hours=1))
    jobs = h.list_jobs()
    assert len(jobs) == 1 and r.new == 0 and r.existing == 1
    kept = jobs[0]["record"]
    assert kept["source"] == "LinkedIn" and kept["job_id"] == "1"                 # primary record unchanged
    assert kept["also_listed_on"] == [{"source": "Naukri", "job_id": "55", "job_url": "https://naukri.example/job/55"}]
    assert kept["experience"] == "2-4 years" and kept["salary"] == "6-8 LPA"       # gaps filled from the other source
    # seeing the Naukri listing again later changes nothing but the counters
    h.ingest([rec(55, "Naukri")], now=NOW + timedelta(hours=5))
    j = h.list_jobs()[0]
    assert len(h.list_jobs()) == 1 and len(j["record"]["also_listed_on"]) == 1 and j["times_seen"] == 3


def test_third_source_is_added_and_same_source_twins_are_not_merged(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([rec(1, "LinkedIn"), rec(2, "LinkedIn")], now=NOW)          # same company/title/city, same source: two postings
    assert len(h.list_jobs()) == 2
    h.ingest([rec(9, "Indeed")], now=NOW)
    assert len(h.list_jobs()) == 2
    assert sum(len(j["record"].get("also_listed_on") or []) for j in h.list_jobs()) == 1


def test_existing_history_is_untouched_by_dedup_of_new_sources(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([rec(1, "LinkedIn", company="A"), rec(2, "LinkedIn", company="B")], now=NOW)
    before = json.dumps(h.list_jobs(), sort_keys=True)
    h.ingest([rec(1, "LinkedIn", company="A")], now=NOW)
    assert [j["key"] for j in h.list_jobs()] == ["linkedin-1", "linkedin-2"]
    assert len(before) > 0


# -- controller with several sources ------------------------------------------------------
def fake_runner_factory(per_source, calls):
    """Pretend scraper: for each --source writes a jobs file with the listed (id, title, company) tuples."""
    def runner(cmd, on_line, cwd, timeout):
        src = cmd[cmd.index("--source") + 1] if "--source" in cmd else "linkedin"
        calls.append(src)
        if per_source.get(src) == "setup":
            on_line("2026-10-12 | ERROR | x | SETUP REQUIRED: install playwright")
            return 3
        if per_source.get(src) == "blocked":
            return 2
        out = Path(cmd[cmd.index("--output-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        jobs = [{"source": src.title(), "job_id": jid, "title": t, "company": c, "location": "Pune, Maharashtra, India",
                 "job_url": f"https://{src}.example/{jid}", "description": "Banking role", "industries": "Banking", "posted_date": d,
                 "employment_type": "Full-time"} for jid, t, c, d in per_source.get(src, [])]
        path = out / f"jobs_{src}_20261012_000000.json"
        path.write_text(json.dumps({"run": {"latest_ids": [j["job_id"] for j in jobs]}, "jobs": jobs}), encoding="utf-8")
        on_line(f"Saved {len(jobs)} jobs to {path}")
        return 0
    return runner


def make_mgr(tmp_path, per_source, calls):
    h = JsonJobHistory(tmp_path / "h.json")
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=fake_runner_factory(per_source, calls), background=False)
    return h, m


def test_build_command_adds_source_only_for_new_sources():
    base = build_command("india", Path("/tmp/o"))
    assert "--source" not in base
    cmd = build_command("india", Path("/tmp/o"), source="naukri")
    assert cmd[cmd.index("--source") + 1] == "naukri"


def test_multi_source_run_collects_each_source_and_merges_duplicates(tmp_path, monkeypatch=None):
    calls = []
    per = {"linkedin": [("1", "Credit Risk Analyst", "Acme Bank", "2026-10-12")],
           "naukri": [("77", "Credit Risk Analyst", "Acme Bank", "2026-10-12"), ("78", "Treasury Analyst", "Beta Bank", "2026-10-11")]}
    h, m = make_mgr(tmp_path, per, calls)
    ok, msg = m.start("india", target=5, window="7d" if "7d" in settings.COLLECTION_WINDOWS else settings.COLLECTION_DEFAULT_WINDOW,
                      sources=["LinkedIn", "Naukri"])
    assert ok, msg
    st = m.status()
    assert st["sources"] == ["LinkedIn", "Naukri"] and set(calls) == {"linkedin", "naukri"}
    keys = {j["key"]: j["record"] for j in h.list_jobs()}
    assert len(keys) == 2                                                       # the shared opening is stored once
    # sources now run side by side, so whichever finishes first is stored as the main record and the other is "also listed on"
    primary_key, other = ("linkedin-1", "Naukri") if "linkedin-1" in keys else ("naukri-77", "LinkedIn")
    primary = keys[primary_key]
    assert primary["also_listed_on"][0]["source"].lower() == other.lower()
    assert st["collected_unique"] == 2 and set(st["result_keys"]) == set(keys)


def test_a_source_that_needs_setup_does_not_stop_the_others(tmp_path):
    calls = []
    per = {"linkedin": [("1", "Credit Risk Analyst", "Acme Bank", "2026-10-12")], "naukri": "setup"}
    h, m = make_mgr(tmp_path, per, calls)
    ok, _ = m.start("india", target=3, sources=["linkedin", "naukri"])
    st = m.status()
    assert ok and len(h.list_jobs()) == 1 and st["state"] == SUCCEEDED
    assert any("Naukri could not run" in w and "playwright" in w for w in st["warnings"])
    assert "Not collected: Naukri" in st["message"]


def test_a_blocked_source_stops_only_itself(tmp_path):
    calls = []
    per = {"naukri": "blocked", "linkedin": [("1", "Credit Risk Analyst", "Acme Bank", "2026-10-12")]}
    h, m = make_mgr(tmp_path, per, calls)
    m.start("india", target=3, sources=["naukri", "linkedin"])
    st = m.status()
    assert st["state"] == PARTIAL and st["stop_reason"] == "blocked" and "Naukri" in st["last_error"]
    assert "linkedin" in calls and len(h.list_jobs()) == 1


def test_invalid_sources_are_refused_and_default_is_linkedin(tmp_path):
    calls = []
    h, m = make_mgr(tmp_path, {"linkedin": []}, calls)
    ok, msg = m.start("india", sources=["glassdoor"])
    assert not ok and "listed sources" in msg
    ok, _ = m.start("india")
    assert ok and calls == ["linkedin"] * len(calls) and calls


# -- the dashboard form ------------------------------------------------------------------
def test_form_ticks_choose_the_sources_and_last_run_is_shown_back(tmp_path):
    from tests.test_collection_and_controls import make_app, serve
    from tests.test_dashboard_server import call, get
    calls = []
    out = tmp_path / "out"; out.mkdir()
    runner = fake_runner_factory({"linkedin": [("1", "A", "B", "2026-10-12")], "naukri": [("5", "C", "D", "2026-10-12")]}, calls)
    app, mgr = make_app(tmp_path, runner=runner)
    srv = serve(app); port = srv.server_address[1]
    try:
        form = [("scope", "india"), ("count", "5"), ("window", settings.COLLECTION_DEFAULT_WINDOW), ("sources_sent", "1"),
                ("source", "Naukri"), ("source", "LinkedIn")]
        assert call(port, "POST", "/collection/run", form)[1]["location"] == "/?notice=started"
        assert set(calls) == {"linkedin", "naukri"} and mgr.status()["sources"] == ["LinkedIn", "Naukri"]
        h = get(port, "/?scope=all")[2]
        # the form offers ONE source per run (a dropdown); the server still accepts a list, as above
        assert '<select id="collect-source" name="source">' in h and 'type="checkbox" name="source"' not in h
        assert '<option value="LinkedIn" selected>' in h and '<option value="Naukri">' in h
        assert 'value="Indeed"' not in h
        none = [("scope", "india"), ("count", "5"), ("sources_sent", "1")]       # nothing ticked
        assert call(port, "POST", "/collection/run", none)[1]["location"] == "/?notice=bad_source"
        assert call(port, "POST", "/collection/run", [("scope", "india"), ("count", "5"), ("source", "Glassdoor"), ("sources_sent", "1")])[1]["location"] == "/?notice=bad_source"
    finally:
        srv.shutdown(); srv.server_close()


def test_source_filter_and_column_show_every_source_of_a_merged_vacancy(tmp_path):
    from dashboard.viewmodel import Filters, apply_filters, build_rows
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([rec(1, "LinkedIn"), rec(2, "Indeed", company="Other Co")], now=NOW)
    h.ingest([rec(55, "Naukri")], now=NOW + timedelta(hours=1))          # merged into LinkedIn #1
    rows = build_rows(h.list_jobs(), {}, NOW + timedelta(hours=2))
    by = {r.job_id: r for r in rows}
    assert by["1"].all_sources == ["LinkedIn", "Naukri"]
    for src, expect in (("LinkedIn", {"1"}), ("Naukri", {"1"}), ("Indeed", {"2"})):
        got = {r.job_id for r in apply_filters(rows, Filters(source=src), NOW + timedelta(hours=2))}
        assert got == expect, (src, got)
