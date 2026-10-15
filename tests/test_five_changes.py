"""Reset filters, Company Reviews column, India / Outside India filter, a restart that really restarts."""
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from collectors.naukri import detail_parser as nk
from dashboard import viewmodel as vm
from dashboard import views
from processing.location import check_location
from processing.pipeline import normalize_all
from store.json_store import JsonJobHistory, JsonRecruiterState
from tests.factories import NOW, entry, make_record
from tests.test_collection_and_controls import make_app, serve
from tests.test_dashboard_server import call, get, row_count, running, titles

ROOT = Path(__file__).resolve().parent.parent


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ---- 1. Reset filters --------------------------------------------------------------------------------------------
def test_reset_filters_button_returns_to_the_default_view_and_changes_no_data(tmp_path):
    with running(tmp_path) as (port, app):
        files = [tmp_path / "job_history.json"]
        before = [md5(f) for f in files]
        filtered = get(port, "/?scope=outside&employment=Contract&state=Karnataka&work_mode=Remote&sort=title&page=2&view=all")[2]
        assert "filter" in filtered and "applied" in filtered
        link = re.search(r'<a class="btn btn-reset" href="([^"]*)"[^>]*data-reset-filters[^>]*>Reset filters</a>', filtered)
        assert link and link.group(1) == "/"                                       # one click = the address with no filters at all
        assert 'autocomplete="off"' in filtered                                    # the browser must not restore old dropdown choices
        default = get(port, link.group(1))[2]
        assert "filters applied" not in default and "filter applied" not in default
        assert row_count(default) > 0 and "Reset filters" in default
        for name, want in (("scope", "india"), ("employment", "all"), ("state", ""), ("work_mode", "all"), ("sort", "recent")):
            m = re.search(rf'<select id="f-{name}" name="{name}".*?</select>', default, re.S)
            assert f'<option value="{want}" selected>' in m.group(0), name          # every dropdown shows its default again
        assert [md5(f) for f in files] == before                                   # nothing deleted or rewritten
        assert app.collection is None                                              # and nothing was started


def test_the_empty_result_message_offers_the_same_reset_button(tmp_path):
    with running(tmp_path) as (port, _):
        html = get(port, "/?scope=outside")[2]
        assert "No vacancies match these filters" in html and ">Reset filters</a>" in html


# ---- 2. Company Reviews ------------------------------------------------------------------------------------------
HEADER = ('<html><body><h1 class="styles_jd-header-title__a">Credit Analyst</h1>'
          '<div class="styles_jd-header-comp-name__b"><a title="Virtusa" class="styles_jhc__hiring-for__c">Virtusa</a>{rating}</div>'
          '<div class="styles_jhc__stat__d">Applicants: {apps}</div>'
          '<div class="styles_JDC__dang-inner-html__e">Role text</div></body></html>')


def parsed(rating="", apps="Less than 10"):
    return nk.parse_job_detail(HEADER.format(rating=rating, apps=apps))


def test_naukri_page_rating_and_review_count_are_read_and_the_company_name_stays_clean():
    d = parsed('<div class="styles_rating-wrapper__x"><a class="amb-rating"><span class="ni-icon-star"></span><span>3.7</span></a>'
               '<a class="amb-reviews"> 689 Reviews</a></div>')
    assert (d["company"], d["company_rating"], d["company_reviews"]) == ("Virtusa", "3.7", "689")
    d = parsed('<div class="styles_rating-wrapper__x"><span>3.6</span><span>6.6K Reviews</span></div>')
    assert (d["company_rating"], d["company_reviews"]) == ("3.6", "6.6K")


def test_rating_text_inside_the_company_box_is_read_but_never_left_in_the_company_name():
    html = HEADER.replace('<a title="Virtusa" class="styles_jhc__hiring-for__c">Virtusa</a>{rating}', "Easemytrip 3.7 689 Reviews")
    d = nk.parse_job_detail(html.format(apps="Less than 10"))
    assert (d["company"], d["company_rating"], d["company_reviews"]) == ("Easemytrip", "3.7", "689")


def test_missing_rating_is_none_and_applicants_are_never_taken_for_reviews():
    d = parsed("", apps="689")                                            # 689 applicants, no rating box
    assert d["company_rating"] is None and d["company_reviews"] is None and d["applicants"] == "689"
    d = parsed('<div class="styles_rating-wrapper__x"></div>', apps="100+")
    assert d["company_rating"] is None and d["company_reviews"] is None
    assert nk.rating_and_reviews("Applicants: 689 4 openings 3.5 Lacs PA 5-10 Yrs") == (None, None)
    assert nk.rating_and_reviews("689 reviews") == (None, "689")
    assert nk.rating_and_reviews("4.1", rating_only_ok=True) == ("4.1", None)
    assert nk.rating_and_reviews("4.1") == (None, None)


def test_search_card_rating_is_read_the_same_way():
    from collectors.naukri.search_parser import _card_rating
    card = BeautifulSoup('<div><a class="comp-name">Virtusa</a><a class="rating"><span class="main-2">3.6</span></a>'
                         '<a class="review">6.6K Reviews</a></div>', "lxml")
    assert _card_rating(card) == ("3.6", "6.6K")


def test_naukri_rating_flows_to_the_stored_record_and_linkedin_has_none():
    base = {"job_id": "1", "title": "Analyst", "company": "Axis Bank", "location": "Pune, Maharashtra, India", "job_url": "https://x/1",
            "description": "d", "industries": "Banking", "employment_type": "Full-time", "posted_age_text": "1 hour ago",
            "collected_at": NOW.isoformat(), "raw": {}}
    nk_rec = normalize_all([{**base, "source": "Naukri", "company_rating": "3.7", "company_reviews": "689"}], as_of=NOW).jobs[0]
    li_rec = normalize_all([{**base, "source": "LinkedIn", "job_id": "2", "job_url": "https://x/2"}], as_of=NOW).jobs[0]
    assert (nk_rec["company_rating"], nk_rec["company_reviews"]) == ("3.7", "689")
    assert li_rec["company_rating"] is None and li_rec["company_reviews"] is None


def test_format_company_reviews():
    f = vm.format_company_reviews
    assert f("3.7", "689") == "3.7 ★ (689 reviews)" and f("3.6", "6.6K") == "3.6 ★ (6.6K reviews)"
    assert f("5.0", "1") == "5.0 ★ (1 review)" and f("4.1", None) == "4.1 ★" and f(None, "12") == "12 reviews"
    assert f(None, None) == ""


def test_table_has_a_company_reviews_column_filled_for_naukri_and_blank_otherwise(tmp_path):
    recs = [make_record(1, "Analyst", "Virtusa", source="Naukri", job_url="https://www.naukri.com/job-listings-x-1", company_rating="3.7", company_reviews="689"),
            make_record(2, "Manager", "Acme Bank"),
            make_record(3, "Officer", "Old Bank", source="Naukri", job_url="https://www.naukri.com/job-listings-x-3"),
            make_record(4, "Clerk", "Junk Bank", source="Naukri", job_url="https://www.naukri.com/job-listings-x-4", company_rating="999", company_reviews="applicants")]
    with running(tmp_path, records=recs, second_run=[]) as (port, _):
        html = get(port, "/?scope=all")[2]
    assert "<th>Company Reviews</th>" in html
    cells = dict(zip(titles(html), re.findall(r'<td class="c-reviews">([^<]*)</td>', html)))
    assert cells["Analyst"] == "3.7 ★ (689 reviews)"
    assert cells["Manager"] == "" and cells["Officer"] == ""                  # LinkedIn and older records: blank, nothing invented
    assert cells["Clerk"] == ""                                               # values that are not a rating / review count are ignored


# ---- 3. India / Outside India ---------------------------------------------------------------------------------------
LOCATIONS = [
    ("Pune, Maharashtra, India", "LinkedIn", "india"), ("Hyderabad, Chennai, Bengaluru", "Naukri", "india"),
    ("Mumbai( Andheri East )", "Naukri", "india"), ("Pune/Pimpri-Chinchwad Area", "LinkedIn", "india"),
    ("Delhi / NCR", "Naukri", "india"), ("Remote - India", "LinkedIn", "india"),
    ("Dubai, United Arab Emirates", "LinkedIn", "outside"), ("United Kingdom (UK)", "Naukri", "outside"),
    ("London, England, United Kingdom", "LinkedIn", "outside"), ("Hyderabad, Sindh, Pakistan", "LinkedIn", "outside"),
    ("Pune, India / Dubai", "Naukri", "unknown"), ("Remote", "LinkedIn", "unknown"), (None, "Naukri", "unknown"),
    ("Somewhere unrecognisable", "LinkedIn", "unknown"),
]


def _rows():
    entries = []
    for i, (loc, src, _) in enumerate(LOCATIONS, 1):
        # the stored country is deliberately wrong for some: only the job's own location text may decide
        e = entry(i, title=f"Job {i}", location=loc, country="India" if i % 2 else "United States", source=src)
        e["key"] = f"{src.lower()}-{i}"
        entries.append(e)
    return vm.build_rows(entries, {}, None, only_gcc_bfsi=False)


def test_scope_comes_from_the_job_location_only():
    got = {r.title: r.scope for r in _rows()}
    for i, (loc, src, want) in enumerate(LOCATIONS, 1):
        assert got[f"Job {i}"] == want, (loc, got[f"Job {i}"])


def test_india_shows_only_india_outside_shows_only_outside_and_unknown_is_in_neither():
    rows = _rows()
    india = vm.apply_filters(rows, vm.Filters(scope="india"), NOW)
    outside = vm.apply_filters(rows, vm.Filters(scope="outside"), NOW)
    everything = vm.apply_filters(rows, vm.Filters(scope="all"), NOW)
    assert {r.scope for r in india} == {"india"} and len(india) == 6
    assert {r.scope for r in outside} == {"outside"} and len(outside) == 4
    assert len(everything) == len(LOCATIONS) and not ({r.key for r in india} & {r.key for r in outside})
    for src in ("LinkedIn", "Naukri"):
        assert {r.scope for r in vm.apply_filters(rows, vm.Filters(scope="india", source=src), NOW)} == {"india"}
        assert {r.scope for r in vm.apply_filters(rows, vm.Filters(scope="outside", source=src), NOW)} == {"outside"}
    assert all(r.source == "Naukri" and r.scope == "india" and r.employment_type == "Permanent"
               for r in vm.apply_filters(rows, vm.Filters(scope="india", source="Naukri", employment="Permanent"), NOW))
    assert all(r.state == "" for r in outside)                      # only India jobs carry a state


def test_two_country_and_missing_locations_are_not_guessed():
    for loc in ("Pune, India / Dubai", "Mumbai, India and London, United Kingdom", None, "", "Remote", "Anywhere"):
        r = check_location(loc)
        assert not r.is_india and r.country is None, loc
    assert check_location("Pune, Maharashtra, India").is_india and check_location("Hyderabad, Sindh, Pakistan").country == "Pakistan"


def test_the_chosen_scope_is_kept_by_sort_links_and_paging():
    f = vm.Filters.from_query({"scope": ["india"]})
    assert "scope=india" in views.list_href(f, sort="title") and "scope=india" in views.list_href(f, page=2)
    assert "scope%3Dindia" in views.detail_href("k", f)
    assert views.list_href(vm.Filters.from_query({}), sort="title") == "/?sort=title"           # nothing chosen: nothing added
    assert "scope=outside" in views.list_href(vm.Filters.from_query({"scope": ["outside"]}), page=2)
    assert views.list_href(vm.Filters.from_query({"scope": ["all"]}), page=2).count("scope=all") == 1


def test_scope_survives_paging_in_the_last_request_view(tmp_path):
    """With a last "N vacancies" request on screen the page defaults to All locations; picking Within India must stick."""
    recs = [make_record(i, f"Job {i}", "Acme Bank", location="Pune, Maharashtra, India" if i % 2 else "Dubai, United Arab Emirates")
            for i in range(1, 31)]
    app, mgr = make_app(tmp_path, collection=True)
    app.history.ingest(recs, now=NOW)
    mgr._update(result_keys=[e["key"] for e in app.history.list_jobs()], target=30, collected_unique=30, state="succeeded")
    srv = serve(app)
    try:
        port = srv.server_address[1]
        assert row_count(get(port, "/")[2]) > 0
        first = get(port, "/?scope=india")[2]
        assert set(titles(first)) <= {f"Job {i}" for i in range(1, 31, 2)}
        nxt = re.search(r'href="(/\?[^"]*page=2[^"]*)"', first)
        if nxt:
            page2 = get(port, nxt.group(1).replace("&amp;", "&"))[2]
            assert set(titles(page2)) <= {f"Job {i}" for i in range(1, 31, 2)}
        srt = re.search(r'href="(/\?[^"]*sort=title[^"]*)"', first)
        assert srt and "scope=india" in srt.group(1)
        assert set(titles(get(port, "/?scope=outside")[2])) <= {f"Job {i}" for i in range(2, 31, 2)}
    finally:
        srv.shutdown(); srv.server_close()


# ---- 4. Restart --------------------------------------------------------------------------------------------------
def test_boot_id_endpoint_and_restart_page(tmp_path):
    fired = []
    app, _ = make_app(tmp_path, restart=lambda: fired.append(1))
    srv = serve(app)
    try:
        port = srv.server_address[1]
        boot = json.loads(get(port, "/app/boot")[2])["boot"]
        assert boot == app.boot_id and len(boot) == 32
        status, _, html = call(port, "POST", "/app/restart", {})
        assert status == 200 and f'data-boot="{boot}"' in html and "Restarting" in html
        time.sleep(1.2)
        assert fired == [1]                                                  # the restart hook ran, once
        js = (ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
        assert "/app/boot" in js and "window.location.href = '/'" in js       # reopens the dashboard (no filters in the address)
    finally:
        srv.shutdown(); srv.server_close()


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _boot(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/app/boot", timeout=1.5) as r:
            return json.loads(r.read())["boot"]
    except Exception:
        return None


def test_the_restart_button_really_starts_a_new_dashboard_process_and_keeps_all_data(tmp_path):
    h = JsonJobHistory(tmp_path / "job_history.json")
    h.ingest([make_record(1), make_record(2, "Officer")], now=NOW)
    st = JsonRecruiterState(tmp_path / "recruiter_state.json", now_fn=lambda: NOW)
    st.set_status("linkedin-1", "Reviewing")
    files = [tmp_path / "job_history.json", tmp_path / "recruiter_state.json"]
    assert files[1].exists()
    before = [md5(f) for f in files]
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(ROOT / "run_dashboard.py"), "--data-dir", str(tmp_path), "--port", str(port)],
                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        first = None
        for _ in range(100):
            first = _boot(port)
            if first or proc.poll() is not None:
                break
            time.sleep(0.2)
        assert first, "dashboard did not start"
        status, _, _ = call(port, "POST", "/app/restart", {})
        assert status == 200
        second = None
        for _ in range(150):
            second = _boot(port)
            if second and second != first:
                break
            time.sleep(0.2)
        assert second and second != first, "a new dashboard process did not come up"       # a different process answered
        assert proc.poll() is None                                                          # same process id, replaced in place
        assert get(port, "/")[0] == 200
        assert [md5(f) for f in files] == before                                            # saved jobs and recruiter state untouched
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
