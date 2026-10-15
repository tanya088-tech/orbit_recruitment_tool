"""The collection manager (with a fake scraper) and the dashboard's collection / restart / logo controls."""
import http.client
import json
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

from config import locations as loc
from config import settings
from dashboard import branding, views
from dashboard.collection import FAILED, IDLE, PARTIAL, SUCCEEDED, CollectionManager, build_command
from dashboard.server import DashboardApp
from store.json_store import JsonJobHistory, JsonRecruiterState
from tests.factories import NOW
from tests.test_dashboard_server import call, get, running


def raw_job(n, **kw):
    base = {"source": "LinkedIn", "job_id": str(7000000000 + n), "title": f"Analyst {n}", "company": "Acme Bank",
            "location": "Pune, Maharashtra, India", "job_url": f"https://www.linkedin.com/jobs/view/{7000000000 + n}",
            "description": "desc", "employment_type": "Full-time", "industries": "Banking",
            "posted_age_text": "2 hours ago", "collected_at": "2026-10-08T09:50:00+00:00", "raw": {}}
    base.update(kw)
    return base


def fake_runner(out_dir, jobs, code=0, lines=None, write=True, per_call=None):
    """Stands in for run_collect.py. It is called once per place; `jobs` are returned on the first call only
    (later places find nothing), unless per_call(n) -> (jobs, code) says otherwise."""
    calls = []
    def run(cmd, on_line, cwd, timeout_s):
        n = len(calls)
        calls.append(cmd)
        got, rc = per_call(n) if per_call else ((jobs if n == 0 else []), code)
        for ln in (lines or []):
            on_line(ln)
        if write:
            path = Path(out_dir) / f"jobs_linkedin_20261008_1000{n:02d}.json"
            path.write_text(json.dumps({"run": {}, "jobs": got}), encoding="utf-8")
            on_line(f"Saved {len(got)} jobs to {path}")
        return rc
    run.calls = calls
    return run


def manager(tmp_path, runner):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    history = JsonJobHistory(tmp_path / "job_history.json")
    return CollectionManager(history, tmp_path, output_dir=out, runner=runner, now_fn=lambda: NOW, background=False), history


# ------------------------------------------------------------------ the command
def test_command_uses_only_configured_values_and_the_chosen_scope():
    for scope in loc.SCOPES:
        cmd = build_command(scope, Path("/tmp/o"))
        assert cmd[1].endswith("run_collect.py")
        i = cmd.index("--locations")
        assert cmd[i + 1:i + 1 + len(loc.search_locations(scope))] == loc.search_locations(scope)
        assert "--days" in cmd and "--max-jobs-per-search" in cmd and "--max-pages" in cmd and "--output-dir" in cmd
    assert "Dubai" not in " ".join(build_command("india", Path("/tmp/o")))
    assert "United Arab Emirates" in build_command("both", Path("/tmp/o"))


# ------------------------------------------------------------------ the run
def test_successful_run_collects_normalizes_and_ingests(tmp_path):
    jobs = [raw_job(1), raw_job(2, location="Dubai, United Arab Emirates")]
    m, history = manager(tmp_path, fake_runner(tmp_path / "out", jobs))
    ok, _ = m.start("both")
    st = m.status()
    assert ok and st["state"] == SUCCEEDED and st["last_success_at"] and st["last_error"] is None
    assert st["last_summary"]["collected"] == 2 and st["last_summary"]["new"] == 2 and st["last_summary"]["scope"] == "both"
    assert len(history.list_jobs()) == 2
    countries = sorted(j["record"].get("country") or "" for j in history.list_jobs())
    assert countries == ["India", "United Arab Emirates"]
    assert (tmp_path / "collection_status.json").exists() and not (tmp_path / "collection.lock").exists()
    # a second run re-finds the same jobs: no duplicates
    later = [dict(j, collected_at="2026-10-09T09:50:00+00:00") for j in jobs]
    m.runner = fake_runner(tmp_path / "out", later)
    m.start("india")
    # (India-only: the Dubai posting is skipped, not re-counted; the saved Dubai job stays in the history)
    assert len(history.list_jobs()) == 2 and m.status()["last_summary"]["new"] == 0 and m.status()["last_summary"]["existing"] == 1


def test_blocked_run_is_partial_and_keeps_what_was_collected(tmp_path):
    m, history = manager(tmp_path, fake_runner(tmp_path / "out", [raw_job(1)], code=2))
    m.start("india")
    st = m.status()
    assert st["state"] == PARTIAL and "refusing requests" in st["last_error"] and len(history.list_jobs()) == 1
    assert st["last_success_at"] is None                              # a partial run is not reported as a success


def test_failed_run_shows_an_error_and_keeps_the_previous_success(tmp_path):
    m, history = manager(tmp_path, fake_runner(tmp_path / "out", [raw_job(1)]))
    m.start("india")
    good = m.status()["last_success_at"]
    for old in (tmp_path / "out").glob("jobs_*.json"):
        old.unlink()
    m.runner = fake_runner(tmp_path / "out", [], code=1, write=False, lines=["2026 | ERROR | network down"])
    m.start("india")
    st = m.status()
    assert st["state"] == FAILED and "No jobs file was saved" in st["last_error"]
    assert st["last_success_at"] == good and "network down" in " ".join(st["warnings"])
    assert not (tmp_path / "collection.lock").exists()                # the lock is always released


def test_progress_follows_the_place_being_searched(tmp_path):
    seen = []
    def runner(cmd, on_line, cwd, timeout_s):
        if not seen:
            seen.append(m.status())
            assert cmd[cmd.index("--locations") + 1:cmd.index("--days")] == ["India"]     # one place per scraper process
        return 1
    m, _ = manager(tmp_path, runner)
    m.start("india")
    assert seen[0]["state"] == "running" and seen[0]["search_done"] == 0 and seen[0]["current_search"] == "India"
    assert seen[0]["search_total"] == len(loc.search_locations("india"))


def test_every_place_is_searched_and_saved_as_it_finishes(tmp_path):
    runner = fake_runner(tmp_path / "out", [], per_call=lambda n: ([raw_job(n + 1, location=f"City {n}, India")], 0))
    m, history = manager(tmp_path, runner)
    m.start("both")
    places = loc.search_locations("both")
    assert len(runner.calls) == len(places) and len(history.list_jobs()) == len(places)      # not just Bengaluru: one job per place
    asked = [c[c.index("--locations") + 1] for c in runner.calls]
    assert asked == places and "Bengaluru, Karnataka, India" in asked and "Delhi, India" in asked and "Singapore" in asked
    assert m.status()["state"] == SUCCEEDED and m.status()["search_done"] == len(places)


def test_one_failing_place_does_not_lose_the_others_and_blocking_stops_the_run(tmp_path):
    runner = fake_runner(tmp_path / "out", [], per_call=lambda n: ([raw_job(n + 1)], 1 if n == 1 else 0) if n != 1 else ([], 1))
    m, history = manager(tmp_path, runner)
    m.start("india")
    st = m.status()
    assert st["state"] == SUCCEEDED and len(history.list_jobs()) == len(loc.search_locations("india")) - 1
    assert any("exit code 1" in w for w in st["warnings"]) and "had problems" in st["message"]
    m2, h2 = manager(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                     fake_runner(tmp_path / "b" / "out" if (tmp_path / "b" / "out").mkdir() is None else tmp_path,
                                 [], per_call=lambda n: ([raw_job(n + 1)], 2 if n == 2 else 0)))
    m2.start("india")
    assert m2.status()["state"] == PARTIAL and len(h2.list_jobs()) == 3          # jobs before the block are kept; the run stops


def test_a_second_run_cannot_start_while_one_is_running(tmp_path):
    gate, started = threading.Event(), threading.Event()
    def slow(cmd, on_line, cwd, timeout_s):
        started.set()
        gate.wait(5)
        return 1
    out = tmp_path / "out"; out.mkdir()
    m = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, output_dir=out, runner=slow, now_fn=lambda: NOW, background=True)
    other = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, output_dir=out, runner=slow, now_fn=lambda: NOW, background=False)
    ok, _ = m.start("india")
    assert ok and started.wait(5) and m.running
    ok2, msg = m.start("india")
    assert not ok2 and "already running" in msg
    # another Ace Talent Consulting window (another process on the same folder) is refused by the lock file too
    lock = tmp_path / "collection.lock"
    saved_lock = lock.read_text()
    lock.write_text(json.dumps({"pid": os.getppid()}))              # as if it belonged to another, live Orbit process
    assert not other.start("india")[0]
    lock.write_text(saved_lock)
    gate.set()
    for _ in range(100):
        if not m.running:
            break
        time.sleep(0.05)
    assert not m.running and not (tmp_path / "collection.lock").exists()


def test_bad_scope_is_refused_and_stale_state_is_recovered(tmp_path):
    m, _ = manager(tmp_path, fake_runner(tmp_path / "out", []))
    ok, _ = m.start("moon")
    assert not ok and m.status()["state"] == IDLE
    # a lock left by a process that no longer exists does not block a new run
    (tmp_path / "collection.lock").write_text(json.dumps({"pid": 2 ** 22 + 12345}))
    assert m.start("india")[0]
    # a status file saying "running" with no live run behind it is shown as interrupted, not as running forever
    (tmp_path / "collection_status.json").write_text(json.dumps({"state": "running", "message": "x"}))
    again, _ = manager(tmp_path, fake_runner(tmp_path / "out", []))
    assert again.status()["state"] != "running" and not again.running
    (tmp_path / "collection_status.json").write_text("{ broken")
    assert manager(tmp_path, fake_runner(tmp_path / "out", []))[0].status()["state"] == IDLE


# ------------------------------------------------------------------ dashboard controls
def make_app(tmp_path, runner=None, collection=True, restart=None):
    history = JsonJobHistory(tmp_path / "job_history.json")
    state = JsonRecruiterState(tmp_path / "recruiter_state.json", now_fn=lambda: NOW)
    out = tmp_path / "out"; out.mkdir(exist_ok=True)
    mgr = CollectionManager(history, tmp_path, output_dir=out, runner=runner or fake_runner(out, [raw_job(1)]),
                            now_fn=lambda: NOW, background=False) if collection else None
    return DashboardApp(history, state, now_fn=lambda: NOW, collection=mgr, restart_fn=restart, static_dir=tmp_path / "static"), mgr


def serve(app):
    from http.server import ThreadingHTTPServer
    from dashboard.server import make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_page_shows_run_refresh_and_restart_controls(tmp_path):
    app, _ = make_app(tmp_path, restart=lambda: None)
    srv = serve(app)
    try:
        h = get(srv.server_address[1], "/")[2]
        assert 'action="/collection/run"' in h and "Run job collection" in h
        assert "Refresh dashboard" in h and 'action="/app/restart"' in h and "Restart app" in h
        assert "Last successful run: none yet" in h and "Not run yet" in h
        for label in ("India only", "India and international", "International only"):
            assert f">{label}</option>" in h
        assert "Powered by <b>Groxa AI</b>" in h
    finally:
        srv.shutdown(); srv.server_close()


def test_run_button_starts_a_collection_and_shows_status(tmp_path):
    app, mgr = make_app(tmp_path)
    srv = serve(app); port = srv.server_address[1]
    try:
        status, headers, _ = call(port, "POST", "/collection/run", {"scope": "india", "count": "50"})
        assert status == 303 and headers["location"] == "/?notice=started"
        assert mgr.status()["state"] == SUCCEEDED
        h = get(port, "/?notice=started&scope=all")[2]
        assert "Collection started." in h and "Last run finished" in h and "Last successful run:" in h and "1 new" in h
        assert json.loads(get(port, "/collection/status")[2])["state"] == SUCCEEDED
        assert len(app.history.list_jobs()) == 1
    finally:
        srv.shutdown(); srv.server_close()


def test_run_button_rejects_bad_scope_duplicates_and_cross_site_posts(tmp_path):
    gate = threading.Event()
    def slow(cmd, on_line, cwd, timeout_s):
        gate.wait(5); return 1
    app, mgr = make_app(tmp_path, runner=slow)
    mgr.background = True
    srv = serve(app); port = srv.server_address[1]
    try:
        assert call(port, "POST", "/collection/run", {"scope": "<script>"})[1]["location"] == "/?notice=bad"
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "50"}, headers={"Origin": "http://evil.example"})[0] == 403
        assert mgr.status()["state"] == IDLE
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "50"})[1]["location"] == "/?notice=started"
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "50"})[1]["location"] == "/?notice=already"   # double click
        h = get(port, "/?notice=already")[2]
        assert 'data-collect-poll="1"' in h and "<progress" in h and "already running" in h
        assert "disabled" in h[h.index('class="collect-run"'):h.index("</form>", h.index('class="collect-run"'))]
        # restart is refused while a collection runs
        assert call(port, "POST", "/app/restart", {})[0] in (303, 400)
        gate.set()
    finally:
        gate.set(); srv.shutdown(); srv.server_close()


def test_unknown_notice_values_are_ignored_and_failures_are_visible(tmp_path):
    app, mgr = make_app(tmp_path, runner=fake_runner(tmp_path / "out", [], code=1, write=False))
    srv = serve(app); port = srv.server_address[1]
    try:
        call(port, "POST", "/collection/run", {"scope": "india", "count": "50"})
        h = get(port, "/?notice=<script>alert(1)</script>")[2]
        assert "<script>alert" not in h and "Last run failed" in h and 'role="alert"' in h and "No jobs file was saved" in h
    finally:
        srv.shutdown(); srv.server_close()


def test_restart_runs_the_restart_hook_and_shows_a_waiting_page(tmp_path):
    fired = threading.Event()
    app, _ = make_app(tmp_path, restart=fired.set)
    srv = serve(app); port = srv.server_address[1]
    try:
        status, _, h = call(port, "POST", "/app/restart", {})
        assert status == 200 and "Restarting Ace Talent Consulting Job Radar" in h and "data-restart-poll" in h
        assert fired.wait(3)
    finally:
        srv.shutdown(); srv.server_close()


def test_restart_is_refused_while_collecting_and_when_not_supported(tmp_path):
    app, mgr = make_app(tmp_path, restart=lambda: (_ for _ in ()).throw(AssertionError("must not restart")))
    mgr._s["state"] = "running"
    srv = serve(app); port = srv.server_address[1]
    try:
        status, headers, _ = call(port, "POST", "/app/restart", {})
        assert status == 303 and headers["location"] == "/?notice=restart_blocked"
    finally:
        srv.shutdown(); srv.server_close()
    app2, _ = make_app(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, restart=None)
    srv2 = serve(app2)
    try:
        assert call(srv2.server_address[1], "POST", "/app/restart", {})[0] == 400
    finally:
        srv2.shutdown(); srv2.server_close()


def test_demo_mode_has_collection_switched_off(tmp_path):
    app, _ = make_app(tmp_path, collection=False)
    srv = serve(app); port = srv.server_address[1]
    try:
        h = get(port, "/")[2]
        assert "Collection is turned off in demo mode." in h
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "50"})[1]["location"] == "/?notice=disabled"
    finally:
        srv.shutdown(); srv.server_close()


# ------------------------------------------------------------------ branding
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


def test_logo_is_downloaded_validated_and_cached(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url); return PNG
    got = branding.ensure_logo(tmp_path, fetch=fetch)
    assert got and got.read_bytes() == PNG and calls == [branding.LOGO_URL] and branding.logo_available(tmp_path)
    branding.ensure_logo(tmp_path, fetch=fetch)
    assert len(calls) == 1                                            # cached, not fetched again
    assert branding.LOGO_URL.startswith("https://www.groxaai.com/")


def test_non_png_or_failed_download_falls_back_to_text(tmp_path):
    assert branding.ensure_logo(tmp_path, fetch=lambda u: b"<html>blocked</html>") is None and not branding.logo_available(tmp_path)
    def boom(u):
        raise OSError("offline")
    assert branding.ensure_logo(tmp_path, fetch=boom) is None
    assert not list(tmp_path.glob("*.tmp"))
    app, _ = make_app(tmp_path)
    h = get_html(app)
    assert "Powered by <b>Groxa AI</b>" in h and "<img" not in h[h.index('class="powered"'):h.index("</a>", h.index('class="powered"'))]


def get_html(app):
    srv = serve(app)
    try:
        return get(srv.server_address[1], "/")[2]
    finally:
        srv.shutdown(); srv.server_close()


def test_logo_is_shown_and_served_when_present(tmp_path):
    static = tmp_path / "static"; static.mkdir()
    (static / branding.LOGO_FILE).write_bytes(PNG)
    app, _ = make_app(tmp_path)
    srv = serve(app); port = srv.server_address[1]
    try:
        h = get(port, "/")[2]
        assert f'<img src="/static/{branding.LOGO_FILE}"' in h and 'href="https://www.groxaai.com' in h
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", f"/static/{branding.LOGO_FILE}")
        r = conn.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == "image/png" and r.read() == PNG
        conn.close()
    finally:
        srv.shutdown(); srv.server_close()
        views.set_logo(None)
    app2, _ = make_app(tmp_path / "none") if (tmp_path / "none").mkdir() is None else (None, None)
    srv2 = serve(app2)
    try:
        assert get(srv2.server_address[1], f"/static/{branding.LOGO_FILE}")[0] == 404
    finally:
        srv2.shutdown(); srv2.server_close()


# ------------------------------------------------------------------ details page sections and demo data
def test_details_page_shows_extracted_sections_or_not_available(tmp_path):
    desc = ("Acme builds made-up banking tools for people who run branches in many places.\n\n"
            "Key Responsibilities:\n- Build services\n- Review code\n\nQualifications:\n- Python\n\nBenefits:\n- Tea\n\n"
            "Candidates need 4+ years of experience with payments.")
    from tests.factories import make_record
    rich, plain = make_record(6001, "Rich job", description=desc), make_record(6002, "Plain job", description="Short text.")
    with running(tmp_path, records=[rich, plain], second_run=[]) as (port, _):
        h = get(port, "/job/linkedin-6001")[2]
        assert "<li>Build services</li>" in h and "<li>Review code</li>" in h and "<li>Python</li>" in h
        assert "Candidates need 4+ years of experience with payments." in h and "Acme builds made-up banking tools" in h
        p = get(port, "/job/linkedin-6002")[2]
        assert "<li>" not in p[p.index("Key responsibilities"):p.index("Recruiter and contact</th>")]
        assert p[p.index("Key responsibilities"):p.index("Recruiter and contact</th>")].count("Not available") == 3
        assert 'Open Original Job' in p


def test_demo_data_builds_and_covers_scopes_industries_and_work_modes(tmp_path):
    from dashboard import viewmodel as vm
    from dashboard.demo import build_demo
    build_demo(tmp_path)
    history = JsonJobHistory(tmp_path / "job_history.json")
    rows = vm.build_rows(history.list_jobs(), {}, None)
    f = lambda **q: vm.apply_filters(rows, vm.Filters.from_query(q), NOW.replace(year=2026) + timedelta(days=0))
    assert {r.scope for r in rows} == {"india", "outside", "unknown"}
    assert {"IT & Software", "Healthcare & Pharma", "Banking & Finance", "Unknown"} <= {r.industry for r in rows}
    assert {"Hybrid", "On-site", "Remote"} <= {r.work_mode for r in rows}
    assert len(f(scope="all")) == len(rows) and 0 < len(f(scope="outside")) < len(rows)


# ------------------------------------------------------------------ origin check (regression: "Request blocked")
def test_pages_send_a_referrer_policy_that_lets_browsers_send_a_real_origin(tmp_path):
    """Root cause of the 'Request blocked' error: 'Referrer-Policy: no-referrer' makes browsers send 'Origin: null'
    on form posts, which the same-origin check (correctly) refused. Same-origin forms must carry the real origin."""
    app, _ = make_app(tmp_path)
    srv = serve(app)
    try:
        _, headers, _ = get(srv.server_address[1], "/")
        assert headers["referrer-policy"] == "same-origin"
    finally:
        srv.shutdown(); srv.server_close()


def test_run_collection_form_post_as_a_browser_sends_it(tmp_path):
    app, mgr = make_app(tmp_path)
    srv = serve(app); port = srv.server_address[1]
    try:
        for host in ("127.0.0.1", "localhost"):
            origin = f"http://{host}:{port}"
            same = {"Host": f"{host}:{port}", "Origin": origin, "Referer": origin + "/", "Sec-Fetch-Site": "same-origin"}
            status, headers, _ = call(port, "POST", "/collection/run", {"scope": "india", "count": "50"}, headers=same)
            assert status == 303 and headers["location"] == "/?notice=started", host
        # a browser that sends only Origin or only Sec-Fetch-Site is accepted too
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "50"}, headers={"Origin": f"http://127.0.0.1:{port}"})[0] == 303
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "50"}, headers={"Sec-Fetch-Site": "same-origin"})[0] == 303
        assert mgr.status()["state"] == SUCCEEDED and len(app.history.list_jobs()) == 1
    finally:
        srv.shutdown(); srv.server_close()


def test_cross_site_null_origin_and_wrong_port_posts_are_still_refused(tmp_path):
    app, mgr = make_app(tmp_path)
    srv = serve(app); port = srv.server_address[1]
    try:
        bad = [{"Origin": "http://evil.example"}, {"Origin": "null"}, {"Origin": f"http://127.0.0.1:{port + 1}"},
               {"Referer": "http://evil.example/page"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
               {"Sec-Fetch-Site": "cross-site", "Origin": f"http://127.0.0.1:{port}"}]       # browser metadata wins over a forged Origin
        for headers in bad:
            for path, form in (("/collection/run", {"scope": "india", "count": "50"}), ("/app/restart", {}), ("/job/linkedin-1/save", {"saved": "1"})):
                assert call(port, "POST", path, form, headers=headers)[0] == 403, (headers, path)
        assert mgr.status()["state"] == IDLE and app.history.list_jobs() == []
    finally:
        srv.shutdown(); srv.server_close()
