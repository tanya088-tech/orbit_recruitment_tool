"""The client's rule: only GCC / BFSI employers headquartered OUTSIDE India, for vacancies located IN India.
Plus the Industry Type filter and the CSV export."""
import csv
import io
import json

from config import settings
from dashboard import export, views
from dashboard import viewmodel as vm
from dashboard.server import DashboardApp
from processing.classifier import classify
from processing.pipeline import keep_eligible, normalize_all
from store.json_store import JsonRecruiterState
from tests.factories import NOW, entry, ago

BANK_JD = ("Credit risk role. The team handles loans, credit, mortgage underwriting, lending and risk for retail banking customers.")
GCC_JD = ("Join our Global Capability Centre in India, the technology arm of a US-based retailer. We run captive operations for the group.")


class Rules:
    """Switch the client's rules on for a test (the other tests run with them off)."""
    def __enter__(self):
        self.old = (settings.REQUIRE_OVERSEAS_HQ, settings.REQUIRE_INDIA_LOCATION)
        settings.REQUIRE_OVERSEAS_HQ = settings.REQUIRE_INDIA_LOCATION = True
        return self

    def __exit__(self, *a):
        settings.REQUIRE_OVERSEAS_HQ, settings.REQUIRE_INDIA_LOCATION = self.old


def c(company="Wells Fargo", title="Analyst", desc="Day to day work.", ind="Financial Services", loc="Hyderabad, Telangana, India"):
    return classify(company, title, desc, ind, location=loc)


def test_known_overseas_banks_with_india_vacancies_qualify():
    with Rules():
        for name in ("Wells Fargo", "JPMorganChase", "Citi", "HSBC", "Standard Chartered India", "Deutsche Bank", "DBS Bank", "U.S. Bank", "BNY"):
            v = c(name)
            assert v.eligible and v.potential_bfsi, name
            assert "Headquarters:" in v.reason


def test_india_headquartered_banks_do_not_qualify():
    with Rules():
        for name in ("HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank", "AU SMALL FINANCE BANK", "IDFC FIRST Bank", "Bajaj Finserv", "Jana Small Finance Bank"):
            v = c(name)
            assert not v.eligible, name
            assert "headquartered in India" in v.reason


def test_a_bank_with_no_headquarters_evidence_is_not_assumed_foreign():
    with Rules():
        v = c("Unknown Finance Co", desc=BANK_JD)
        assert not v.eligible and "no reliable evidence" in v.reason
        assert not c("Acme Bank", desc=BANK_JD).eligible


def test_a_headquarters_statement_in_the_description_counts_for_an_unlisted_employer():
    with Rules():
        v = c("Meridian Bank", desc=BANK_JD + " Meridian is headquartered in Toronto, Canada and has offices worldwide.", ind="Banking")
        assert v.eligible and "Canada" in v.reason or "Toronto" in v.reason
        v = c("Meridian Bank", desc=BANK_JD + " We are a US-based bank with an India centre.", ind="Banking")
        assert v.eligible
        v = c("Meridian Bank", desc=BANK_JD + " The bank is headquartered in Pune, India.", ind="Banking")
        assert not v.eligible and "headquartered in India" in v.reason


def test_the_company_name_or_job_title_alone_never_qualifies():
    with Rules():
        # a BFSI word in the name / a BFSI title, with an unrelated industry and no evidence in the posting
        assert not c("Global Trust Bank Pvt Ltd", title="Mortgage Underwriter", ind="Healthcare", desc="Reach out for details.").eligible
        # an overseas parent without any GCC / BFSI evidence in the posting (an ordinary manufacturer's plant job)
        assert not c("Siemens", title="Plant Manager", ind="Manufacturing", desc="Run the plant floor and production planning.").eligible


def test_non_bfsi_groups_qualify_as_gcc_only_with_gcc_evidence_in_the_posting():
    with Rules():
        v = c("Walmart", title="Software Engineer", ind="Retail", desc=GCC_JD)
        assert v.eligible and v.potential_gcc and not v.potential_bfsi
        assert not c("Walmart", title="Store Associate", ind="Retail", desc="Help customers in the store.").eligible
        v = c("Siemens", title="Engineer", ind="Manufacturing", desc="Siemens is a German multinational. " + GCC_JD)
        assert v.eligible


def test_vacancies_outside_india_or_without_a_location_do_not_qualify():
    with Rules():
        assert not c(loc="New York, NY, United States").eligible
        assert not c(loc="London, United Kingdom").eligible
        assert not c(loc="").eligible
        assert not c(loc="Pune, India / Dubai").eligible
        assert c(loc="Pune, Maharashtra, India").eligible


def test_staffing_and_unnamed_employers_remain_excluded():
    with Rules():
        assert not c("Wells Fargo", ind="Staffing and Recruiting").eligible
        assert not c("Confidential", desc=BANK_JD).eligible


def _job(company, location="Pune, Maharashtra, India", industries="Banking", desc=BANK_JD, jid="9001"):
    return {"source": "Naukri", "job_id": jid, "title": "Analyst", "company": company, "location": location,
            "job_url": f"https://www.naukri.com/job-listings-x-{jid}", "description": desc, "industries": industries,
            "employment_type": "Full-time", "posted_age_text": "2 hours ago", "collected_at": NOW.isoformat(), "raw": {}}


def test_collection_gate_and_dashboard_apply_the_same_rule():
    with Rules():
        jobs = [_job("Wells Fargo", jid="1"), _job("HDFC Bank", jid="2"), _job("Wells Fargo", "Austin, Texas, United States", jid="3")]
        kept, dropped = keep_eligible(normalize_all(jobs, as_of=NOW).jobs)
        assert [r["job_id"] for r in kept] == ["1"] and {r["job_id"] for r in dropped} == {"2", "3"}
        # the dashboard shows the same: stored records of all three, only the qualifying one is displayed
        entries = [entry(i, company=co, location=loc, gcc=False, bfsi=True, description=BANK_JD, industries="Banking")
                   for i, (co, loc) in enumerate([("Wells Fargo", "Pune, Maharashtra, India"), ("HDFC Bank", "Pune, Maharashtra, India"),
                                                  ("Wells Fargo", "Austin, Texas, United States")], start=1)]
        old = settings.DISPLAY_ONLY_GCC_BFSI
        settings.DISPLAY_ONLY_GCC_BFSI = True
        try:
            rows = vm.build_rows(entries, {}, None)
        finally:
            settings.DISPLAY_ONLY_GCC_BFSI = old
        assert [r.company for r in rows] == ["Wells Fargo"] and rows[0].location.startswith("Pune")


# ---------------------------------------------------------------- Industry Type filter
def _rows():
    spec = [(1, "Wells Fargo", "Financial Services"), (2, "Walmart", "Retail"), (3, "Siemens", "Manufacturing"),
            (4, "Microsoft", "IT Services and IT Consulting"), (5, "Pfizer", "Pharmaceutical Manufacturing"), (6, "Odd Co", None)]
    return vm.build_rows([entry(i, company=co, industries=ind, gcc=True) for i, co, ind in spec], {}, None, only_gcc_bfsi=False)


def test_industry_type_options_list_all_fourteen_client_industries_and_no_gcc_bfsi():
    from processing.industry import CLIENT_INDUSTRIES
    rows = _rows()
    opts = vm.filter_options(rows)["industries"]
    assert opts[:14] == CLIENT_INDUSTRIES and len(CLIENT_INDUSTRIES) == 14
    assert opts[14:] == ["Other"] or opts[14:] == []
    assert "GCC" not in opts and "BFSI" not in opts
    assert vm.filter_options(rows[:1])["industries"][:14] == CLIENT_INDUSTRIES      # fixed list, independent of the data


def test_each_client_industry_label_maps_to_its_category():
    from processing.industry import classify_industry
    cases = {"Pharmaceutical Manufacturing": "Pharmaceuticals & Life Sciences", "Automotive": "Automotive & Auto Components",
             "Oil and Gas": "Oil, Gas & Energy", "Truck Transportation": "Logistics, Supply Chain & Transportation",
             "Real Estate": "Infrastructure, Construction & Real Estate", "Hospitality": "Hospitality, Travel & Tourism",
             "Consumer Goods": "FMCG & Consumer Goods", "E-Learning Providers": "Education & EdTech"}
    for label, want in cases.items():
        assert classify_industry(label).category == want, label


def test_industry_type_filter_narrows_the_list_and_survives_in_the_url():
    rows = _rows()
    f = vm.Filters.from_query({"industry": ["Retail & E-commerce"]})
    got = vm.apply_filters(rows, f, NOW)
    assert [r.company for r in got] == ["Walmart"]
    assert "industry=Retail+%26+E-commerce" in f.to_query() and f.active_count == 1
    assert vm.apply_filters(rows, vm.Filters(), NOW) == vm.apply_filters(rows, vm.Filters(industry=""), NOW)


def test_the_page_shows_an_industry_type_select_without_gcc_or_bfsi_choices():
    rows = _rows()
    html = views._filters_form(vm.Filters(industry="IT & Software Services"), vm.filter_options(rows))
    assert 'name="industry"' in html and "Industry Type" in html and "All industries" in html
    assert '<option value="IT &amp; Software Services" selected>' in html
    assert ">GCC<" not in html and ">BFSI<" not in html


# ---------------------------------------------------------------- CSV export
def _export_rows():
    es = [entry(1, title="Old job", company="Wells Fargo", posted=ago(days=3), description="=cmd|' /C calc'!A0 Responsibilities:\n- Do x"),
          entry(2, title="New job, with comma", company="Citi", posted=ago(minutes=10)),
          entry(3, title="Undated job", company="HSBC", posted=None, precision="unknown"),
          entry(4, title="Mid job", company="Barclays", posted=ago(hours=5))]
    return vm.build_rows(es, {}, None, only_gcc_bfsi=False)


def test_csv_is_newest_first_with_unknown_dates_last_and_opens_in_spreadsheets():
    data = export.build_csv(_export_rows())
    assert data.startswith(b"\xef\xbb\xbf")                                  # BOM: Excel reads UTF-8 correctly
    recs = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    head = recs[0]
    assert head[:6] == ["Company name", "Company website", "Company LinkedIn page", "Company rating", "Company reviews", "Job title"]
    titles = [r[head.index("Job title")] for r in recs[1:]]
    assert titles == ["New job, with comma", "Mid job", "Old job", "Undated job"]
    assert len(recs) == 5 and all(len(r) == len(head) for r in recs)
    old = recs[3]
    assert old[head.index("Full job description")].startswith("'=cmd")        # formula text is neutralised, not executed
    assert b"\r\n" in data


def test_csv_carries_every_details_field():
    head = next(csv.reader(io.StringIO(export.build_csv(_export_rows()).decode("utf-8-sig"), newline="")))
    for name in ("Company name", "Job title", "Designation", "Industry Type", "Location", "Employment type", "Work mode", "Posting date",
                 "Source", "Original job URL", "Job summary", "Full job description", "Key responsibilities", "Required qualifications and skills",
                 "Experience required", "Key skills", "Contact details available", "Contact email", "Contact phone", "Salary", "Openings",
                 "Applicants so far", "Posted by", "Role category", "Also listed on", "First found by the tool", "Company website"):
        assert name in head, name


class FakeHistory:
    def __init__(self, entries): self.entries = entries
    def list_jobs(self): return self.entries
    def latest_run(self): return None
    def get_job(self, key): return next((e for e in self.entries if e["key"] == key), None)


def test_export_route_returns_all_eligible_vacancies_not_just_one_page(tmp_path):
    from tests.test_collection_and_controls import serve
    import http.client
    n = settings.PAGE_SIZE * 2 + 7 if hasattr(settings, "PAGE_SIZE") else 60
    es = [entry(i, title=f"Job {i}", company="Wells Fargo", posted=ago(minutes=i)) for i in range(1, n + 1)]
    app = DashboardApp(FakeHistory(es), JsonRecruiterState(tmp_path / "s.json", now_fn=lambda: NOW), now_fn=lambda: NOW, static_dir=tmp_path / "static")
    srv = serve(app)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        conn.request("GET", "/export.csv")
        r = conn.getresponse(); body = r.read()
        assert r.status == 200 and r.getheader("Content-Type").startswith("text/csv")
        assert "attachment" in r.getheader("Content-Disposition") and ".csv" in r.getheader("Content-Disposition")
        recs = list(csv.reader(io.StringIO(body.decode("utf-8-sig"), newline="")))
        assert len(recs) == n + 1
        conn.request("GET", "/")
        page = conn.getresponse().read().decode("utf-8")
        assert 'href="/export.csv"' in page and "Export CSV" in page
    finally:
        srv.shutdown(); srv.server_close()


# ------------------------------------------- the 14 industries keep the existing ordering and eligibility rules
def test_industry_filter_keeps_newest_first_with_contact_details_first_inside_a_window():
    from tests.factories import make_record
    recs = [make_record(1, "Old with phone", industries="Financial Services", description="Call 9876501234.", posted=ago(hours=30)),
            make_record(2, "New no contact", industries="Financial Services", posted=ago(hours=2)),
            make_record(3, "New with mail", industries="Financial Services", description="Email hr@acme.example", posted=ago(hours=2)),
            make_record(4, "Other industry", industries="Retail", posted=ago(hours=1))]
    from tests.test_viewmodel import rows_from
    rows = rows_from(recs)
    got = vm.apply_filters(rows, vm.Filters(industry="Banking, Financial Services & Insurance (BFSI)"), NOW)
    titles = [r.title for r in vm.sort_rows(got, "recent")]
    assert "Other industry" not in titles
    assert titles.index("New with mail") < titles.index("New no contact") < titles.index("Old with phone")
