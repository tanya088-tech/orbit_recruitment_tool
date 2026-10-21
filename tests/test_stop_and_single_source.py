"""The Stop button, one source per run, and the faster Naukri search (fewer detail pages opened)."""
import pytest

from config import settings
from dashboard import views
from dashboard.collection import PARTIAL, CollectionManager
from models.job import RunStats, SearchParams
from store.json_store import JsonJobHistory
from tests.factories import NOW
from tests.test_cross_source import fake_runner_factory


# ---- Stop button -----------------------------------------------------------------------------------------------
def test_stop_ends_the_run_after_the_current_place_and_keeps_what_was_found(tmp_path):
    calls = []
    inner = fake_runner_factory({"linkedin": [("1", "Credit Risk Analyst", "Acme Bank", "2026-10-12")]}, calls)
    h = JsonJobHistory(tmp_path / "h.json")
    holder = {}

    def runner(cmd, on_line, cwd, timeout):
        assert holder["m"].stop()                     # pressed while the first place is being searched
        return inner(cmd, on_line, cwd, timeout)
    m = holder["m"] = CollectionManager(h, tmp_path, tmp_path / "out", runner=runner, now_fn=lambda: NOW, background=False)
    ok, _ = m.start("india", target=50)
    st = m.status()
    assert ok and len(calls) == 1                     # no further place was searched
    assert st["state"] == PARTIAL and st["stop_reason"] == "stopped" and not st["stop_requested"]
    assert "Stopped by you" in st["message"] and not st["last_error"]
    assert len(h.list_jobs()) == 1                    # the place that was running when Stop was pressed is still saved


def test_stop_when_nothing_is_running_does_nothing(tmp_path):
    m = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, tmp_path / "out", runner=lambda *a: 0, background=False)
    assert m.stop() is False


def test_stop_button_is_shown_only_while_a_collection_runs():
    base = {"state": "running", "scope": "india", "window": "24h", "target": 10, "collected_unique": 0, "stop_reason": None,
            "search_done": 0, "search_total": 76, "warnings": [], "log_tail": [], "last_success_at": None, "last_summary": None}
    cv = lambda **kw: {"status": {**base, **kw}, "enabled": True, "default_scope": "india"}
    running = views._collection_panel(cv(), "/", NOW)
    assert 'action="/collection/stop"' in running and "Stop search" in running
    assert "Stopping..." in views._collection_panel(cv(stop_requested=True), "/", NOW)
    assert 'action="/collection/stop"' not in views._collection_panel(cv(state="succeeded"), "/", NOW)
    assert "Stopped by you" in views._collection_panel(cv(state="partial", stop_reason="stopped"), "/", NOW)


def test_stop_route_reports_whether_anything_was_running(tmp_path):
    from tests.test_collection_and_controls import make_app, serve
    from tests.test_dashboard_server import call
    app, _ = make_app(tmp_path)
    srv = serve(app)
    try:
        assert call(srv.server_address[1], "POST", "/collection/stop", {})[1]["location"] == "/?notice=not_running"
    finally:
        srv.shutdown(); srv.server_close()


def test_the_scraper_treats_ctrl_break_like_ctrl_c_so_it_saves_what_it_has():
    import run_collect
    with pytest.raises(KeyboardInterrupt):
        run_collect._break_as_interrupt(None, None)


# ---- one source per run ----------------------------------------------------------------------------------------
def test_the_collection_form_offers_one_source_at_a_time():
    cv = {"status": {"state": "idle", "warnings": [], "log_tail": []}, "enabled": True, "default_scope": "india"}
    h = views._collection_panel(cv, "/", NOW)
    assert '<select id="collect-source" name="source">' in h and 'type="checkbox" name="source"' not in h
    assert f'<option value="{settings.COLLECTION_DEFAULT_SOURCE}" selected>' in h
    for name in settings.SUPPORTED_SOURCES:
        assert f'value="{name}"' in h


# ---- faster Naukri ---------------------------------------------------------------------------------------------
def test_indian_headquartered_employers_are_not_opened_while_the_overseas_rule_is_on(monkeypatch):
    from processing.classifier import skip_before_fetch_reason as why
    monkeypatch.setattr(settings, "REQUIRE_OVERSEAS_HQ", True)
    assert "India" in why("Axis Bank") and "India" in why("IDFC FIRST Bank")
    assert why("Randstad India Staffing Solutions") == "can never qualify"
    assert why("HSBC") is None and why("Acme Bank") is None
    monkeypatch.setattr(settings, "REQUIRE_OVERSEAS_HQ", False)
    assert why("Axis Bank") is None


def test_the_browser_search_does_not_open_cards_that_cannot_qualify(monkeypatch):
    from collectors.browser_source import BrowserListSource
    monkeypatch.setattr(settings, "REQUIRE_OVERSEAS_HQ", True)
    monkeypatch.setattr(settings, "COLLECTION_SKIP_INELIGIBLE_BEFORE_FETCH", True)   # tests switch it off by default
    opened = []

    class Client:
        def get(self, url, wait_for=None, expand=None):
            return "page"

    class Src(BrowserListSource):
        name = "fake"

        def search_url(self, params, page):
            return f"search-{page}"

        def parse_search(self, html):
            return [{"job_id": "1", "job_url": "u1", "company": "Axis Bank", "posted_date": None},
                    {"job_id": "2", "job_url": "u2", "company": "Barclays", "posted_date": None}]

        def _collect_one(self, stub):
            opened.append(stub["company"])
            raise RuntimeError("not needed")
    list(Src(Client()).search(SearchParams(keywords="bank", max_pages=1), RunStats()))
    assert opened == ["Barclays"]


@pytest.mark.parametrize("factor, expected", [(2, 5), (0, 15)])
def test_naukri_gives_each_keyword_its_share_instead_of_the_full_number(monkeypatch, factor, expected):
    from collectors.browser_source import BrowserListSource
    from collectors.naukri.source import NaukriSource
    monkeypatch.setattr(settings, "NAUKRI_KEYWORD_SHARE_FACTOR", factor)
    caps = []

    def fake_search(self, params, stats, skip_ids=None):
        caps.append(params.max_jobs)
        return iter(())
    monkeypatch.setattr(BrowserListSource, "search", fake_search)
    params = SearchParams(keywords="a OR b OR c OR d OR e OR f", max_jobs=15, count_known=True)
    list(NaukriSource(client=object()).search(params, RunStats(), set()))
    assert caps == [expected] * 6                     # 15 x 2 / 6 keywords = 5 each (was 15 each = 90 pages)
