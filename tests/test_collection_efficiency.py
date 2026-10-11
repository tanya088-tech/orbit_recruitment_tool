"""Phase 2: skipping already-collected jobs, pagination, per-page progress, interrupt handling.

No test touches the network. Pagination tests use a fake LinkedIn that follows the contract we ASSUME
(and verify_pagination.py checks live): `start` is a zero-based result offset and a page returns up to
`per_page` listings. That assumption is stated here because it has not been confirmed against LinkedIn.
"""
import json
from pathlib import Path

from collectors.collector import Collector
from collectors.linkedin.source import LinkedInSource
from config import settings
from dashboard.collection import PARTIAL, SUCCEEDED, CollectionManager, build_command
from models.job import SearchParams
from store.json_store import JsonJobHistory
from tests.factories import NOW
from tests.test_collection_and_controls import fake_runner, manager, raw_job
from tests.test_collector import read

CARD = """<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:{id}">
<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/{id}"></a><div class="base-search-card__info">
<h3 class="base-search-card__title">Job {id}</h3><h4 class="base-search-card__subtitle"><a class="hidden-nested-link" href="#">Acme</a></h4>
<div class="base-search-card__metadata"><span class="job-search-card__location">Pune, India</span>
<time class="job-search-card__listdate" datetime="2026-10-09">1 day ago</time></div></div></div></li>"""


class PagedFake:
    """A LinkedIn that holds `total` listings (ids 1..total) and returns `per_page` per request from offset `start`."""
    def __init__(self, total=60, per_page=10):
        self.total, self.per_page = total, per_page
        self.search_starts, self.detail_ids = [], []

    def get(self, url, params=None):
        if "seeMoreJobPostings" in url:
            start = params["start"]
            self.search_starts.append(start)
            ids = range(start + 1, min(start + self.per_page, self.total) + 1)
            return "<ul>" + "".join(CARD.format(id=4000000000 + i) for i in ids) + "</ul>"
        self.detail_ids.append(url.rsplit("/", 1)[-1])
        return read("job_detail_ld.html")


def collect(client, max_pages=40, skip_ids=None, days=30):
    params = SearchParams(keywords="bank", location="India", days=days, max_pages=max_pages)
    return Collector(LinkedInSource(client)).run([params], skip_ids=skip_ids)


# ------------------------------------------------------------------ skipping known jobs
def test_known_job_ids_are_not_fetched_again():
    known = {str(4000000000 + i) for i in range(1, 6)}
    fake = PagedFake(total=10, per_page=10)
    res = collect(fake, max_pages=1, skip_ids=set(known))
    assert len(res.jobs) == 5 and res.stats.skipped_duplicate == 5
    assert not known & set(fake.detail_ids) and len(fake.detail_ids) == 5      # no detail-page request for a known job


def test_without_the_option_nothing_is_skipped_as_before():
    fake = PagedFake(total=10, per_page=10)
    res = collect(fake, max_pages=1)
    assert len(res.jobs) == 10 and res.stats.skipped_duplicate == 0 and len(fake.detail_ids) == 10
    assert len(collect(PagedFake(10, 10), max_pages=1, skip_ids=set()).jobs) == 10
    assert len(collect(PagedFake(10, 10), max_pages=1, skip_ids=None).jobs) == 10


def test_run_collect_accepts_a_skip_ids_file():
    import run_collect
    args = run_collect.build_parser().parse_args(["--skip-ids-file", "x.txt"])
    assert args.skip_ids_file == "x.txt" and run_collect.build_parser().parse_args([]).skip_ids_file is None


def test_dashboard_passes_the_history_ids_to_every_place_and_skips_nothing_when_disabled(tmp_path, monkeypatch=None):
    out = tmp_path / "out"; out.mkdir()
    seen = []
    def runner(cmd, on_line, cwd, timeout_s):
        file = Path(cmd[cmd.index("--skip-ids-file") + 1]) if "--skip-ids-file" in cmd else None
        seen.append(set(file.read_text().split()) if file else None)
        path = out / f"jobs_linkedin_20261010_1000{len(seen):02d}.json"
        jobs = [raw_job(len(seen))] if len(seen) <= 2 else []
        path.write_text(json.dumps({"run": {}, "jobs": jobs}))
        on_line(f"Saved {len(jobs)} jobs to {path}")
        return 0
    h = JsonJobHistory(tmp_path / "job_history.json")
    h.ingest([raw_job(99)], now=NOW)                                      # a job that was already in the history
    m = CollectionManager(h, tmp_path, output_dir=out, runner=runner, now_fn=lambda: NOW, background=False)
    m.start("india")
    assert seen[0] == {"7000000099"}                                      # place 1 skips what the history holds
    assert seen[1] == {"7000000099", "7000000001"}                        # place 2 also skips what place 1 just added
    assert m.status()["state"] == SUCCEEDED and len(h.list_jobs()) == 3
    assert len(h.runs()) == 3                                             # 1 earlier run + 2 places with jobs; empty places add no empty run


def test_skip_option_can_be_switched_off(tmp_path):
    original = settings.COLLECTION_SKIP_KNOWN_IDS
    settings.COLLECTION_SKIP_KNOWN_IDS = False
    try:
        cmds = []
        def runner(cmd, on_line, cwd, timeout_s):
            cmds.append(cmd); return 1
        m, _ = manager(tmp_path, runner)
        m.start("india")
        assert cmds and all("--skip-ids-file" not in c for c in cmds) and not (tmp_path / "known_job_ids.txt").exists()
    finally:
        settings.COLLECTION_SKIP_KNOWN_IDS = original
    assert "--skip-ids-file" not in build_command("india", Path("/tmp/o"))
    assert build_command("india", Path("/tmp/o"), ["Pune, India"], Path("/tmp/k.txt"))[-2:] == ["--skip-ids-file", "/tmp/k.txt"]


# ------------------------------------------------------------------ pagination
def test_default_pagination_is_unchanged_start_equals_page_times_25():
    assert settings.LINKEDIN_PAGINATION == "fixed"
    fake = PagedFake(total=100, per_page=10)
    collect(fake, max_pages=4)
    assert fake.search_starts == [0, 25, 50, 75]


def test_when_a_page_returns_10_the_fixed_step_skips_listings_and_returned_mode_does_not():
    fixed = PagedFake(total=100, per_page=10)
    got_fixed = {j.job_id for j in collect(fixed, max_pages=4).jobs}
    assert len(got_fixed) == 40 and fixed.search_starts == [0, 25, 50, 75]    # 40 collected, but they cover offsets 0-9, 25-34 ...
    settings.LINKEDIN_PAGINATION = "returned"
    try:
        returned = PagedFake(total=100, per_page=10)
        got = {j.job_id for j in collect(returned, max_pages=4).jobs}
        assert returned.search_starts == [0, 10, 20, 30]
        assert got == {str(4000000000 + i) for i in range(1, 41)}              # the first 40 listings, none skipped
        assert got != got_fixed
    finally:
        settings.LINKEDIN_PAGINATION = "fixed"


def test_returned_mode_follows_25_per_page_and_stops_at_the_end_or_when_stuck():
    settings.LINKEDIN_PAGINATION = "returned"
    try:
        big = PagedFake(total=60, per_page=25)
        res = collect(big, max_pages=40)
        assert big.search_starts == [0, 25, 50, 60] and len(res.jobs) == 60    # follows the 25-listing pages, then the short last page, then the empty one

        class Stuck(PagedFake):                                                # ignores the offset: always the same page
            def get(self, url, params=None):
                if "seeMoreJobPostings" in url:
                    self.search_starts.append(params["start"])
                    return "<ul>" + "".join(CARD.format(id=4000000000 + i) for i in range(1, 6)) + "</ul>"
                return read("job_detail_ld.html")
        stuck = Stuck()
        assert len(collect(stuck, max_pages=40).jobs) == 5 and len(stuck.search_starts) == 2   # stops instead of looping 40 times
    finally:
        settings.LINKEDIN_PAGINATION = "fixed"


def test_verify_pagination_script_exists_and_makes_only_three_requests():
    import ast
    src = Path(__file__).resolve().parent.parent.joinpath("verify_pagination.py").read_text()
    ast.parse(src)
    assert "(0, 10, 25)" in src


# ------------------------------------------------------------------ progress and interruption
def test_progress_shows_place_and_page_and_resets_for_each_place(tmp_path):
    seen = []
    def runner(cmd, on_line, cwd, timeout_s):
        on_line("collectors.linkedin.source | Search page 1: 10 listings")
        on_line("collectors.linkedin.source | Search page 7: 10 listings")
        seen.append(m.status())
        return 1
    m, _ = manager(tmp_path, runner)
    m.start("india")
    assert seen[0]["current_page"] == 7 and seen[0]["current_search"] == "India" and seen[0]["search_done"] == 0
    assert seen[1]["current_search"].startswith("Bengaluru") and seen[1]["search_done"] == 1 and seen[1]["current_page"] == 7


def test_a_scraper_interrupted_by_the_user_stops_the_run_and_keeps_what_it_saved(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    calls = []
    def runner(cmd, on_line, cwd, timeout_s):
        calls.append(cmd)
        path = out / "jobs_linkedin_20261010_190744.json"
        path.write_text(json.dumps({"run": {}, "jobs": [raw_job(1), raw_job(2)]}))
        on_line("collectors.collector | Interrupted by user - saving what was collected so far")
        on_line(f"Saved 2 jobs to {path}")
        return 0                                                              # run_collect exits normally after Ctrl+C
    m = CollectionManager(JsonJobHistory(tmp_path / "job_history.json"), tmp_path, output_dir=out, runner=runner,
                          now_fn=lambda: NOW, background=False)
    m.start("india")
    st = m.status()
    assert len(calls) == 1                                                    # it did not carry on to the next place
    assert st["state"] == PARTIAL and "Interrupted" in st["message"] and st["last_summary"]["new"] == 2
    assert len(m.history.list_jobs()) == 2 and not m.running and not (tmp_path / "collection.lock").exists()


def test_panel_and_script_show_the_page_number(tmp_path):
    root = Path(__file__).resolve().parent.parent
    assert "current_page" in (root / "dashboard" / "views.py").read_text()
    assert "current_page" in (root / "dashboard" / "static" / "app.js").read_text()
