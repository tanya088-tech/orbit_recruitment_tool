"""Recruiter-chosen number of vacancies: "N" means the N most recent postings, shown on their own."""
import json
from pathlib import Path

from config import locations as loc
from config import settings
from dashboard.collection import PARTIAL, SUCCEEDED, CollectionManager, build_command, parse_target
from tests.test_collection_and_controls import make_app, raw_job, serve
from tests.test_collection_and_controls import manager as make_manager
from tests.test_dashboard_server import call, get

PLACES = loc.search_locations("india")
KEY = lambda i: f"linkedin-{7000000000 + i}"


class Universe:
    """A fake scraper over listings per place, NEWEST FIRST. Like run_collect.py it honours --max-jobs-per-search,
    --skip-ids-file and --count-known (known jobs count toward the cap and are listed in run.latest_ids)."""

    def __init__(self, out_dir, listings, code_for=None, lines_for=None):
        self.out, self.listings, self.calls = Path(out_dir), listings, []
        self.code_for, self.lines_for = code_for or {}, lines_for or {}

    def __call__(self, cmd, on_line, cwd, timeout_s):
        place = cmd[cmd.index("--locations") + 1]
        cap = int(cmd[cmd.index("--max-jobs-per-search") + 1])
        count_known = "--count-known" in cmd
        exclude = set(Path(cmd[cmd.index("--exclude-ids-file") + 1]).read_text(encoding="utf-8").split()) if "--exclude-ids-file" in cmd else set()
        skip = set()
        if "--skip-ids-file" in cmd:
            skip = set(Path(cmd[cmd.index("--skip-ids-file") + 1]).read_text(encoding="utf-8").split())
        n = len(self.calls)
        fetched, latest, taken = [], [], 0
        for j in self.listings.get(place, []):
            if cap and taken >= cap:
                break
            if j["job_id"] in skip:
                if count_known and cap and j["job_id"] not in exclude:
                    latest.append(j["job_id"]); taken += 1
                continue
            fetched.append(j); taken += 1
            if count_known:
                latest.append(j["job_id"])
        self.calls.append({"place": place, "cap": cap, "count_known": count_known, "fetched": len(fetched), "skipped": len(skip)})
        for ln in self.lines_for.get(n, []):
            on_line(ln)
        path = self.out / f"jobs_linkedin_20261008_2000{n:02d}.json"
        path.write_text(json.dumps({"run": {"latest_ids": latest}, "jobs": fetched}), encoding="utf-8")
        on_line(f"Saved {len(fetched)} jobs to {path}")
        return self.code_for.get(n, 0)


def ids(start, count, **kw):
    return [raw_job(i, **kw) for i in range(start, start + count)]


def run(tmp_path, listings, target, **kw):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    uni = Universe(out, listings, **kw)
    mgr, hist = make_manager(tmp_path, uni)
    ok, msg = mgr.start("india", target)
    assert ok, msg
    return mgr, hist, uni


# ---- the number ---------------------------------------------------------------------------------------------
def test_vacancy_count_validation():
    cases = [("50", 50), ("100", 100), ("200", 200), (" 75 ", 75), ("1", 1), (str(settings.COLLECTION_TARGET_MAX), settings.COLLECTION_TARGET_MAX),
             ("0", None), ("-5", None), ("abc", None), ("", None), (None, None), ("5.5", None), ("1e3", None),
             (str(settings.COLLECTION_TARGET_MAX + 1), None), ("50; rm -rf /", None), ("٥٠", None)]
    for value, want in cases:
        assert parse_target(value) == want, value


def test_quick_picks_are_50_100_200():
    assert tuple(settings.COLLECTION_TARGET_CHOICES) == (50, 100, 200)


def test_manager_refuses_bad_targets_and_starts_nothing(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: ids(1, 5)})
    mgr, _ = make_manager(tmp_path, uni)
    for bad in (0, -1, settings.COLLECTION_TARGET_MAX + 1, "50", 5.0, True):
        assert not mgr.start("india", bad)[0]
    assert uni.calls == [] and mgr.status()["state"] == "idle"


def test_command_asks_for_the_latest_n_and_counts_known_jobs(tmp_path):
    known = Path("/tmp/k.txt")
    cmd = build_command("india", Path("/tmp/o"), ["Pune, India"], known, max_jobs=20, count_known=True)
    assert cmd[cmd.index("--max-jobs-per-search") + 1] == "20" and "--count-known" in cmd
    assert "--count-known" not in build_command("india", Path("/tmp/o"), ["Pune, India"], known, max_jobs=20)
    assert "--count-known" not in build_command("india", Path("/tmp/o"), ["Pune, India"], None, max_jobs=20, count_known=True)   # needs the skip list
    assert build_command("india", Path("/tmp/o"))[build_command("india", Path("/tmp/o")).index("--max-jobs-per-search") + 1] == str(settings.COLLECTION_MAX_JOBS_PER_SEARCH)


# ---- exactly the N most recent -------------------------------------------------------------------------------
def test_five_requested_gives_exactly_the_five_most_recent_postings(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 400)}, 5)          # 1 is the newest listing
    st = mgr.status()
    assert st["result_keys"] == [KEY(i) for i in range(1, 6)] and st["collected_unique"] == 5
    assert len(hist.list_jobs()) == 5 and st["stop_reason"] == "target_reached" and len(uni.calls) == 1
    assert uni.calls[0]["cap"] == 5 and uni.calls[0]["count_known"] and "Target reached" in st["message"]


def test_postings_already_in_the_history_still_count_as_part_of_the_latest_n(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    mgr, hist = make_manager(tmp_path, Universe(out, {PLACES[0]: ids(1, 3)}))
    mgr.start("india", 3)                                                 # 1-3 are collected earlier
    assert len(hist.list_jobs()) == 3
    listings = {PLACES[0]: ids(1, 40)}
    uni = Universe(out, listings)
    m2 = CollectionManager(hist, tmp_path, output_dir=out, runner=uni, now_fn=mgr.now, background=False)
    m2.start("india", 5)
    st = m2.status()
    assert st["result_keys"] == [KEY(i) for i in range(1, 6)]            # the 5 newest, NOT 3 old + the next 5
    assert (st["collected_unique"], st["new_added"], st["already_had"]) == (5, 2, 3)
    assert uni.calls[0]["fetched"] == 2 and len(hist.list_jobs()) == 5     # only the 2 missing ones were fetched and stored


def test_result_continues_into_the_next_place_only_when_needed(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 3), PLACES[1]: ids(100, 30), PLACES[2]: ids(200, 30)}, 5)
    st = mgr.status()
    assert [c["cap"] for c in uni.calls] == [5, 2] and len(uni.calls) == 2
    assert st["result_keys"] == [KEY(1), KEY(2), KEY(3), KEY(100), KEY(101)] and st["stop_reason"] == "target_reached"


def test_the_same_posting_in_two_places_counts_once(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 4), PLACES[1]: ids(1, 4) + ids(50, 10)}, 6)
    st = mgr.status()
    assert len(set(st["result_keys"])) == len(st["result_keys"]) == 6
    assert st["result_keys"] == [KEY(i) for i in (1, 2, 3, 4, 50, 51)] and len(hist.list_jobs()) == 6


def test_a_repost_under_another_id_resolves_to_the_stored_vacancy(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    existing = raw_job(1, job_url="https://www.linkedin.com/jobs/view/1")
    mgr, hist = make_manager(tmp_path, Universe(out, {PLACES[0]: [existing]}))
    mgr.start("india", 1)
    twin = raw_job(900, job_url=existing["job_url"])
    uni = Universe(out, {PLACES[0]: [twin] + ids(10, 8)})
    m2 = CollectionManager(hist, tmp_path, output_dir=out, runner=uni, now_fn=mgr.now, background=False)
    m2.start("india", 3)
    st = m2.status()
    assert st["result_keys"][0] == KEY(1) and len(set(st["result_keys"])) == len(st["result_keys"]) <= 3
    assert len(hist.list_jobs()) <= 3 + 1                                  # the twin did not become a second copy


# ---- fewer available than requested --------------------------------------------------------------------------
def test_results_exhausted_reports_the_actual_count_and_why(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 20), PLACES[3]: ids(100, 17)}, 100)
    st = mgr.status()
    assert len(uni.calls) == len(PLACES) and st["state"] == SUCCEEDED and st["stop_reason"] == "exhausted"
    assert st["target"] == 100 and st["collected_unique"] == 37 == len(st["result_keys"])
    assert "37 of 100" in st["message"] and "exhausted" in st["message"].lower()


# ---- could not continue ---------------------------------------------------------------------------------------
def test_blocked_run_keeps_what_it_had_and_shows_no_red_block_message(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 10), PLACES[1]: ids(50, 10)}, 100, code_for={1: 2})
    st = mgr.status()
    assert st["state"] == PARTIAL and st["stop_reason"] == "blocked" and st["message"].startswith("Collection finished")
    assert st["collected_unique"] == len(st["result_keys"]) >= 10 and len(hist.list_jobs()) >= 10
    from dashboard import views
    from tests.factories import NOW
    html = views._collection_panel({"status": st, "enabled": True, "default_scope": "india"}, "/", NOW)
    assert "refused" not in html.lower() and "data-collect-error" not in html and "HTTP 429" not in html.split("<details")[0]


def test_interrupted_run_is_partial_with_a_count(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 10), PLACES[1]: ids(50, 10)}, 100,
                         lines_for={0: ["2026-10-08 | WARNING | Interrupted by user"]})
    st = mgr.status()
    assert st["state"] == PARTIAL and st["stop_reason"] == "interrupted" and len(uni.calls) == 1
    assert st["collected_unique"] == 10 and "10 of 100" in st["message"]


def test_a_failing_place_does_not_stop_the_count_and_is_reported(tmp_path):
    mgr, hist, uni = run(tmp_path, {PLACES[0]: ids(1, 3), PLACES[1]: ids(50, 3)}, 100, code_for={0: 1})
    st = mgr.status()
    assert st["collected_unique"] == 3 and st["stop_reason"] == "incomplete" and "could not be searched" in st["message"]


# ---- existing behaviour is untouched ---------------------------------------------------------------------------
def test_without_a_target_everything_is_collected_as_before(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: ids(1, 12), PLACES[2]: ids(50, 8)})
    mgr, hist = make_manager(tmp_path, uni)
    assert mgr.start("india")[0]
    st = mgr.status()
    assert st["target"] is None and st["result_keys"] == [] and len(hist.list_jobs()) == 20 and st["state"] == SUCCEEDED
    assert all(c["cap"] == settings.COLLECTION_MAX_JOBS_PER_SEARCH and not c["count_known"] for c in uni.calls) and len(uni.calls) == len(PLACES)


def test_the_result_survives_a_restart_and_history_is_never_trimmed(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    mgr, hist = make_manager(tmp_path, Universe(out, {PLACES[0]: ids(1, 30)}))
    mgr.start("india")                                                    # 30 jobs in the history from a normal run
    uni = Universe(out, {PLACES[0]: ids(1, 30)})
    m2 = CollectionManager(hist, tmp_path, output_dir=out, runner=uni, now_fn=mgr.now, background=False)
    m2.start("india", 5)
    again = CollectionManager(hist, tmp_path, output_dir=out, runner=lambda *a: 0, now_fn=mgr.now, background=False)
    st = again.status()
    assert (st["target"], st["collected_unique"], st["stop_reason"]) == (5, 5, "target_reached") and len(st["result_keys"]) == 5
    assert len(hist.list_jobs()) == 30 and uni.calls[0]["fetched"] == 0       # all 5 were already held: nothing fetched, nothing lost


# ---- the dashboard ---------------------------------------------------------------------------------------------
def test_panel_has_an_optional_number_field_with_the_three_quick_picks(tmp_path):
    app, mgr = make_app(tmp_path)
    srv = serve(app)
    try:
        h = get(srv.server_address[1], "/")[2]
        assert 'name="count"' in h and 'id="collect-count"' in h and "Number of vacancies (optional)" in h and " required" not in h.split('id="collect-count"')[1].split(">")[0]
        for n in (50, 100, 200):
            assert f'<option value="{n}">' in h
        assert mgr.status()["state"] == "idle" and "data-result-banner" not in h
    finally:
        srv.shutdown(); srv.server_close()


def test_nothing_is_scraped_until_a_valid_number_is_submitted(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: ids(1, 60)})
    app, mgr = make_app(tmp_path, runner=uni)
    srv = serve(app); port = srv.server_address[1]
    try:
        for form in ({"scope": "india", "count": "0"},
                     {"scope": "india", "count": "abc"}, {"scope": "india", "count": str(settings.COLLECTION_TARGET_MAX + 1)}):
            status, headers, _ = call(port, "POST", "/collection/run", form)
            assert status == 303 and headers["location"] == "/?notice=bad_count", form
        assert uni.calls == [] and mgr.status()["state"] == "idle"
        assert "whole number from 1 to" in get(port, "/?notice=bad_count")[2]
        status, headers, _ = call(port, "POST", "/collection/run", {"scope": "india", "count": "40"})
        assert headers["location"] == "/?notice=started" and uni.calls[0]["cap"] == 40
    finally:
        srv.shutdown(); srv.server_close()


def test_dashboard_lists_exactly_the_requested_vacancies_and_can_show_everything(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: ids(1, 60)})
    app, mgr = make_app(tmp_path, runner=uni)
    srv = serve(app); port = srv.server_address[1]
    try:
        call(port, "POST", "/collection/run", {"scope": "india", "count": "50"})         # an earlier, larger collection: 50 in history
        mgr2 = CollectionManager(app.history, tmp_path, output_dir=out, runner=Universe(out, {PLACES[0]: ids(1, 60)}),
                                 now_fn=mgr.now, background=False)
        app.collection = mgr2
        call(port, "POST", "/collection/run", {"scope": "india", "count": "5"})
        h = get(port, "/")[2]
        assert h.count('class="job-row"') == 5 or h.count("/job/linkedin-") >= 5
        assert "Showing 1 to 5 of 5 vacancies" in h and "data-result-banner" in h and "Show all collected jobs" in h
        assert "<b data-count-requested>5</b>" in h and "<b data-count-collected>5</b>" in h
        assert "<b data-count-status>Target reached</b>" in h
        allh = get(port, "/?view=all&scope=all")[2]
        assert "of 50 vacancies" in allh and "Show only my last request" in allh
        assert '"result_keys"' not in get(port, "/collection/status")[2] and json.loads(get(port, "/collection/status")[2])["collected_unique"] == 5
        for k in range(6, 9):
            assert f"linkedin-{7000000000 + k}" not in h                                    # older postings are not listed
    finally:
        srv.shutdown(); srv.server_close()


# ---- the real LinkedIn source (fake pages, no network) -----------------------------------------------------------
def test_linkedin_source_takes_the_n_newest_listings_counting_known_ones():
    from collectors.collector import Collector
    from collectors.linkedin.source import LinkedInSource
    from models.job import SearchParams
    from tests.test_collection_efficiency import PagedFake
    ident = lambda i: str(4000000000 + i)

    def go(skip, exclude=frozenset(), count_known=True, n=5):
        fake = PagedFake(total=60, per_page=25)
        params = SearchParams(keywords="bank", location="India", days=30, max_jobs=n, max_pages=3,
                              count_known=count_known, exclude_ids=exclude)
        return Collector(LinkedInSource(fake)).run([params], skip_ids={ident(i) for i in skip}), fake

    res, fake = go(skip=[1, 2, 3])
    assert res.stats.latest_ids == [ident(i) for i in range(1, 6)]                  # the 5 newest listings, known ones included
    assert [j.job_id for j in res.jobs] == [ident(4), ident(5)] and fake.detail_ids == [ident(4), ident(5)]
    res, _ = go(skip=[1, 2, 3], exclude=frozenset({ident(1), ident(2), ident(3)}))   # already counted elsewhere: not counted again
    assert res.stats.latest_ids == [ident(i) for i in range(4, 9)]
    res, _ = go(skip=[1, 2, 3], count_known=False)                                  # the old behaviour: N NEW jobs
    assert [j.job_id for j in res.jobs] == [ident(i) for i in range(4, 9)] and res.stats.latest_ids == []


# ---- "posted within" window and newest-first order ----------------------------------------------------------------
def test_a_request_covers_the_last_24_hours_unless_another_window_is_chosen(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni_cmds = []

    def spy(cmd, on_line, cwd, timeout_s):
        uni_cmds.append(cmd)
        return Universe(out, {})(cmd, on_line, cwd, timeout_s)
    mgr, _ = make_manager(tmp_path, spy)
    mgr.start("india", 5)
    assert uni_cmds[0][uni_cmds[0].index("--days") + 1] == "1" and mgr.status()["window"] == "24h"
    assert "last 24 hours" in mgr.status()["message"]            # "Collected 0 of 5 requested vacancies posted in the last 24 hours"
    mgr.start("india", 5, "7d")
    assert uni_cmds[len(PLACES)][uni_cmds[len(PLACES)].index("--days") + 1] == "7" and mgr.status()["window"] == "7d"
    assert not mgr.start("india", 5, "forever")[0]
    mgr.start("india", None, "7d")                                # no number: the chosen period still applies
    assert uni_cmds[-1][uni_cmds[-1].index("--days") + 1] == "7" and mgr.status()["window"] == "7d"


def test_form_offers_the_window_with_24_hours_selected_and_refuses_unknown_ones(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: ids(1, 5)})
    app, mgr = make_app(tmp_path, runner=uni)
    srv = serve(app); port = srv.server_address[1]
    try:
        h = get(port, "/")[2]
        assert 'name="window"' in h and '<option value="24h" selected>Last 24 hours</option>' in h and "Last 30 days" in h
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "5", "window": "bogus"})[1]["location"] == "/?notice=bad"
        assert uni.calls == []
        call(port, "POST", "/collection/run", {"scope": "india", "count": "5", "window": "3d"})
        assert mgr.status()["window"] == "3d" and "last 3 days" in get(port, "/")[2]
    finally:
        srv.shutdown(); srv.server_close()


def test_the_requested_vacancies_are_listed_most_recently_posted_first(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    jobs = [raw_job(1, title="Posted twenty hours ago", posted_age_text="20 hours ago"),
            raw_job(2, title="Posted two hours ago", posted_age_text="2 hours ago"),
            raw_job(3, title="Posted ten hours ago", posted_age_text="10 hours ago")]       # LinkedIn's order is not trusted
    app, mgr = make_app(tmp_path, runner=Universe(out, {PLACES[0]: jobs}))
    srv = serve(app); port = srv.server_address[1]
    try:
        call(port, "POST", "/collection/run", {"scope": "india", "count": "3"})
        h = get(port, "/")[2]
        order = [h.index(t) for t in ("Posted two hours ago", "Posted ten hours ago", "Posted twenty hours ago")]
        assert order == sorted(order) and "Showing 1 to 3 of 3 vacancies" in h and "last 24 hours" in h
    finally:
        srv.shutdown(); srv.server_close()


# ---- only GCC / BFSI openings ---------------------------------------------------------------------------------
def shop(n):
    return raw_job(n, title="Shop Assistant", company="Happy Shoes", industries="Retail", description="Sell shoes to walk-in customers.")


def test_only_gcc_or_bfsi_postings_are_kept_and_the_count_is_still_met(tmp_path):
    assert settings.COLLECTION_ONLY_GCC_BFSI is True
    mixed = []
    for i in range(1, 13):                       # newest first: two shop jobs for every bank job
        mixed.append(raw_job(i) if i % 3 == 0 else shop(i))
    mgr, hist, uni = run(tmp_path, {PLACES[0]: mixed}, 3)
    st = mgr.status()
    kept = {j["record"]["job_id"] for j in hist.list_jobs()}
    assert kept == {str(7000000000 + i) for i in (3, 6, 9)}                  # three bank jobs; no shop job stored
    assert st["collected_unique"] == 3 and st["stop_reason"] == "target_reached"
    assert st["skipped_not_relevant"] >= 1 and "did not look like GCC or BFSI" in st["message"]
    assert all(j["record"]["potential_bfsi"] or j["record"]["potential_gcc"] for j in hist.list_jobs())
    assert len(uni.calls) > 1                                               # it searched again to make up the count
    fetched_ids = [c["fetched"] for c in uni.calls]
    assert sum(fetched_ids) <= 12                                           # a rejected posting is not fetched a second time


def test_nothing_relevant_stores_nothing_and_never_looks_like_success(tmp_path):
    mgr, hist, _ = run(tmp_path, {PLACES[0]: [shop(i) for i in range(1, 6)]}, 3)
    st = mgr.status()
    assert hist.list_jobs() == [] and st["collected_unique"] == 0 and st["stop_reason"] != "target_reached"
    assert "Collected 0 of 3" in st["message"] and "did not look like GCC or BFSI" in st["message"]


def test_the_gate_can_be_switched_off_and_existing_history_is_untouched(tmp_path):
    settings.COLLECTION_ONLY_GCC_BFSI = False
    try:
        mgr, hist, _ = run(tmp_path, {PLACES[0]: [shop(1), shop(2), raw_job(3)]}, 3)
        assert len(hist.list_jobs()) == 3 and mgr.status()["collected_unique"] == 3
    finally:
        settings.COLLECTION_ONLY_GCC_BFSI = True


def test_old_history_jobs_that_fail_the_strict_rules_do_not_count_towards_the_requested_number(tmp_path):
    """Saved under looser rules, hidden by the dashboard: they must not use up part of "N vacancies" (the page showed 2 of 10)."""
    out = tmp_path / "out"; out.mkdir()
    settings.COLLECTION_ONLY_GCC_BFSI = False                      # how they got into the history in the first place
    try:
        mgr, hist = make_manager(tmp_path, Universe(out, {PLACES[0]: [shop(1), shop(2), shop(3), raw_job(4)]}))
        mgr.start("india", 4)
    finally:
        settings.COLLECTION_ONLY_GCC_BFSI = True
    assert len(hist.list_jobs()) == 4
    before = json.dumps(hist.list_jobs(), sort_keys=True, default=str)
    listings = {PLACES[0]: [shop(1), shop(2), shop(3), raw_job(4)] + [raw_job(i) for i in range(5, 30)]}
    uni = Universe(out, listings)
    m2 = CollectionManager(hist, tmp_path, output_dir=out, runner=uni, now_fn=mgr.now, background=False)
    m2.start("india", 3)
    st = m2.status()
    assert st["result_keys"] == [KEY(4), KEY(5), KEY(6)]            # the three newest QUALIFYING postings, not 1-3 (shop jobs)
    assert st["collected_unique"] == 3 and st["stop_reason"] == "target_reached"
    assert len(hist.list_jobs()) >= 6 and all(k in {e["key"] for e in hist.list_jobs()} for k in (KEY(1), KEY(2), KEY(3)))   # nothing deleted
    from dashboard import viewmodel as vm
    shown = vm.build_rows(hist.list_jobs(), {}, None, only_gcc_bfsi=True)
    assert {r.key for r in shown if r.key in st["result_keys"]} == set(st["result_keys"])      # every counted vacancy is visible
