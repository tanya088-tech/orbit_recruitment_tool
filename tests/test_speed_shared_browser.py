"""Speed: sources are searched at the same time, and one browser serves the whole run (with a safe fallback)."""
import json
import os
import threading
import time
from pathlib import Path

from collectors.browser_host import BrowserHost, ENV_VAR
from config import settings
from dashboard.collection import CollectionManager
from store.json_store import JsonJobHistory
from tests.test_cross_source import fake_runner_factory


class FakeProc:
    def __init__(self): self.terminated = False
    def poll(self): return None
    def terminate(self): self.terminated = True
    def wait(self, timeout=None): return 0
    def kill(self): pass


def test_host_start_returns_url_and_stop_terminates(tmp_path):
    procs = []
    h = BrowserHost(tmp_path / "p", wait_seconds=2, find_binary=lambda: "/x/chrome", popen=lambda *a, **k: procs.append(FakeProc()) or procs[-1],
                    answers=lambda u: True, port_fn=lambda: 9333)
    assert h.start() == "http://127.0.0.1:9333"
    h.stop()
    assert procs[0].terminated and h.url is None


def test_host_start_returns_none_when_browser_missing_or_silent(tmp_path):
    def boom(): raise FileNotFoundError("no chromium")
    assert BrowserHost(tmp_path / "a", find_binary=boom).start() is None
    p = []
    silent = BrowserHost(tmp_path / "b", wait_seconds=0.3, find_binary=lambda: "x", popen=lambda *a, **k: p.append(FakeProc()) or p[-1],
                         answers=lambda u: False, port_fn=lambda: 9334)
    assert silent.start() is None and p[0].terminated                          # cleaned up, collection falls back


class FakeHost:
    def __init__(self, url): self.url, self.started, self.stopped = url, False, False
    def start(self): self.started = True; return self.url
    def stop(self): self.stopped = True


def _mgr(tmp_path, per, calls, runner=None):
    h = JsonJobHistory(tmp_path / "h.json")
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=runner or fake_runner_factory(per, calls), background=False)
    return h, m


def test_shared_browser_env_set_during_run_and_cleared_after(tmp_path, monkeypatch=None):
    seen = []
    inner = fake_runner_factory({"naukri": [("1", "Credit Analyst", "Acme Bank", "2026-10-12")]}, [])
    def runner(cmd, on_line, cwd, timeout):
        seen.append(os.environ.get(ENV_VAR))
        return inner(cmd, on_line, cwd, timeout)
    h, m = _mgr(tmp_path, None, None, runner)
    host = FakeHost("http://127.0.0.1:9555")
    m.share_browser, m.browser_host_factory = True, lambda: host
    old = settings.BROWSER_HEADLESS
    settings.BROWSER_HEADLESS = False
    try:
        ok, msg = m.start("india", target=2, window=settings.COLLECTION_DEFAULT_WINDOW, sources=["Naukri"])
    finally:
        settings.BROWSER_HEADLESS = old
    assert ok, msg
    assert host.started and host.stopped
    assert seen and all(v == "http://127.0.0.1:9555" for v in seen)
    assert ENV_VAR not in os.environ


def test_shared_browser_failure_falls_back_to_per_place(tmp_path):
    seen = []
    inner = fake_runner_factory({"naukri": [("1", "Credit Analyst", "Acme Bank", "2026-10-12")]}, [])
    def runner(cmd, on_line, cwd, timeout):
        seen.append(os.environ.get(ENV_VAR))
        return inner(cmd, on_line, cwd, timeout)
    h, m = _mgr(tmp_path, None, None, runner)
    m.share_browser, m.browser_host_factory = True, lambda: FakeHost(None)
    old = settings.BROWSER_HEADLESS
    settings.BROWSER_HEADLESS = False
    try:
        ok, _ = m.start("india", target=2, window=settings.COLLECTION_DEFAULT_WINDOW, sources=["Naukri"])
    finally:
        settings.BROWSER_HEADLESS = old
    assert ok and seen and all(v is None for v in seen)


def test_no_shared_browser_for_linkedin_only_or_fake_runner(tmp_path):
    h, m = _mgr(tmp_path, {"linkedin": [("1", "Credit Analyst", "Acme Bank", "2026-10-12")]}, [])
    assert m.share_browser is False                                           # tests with fake runners never start a browser
    host = FakeHost("http://x")
    m.share_browser, m.browser_host_factory = True, lambda: host
    m.start("india", target=2, window=settings.COLLECTION_DEFAULT_WINDOW, sources=["LinkedIn"])
    assert not host.started                                                   # LinkedIn uses plain HTTP, no browser needed


def test_sources_are_searched_at_the_same_time(tmp_path):
    active, peak, lock, calls = [0], [0], threading.Lock(), []
    inner = fake_runner_factory({"linkedin": [("1", "Credit Analyst", "Acme Bank", "2026-10-12")],
                                 "naukri": [("9", "Treasury Analyst", "Beta Bank", "2026-10-12")]}, calls)
    def runner(cmd, on_line, cwd, timeout):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0])
        time.sleep(0.15)
        try:
            return inner(cmd, on_line, cwd, timeout)
        finally:
            with lock: active[0] -= 1
    h, m = _mgr(tmp_path, None, None, runner)
    old = settings.COLLECTION_PARALLEL_SOURCES
    settings.COLLECTION_PARALLEL_SOURCES = True
    try:
        ok, msg = m.start("india", target=4, window=settings.COLLECTION_DEFAULT_WINDOW, sources=["LinkedIn", "Naukri"])
    finally:
        settings.COLLECTION_PARALLEL_SOURCES = old
    assert ok, msg
    assert peak[0] == 2 and set(calls) == {"linkedin", "naukri"}
    assert len(h.list_jobs()) == 2


def test_sequential_when_parallel_switched_off(tmp_path):
    active, peak, lock = [0], [0], threading.Lock()
    inner = fake_runner_factory({"linkedin": [("1", "A", "Acme Bank", "2026-10-12")], "naukri": [("9", "B", "Beta Bank", "2026-10-12")]}, [])
    def runner(cmd, on_line, cwd, timeout):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0])
        try:
            return inner(cmd, on_line, cwd, timeout)
        finally:
            with lock: active[0] -= 1
    h, m = _mgr(tmp_path, None, None, runner)
    old = settings.COLLECTION_PARALLEL_SOURCES
    settings.COLLECTION_PARALLEL_SOURCES = False
    try:
        m.start("india", target=4, window=settings.COLLECTION_DEFAULT_WINDOW, sources=["LinkedIn", "Naukri"])
    finally:
        settings.COLLECTION_PARALLEL_SOURCES = old
    assert peak[0] == 1


def test_request_pacing_is_short_and_staffing_employers_are_not_opened():
    from config import settings
    from processing.classifier import employer_can_never_qualify as never
    assert settings.REQUEST_DELAY_MAX <= 3.5 and settings.REQUEST_DELAY_MIN < settings.REQUEST_DELAY_MAX
    assert never("Randstad India Staffing Solutions") and never("Confidential") and not never("HSBC Technology India")


def test_card_prefilter_skips_the_detail_download_for_staffing_cards():
    from collectors.linkedin import source as src
    from config import settings
    from models.job import RunStats, SearchParams
    opened = []

    class Client:
        def get(self, url, params=None):
            opened.append(url)
            raise RuntimeError("stop")

    stubs = [{"job_id": "1", "company": "Acme Staffing Services", "title": "t", "posted_date": None, "posted_age_text": "1 hour ago",
              "job_url": "u1", "location": "Pune", "company_url": None, "raw": ""}]
    orig = src.parse_search_results, settings.COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH
    src.parse_search_results = lambda html: stubs if not opened[1:] and len(opened) < 2 else []
    settings.COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH = True
    try:
        list(src.LinkedInSource(client=type("C", (), {"get": lambda self, url, params=None: (opened.append(url) or "<x/>")})()).search(
            SearchParams(keywords="k", location="Pune", days=30, max_jobs=0, max_pages=2), RunStats()))
    finally:
        src.parse_search_results, settings.COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH = orig
    assert all("jobPosting" not in u for u in opened)       # only the search page was requested
