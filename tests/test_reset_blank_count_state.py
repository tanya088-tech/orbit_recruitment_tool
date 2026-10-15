"""Reset filters, collecting without a vacancy count, and the dynamic State filter."""
import hashlib
import re
from urllib.parse import parse_qsl, urlsplit

from config import settings
from dashboard import viewmodel as vm
from dashboard.regions import indian_state
from tests.factories import NOW, ago, make_record
from tests.test_collection_and_controls import make_app, serve
from tests.test_dashboard_server import call, get, row_count, running, titles
from tests.test_location_scope import INDIA_PLACE, PUNE, UK, collect, key, nk
from tests.test_viewmodel import rows_from


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def selected(html, name):
    sel = re.search(rf'<select id="f-{name}".*?</select>', html, re.S).group(0)
    return re.search(r'<option value="([^"]*)" selected>', sel).group(1)


def hrefs(html):
    return [h.replace("&amp;", "&") for h in re.findall(r'href="(/[^"]*)"', html)]


def dataset(extra=0):
    recs = [make_record(1, "Pune A", "Acme Bank", "Pune, Maharashtra, India", "Permanent", posted=ago(hours=2), work_mode="Remote"),
            make_record(2, "Pune B", "Acme Bank", "Pune, Maharashtra, India", "Contract", posted=ago(hours=3), work_mode="On-site"),
            make_record(3, "Bengaluru A", "Acme Bank", "Bengaluru, Karnataka, India", "Permanent", posted=ago(hours=4), work_mode="Remote"),
            make_record(4, "Delhi A", "Acme Bank", "New Delhi, Delhi, India", "Permanent", posted=ago(hours=5)),
            make_record(5, "London A", "Acme Bank", "London, England, United Kingdom", "Permanent", posted=ago(hours=6), country="United Kingdom"),
            make_record(6, "Nowhere A", "Acme Bank", None, "Permanent", posted=ago(hours=7), country=None),
            make_record(7, "Ambiguous A", "Acme Bank", "Mumbai, India and London, United Kingdom", "Permanent", posted=ago(hours=8))]
    recs += [make_record(100 + i, f"Mumbai {i:03d}", "Acme Bank", "Mumbai, Maharashtra, India", "Permanent", posted=ago(hours=10 + i))
             for i in range(extra)]
    return recs


# ---- 1. Reset filters -------------------------------------------------------------------------------------------------
def test_reset_filters_is_a_visible_button_that_returns_to_the_defaults(tmp_path):
    with running(tmp_path, records=dataset(extra=60), second_run=[]) as (port, app):
        files = [tmp_path / "job_history.json"]
        before = [md5(f) for f in files]
        busy = get(port, "/?scope=all&state=Maharashtra&employment=Permanent&work_mode=Remote&sort=title&page=2&view=all")[2]
        m = re.search(r'<a class="btn btn-reset" href="([^"]*)"[^>]*data-reset-filters[^>]*>Reset filters</a>', busy)
        assert m and m.group(1) == "/"                              # one click: no filter, sort or page in the address
        assert "btn-quiet" not in m.group(0)                        # an outlined button, not invisible text
        default = get(port, m.group(1))[2]
        for name, want in (("scope", "india"), ("state", ""), ("employment", "all"), ("work_mode", "all"), ("sort", "recent")):
            assert selected(default, name) == want, name
        assert "filter applied" not in default and "filters applied" not in default
        figs = dict((label, int(n)) for n, label in re.findall(r"<b>(\d+)</b><span>([^<]+)</span>", default))
        assert figs["Total openings"] == len(vm.apply_filters(app.rows(), vm.Filters(), NOW))   # KPIs follow the reset list
        assert row_count(busy) != row_count(default)
        assert [md5(f) for f in files] == before and app.collection is None      # nothing deleted, rewritten or started


def test_reset_style_exists_in_the_stylesheet():
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "dashboard" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".btn-reset" in css


# ---- 2. collecting without a vacancy count ------------------------------------------------------------------------------
def test_a_blank_count_is_accepted_and_does_not_mean_zero(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    from tests.test_vacancy_target import Universe
    uni = Universe(out, {INDIA_PLACE: [nk(1), nk(2), nk(3)]})
    app, mgr = make_app(tmp_path, runner=uni)
    srv = serve(app); port = srv.server_address[1]
    try:
        status, headers, _ = call(port, "POST", "/collection/run", {"scope": "india", "window": "7d", "count": ""})
        assert status == 303 and headers["location"] == "/?notice=started"
        st = mgr.status()
        assert st["target"] is None and st["window"] == "7d" and st["state"] == "succeeded"
        assert uni.calls and uni.calls[0]["cap"] == settings.COLLECTION_MAX_JOBS_PER_SEARCH       # not capped at 0 / 1 / any number
        assert st["collected_unique"] == 3 and st["new_added"] == 3
        # a number still behaves as before, and a bad one is still refused
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "abc"})[1]["location"] == "/?notice=bad_count"
        assert call(port, "POST", "/collection/run", {"scope": "india", "count": "0"})[1]["location"] == "/?notice=bad_count"
    finally:
        srv.shutdown(); srv.server_close()


def test_blank_count_uses_the_chosen_period_scope_and_rules(tmp_path):
    cmds = []
    from tests.test_vacancy_target import Universe
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {INDIA_PLACE: [nk(1, UK, title="Fund Accountant"), nk(2, None), nk(3), nk(4, "Mumbai, India / Dubai"), nk(5)]})

    def spy(cmd, on_line, cwd, timeout_s):
        cmds.append(cmd)
        return uni(cmd, on_line, cwd, timeout_s)
    from tests.test_collection_and_controls import manager as make_manager
    mgr, hist = make_manager(tmp_path, spy)
    ok, _ = mgr.start("india", None, "3d", sources=["naukri"])
    assert ok
    assert cmds[0][cmds[0].index("--days") + 1] == "3"                         # Last 3 days
    st = mgr.status()
    assert {e["key"] for e in hist.list_jobs()} == {key(3), key(5)}             # India-only + eligibility rules still applied
    assert st["skipped_out_of_scope"] == 3 and st["collected_unique"] == 2 and st["stop_reason"] == "exhausted"
    assert "all eligible vacancies" in st["message"] and "last 3 days" in st["message"]
    assert st["result_keys"] == []                                             # nothing is ranked or cut to a target


def test_blank_count_does_not_store_duplicates(tmp_path):
    from tests.test_vacancy_target import Universe
    out = tmp_path / "out"; out.mkdir()
    mgr, hist, _ = collect(tmp_path, {INDIA_PLACE: [nk(1), nk(1), nk(2)]}, "india", None)
    assert sorted(e["key"] for e in hist.list_jobs()) == [key(1), key(2)]


def test_the_panel_explains_target_and_all_eligible_modes(tmp_path):
    app, mgr = make_app(tmp_path)
    srv = serve(app); port = srv.server_address[1]
    try:
        h = get(port, "/")[2]
        field = re.search(r'<input id="collect-count"[^>]*>', h).group(0)
        assert "required" not in field and "Number of vacancies (optional)" in h
        assert "Blank" in h and "all eligible, unique vacancies" in h and "With a number" in h
        call(port, "POST", "/collection/run", {"scope": "india", "window": "24h", "count": ""})
        h = get(port, "/")[2]
        assert "All eligible vacancies (within search limits)" in h
        assert "data-count-mode" in h and "Requested:" not in h
        call(port, "POST", "/collection/run", {"scope": "india", "window": "24h", "count": "5"})
        h = get(port, "/")[2]
        assert "Requested:" in h and "data-count-mode" not in h
    finally:
        srv.shutdown(); srv.server_close()


# ---- 3. State filter --------------------------------------------------------------------------------------------------
def test_state_names_are_normalised_from_the_location_text():
    cases = {"Pune, Maharashtra, India": "Maharashtra", "Pune": "Maharashtra", "Greater Bengaluru Area": "Karnataka",
             "Bangalore Urban, Karnataka": "Karnataka", "Bhubaneswar, Orissa, India": "Odisha", "New Delhi": "Delhi",
             "Gurugram, Haryana": "Haryana", "Hyderabad, Telangana, India": "Telangana", "Mumbai( Andheri East )": "Maharashtra",
             "Remote - India": "", "India": "", "": "", None: "", "Smalltown": ""}
    for loc, want in cases.items():
        assert indian_state(loc) == want, loc


def test_the_state_list_comes_from_the_stored_vacancies_only():
    rows = rows_from(dataset())
    opts = vm.filter_options(rows)["states"]
    assert opts == ["Delhi", "Karnataka", "Maharashtra"]                                    # nothing hard-coded, nothing outside the data
    more = rows_from(dataset() + [make_record(50, "Goa A", "Acme Bank", "Panaji, Goa, India", "Permanent")])
    assert "Goa" in vm.filter_options(more)["states"] and "Goa" not in opts
    assert vm.filter_options(rows_from([])) ["states"] == []


def test_outside_missing_and_ambiguous_locations_never_get_an_indian_state():
    rows = {r.title: r for r in rows_from(dataset())}
    for t in ("London A", "Nowhere A", "Ambiguous A"):
        assert rows[t].state_name == "", t
    assert rows["Pune A"].state_name == "Maharashtra" and rows["Delhi A"].state_name == "Delhi"
    all_rows = list(rows.values())
    got = vm.apply_filters(all_rows, vm.Filters(scope="all", state="Maharashtra"), NOW)
    assert {r.title for r in got} == {"Pune A", "Pune B"}
    assert vm.apply_filters(all_rows, vm.Filters(scope="outside", state="Maharashtra"), NOW) == []


def test_state_filter_works_with_scope_employment_and_work_mode_over_http(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, _):
        h = get(port, "/")[2]
        assert selected(h, "state") == "" and "All states" in h
        opts = re.findall(r'<option value="([^"]*)"', re.search(r'<select id="f-state".*?</select>', h, re.S).group(0))
        assert opts == ["", "Delhi", "Karnataka", "Maharashtra"]
        t = lambda q: set(titles(get(port, "/?" + q)[2]))
        assert t("state=Maharashtra") == {"Pune A", "Pune B"}
        assert t("state=Maharashtra&employment=Contract") == {"Pune B"}
        assert t("state=Maharashtra&work_mode=Remote") == {"Pune A"}
        assert t("state=Maharashtra&employment=Permanent&work_mode=Remote") == {"Pune A"}
        assert t("state=Karnataka&scope=all") == {"Bengaluru A"}
        assert t("state=Maharashtra&scope=outside") == set()
        h = get(port, "/?state=Maharashtra")[2]
        assert selected(h, "state") == "Maharashtra" and "(1 filter applied" in h
        assert t("state=%3Cscript%3E") == set()


def test_state_survives_sorting_pagination_and_opening_details(tmp_path):
    with running(tmp_path, records=dataset(extra=130), second_run=[]) as (port, _):
        h = get(port, "/?state=Maharashtra&sort=title")[2]
        links = hrefs(h)
        sort_links = [l for l in links if "sort=" in l and "state=Maharashtra" in l]
        assert sort_links                                                        # header sort links keep the state
        page2 = next(l for l in links if "page=2" in l)
        assert "state=Maharashtra" in page2 and "sort=title" in page2
        h2 = get(port, page2)[2]
        assert selected(h2, "state") == "Maharashtra" and selected(h2, "sort") == "title"
        detail = re.search(r'href="(/job/[^"]+)"', h2).group(1).replace("&amp;", "&")
        assert "state%3DMaharashtra" in detail or "state=Maharashtra" in detail
        back = re.search(r'<a href="(/\?[^"]*)">Back to vacancies</a>', get(port, detail)[2]).group(1).replace("&amp;", "&")
        assert dict(parse_qsl(urlsplit(back).query)).get("state") == "Maharashtra"
