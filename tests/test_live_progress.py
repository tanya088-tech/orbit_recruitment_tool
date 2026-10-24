"""While a collection runs, the dashboard shows live progress read from the scraper's log lines as they arrive:
search pages read, job cards seen, cards skipped, job pages opened, jobs fetched, and the latest log lines."""
import sys
import time

from dashboard import views
from dashboard.collection import CollectionManager, subprocess_runner
from store.json_store import JsonJobHistory

NAUKRI = [
    "22:41:37 | INFO    | collectors.collector | [naukri] Search 1/1: 'Barclays OR HSBC' in 'India' (last 1d)",
    "22:41:40 | INFO    | collectors.browser_source | [naukri] search page 1: 20 listings",
    "22:41:41 | INFO    | collectors.browser_source | Not opening https://www.naukri.com/job-listings-x-1: Acme Staffing is not one of the listed employers",
    "22:41:42 | INFO    | collectors.browser_source | Not opening https://www.naukri.com/job-listings-x-2: (no company) is not one of the listed employers",
    "22:41:45 | INFO    | collectors.browser_source | Fetched job 241026012962: Barclays - AWS Application Support Professional",
    "22:41:47 | ERROR   | collectors.browser_source | Failed to collect https://www.naukri.com/job-listings-x-3: could not load",
    "22:41:50 | INFO    | collectors.browser_source | [naukri] search page 2: 5 listings",
]
LINKEDIN = [
    "14:55:48 | INFO    | collectors.linkedin.source | Search page 1: 10 listings",
    "14:55:49 | INFO    | collectors.linkedin.source | Fetched job 4482801678: Northern Trust - Analyst",
    "14:55:50 | WARNING | collectors.linkedin.source | Job removed or missing: https://www.linkedin.com/jobs/view/1 (HTTP 404)",
]


def _mgr(tmp_path):
    return CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, tmp_path / "out", runner=lambda *a: 0, background=False)


def test_naukri_and_linkedin_lines_move_the_live_numbers(tmp_path):
    m = _mgr(tmp_path)
    for line in NAUKRI + LINKEDIN:
        m._on_line(line, {})
    st = m.status()
    assert st["live"] == {"pages": 3, "cards": 35, "skipped": 2, "opened": 4, "fetched": 2}
    assert st["current_page"] == 1 and st["listings_on_page"] == 10          # Naukri's lower-case "search page" is read too
    assert st["log_tail"][-1].endswith("(HTTP 404)")


def test_a_new_run_starts_the_live_numbers_at_zero(tmp_path):
    m = _mgr(tmp_path)
    m._on_line(NAUKRI[1], {})
    assert m.status()["live"]["pages"] == 1
    m.start("india", target=1, sources=["linkedin"])
    assert m.status()["live"]["pages"] == 0
    assert _mgr(tmp_path / "fresh").status()["live"]["fetched"] == 0


def test_scraper_lines_arrive_while_it_is_still_running(tmp_path):
    """Without PYTHONUNBUFFERED the child's output to a pipe is held back until it ends."""
    child = ("import logging, sys, time\n"
             "logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')\n"
             "logging.info('[naukri] search page 1: 20 listings')\n"
             "time.sleep(2.0)\n"
             "logging.info('done')\n")
    got = []
    started = time.monotonic()
    code = subprocess_runner([sys.executable, "-c", child], lambda ln: got.append((time.monotonic() - started, ln)), tmp_path, 30)
    ended = time.monotonic() - started
    assert code == 0 and [ln for _, ln in got] == ["[naukri] search page 1: 20 listings", "done"]
    assert ended - got[0][0] >= 1.5, got                                       # the first line came ~2 s before the end


def test_running_panel_shows_live_numbers_and_a_log_box_the_page_refreshes():
    st = {"state": "running", "target": 10, "window": "24h", "search_done": 0, "search_total": 1, "current_search": "India",
          "live": {"pages": 7, "cards": 140, "skipped": 120, "opened": 6, "fetched": 5}, "log_tail": [], "warnings": [], "message": "x"}
    cv = {"status": st, "enabled": True, "default_scope": "india"}
    html = views._collection_panel(cv, "/", None)
    for key, value in (("pages", 7), ("cards", 140), ("skipped", 120), ("opened", 6), ("fetched", 5)):
        assert f"data-live-{key}>{value}<" in html
    assert "data-collect-log" in html                                         # present even before the first log line
    assert "Jobs fetched" in html and "added to your list when each search" in html


def test_app_js_refreshes_live_numbers_and_log():
    from pathlib import Path
    js = (Path(views.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-live-" in js and "data-collect-log" in js and "log_tail" in js
