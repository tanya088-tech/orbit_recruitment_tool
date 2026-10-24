"""Naukri: parsers (real-structure fixtures), URLs, the browser client and the shared search loop."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from config import settings
from collectors.browser_client import BrowserClient, looks_blocked
from collectors.collector import Collector
from collectors.errors import BlockedError, NotFoundError, SetupError
from collectors.naukri import detail_parser as nk_detail, search_parser as nk_search
from collectors.naukri.source import NaukriSource, age_filter, search_url as nk_url
from collectors.registry import available_sources, get_source
from models.job import RunStats, SearchParams

FIX = Path(__file__).parent / "fixtures"
read = lambda n: (FIX / n).read_text(encoding="utf-8")


def fresh(html):
    """The fixture's posting date moves to today, so the tests that search 'the last 1 day' do not expire as the calendar moves on."""
    from datetime import date
    return html.replace("2026-10-12", date.today().isoformat())


# -- Naukri parsers ---------------------------------------------------------
def test_naukri_cards_are_read_completely():
    stubs = nk_search.parse_search_results(read("naukri_search.html"))
    assert [s["job_id"] for s in stubs] == ["091026021155", "250926916028"]   # card without an id is skipped
    a, b = stubs
    assert a["title"] == "Junior Banking Officer (Fresher)" and a["company"] == "Axis Bank"
    assert a["location"] == "Kolkata(Hooghly)" and a["experience"] == "0 Yrs" and a["salary"] == "3.25-4.25 Lacs PA"
    assert a["skills"] == ["Branch Banking Operations", "Customer Service"]
    assert "?" not in a["job_url"] and a["posted_age_text"] == "2 days ago"
    assert b["salary"] is None and b["location"] == "Agartala, Gangtok" and b["experience"] == "0-2 Yrs"
    assert b["posted_date"] is not None


def test_naukri_detail_prefers_visible_header_over_misleading_json_ld():
    d = nk_detail.parse_job_detail(read("naukri_detail.html"))
    assert d["title"] == "ICICI Bank Probationary Officer Program" and d["company"] == "ICICI Bank"
    assert d["experience"] == "0 - 2 years"                       # NOT the JSON-LD "1 month"
    assert d["salary"] is None                                    # "Not Disclosed" is not a salary
    assert d["location"] == "Agartala, Gangtok"
    assert d["posted_date"] == date(2026, 10, 9) and d["posted_age_text"] == "2 days ago"
    assert d["employment_type"] == "Full-time" and d["job_role"] == "Probationary Officer"
    assert d["industries"] == "Banking" and d["job_function"] == "Sales & Business Development"
    assert d["skills"] == ["Banking", "Sales"]
    assert "Sell banking products" in d["description"] and "LD fallback" not in d["description"]
    assert d["raw"]["applicants"] == "100+"


def test_naukri_detail_falls_back_to_json_ld_when_markup_changes():
    html = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Analyst","datePosted":"2026-10-01",'
            '"hiringOrganization":{"name":"HDFC"},"description":"<p>Real text</p>","skills":["a","b"]}</script>')
    d = nk_detail.parse_job_detail(html)
    assert (d["title"], d["company"], d["description"], d["skills"]) == ("Analyst", "HDFC", "Real text", ["a", "b"])
    assert d["experience"] is None and d["salary"] is None        # not invented


def test_naukri_empty_page_gives_nothing_not_errors():
    assert nk_search.parse_search_results("<html></html>") == []
    d = nk_detail.parse_job_detail("<html></html>")
    assert d["title"] is None and d["description"] is None and d["skills"] == []


# -- URLs ------------------------------------------------------------------------
def test_naukri_urls():
    u = nk_url(SearchParams("bank OR fintech", "Pune, India", days=3), 0)
    assert u == "https://www.naukri.com/bank-jobs-in-pune?k=bank&l=pune&jobAge=3&sort=f"       # ONE keyword per URL
    assert "," not in nk_url(SearchParams("GCC OR bank OR financial services", "India", days=1), 0)
    assert nk_url(SearchParams("GCC OR bank OR financial services", "India", days=1), 0) == "https://www.naukri.com/gcc-jobs?k=GCC&jobAge=1&sort=f"
    assert nk_url(SearchParams("financial services", "Pune, India", days=1), 0) == \
        "https://www.naukri.com/financial-services-jobs-in-pune?k=financial%20services&l=pune&jobAge=1&sort=f"
    assert nk_url(SearchParams("banking", "India", days=1), 1) == "https://www.naukri.com/banking-jobs-2?k=banking&jobAge=1&sort=f"
    assert [age_filter(d) for d in (1, 2, 5, 8, 20, 90)] == [1, 3, 7, 15, 30, 30]


def test_registry_has_both_sources():
    assert available_sources() == ["linkedin", "naukri"]
    assert get_source("Naukri", client=object()).name == "naukri"


# -- browser client -------------------------------------------------------------------
class FakePage:
    def __init__(self, html="<html><body>ok</body></html>", status=200, title="Jobs"):
        self.html, self.status, self.t, self.visited, self.clicked = html, status, title, [], []

    def goto(self, url, **kw):
        self.visited.append(url)
        return type("R", (), {"status": self.status})()

    def wait_for_selector(self, sel, timeout=0):
        pass

    def query_selector_all(self, sel):
        page = self
        class El:
            def click(self, timeout=0):
                page.clicked.append(sel)
        return [El()]

    def content(self):
        return self.html

    def title(self):
        return self.t


def client(page):
    return BrowserClient(delay_min=0, delay_max=0, page_factory=lambda: page, sleep=lambda s: None)


def test_browser_client_returns_html_and_expands_buttons():
    page = FakePage()
    assert "ok" in client(page).get("https://x.test/a", params={"q": 1}, expand=["button.more"])
    assert page.visited == ["https://x.test/a?q=1"] and page.clicked == ["button.more"]


def test_browser_client_stops_on_challenge_pages_and_blocking_statuses():
    for page in (FakePage(title="Security Check"), FakePage(html="<title>Just a moment...</title>"), FakePage(status=403), FakePage(status=429)):
        with pytest.raises(BlockedError):
            client(page).get("https://x.test")
    with pytest.raises(NotFoundError):
        client(FakePage(status=404)).get("https://x.test")
    assert not looks_blocked("Jobs", "<title>Jobs</title><p>Background and security check, captcha-solving a plus</p>")
    assert looks_blocked("", '<script src="/cdn-cgi/challenge-platform/x"></script>')


def test_missing_playwright_is_a_setup_error(monkeypatch=None):
    import sys
    saved = sys.modules.get("playwright.sync_api")
    sys.modules["playwright.sync_api"] = None          # makes the import fail
    try:
        with pytest.raises(SetupError):
            BrowserClient(delay_min=0, delay_max=0).get("https://x.test")
    finally:
        if saved is None:
            sys.modules.pop("playwright.sync_api", None)
        else:
            sys.modules["playwright.sync_api"] = saved


# -- the shared search loop, run on fixtures -------------------------------------------
class ScriptedPage(FakePage):
    """Serves search pages / job pages from fixtures by URL."""
    def __init__(self, routes):
        super().__init__()
        self.routes = routes

    def goto(self, url, **kw):
        self.visited.append(url)
        for key, html in self.routes.items():
            if key in url:
                self.html = html
                return type("R", (), {"status": 200})()
        self.html = "<html></html>"
        return type("R", (), {"status": 200})()


def test_naukri_source_end_to_end_on_fixtures():
    page = ScriptedPage({"-jobs": read("naukri_search.html"), "job-listings": read("naukri_detail.html")})
    page.routes = {"job-listings-icici": read("naukri_detail.html"), "job-listings-junior": read("naukri_detail.html"),
                   "naukri.com/bank-jobs": read("naukri_search.html")}
    res = Collector(NaukriSource(client=client(page))).run(
        [SearchParams("bank", "India", days=365, max_pages=1)])
    assert [j.job_id for j in res.jobs] == ["091026021155", "250926916028"]
    j = res.jobs[1]
    assert j.source == "Naukri" and j.experience == "0 - 2 years" and j.skills == ["Banking", "Sales"] and j.salary is None
    assert j.employment_type == "Full-time" and j.posted_date == date(2026, 10, 9)
    assert "Sell banking products" in j.description
    assert res.stats.collected == 2 and not res.stats.blocked


def test_source_reports_setup_needed_instead_of_crashing():
    class NoBrowser:
        def get(self, *a, **k):
            raise SetupError("install playwright")
    res = Collector(NaukriSource(client=NoBrowser())).run([SearchParams("bank", "India", days=3)])
    assert res.stats.setup_error == "install playwright" and not res.stats.blocked and res.jobs == []


def test_count_known_and_skip_ids_work_for_new_sources():
    page = ScriptedPage({"job-listings": read("naukri_detail.html"), "naukri.com/bank-jobs": read("naukri_search.html")})
    p = SearchParams("bank", "India", days=365, max_jobs=2, max_pages=1, count_known=True)
    res = Collector(NaukriSource(client=client(page))).run([p], skip_ids={"091026021155"})
    assert res.stats.latest_ids == ["091026021155", "250926916028"] and [j.job_id for j in res.jobs] == ["250926916028"]


def test_naukri_jobs_flow_through_normalisation_with_all_fields():
    from processing.pipeline import normalize_all
    page = ScriptedPage({"job-listings": read("naukri_detail.html"), "naukri.com/bank-jobs": read("naukri_search.html")})
    nk = Collector(NaukriSource(client=client(page))).run([SearchParams("bank", "India", days=365, max_pages=1)]).jobs
    assert len(nk) == 2
    run = normalize_all([j.to_dict() for j in nk])
    assert len(run.jobs) == 2 and not run.failed
    n = next(r for r in run.jobs if r["job_id"] == "250926916028")
    assert n["source"] == "Naukri" and n["experience"] == "0 - 2 years" and n["skills"] == ["Banking", "Sales"]
    assert n["posted_at"] == "2026-10-09" and n["employment_type"] == "Permanent"


def test_indeed_is_no_longer_a_source():
    from collectors.registry import available_sources
    assert "indeed" not in available_sources() and "Indeed" not in settings.SUPPORTED_SOURCES


def test_a_refusal_says_what_the_page_displayed():
    class P(FakePage):
        def inner_text(self, sel):
            return "Access Denied. You don't have permission to access this page"
    for page in (P(status=403, title="Access Denied"),):
        try:
            client(page).get("https://x.test")
            assert False, "expected BlockedError"
        except BlockedError as exc:
            assert "HTTP 403" in str(exc) and "Access Denied" in str(exc)


def test_a_js_redirect_to_a_session_endpoint_is_reported_with_both_urls():
    from collectors.browser_client import redirected_to_gate
    class Redirected(FakePage):
        url = "https://www.naukri.com/auth;jsessionid=node01abc"
        def inner_text(self, sel):
            return "HTTP ERROR 400 Bad Request URI: /auth;jsessionid=node01abc"
    page = Redirected(title="Error 400")
    try:
        client(page).get("https://www.naukri.com/bank-jobs?k=bank")
        assert False, "expected BlockedError"
    except BlockedError as exc:
        msg = str(exc)
        assert "requested=https://www.naukri.com/bank-jobs?k=bank" in msg and "final=https://www.naukri.com/auth;jsessionid=node01abc" in msg
        assert "sign-in" in msg and "400" in msg
    assert redirected_to_gate("https://www.naukri.com/bank-jobs", "https://www.naukri.com/nlogin/login")
    assert not redirected_to_gate("https://www.naukri.com/bank-jobs", "https://www.naukri.com/bank-jobs-2")
    assert not redirected_to_gate("https://www.naukri.com/bank-jobs", "https://www.naukri.com/bank-jobs")


def test_http_400_error_message_carries_the_diagnosis():
    try:
        client(FakePage(status=400, title="Bad Request")).get("https://x.test/a")
        assert False
    except Exception as exc:
        assert "requested=https://x.test/a" in str(exc) and "status=400" in str(exc)


# -- the real "Operations Coordinator - Procurement" listing (page structure captured from naukri.com) -------------
def test_procurement_listing_every_visible_field_is_captured():
    from collectors.naukri.detail_parser import completeness_gaps
    html = read("naukri_detail_procurement.html")
    d = nk_detail.parse_job_detail(html)
    assert d["title"] == "Operations Coordinator - Procurement"
    assert d["company"] == "Confidential" and d["posted_by"] == "Aarons Visions"
    assert d["experience"] == "7 - 12 years"                       # visible text; JSON-LD says 84 months
    assert d["salary"] == "18-33 Lacs P.A."
    assert d["work_mode_text"] == "Hybrid"
    assert d["location"] == "Chennai, Bengaluru, Mumbai (All Areas)"
    assert d["posted_age_text"] == "Just now" and d["posted_date"] == date(2026, 10, 12)
    assert d["openings"] == "1" and d["applicants"] == "Less than 10"
    assert d["employment_details"] == "Full Time, Permanent" and d["employment_type"] == "Full-time"
    assert d["job_role"] == "Purchase Executive / Officer" and d["role_category"] == "Procurement & Purchase"
    assert d["job_function"] == "Procurement & Supply Chain" and d["industries"] == "Petrochemical / Plastics / Rubber"
    assert d["education"] == "UG: Any Graduate"
    assert len(d["skills"]) == 14 and d["skills"][0] == "Procurement" and d["skills"][-1] == "procurement report"
    desc = d["description"]
    assert desc.startswith("Preparation and coordination of MIS reports.") and desc.rstrip().endswith("Advance Excel is a must.")
    assert 230 <= len(desc) <= 260 and "Role:" not in desc and "Key Skills" not in desc      # the real description is this short
    assert "Continue with Google" not in desc and "Read more" not in desc
    assert completeness_gaps(html, {**d}) == []


def test_completeness_check_reports_what_the_page_shows_but_was_missed():
    from collectors.naukri.detail_parser import completeness_gaps
    html = read("naukri_detail_procurement.html")
    d = nk_detail.parse_job_detail(html)
    d.update(openings=None, education=None, work_mode_text=None, description="Preparation only")
    gaps = " | ".join(completeness_gaps(html, d))
    assert "Openings" in gaps and "Education" in gaps and "work-mode" in gaps and "description on page" in gaps


def test_employment_labels():
    from collectors.naukri.detail_parser import employment_label
    cases = {"Full Time, Permanent": "Full-time", "Full Time, Contractual": "Contract", "Part Time, Permanent": "Part-time",
             "Internship": "Internship", "Temporary": "Temporary", "Walk-in": None, None: None}
    for raw, want in cases.items():
        assert employment_label(raw) == want, raw


def test_procurement_job_flows_to_history_and_the_details_page(tmp_path):
    from processing.pipeline import normalize_all
    from dashboard import views, viewmodel as vm
    from models.job import Job
    from store.json_store import JsonJobHistory
    from tests.factories import NOW
    d = nk_detail.parse_job_detail(read("naukri_detail_procurement.html"))
    stub = {"job_id": "280426921786", "job_url": "https://www.naukri.com/job-listings-operations-coordinator-procurement-aarons-visions-chennai-bengaluru-mumbai-all-areas-7-to-12-years-280426921786",
            "title": "Operations Coordinator - Procurement", "company": "Confidential", "location": "Chennai", "posted_age_text": "Just now",
            "posted_date": date(2026, 10, 12), "raw": "<div/>", "skills": []}
    job = NaukriSource(client=object()).build_job(stub, d)
    run = normalize_all([job.to_dict()])
    rec = run.jobs[0]
    assert rec["work_mode"] == "Hybrid" and rec["employment_type"] == "Permanent"       # Hybrid comes from the page's own badge
    assert rec["openings"] == "1" and rec["education"] == "UG: Any Graduate" and rec["posted_by"] == "Aarons Visions"
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest(run.jobs, now=NOW)
    entry = h.list_jobs()[0]
    row = next(r for r in vm.build_rows([entry], {}, NOW))
    html = views._details_table(row, NOW)
    for text in ("Hybrid", "Full Time, Permanent", "Procurement &amp; Purchase", "Purchase Executive / Officer", "Less than 10",
                 "Aarons Visions", "UG: Any Graduate", "7 - 12 years", "18-33 Lacs P.A.", "MIS Reporting", "Advance Excel is a must"):
        assert text in html, text


# -- dashboard-style collection: several keywords, 403, headless -------------------------------------------------
def test_browser_is_visible_by_default_because_naukri_and_indeed_refuse_headless():
    assert settings.BROWSER_HEADLESS is False


def test_several_keywords_run_as_separate_one_keyword_searches_and_merge_without_repeats():
    page = ScriptedPage({})
    def card(i, t):
        return (f'<div class="srp-jobtuple-wrapper" data-job-id="{i}"><a class="title" title="{t}" href="https://www.naukri.com/job-listings-x-{i}">{t}</a>'
                f'<a class="comp-name">Co</a><span class="job-post-day">Just now</span></div>')
    page.routes = {"gcc-jobs?": "<html>" + card("900000000001", "A") + card("900000000002", "B") + "</html>",
                   "bank-jobs?": "<html>" + card("900000000002", "B") + card("900000000003", "C") + "</html>",
                   "financial-services-jobs?": "<html></html>",
                   "job-listings": fresh(read("naukri_detail_procurement.html"))}
    src = NaukriSource(client=client(page))
    p = SearchParams("GCC OR bank OR financial services", "India", days=1, max_pages=1, max_jobs=3, count_known=True)
    res = Collector(src).run([p])
    searches = [u for u in page.visited if "/jobs" in u or "-jobs?" in u]
    assert [("gcc-jobs?k=GCC" in u) or ("bank-jobs?k=bank" in u) or ("financial-services-jobs?k=financial%20services" in u) for u in searches] == [True] * 3
    assert all("jobAge=1" in u and "sort=f" in u and "," not in u for u in searches)
    assert sorted(j.job_id for j in res.jobs) == ["900000000001", "900000000002", "900000000003"]
    assert res.stats.latest_ids[:3] == ["900000000001", "900000000002", "900000000003"] or len(res.stats.latest_ids) == 3
    assert len([u for u in page.visited if "job-listings" in u]) == 3             # job 2 was found twice, fetched once


def test_a_403_midway_keeps_earlier_keywords_and_reports_the_block_once():
    class P(ScriptedPage):
        def goto(self, url, **kw):
            self.visited.append(url)
            if "bank-jobs?" in url:
                self.html = "<html></html>"
                return type("R", (), {"status": 403})()
            return super().goto(url, **kw)
    card = ('<div class="srp-jobtuple-wrapper" data-job-id="900000000001"><a class="title" title="A" href="https://www.naukri.com/job-listings-x-900000000001">A</a>'
            '<span class="job-post-day">Just now</span></div>')
    page = P({"gcc-jobs?": "<html>" + card + "</html>", "job-listings": fresh(read("naukri_detail_procurement.html"))})
    res = Collector(NaukriSource(client=client(page))).run([SearchParams("GCC OR bank OR financial services", "India", days=1, max_pages=1)])
    assert res.stats.blocked and [j.job_id for j in res.jobs] == ["900000000001"]
    assert len([u for u in page.visited if "bank-jobs?" in u]) == 1            # not retried
    assert not any("financial-services-jobs" in u for u in page.visited)       # the source stopped


def test_stop_midway_keeps_the_jobs_already_fetched_by_earlier_keywords():
    """Naukri holds each keyword's jobs until all keywords are searched; Stop (Ctrl+Break -> KeyboardInterrupt) must not lose them."""
    class P(ScriptedPage):
        def goto(self, url, **kw):
            if "bank-jobs?" in url:
                raise KeyboardInterrupt
            return super().goto(url, **kw)
    card = ('<div class="srp-jobtuple-wrapper" data-job-id="900000000001"><a class="title" title="A" href="https://www.naukri.com/job-listings-x-900000000001">A</a>'
            '<span class="job-post-day">Just now</span></div>')
    page = P({"gcc-jobs?": "<html>" + card + "</html>", "job-listings": fresh(read("naukri_detail_procurement.html"))})
    res = Collector(NaukriSource(client=client(page))).run([SearchParams("GCC OR bank OR financial services", "India", days=1, max_pages=1)])
    assert [j.job_id for j in res.jobs] == ["900000000001"]
    assert not any("financial-services-jobs" in u for u in page.visited)       # stopped: later keywords are not searched


def test_dashboard_shows_a_blocked_source_clearly_and_runs_the_other_sources(tmp_path):
    from tests.test_cross_source import fake_runner_factory, make_mgr
    from dashboard.collection import PARTIAL, short_reason
    calls = []
    def runner(cmd, on_line, cwd, timeout):
        if "--source" in cmd and cmd[cmd.index("--source") + 1] == "naukri":
            on_line("01:06:14 | ERROR   | collectors.collector | SOURCE BLOCKED US - stopping run. Reason: HTTP 403: the site refused the request "
                    "(rate limit, security check or login wall). requested=https://www.naukri.com/gcc-jobs?k=gcc; final=https://www.naukri.com/gcc-jobs?k=gcc; "
                    "status=403; page='Access Denied | Access Denied You don't have permission'")
            calls.append("naukri")
            return 2
        return fake_runner_factory({"linkedin": [("1", "Credit Risk Analyst", "Acme Bank", "2026-10-12")]}, calls)(cmd, on_line, cwd, timeout)
    from store.json_store import JsonJobHistory
    from dashboard.collection import CollectionManager
    h = JsonJobHistory(tmp_path / "h.json")
    before = h.list_jobs()
    m = CollectionManager(h, tmp_path, tmp_path / "out", runner=runner, background=False)
    m.start("india", target=5, sources=["Naukri", "LinkedIn"])
    st = m.status()
    assert calls.count("naukri") == 1 and "linkedin" in calls                  # blocked once, never retried; LinkedIn still ran
    assert st["state"] == PARTIAL and st["stop_reason"] == "blocked"
    assert "Naukri" in st["message"] and "HTTP 403 - Access Denied" in st["last_error"] and "Naukri blocked: HTTP 403 - Access Denied" in " ".join(st["warnings"])
    assert len(h.list_jobs()) == 1 and before == []
    assert short_reason("status=403; page='Access Denied | x'") == "HTTP 403 - Access Denied"


# -- company website -----------------------------------------------------------------------------------------------
ABOUT = ('<section class="styles_about-company__z4Qh1"><h2>About the company</h2><a href="schneider-electric-overview-20302?utm_medium=desktop"></a>'
         '<a class="styles_company-info-rnr__l3lLD" href="https://www.ambitionbox.com/reviews/schneider-electric-reviews">4.1 reviews</a>'
         '<span><a href="https://www.se.com/ww/en/" target="_blank" rel="nofollow">Schneider Electric website</a></span></section>')


def test_naukri_company_website_is_read_only_from_the_about_the_company_link():
    assert nk_detail.parse_job_detail("<html><body>" + ABOUT + "</body></html>")["company_website"] == "https://www.se.com/ww/en/"
    assert nk_detail.parse_job_detail(read("naukri_detail_procurement.html"))["company_website"] is None       # none stated: blank
    other = '<section class="styles_about-company__x"><a href="https://www.ambitionbox.com/x">Acme website</a><a href="https://twitter.com/acme">Acme website</a></section>'
    assert nk_detail.parse_job_detail("<html><body>" + other + "</body></html>")["company_website"] is None   # review / social links are not the website
    elsewhere = '<div><a href="https://evil.example">Visit website</a></div>'
    assert nk_detail.parse_job_detail("<html><body>" + elsewhere + "</body></html>")["company_website"] is None


def test_details_page_labels_the_field_by_source_and_leaves_it_blank_when_unknown():
    from dashboard import views, viewmodel as vm
    from tests.factories import NOW, make_record
    nk = {"key": "naukri-1", "record": make_record(1, company="Schneider Electric", source="Naukri", company_website="https://www.se.com/ww/en/")}
    nk_none = {"key": "naukri-2", "record": make_record(2, company="Acme Bank", source="Naukri")}
    li = {"key": "linkedin-3", "record": make_record(3, company="HSBC", company_url="https://uk.linkedin.com/company/hsbc")}
    li_shared = {"key": "linkedin-4", "record": make_record(4, company="HSBC", company_url=None)}
    li_none = {"key": "linkedin-5", "record": make_record(5, company="Lone Co", company_url=None)}
    rows = {r.key: r for r in vm.build_rows([nk, nk_none, li, li_shared, li_none], {}, None)}
    h = {k: views._details_table(rows[k], NOW) for k in rows}
    assert '<th scope="row">Company Website</th><td><a href="https://www.se.com/ww/en/"' in h["naukri-1"] and 'rel="noopener noreferrer"' in h["naukri-1"]
    assert "Company LinkedIn Page" not in h["naukri-1"]
    assert '<th scope="row">Company Website</th><td></td>' in h["naukri-2"]
    assert '<th scope="row">Company LinkedIn Page</th><td><a href="https://www.linkedin.com/company/hsbc"' in h["linkedin-3"]
    assert "Company Website" not in h["linkedin-3"]
    assert "Taken from another LinkedIn job of this company" in h["linkedin-4"] and "company/hsbc" in h["linkedin-4"]
    assert '<th scope="row">Company LinkedIn Page</th><td></td>' in h["linkedin-5"]
    js = {"key": "naukri-6", "record": make_record(6, company="Evil", source="Naukri", company_website="javascript:alert(1)")}
    assert "javascript:" not in views._details_table(vm.build_rows([js], {}, None)[0], NOW)


def test_a_blocked_source_is_rested_so_retrying_does_not_extend_the_block(tmp_path):
    from datetime import timedelta
    from tests.test_cross_source import fake_runner_factory
    from tests.factories import NOW
    from dashboard.collection import CollectionManager
    from config import settings
    from store.json_store import JsonJobHistory
    calls, clock = [], {"now": NOW}

    def runner(cmd, on_line, cwd, timeout):
        src = cmd[cmd.index("--source") + 1] if "--source" in cmd else "linkedin"
        if src == "linkedin":
            on_line("00:23:24 | ERROR   | collectors.collector | SOURCE BLOCKED US - stopping run. Reason: HTTP 429 (rate limited / blocked)")
            calls.append("linkedin")
            return 2
        return fake_runner_factory({"naukri": [("9", "Credit Risk Analyst", "Acme Bank", "2026-10-12")]}, calls)(cmd, on_line, cwd, timeout)

    m = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, tmp_path / "out", runner=runner, now_fn=lambda: clock["now"], background=False)
    m.start("india", target=5, sources=["LinkedIn"])
    assert calls.count("linkedin") == 1 and m.cooling_until("linkedin")
    assert "rest" in m.status()["last_error"].lower() or "later" in m.status()["last_error"].lower()
    ok, msg = m.start("india", target=5, sources=["LinkedIn"])                     # straight away: refused, not sent to LinkedIn
    assert not ok and "resting" in msg.lower() or "rested" in msg
    assert calls.count("linkedin") == 1
    ok, _ = m.start("india", target=5, sources=["LinkedIn", "Naukri"])             # another source still runs
    assert ok and calls.count("linkedin") == 1 and any(c != "linkedin" for c in calls)
    clock["now"] = NOW + timedelta(minutes=settings.SOURCE_COOLDOWN_MINUTES + 1)   # after the rest it is tried again
    assert m.cooling_until("linkedin") is None and m.start("india", target=5, sources=["LinkedIn"])[0]
    assert calls.count("linkedin") == 2


# -- our own browser failing is not "the site blocked us" ------------------------------------------
from collectors.errors import FetchError, LocalBrowserError
from collectors.browser_client import local_failure_kind


class FlakyPage(FakePage):
    """goto raises the given errors one after another (None = succeed)."""
    def __init__(self, errors):
        super().__init__()
        self.errors = list(errors)

    def goto(self, url, **kw):
        self.visited.append(url)
        err = self.errors.pop(0) if self.errors else None
        if err is not None:
            raise err
        return type("R", (), {"status": 200})()


def test_local_failure_kinds_are_recognised_and_site_errors_are_not():
    assert local_failure_kind(RuntimeError("Page.goto: net::ERR_NETWORK_CHANGED at https://x")) == "network"
    assert local_failure_kind(RuntimeError("TargetClosedError: Page.goto: Page crashed")) == "crash"
    assert local_failure_kind(RuntimeError("Page.goto: net::ERR_ABORTED; maybe frame was detached?")) == "crash"
    for site_side in ("Page.goto: Timeout 30000ms exceeded", "net::ERR_CONNECTION_RESET", "HTTP 503", "net::ERR_HTTP2_PROTOCOL_ERROR"):
        assert local_failure_kind(RuntimeError(site_side)) is None


def test_a_crashed_page_is_reopened_and_the_same_url_is_loaded_again():
    made = []
    pages = [FlakyPage([RuntimeError("TargetClosedError: Page.goto: Page crashed")]), FakePage()]
    def factory():
        made.append(1)
        return pages[len(made) - 1]
    c = BrowserClient(delay_min=0, delay_max=0, page_factory=factory, sleep=lambda s: None)
    assert "ok" in c.get("https://x.test/job")
    assert len(made) == 2 and pages[0].visited == ["https://x.test/job"] and pages[1].visited == ["https://x.test/job"]


def test_a_network_change_waits_and_retries_without_reopening_the_page():
    waits, made = [], []
    page = FlakyPage([RuntimeError("Page.goto: net::ERR_NETWORK_CHANGED at https://x.test/job")] * 2)
    c = BrowserClient(delay_min=0, delay_max=0, page_factory=lambda: (made.append(1), page)[1], sleep=waits.append)
    assert "ok" in c.get("https://x.test/job")
    assert len(made) == 1 and len(page.visited) == 3
    assert [w for w in waits if w] == [settings.BROWSER_RECOVERY_WAIT * 3, settings.BROWSER_RECOVERY_WAIT * 6]


def test_a_browser_that_keeps_crashing_is_a_local_error_never_a_block():
    crash = RuntimeError("TargetClosedError: Page.goto: Page crashed")
    page = FlakyPage([crash] * 10)
    try:
        BrowserClient(delay_min=0, delay_max=0, page_factory=lambda: page, sleep=lambda s: None).get("https://x.test/job")
        raised = None
    except Exception as exc:
        raised = exc
    assert isinstance(raised, LocalBrowserError) and isinstance(raised, FetchError) and not isinstance(raised, BlockedError)
    assert "did not refuse anything" in str(raised)
    assert len(page.visited) == settings.BROWSER_RECOVERY_RETRIES + 1


def test_an_ordinary_load_error_is_still_a_plain_fetch_error_and_a_403_is_still_a_block():
    page = FlakyPage([RuntimeError("Page.goto: Timeout 30000ms exceeded")])
    try:
        client(page).get("https://x.test/job")
        raised = None
    except Exception as exc:
        raised = exc
    assert isinstance(raised, FetchError) and not isinstance(raised, (LocalBrowserError, BlockedError)) and len(page.visited) == 1
    with pytest.raises(BlockedError):
        client(FakePage(status=403)).get("https://x.test/job")


class _DetailCrashPage(ScriptedPage):
    def __init__(self, routes, error):
        super().__init__(routes)
        self.error = error

    def goto(self, url, **kw):
        if "job-listings" in url:
            self.visited.append(url)
            raise self.error
        return super().goto(url, **kw)


def _naukri_run(error, monkeypatch):
    page = _DetailCrashPage({"naukri.com/bank-jobs": read("naukri_search.html")}, error)
    res = Collector(NaukriSource(client=client(page))).run([SearchParams("bank", "India", days=365, max_pages=1)])
    return res, page


def test_repeated_browser_crashes_stop_the_place_without_reporting_a_block(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONSECUTIVE_FAILURES", 1)             # even the strictest "blocked" breaker must not fire
    monkeypatch.setattr(settings, "MAX_CONSECUTIVE_BROWSER_FAILURES", 2)
    res, page = _naukri_run(RuntimeError("TargetClosedError: Page.goto: Page crashed"), monkeypatch)
    assert not res.stats.blocked and res.jobs == [] and res.stats.setup_error is None
    detail_visits = [u for u in page.visited if "job-listings" in u]
    assert len(detail_visits) == 2 * (settings.BROWSER_RECOVERY_RETRIES + 1)


def test_repeated_ordinary_failures_still_trip_the_blocked_breaker(monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONSECUTIVE_FAILURES", 2)
    res, _ = _naukri_run(RuntimeError("Page.goto: Timeout 30000ms exceeded"), monkeypatch)
    assert res.stats.blocked
