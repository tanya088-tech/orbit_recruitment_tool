"""End-to-end tests: a real dashboard server on a random local port, driven over HTTP."""
import contextlib
import http.client
import json
import re
import threading
import urllib.parse
from datetime import timedelta
from http.server import ThreadingHTTPServer

from dashboard.server import DashboardApp, make_handler, safe_next, safe_q
from store.json_store import JsonJobHistory, JsonRecruiterState
from tests.factories import NOW, make_record, standard_records

KEYS = {"A": "linkedin-1001", "B": "linkedin-1002", "C": "linkedin-1003", "D": "linkedin-1004", "E": "linkedin-1005", "F": "linkedin-1006"}


@contextlib.contextmanager
def running(tmp_path, records=None, second_run=None):
    """Start the dashboard. Run 1 holds `records`; run 2 (an hour ago) holds `second_run` (these become 'New')."""
    s = standard_records()
    first = records if records is not None else [s[k] for k in "ABCD"]
    second = second_run if second_run is not None else [s["C"], s["E"], s["F"]]
    history = JsonJobHistory(tmp_path / "job_history.json")
    history.ingest(first, now=NOW - timedelta(days=2))
    if second:
        history.ingest(second, now=NOW - timedelta(hours=1))
    state = JsonRecruiterState(tmp_path / "recruiter_state.json", now_fn=lambda: NOW)
    app = DashboardApp(history, state, now_fn=lambda: NOW)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1], app
    finally:
        srv.shutdown()
        srv.server_close()


def call(port, method, path, form=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = dict(headers or {})
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form)
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, path, body=body, headers=hdrs)
    r = conn.getresponse()
    text = r.read().decode("utf-8")
    out = (r.status, {k.lower(): v for k, v in r.getheaders()}, text)
    conn.close()
    return out


def get(port, path):
    return call(port, "GET", path)


def titles(html):
    return re.findall(r'class="job-link"[^>]*>([^<]+)<', html)


def row_count(html):
    return html.count('<tr class="fresh-')


# ------------------------------------------------------------------ page 1
def test_summary_page_has_cards_filters_table_and_security_headers(tmp_path):
    with running(tmp_path) as (port, _):
        status, headers, html = get(port, "/")
        assert status == 200 and "script-src 'self'" in headers["content-security-policy"]
        for label in ["Total openings", "Permanent openings", "Contract openings"]:
            assert f"<span>{label}</span>" in html, label
        for label in ["Location scope", "State", "Employment type", "Work mode", "Source"]:
            assert f">{label}</label>" in html, label
        for gone in ['for="f-posted"', "Job posted</label>"]:
            assert gone not in html, gone
        for gone in ["Company</label>", "Job title or keyword", "GCC / BFSI", "GCC vacancies", "BFSI vacancies", "New vacancies", "Recruitment status"]:
            assert gone not in html, gone
        for opt in ["Within India", "Outside India", "All locations", "Last 24 hours", "Last 3 days", "Last 7 days",
                    "Last 30 days", "All", "Permanent", "Contract", "On-site", "Hybrid", "Remote"]:
            assert f">{opt}</option>" in html, opt
        for col in ["Job title", "Company", "Location", "Industry", "Employment type", "Posted", "Source"]:
            assert col in html
        assert row_count(html) == 6 and html.count("View details") == 6
        figs = dict((label, int(n)) for n, label in re.findall(r"<b>(\d+)</b><span>([^<]+)</span>", html))
        assert figs == {"Total openings": 6, "Permanent openings": 4, "Contract openings": 2}
        assert 'name="employment"' in html and 'name="status"' not in html


def test_new_badge_only_on_jobs_first_found_in_latest_run(tmp_path):
    with running(tmp_path) as (port, _):
        html = get(port, "/")[2]
        new_rows = [r for r in html.split('<tr class="fresh-')[1:] if 'badge-new' in r]
        assert len(new_rows) == 2
        assert {"Payments Associate", "Treasury Analyst"} == {titles(r)[0] for r in new_rows}
        assert "5 new" not in html and "2 new, 1 already existing" in html      # header summarises the last run


def test_default_sort_newest_first_and_other_sorts(tmp_path):
    with running(tmp_path) as (port, _):
        assert titles(get(port, "/")[2]) == ["Credit Risk Analyst", "Technology Lead GCC", "Payments Associate",
                                             "KYC Analyst", "Insurance Underwriter", "Treasury Analyst"]
        assert titles(get(port, "/?sort=oldest")[2])[0] == "Insurance Underwriter"
        assert titles(get(port, "/?sort=title")[2])[:2] == ["Credit Risk Analyst", "Insurance Underwriter"]
        company_sorted = get(port, "/?sort=company")[2]
        assert titles(company_sorted)[0] in ("Credit Risk Analyst", "KYC Analyst", "Treasury Analyst")   # Acme Bank first


def test_filters_over_http(tmp_path):
    with running(tmp_path) as (port, _):
        t = lambda q: set(titles(get(port, "/?" + q)[2]))
        # Source and Job posted are no longer dashboard filters: links that still carry them show everything
        for gone in ("posted=24h", "posted=3d"):
            assert row_count(get(port, "/?" + gone)[2]) == 6, gone
        assert row_count(get(port, "/?source=Naukri")[2]) == 0 and row_count(get(port, "/?source=LinkedIn")[2]) == 6     # the Source filter works
        assert t("work_mode=Remote") == {"Payments Associate"} and row_count(get(port, "/?employment=Remote")[2]) == 6
        assert t("employment=Contract") == {"KYC Analyst", "Insurance Underwriter"}
        assert row_count(get(port, "/?state=Maharashtra&employment=Permanent")[2]) == 2
        # the removed filters are ignored
        for removed in ("classification=gcc", "location=Maharashtra", "company=acme", "keyword=zzz", "status=Reviewing", "saved=1"):
            assert row_count(get(port, "/?" + removed)[2]) == 6, removed
        # cards follow the filters
        html = get(port, "/?employment=Contract")[2]
        assert re.search(r"<b>2</b><span>Total openings", html) and "(1 filter applied, 6 in total)" in html


def test_no_match_and_hostile_filter_values_are_handled(tmp_path):
    with running(tmp_path) as (port, _):
        status, _, html = get(port, "/?state=Nowhere&employment=Contract")
        assert status == 200 and "No vacancies match these filters" in html and row_count(html) == 0
        status, _, html = get(port, "/?posted=forever&scope=%3Cscript%3E&page=-9&sort=drop+table&source=%3Cscript%3Ealert(1)%3C/script%3E")
        assert status == 200 and "<script>alert(1)" not in html
        assert row_count(get(port, "/?state=%3Cscript%3E")[2]) == 0 and "<script>" not in get(port, "/?state=%3Cscript%3E")[2]


def test_empty_history_shows_guidance(tmp_path):
    with running(tmp_path, records=[], second_run=[]) as (port, _):
        status, _, html = get(port, "/")
        assert status == 200 and "No vacancies yet" in html and "Run job collection" in html


def test_pagination_over_http(tmp_path):
    many = [make_record(5000 + i, title=f"Role {i:03d}", posted=(NOW - timedelta(minutes=i + 1)).isoformat(timespec="seconds")) for i in range(60)]
    with running(tmp_path, records=many, second_run=[]) as (port, _):
        html = get(port, "/")[2]
        assert row_count(html) == 50 and "Page 1 of 2" in html and 'href="/?page=2"' in html
        assert titles(html)[0] == "Role 000"                                    # newest first
        html2 = get(port, "/?page=2")[2]
        assert row_count(html2) == 10 and "Page 2 of 2" in html2
        assert row_count(get(port, "/?page=999")[2]) == 10                       # clamped to last page


# ------------------------------------------------------------------ page 2
def test_details_page_shows_every_required_field(tmp_path):
    with running(tmp_path) as (port, _):
        status, _, html = get(port, f"/job/{KEYS['A']}")
        assert status == 200
        for needle in ["Credit Risk Analyst", "Acme Bank", "Pune, Maharashtra, India", "Banking, Financial Services &amp; Insurance (BFSI)", "Financial Services", "Permanent",
                       "LinkedIn", "1001", "Just now", "Estimated from the source", "Open Original Job", "Original job URL",
                       "Job summary", "Full job description", "Save job", "Recruitment status", "Add a note"]:
            assert needle in html, needle
        assert "Line 1 of the description." in html and "Line 2 about &lt;b&gt;risk&lt;/b&gt; models." in html   # full text, escaped
        assert "<b>risk</b>" not in html and "Why this is flagged" not in html and "GCC" not in html
        for status_name in ["New", "Reviewing", "Candidate Search Started", "Candidate Found", "Submitted", "Closed", "Not Relevant"]:
            assert f">{status_name}</option>" in html


def test_original_link_is_correct_and_safe(tmp_path):
    with running(tmp_path) as (port, _):
        html = get(port, f"/job/{KEYS['A']}")[2]
        assert re.search(r'<a class="btn btn-primary" href="https://www\.linkedin\.com/jobs/view/1001" target="_blank" rel="noopener noreferrer">Open Original Job</a>', html)
    bad = [make_record(7001, "Bad link job", job_url="javascript:alert(1)"), make_record(7002, "No link job", job_url=None)]
    with running(tmp_path / "x", records=bad, second_run=[]) as (port, _):
        for key in ("linkedin-7001", "linkedin-7002"):
            html = get(port, f"/job/{key}")[2]
            assert "Original link not available" in html and "javascript:" not in html


def test_details_page_with_missing_data(tmp_path):
    empty = {"source": "LinkedIn", "job_id": "8001", "job_url": "https://www.linkedin.com/jobs/view/8001"}
    with running(tmp_path, records=[empty], second_run=[]) as (port, _):
        status, _, html = get(port, "/job/linkedin-8001")
        assert status == 200 and "Untitled vacancy" in html
        assert html.count("Not available") >= 4 and "LinkedIn did not provide a description" in html
        assert "Unknown" in html and "Key responsibilities" in html
        summary = get(port, "/")[2]
        assert row_count(summary) == 0 and "hidden by the location scope" in summary
        assert row_count(get(port, "/?scope=all")[2]) == 1
    # an India job with every other field missing is listed and does not break the page
    bare = {"source": "LinkedIn", "job_id": "8002", "country": "India", "location": "India",
            "job_url": "https://www.linkedin.com/jobs/view/8002"}
    with running(tmp_path / "b", records=[bare], second_run=[]) as (port, _):
        summary = get(port, "/")[2]
        assert row_count(summary) == 1 and "Untitled vacancy" in summary


def test_back_link_keeps_filters_and_rejects_hostile_q(tmp_path):
    with running(tmp_path) as (port, _):
        html = get(port, "/?state=Maharashtra&employment=Permanent")[2]
        link = re.search(r'href="(/job/linkedin-1001\?q=[^"]*)"', html).group(1)
        detail = get(port, link.replace("&amp;", "&"))[2]
        back = re.search(r'<a href="(/\?[^"]*)">Back to vacancies</a>', detail).group(1)
        assert "state=Maharashtra" in back and "employment=Permanent" in back
        evil = get(port, f"/job/{KEYS['A']}?q=" + urllib.parse.quote("<script>alert(1)</script>"))[2]
        assert '<a href="/">Back to vacancies</a>' in evil


def test_html_injection_is_escaped_everywhere(tmp_path):
    xss = make_record(9001, title="<script>alert('t')</script>", company="<img src=x onerror=alert(1)>", location="<b>Pune</b>, India",
                      description="<script>alert('d')</script>", classification_reason="<script>alert('r')</script>")
    with running(tmp_path, records=[xss], second_run=[]) as (port, app):
        app.state.add_note("linkedin-9001", "<script>alert('note')</script>")
        for path in ("/", "/job/linkedin-9001"):
            html = get(port, path)[2]
            assert "<script>alert" not in html and "<img src=x" not in html and "<b>Pune</b>" not in html
            assert "&lt;script&gt;" in html


# ------------------------------------------------------------------ save / status / notes
def test_save_toggle_persists_and_filters(tmp_path):
    with running(tmp_path) as (port, app):
        status, headers, _ = call(port, "POST", f"/job/{KEYS['A']}/save", {"saved": "1"})
        assert status == 303 and headers["location"] == f"/job/{KEYS['A']}"
        assert app.state.get(KEYS["A"])["saved"] is True
        assert "Remove from saved jobs" in get(port, f"/job/{KEYS['A']}")[2]
        assert "Saved</span>" in get(port, f"/job/{KEYS['A']}")[2]
        assert 'aria-label="Remove from saved jobs"' in get(port, "/")[2]
        call(port, "POST", f"/job/{KEYS['A']}/save", {"saved": "0"})
        assert app.state.get(KEYS["A"])["saved"] is False and "Remove from saved jobs" not in get(port, f"/job/{KEYS['A']}")[2]


def test_save_from_table_star_returns_to_the_same_list_view(tmp_path):
    with running(tmp_path) as (port, _):
        status, headers, _ = call(port, "POST", f"/job/{KEYS['B']}/save", {"saved": "1", "next": "/?posted=24h&page=1"})
        assert status == 303 and headers["location"] == "/?posted=24h&page=1"


def test_status_change_persists_shows_and_filters(tmp_path):
    with running(tmp_path) as (port, app):
        for st in ["Reviewing", "Candidate Search Started", "Candidate Found", "Submitted", "Closed", "Not Relevant", "New"]:
            assert call(port, "POST", f"/job/{KEYS['C']}/status", {"status": st})[0] == 303
            assert app.state.get(KEYS["C"])["status"] == st
        call(port, "POST", f"/job/{KEYS['C']}/status", {"status": "Candidate Found"})
        assert "status-Candidate-Found" in get(port, f"/job/{KEYS['C']}")[2]
        assert row_count(get(port, "/?status=Candidate+Found")[2]) == 6            # no status filter any more
        assert 'status-Candidate-Found">Candidate Found' in get(port, "/")[2]
        status, _, html = call(port, "POST", f"/job/{KEYS['C']}/status", {"status": "Hired"})
        assert status == 400 and "invalid status" in html
        assert app.state.get(KEYS["C"])["status"] == "Candidate Found"


def test_notes_add_show_delete_validate_and_persist(tmp_path):
    with running(tmp_path) as (port, app):
        assert call(port, "POST", f"/job/{KEYS['D']}/notes", {"note": "Spoke to <b>HR</b>"})[0] == 303
        call(port, "POST", f"/job/{KEYS['D']}/notes", {"note": "Second note"})
        html = get(port, f"/job/{KEYS['D']}")[2]
        assert "Spoke to &lt;b&gt;HR&lt;/b&gt;" in html and "Second note" in html and "Notes (2)" in html
        assert html.index("Second note") < html.index("Spoke to")                 # newest first
        assert call(port, "POST", f"/job/{KEYS['D']}/notes", {"note": "   "})[0] == 400
        assert call(port, "POST", f"/job/{KEYS['D']}/notes", {"note": "x" * 2001})[0] == 400
        note_id = app.state.get(KEYS["D"])["notes"][0]["id"]
        assert call(port, "POST", f"/job/{KEYS['D']}/notes/{note_id}/delete", {})[0] == 303
        assert [n["text"] for n in app.state.get(KEYS["D"])["notes"]] == ["Second note"]
    # a brand-new server on the same files still has the data
    with running(tmp_path) as (port2, _):
        pass
    again = JsonRecruiterState(tmp_path / "recruiter_state.json").get(KEYS["D"])
    assert [n["text"] for n in again["notes"]] == ["Second note"]


def test_recruiter_work_survives_a_new_scraper_run(tmp_path):
    with running(tmp_path) as (port, app):
        call(port, "POST", f"/job/{KEYS['A']}/save", {"saved": "1"})
        call(port, "POST", f"/job/{KEYS['A']}/status", {"status": "Reviewing"})
        call(port, "POST", f"/job/{KEYS['A']}/notes", {"note": "keep me"})
        app.history.ingest([standard_records()["A"], make_record(2001, "Brand new job")], now=NOW)    # next scraper run re-finds A
        html = get(port, "/")[2]
        assert row_count(html) == 7                                               # A not duplicated, one new job added
        detail = get(port, f"/job/{KEYS['A']}")[2]
        assert "Reviewing" in detail and "keep me" in detail and "Remove from saved jobs" in detail
        assert "Found in 2 scraper runs" in detail


# ------------------------------------------------------------------ safety & errors
def test_redirect_targets_are_validated(tmp_path):
    assert safe_next("/?posted=24h") == "/?posted=24h"
    for bad in ["https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)", "", "/a\nb", "/é"]:
        assert safe_next(bad, "/fallback") == "/fallback"
    assert safe_q("posted=24h&company=Goldman+Sachs") and safe_q("<script>") == ""
    with running(tmp_path) as (port, _):
        for evil in ["https://evil.com", "//evil.com"]:
            _, headers, _ = call(port, "POST", f"/job/{KEYS['A']}/save", {"saved": "1", "next": evil})
            assert headers["location"] == f"/job/{KEYS['A']}"


def test_cross_site_form_posts_are_blocked(tmp_path):
    with running(tmp_path) as (port, app):
        status, _, _ = call(port, "POST", f"/job/{KEYS['A']}/save", {"saved": "1"}, headers={"Origin": "http://evil.example"})
        assert status == 403 and app.state.get(KEYS["A"])["saved"] is False
        ok, _, _ = call(port, "POST", f"/job/{KEYS['A']}/save", {"saved": "1"}, headers={"Origin": f"http://127.0.0.1:{port}"})
        assert ok == 303


def test_unknown_pages_jobs_and_static_files(tmp_path):
    with running(tmp_path) as (port, app):
        assert get(port, "/nope")[0] == 404 and get(port, "/job/linkedin-424242")[0] == 404
        assert call(port, "POST", "/job/linkedin-424242/save", {"saved": "1"})[0] == 404
        assert call(port, "POST", "/job/bad%20key!/save", {"saved": "1"})[0] == 404
        assert call(port, "POST", "/", {"x": "1"})[0] == 404
        assert app.state.get_all() == {}                                           # nothing was written
        status, headers, css = get(port, "/static/style.css")
        assert status == 200 and headers["content-type"].startswith("text/css") and "--ember" in css
        assert get(port, "/static/app.js")[0] == 200
        for path in ["/static/../server.py", "/static/..%2Fserver.py", "/static/secret.txt", "/static/"]:
            assert get(port, path)[0] == 404
        assert get(port, "/healthz")[2] == "ok"


def test_corrupt_recruiter_file_gives_a_clear_error_not_a_crash(tmp_path):
    with running(tmp_path) as (port, _):
        (tmp_path / "recruiter_state.json").write_text("{ broken")
        status, _, html = get(port, "/")
        assert status == 500 and "Could not read saved data" in html and "recruiter_state.json" in html
        assert (tmp_path / "recruiter_state.json").read_text() == "{ broken"      # never overwritten


def test_every_collected_job_is_listed_by_scope_and_kpis_follow_filters(tmp_path):
    """Pan-India and international jobs all reach the dashboard; the scope and other filters narrow them."""
    s = standard_records()
    extra = [
        make_record(2001, "Marketing Manager", "Retail Co", "Mumbai, Maharashtra, India", "Permanent", False, False, posted=ago_days(20)),
        make_record(2002, "Old Treasury Role", "Acme Bank", "Kolkata, West Bengal, India", "Contract", False, True, posted=ago_days(40)),
        make_record(2003, "Abroad Analyst", "UK Bank", "London, England, United Kingdom", "Contract", False, True, country="United Kingdom"),
        make_record(2004, "Dubai Banker", "Gulf Bank", "Dubai, United Arab Emirates", "Permanent", False, True, country="United Arab Emirates"),
    ]
    figs = lambda h: dict((label, int(n)) for n, label in re.findall(r"<b>(\d+)</b><span>([^<]+)</span>", h))
    with running(tmp_path, records=list(s.values()) + extra, second_run=[]) as (port, _):
        html = get(port, "/")[2]
        assert row_count(html) == 8 and "Abroad Analyst" not in html            # default: within India
        assert "2 other collected jobs are hidden by the location scope" in html
        assert figs(html) == {"Total openings": 8, "Permanent openings": 5, "Contract openings": 3}
        out = get(port, "/?scope=outside")[2]
        assert set(titles(out)) == {"Abroad Analyst", "Dubai Banker"} and figs(out)["Total openings"] == 2
        assert figs(out)["Contract openings"] == 1 and "hidden by the location scope" in out
        allh = get(port, "/?scope=all")[2]
        assert row_count(allh) == 10 and figs(allh)["Total openings"] == 10 and "hidden by the location scope" not in allh
        assert figs(get(port, "/?scope=all&employment=Contract")[2])["Total openings"] == 4


def ago_days(n):
    from tests.factories import ago
    return ago(days=n)
