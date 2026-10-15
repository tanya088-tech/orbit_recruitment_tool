"""Every dashboard dropdown must show exactly what is applied, and the jobs listed must match it - alone,
combined, after a refresh, and when another filter is changed."""
import itertools
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from config import settings
from dashboard import viewmodel as vm
from dashboard import views
from tests.factories import NOW, ago, make_record
from tests.test_collection_and_controls import make_app, serve
from tests.test_dashboard_server import call, get, row_count, running, titles

FILTERS = {
    "scope": vm.SCOPE_OPTIONS,
    "employment": vm.EMPLOYMENT_OPTIONS,
    "state": ["", "Maharashtra", "Karnataka"],
    "work_mode": vm.WORK_MODE_OPTIONS,
}
SORTS = list(vm.SORT_LABELS)


def dataset():
    """Jobs that differ in every filtered attribute, so every option has at least one match and one non-match."""
    recs, n = [], 0
    for loc, country in (("Pune, Maharashtra, India", "India"), ("Bengaluru, Karnataka, India", "India"), ("London, England, United Kingdom", "United Kingdom"), (None, None)):
        for emp in ("Permanent", "Contract"):
            for src in ("LinkedIn", "Naukri"):
                for mode in ("On-site", "Remote"):
                    n += 1
                    recs.append(make_record(1000 + n, title=f"Job {n}", location=loc, country=country, employment=emp, source=src,
                                            work_mode=mode, posted=ago(hours=5 + (n * 37) % 900), precision="exact"))
    return recs


def selected(html, name):
    m = re.search(rf'<select id="f-{name}" name="{name}" data-autosubmit>(.*?)</select>', html, re.S)
    assert m, name
    picks = re.findall(r'<option value="([^"]*)" selected>', m.group(1))
    assert len(picks) == 1, (name, picks)
    return picks[0]


def expected_ids(rows, query):
    f = vm.Filters.from_query({k: [v] for k, v in query.items()})
    return {r.key for r in vm.apply_filters(rows, f, NOW)}


def check_page(html, rows, query, port_rows=None):
    """The dropdowns equal the query, and every listed job satisfies every applied filter."""
    for name, default in (("scope", "india"), ("employment", "all"), ("state", ""), ("work_mode", "all"), ("sort", "recent")):
        assert selected(html, name) == query.get(name, default), (name, query)
    want = expected_ids(rows, query)
    assert row_count(html) == min(len(want), settings.DASHBOARD_PAGE_SIZE), query
    assert f"of {len(want)} vacancies" in html or (not want and "No matching vacancies" in html) or (not want and "No vacancies match" in html), query


def test_every_single_filter_option_is_shown_and_applied(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, app):
        rows = app.rows()
        for name, options in FILTERS.items():
            for opt in options:
                q = {name: opt} if opt != FILTERS[name][0] or name != "scope" else {}
                html = get(port, "/?" + urlencode({name: opt, "scope": "all"} if name != "scope" else {name: opt}))[2]
                query = {name: opt, "scope": "all"} if name != "scope" else {name: opt}
                check_page(html, rows, query)


def test_all_pairs_of_filters_stay_synchronized(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, app):
        rows = app.rows()
        checked = 0
        for (n1, o1), (n2, o2) in itertools.combinations(FILTERS.items(), 2):
            for a, b in itertools.product(o1, o2):
                query = {n1: a, n2: b}
                query.setdefault("scope", "all") if "scope" not in query else None
                check_page(get(port, "/?" + urlencode(query))[2], rows, query)
                checked += 1
        assert checked == 3 * 3 + 3 * 3 + 3 * 4 + 3 * 3 + 3 * 4 + 3 * 4          # every pair of the four filters, every value of each


def test_full_combination_matrix_through_the_page_renderer(tmp_path):
    """Every combination of the four filters (108) and every sort, rendered exactly as the server does."""
    with running(tmp_path, records=dataset(), second_run=[]) as (port, app):
        rows = app.rows()
        options = vm.filter_options(rows)
        count = 0
        for scope, emp, state, mode in itertools.product(*FILTERS.values()):
            f = vm.Filters.from_query({"scope": scope, "employment": emp, "state": state, "work_mode": mode})
            matched = vm.sort_rows(vm.apply_filters(rows, f, NOW), f.sort)
            html = views.render_summary(len(rows), vm.paginate(matched, 1), vm.summary_cards(matched), f, options, None, NOW)
            for name, val in (("scope", scope), ("employment", emp), ("state", state), ("work_mode", mode)):
                assert selected(html, name) == val, (name, val)
            for r in matched:                                     # each listed job satisfies each applied filter on its own
                assert scope == "all" or r.scope == scope
                assert emp == "all" or r.employment_type == emp
                assert not state or r.state_name == state
                assert mode == "all" or r.work_mode == mode
            count += 1
        for sort in SORTS:
            f = vm.Filters.from_query({"scope": "all", "sort": sort})
            html = views.render_summary(len(rows), vm.paginate(vm.sort_rows(rows, sort), 1), vm.summary_cards(rows), f, options, None, NOW)
            assert selected(html, "sort") == sort
        assert count == 3 * 3 * 3 * 4


def test_submitting_the_form_again_changes_nothing_and_refresh_is_stable(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, app):
        q = {"scope": "india", "employment": "Contract", "state": "Karnataka", "work_mode": "Remote", "sort": "oldest"}
        first = get(port, "/?" + urlencode(q))[2]
        values = {n: selected(first, n) for n in ("scope", "employment", "state", "work_mode", "sort")}
        assert values == q
        again = get(port, "/?" + urlencode(values))[2]                         # what the browser sends when "Apply filters" is pressed
        refreshed = get(port, "/?" + urlencode(q))[2]
        assert titles(first) == titles(again) == titles(refreshed)
        assert {n: selected(again, n) for n in values} == values
        # changing ONE filter keeps the others
        changed = get(port, "/?" + urlencode({**values, "state": ""}))[2]
        assert {n: selected(changed, n) for n in values} == {**values, "state": ""}


def test_links_on_the_page_carry_the_applied_filters(tmp_path):
    recs = [make_record(2000 + i, title=f"Linked {i}", source="LinkedIn", employment="Contract", work_mode="Remote", posted=ago(hours=2 + i), precision="exact")
            for i in range(settings.DASHBOARD_PAGE_SIZE + 5)]
    with running(tmp_path, records=recs, second_run=[]) as (port, app):
        q = {"scope": "india", "employment": "Contract", "state": "Maharashtra", "work_mode": "Remote"}
        h = get(port, "/?" + urlencode(q))[2]
        hrefs = [x.replace("&amp;", "&") for x in re.findall(r'href="(/\?[^"]*)"', h)]
        sorts = [x for x in hrefs if "sort=" in x]
        assert sorts and "page=2" in " ".join(hrefs)
        for href in sorts + [x for x in hrefs if "page=2" in x]:
            params = dict(parse_qsl(urlsplit(href).query))
            for k, v in q.items():
                if v not in ("india", "all", ""):
                    assert params.get(k) == v, (href, k)
        page2 = get(port, [x for x in hrefs if "page=2" in x][0])[2]
        assert selected(page2, "employment") == "Contract" and selected(page2, "state") == "Maharashtra"
        detail = re.search(r'href="(/job/[^"]+)"', h).group(1).replace("&amp;", "&")
        back = re.search(r'href="(/\?[^"]*)"[^>]*>[^<]*(?:Back|back)', get(port, detail)[2])
        assert back and "employment=Contract" in back.group(1).replace("&amp;", "&")


def test_unusual_values_are_shown_honestly_not_replaced_by_the_first_option(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, app):
        assert selected(get(port, "/?state=karnataka&scope=all")[2], "state") == "Karnataka"             # case differs
        assert row_count(get(port, "/?state=karnataka&scope=all")[2]) > 0
        h = get(port, "/?state=Goa&scope=all")[2]                                                       # a state with no jobs
        assert selected(h, "state") == "Goa" and row_count(h) == 0
        h = get(port, "/?scope=bogus&employment=bogus&posted=bogus&work_mode=bogus&sort=bogus")[2]     # invalid -> defaults, shown as defaults
        assert (selected(h, "scope"), selected(h, "employment"), selected(h, "state"), selected(h, "work_mode"), selected(h, "sort")) == \
               ("india", "all", "", "all", "recent")
        h = get(port, "/?state=%3Cscript%3Ealert(1)%3C/script%3E")[2]
        assert "<script>alert" not in h


def test_source_and_posted_dropdowns_are_gone_from_the_dashboard_filters(tmp_path):
    with running(tmp_path, records=[make_record(1)], second_run=[]) as (port, app):
        h = get(port, "/")[2]
        assert 'id="f-source"' not in h and 'id="f-posted"' not in h
        assert 'id="collect-window"' in h and 'name="source"' in h          # the collection panel keeps both choices


# ---- the collection form (the "International shows India" case) ----------------------------------------------
def test_collection_form_shows_the_options_of_the_last_run(tmp_path):
    app, mgr = make_app(tmp_path)
    srv = serve(app); port = srv.server_address[1]
    try:
        h = get(port, "/")[2]
        assert re.search(r'<option value="india" selected>', h)                                 # nothing run yet: the default
        call(port, "POST", "/collection/run", {"scope": "international", "count": "75", "window": "7d"})
        for _ in range(2):                                                                     # also after a refresh
            h = get(port, "/")[2]
            assert '<option value="international" selected>International only</option>' in h
            assert '<option value="7d" selected>Last 7 days</option>' in h
            panel = h[h.index('id="collect-scope"'):h.index('id="collect-window"')]
            assert 'value="75"' in h and 'value="india" selected' not in panel
        call(port, "POST", "/collection/run", {"scope": "both", "count": "50"})
        assert '<option value="both" selected>' in get(port, "/")[2] and '<option value="24h" selected>' in get(port, "/")[2]
    finally:
        srv.shutdown(); srv.server_close()


def test_after_a_vacancy_request_the_location_filter_shows_what_is_displayed(tmp_path):
    from tests.test_vacancy_target import Universe, PLACES, ids
    out = tmp_path / "out"; out.mkdir()
    jobs = ids(1, 4, location="London, England, United Kingdom")
    from config import locations as loc_cfg
    app, mgr = make_app(tmp_path, runner=Universe(out, {loc_cfg.search_locations("international")[0]: jobs}))
    srv = serve(app); port = srv.server_address[1]
    try:
        call(port, "POST", "/collection/run", {"scope": "international", "count": "4"})
        h = get(port, "/")[2]
        assert row_count(h) == 0 and selected(h, "scope") == "india"                             # the dashboard filter defaults to India
        h = get(port, "/?scope=outside")[2]
        assert row_count(h) == 4 and selected(h, "scope") == "outside"
        assert selected(get(port, "/?scope=all")[2], "scope") == "all"
    finally:
        srv.shutdown(); srv.server_close()
