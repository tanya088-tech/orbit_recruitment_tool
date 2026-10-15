"""Location scope: what a scoped collection keeps and counts, the dashboard's India-first default, and the explanation of gaps."""
import json
import re
from pathlib import Path

from config import locations as loc
from config import settings
from dashboard.collection import CollectionManager
from store.json_store import JsonJobHistory
from tests.factories import NOW, make_record
from tests.test_collection_and_controls import make_app, manager as make_manager, raw_job, serve
from tests.test_dashboard_server import call, get, row_count, titles
from tests.test_vacancy_target import PLACES, Universe

INDIA_PLACE = PLACES[0]                                    # "India": Naukri turns this into a nationwide search (no location filter)
ABROAD_PLACE = loc.search_locations("international")[0]
UK = "United Kingdom (UK)"
PUNE = "Pune, Maharashtra, India"


def nk(n, location=PUNE, **kw):
    return raw_job(n, source="Naukri", job_url=f"https://www.naukri.com/job-listings-x-{7000000000 + n}", location=location, **kw)


def key(n):
    return f"naukri-{7000000000 + n}"


def collect(tmp_path, listings, scope, target, history_jobs=()):
    out = tmp_path / "out"; out.mkdir(exist_ok=True)
    uni = Universe(out, listings)
    mgr, hist = make_manager(tmp_path, uni)
    if history_jobs:
        from processing.pipeline import normalize_all
        hist.ingest(normalize_all(list(history_jobs), as_of=NOW).jobs, now=NOW)
    ok, msg = mgr.start(scope, target, sources=["naukri"])
    assert ok, msg
    return mgr, hist, uni


# ---- collection: India only -----------------------------------------------------------------------------------------
def test_a_uk_vacancy_from_a_nationwide_naukri_search_is_rejected_in_an_india_only_collection(tmp_path):
    listing = [nk(1, UK, title="Fund Accountant"), nk(2), nk(3)]            # newest first, the UK job on top
    mgr, hist, _ = collect(tmp_path, {INDIA_PLACE: listing}, "india", 2)
    st = mgr.status()
    assert st["result_keys"] == [key(2), key(3)] and st["collected_unique"] == 2 and st["stop_reason"] == "target_reached"
    assert {e["key"] for e in hist.list_jobs()} == {key(2), key(3)}                       # the UK job was not stored
    assert st["skipped_out_of_scope"] == 1 and st["skipped_not_relevant"] == 0
    assert "not confidently in India" in st["message"] and "not counted towards your number" in st["message"]


def test_the_collector_keeps_searching_after_rejecting_out_of_scope_vacancies(tmp_path):
    listing = [nk(i, UK) for i in range(1, 6)] + [nk(i) for i in range(6, 40)]       # five abroad first, then India
    mgr, hist, uni = collect(tmp_path, {INDIA_PLACE: listing}, "india", 3)
    st = mgr.status()
    assert st["result_keys"] == [key(6), key(7), key(8)] and st["stop_reason"] == "target_reached"
    assert len(uni.calls) > 1                                                             # it searched again to make up the number
    assert st["skipped_out_of_scope"] == 5
    assert sum(c["fetched"] for c in uni.calls) <= 5 + 3 + 3                              # rejected postings are not fetched twice


def test_a_uk_vacancy_already_in_the_history_is_kept_there_but_not_counted(tmp_path):
    uk = nk(1, UK, title="Fund Accountant")
    mgr, hist, _ = collect(tmp_path, {INDIA_PLACE: [uk, nk(2), nk(3), nk(4)]}, "india", 2, history_jobs=[uk])
    st = mgr.status()
    keys = {e["key"] for e in hist.list_jobs()}
    assert key(1) in keys                                                                  # never deleted
    assert st["result_keys"] == [key(2), key(3)] and key(1) not in st["result_keys"] and st["collected_unique"] == 2


# ---- collection: international only ---------------------------------------------------------------------------------
def test_an_international_only_collection_rejects_india_vacancies(tmp_path):
    dubai = "Dubai, United Arab Emirates"
    listing = [nk(1), nk(2, "Mumbai( Andheri East )"), nk(3, dubai), nk(4, UK), nk(5, dubai)]
    mgr, hist, _ = collect(tmp_path, {ABROAD_PLACE: listing}, "international", 3)
    st = mgr.status()
    assert st["result_keys"] == [key(3), key(4), key(5)] and st["collected_unique"] == 3
    assert {e["key"] for e in hist.list_jobs()} == {key(3), key(4), key(5)} and st["skipped_out_of_scope"] == 2
    assert "not confidently outside India" in st["message"]


def test_missing_and_ambiguous_locations_qualify_for_neither_scope(tmp_path):
    odd = [None, "", "Remote", "Anywhere in the world", "Pune, India / Dubai", "Mumbai, India and London, United Kingdom"]
    for scope, place, good in (("india", INDIA_PLACE, PUNE), ("international", ABROAD_PLACE, UK)):
        sub = tmp_path / scope; sub.mkdir()
        listing = [nk(i + 1, v) for i, v in enumerate(odd)] + [nk(20, good), nk(21, good)]
        mgr, hist, _ = collect(sub, {place: listing}, scope, 2)
        st = mgr.status()
        assert st["result_keys"] == [key(20), key(21)] and {e["key"] for e in hist.list_jobs()} == {key(20), key(21)}, scope
        assert st["skipped_out_of_scope"] == len(odd), scope


def test_the_both_scope_is_not_location_filtered(tmp_path):
    mgr, hist, _ = collect(tmp_path, {p: [] for p in loc.search_locations("both")} | {INDIA_PLACE: [nk(1, UK), nk(2), nk(3, None)]}, "both", 3)
    assert {e["key"] for e in hist.list_jobs()} == {key(1), key(2), key(3)} and mgr.status()["skipped_out_of_scope"] == 0


# ---- the dashboard: India first --------------------------------------------------------------------------------------
def _scope_selected(html):
    sel = re.search(r'<select id="f-scope".*?</select>', html, re.S).group(0)
    return re.search(r'<option value="([^"]*)" selected>', sel).group(1)


def _app_with_request(tmp_path, records, target=None):
    app, mgr = make_app(tmp_path)
    app.history.ingest(records, now=NOW)
    keys = [e["key"] for e in app.history.list_jobs()]
    mgr._update(result_keys=keys, target=target or len(keys), collected_unique=len(keys), new_added=0, already_had=len(keys),
                state="succeeded", window="24h", skipped_not_relevant=0, skipped_out_of_scope=0, stop_reason="target_reached")
    return app, mgr


def _mixed(n=30):
    return [make_record(i, f"Job {i:02d}", "Acme Bank", location=PUNE if i % 2 else "Dubai, United Arab Emirates") for i in range(1, n + 1)]


def test_default_and_reset_filters_are_within_india_even_when_showing_the_last_request(tmp_path):
    app, _ = _app_with_request(tmp_path, [make_record(1, "Pune job", location=PUNE), make_record(2, "UK job", location=UK)])
    srv = serve(app); port = srv.server_address[1]
    try:
        home = get(port, "/")[2]
        assert _scope_selected(home) == "india" and titles(home) == ["Pune job"]
        reset = re.search(r'href="([^"]*)"[^>]*data-reset-filters', home).group(1)
        assert reset == "/"
        after_reset = get(port, reset)[2]
        assert _scope_selected(after_reset) == "india" and titles(after_reset) == ["Pune job"]
        assert titles(get(port, "/?scope=outside")[2]) == ["UK job"] and _scope_selected(get(port, "/?scope=outside")[2]) == "outside"
        everything = get(port, "/?scope=all")[2]
        assert _scope_selected(everything) == "all" and sorted(titles(everything)) == ["Pune job", "UK job"]
    finally:
        srv.shutdown(); srv.server_close()


def test_explicit_scopes_survive_sorting_paging_and_opening_details(tmp_path):
    app, _ = _app_with_request(tmp_path, _mixed(260))
    srv = serve(app); port = srv.server_address[1]
    try:
        for scope, parity in (("india", 1), ("outside", 0), ("all", None)):
            page = get(port, f"/?scope={scope}")[2]
            assert _scope_selected(page) == scope
            if parity is not None:
                assert all(int(t.split()[1]) % 2 == parity for t in titles(page)), scope
            links = re.findall(r'href="(/\?[^"]*)"', page)
            sort_link = next(l for l in links if "sort=title" in l)
            next_link = next(l for l in links if "page=2" in l)
            assert f"scope={scope}" in sort_link and f"scope={scope}" in next_link, scope
            p2 = get(port, next_link.replace("&amp;", "&"))[2]
            assert _scope_selected(p2) == scope
            if parity is not None:
                assert all(int(t.split()[1]) % 2 == parity for t in titles(p2)), scope
            srt = get(port, sort_link.replace("&amp;", "&"))[2]
            assert _scope_selected(srt) == scope
            detail = re.search(r'class="job-link" href="([^"]*)"', page).group(1).replace("&amp;", "&")
            assert f"scope%3D{scope}" in detail, scope
            back = re.search(r'href="(/\?[^"]*)"[^>]*>[^<]*Back', get(port, detail)[2]) or re.search(r'href="(/\?[^"]*scope[^"]*)"', get(port, detail)[2])
            assert back and f"scope={scope}" in back.group(1), scope
    finally:
        srv.shutdown(); srv.server_close()


# ---- the summary tells the truth ---------------------------------------------------------------------------------------
def test_the_summary_explains_why_fewer_vacancies_are_shown_than_were_requested(tmp_path):
    records = [make_record(1, "Pune bank job", location=PUNE),
               make_record(2, "Fund Accountant", "Be One Professionals", location=UK),
               make_record(3, "Brand Executive", "Sunrise Textiles", location=PUNE, industries="Textile Manufacturing",
                           potential_bfsi=False)]
    settings.DISPLAY_ONLY_GCC_BFSI = True
    try:
        app, _ = _app_with_request(tmp_path, records, target=3)
        srv = serve(app); port = srv.server_address[1]
        try:
            html = get(port, "/")[2]
            assert titles(html) == ["Pune bank job"]
            banner = re.search(r'data-result-banner>(.*?)<a', html, re.S).group(1)
            assert "collected 3 vacancies" in banner and "for 3" in banner and "Showing 1" in banner
            assert "1 is hidden because it does not meet the current GCC/BFSI rules" in banner
            assert "1 is outside the selected Location scope (Within India)" in banner
            assert "Collected (unique): <b data-count-collected>3</b>" in html                  # the old result is not rewritten
            for label in ("Requested:", "Collected (unique):", "New to history:", "Already collected:", "Rejected (not counted):"):
                assert label in html, label
            wide = get(port, "/?scope=all")[2]
            assert "outside the selected Location scope" not in wide and titles(wide).count("Fund Accountant") == 1
        finally:
            srv.shutdown(); srv.server_close()
    finally:
        settings.DISPLAY_ONLY_GCC_BFSI = False


def test_a_run_reports_requested_collected_new_already_and_rejected_separately(tmp_path):
    listing = [nk(1, UK), nk(2), nk(3, None), nk(4), nk(5)]
    mgr, hist, _ = collect(tmp_path, {INDIA_PLACE: listing}, "india", 2)
    st = mgr.status()
    assert (st["target"], st["collected_unique"], st["new_added"], st["already_had"]) == (2, 2, 2, 0)
    assert st["skipped_out_of_scope"] == 2 and st["skipped_not_relevant"] == 0
    assert "2 posting(s) were skipped" in st["message"] and "2 new to your history, 0 already collected" in st["message"]


def test_the_collection_panel_says_it_is_not_the_dashboard_location_filter(tmp_path):
    app, _ = make_app(tmp_path)
    srv = serve(app)
    try:
        html = get(srv.server_address[1], "/")[2]
        assert "Location scope filter below only changes what is shown" in html
    finally:
        srv.shutdown(); srv.server_close()
