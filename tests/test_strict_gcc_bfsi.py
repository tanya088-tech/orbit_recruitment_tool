"""Only GCC- or BFSI-related vacancies may reach the dashboard - for BOTH LinkedIn and Naukri.

Every scenario below runs through the real normalization (evaluate_job via normalize_all), the collection gate
(keep_eligible), the history store and the dashboard rows (build_rows with the strict view filter ON).
"""
from datetime import date

from config import settings
from dashboard import viewmodel as vm
from processing.pipeline import keep_eligible, normalize_all
from store.json_store import JsonJobHistory
from tests.factories import NOW

SOURCES = ("LinkedIn", "Naukri")
_n = [0]


def job(source, title, company, industries=None, description="Day-to-day work in the team.", posted_by=None):
    _n[0] += 1
    jid = str(7000000 + _n[0])
    url = (f"https://www.linkedin.com/jobs/view/{jid}" if source == "LinkedIn"
           else f"https://www.naukri.com/job-listings-x-{jid}")
    return {"source": source, "job_id": jid, "title": title, "company": company, "location": "Pune, Maharashtra, India",
            "job_url": url, "description": description, "industries": industries, "employment_type": "Full-time",
            "posted_age_text": "2 hours ago", "posted_date": date(2026, 10, 8).isoformat(), "posted_by": posted_by,
            "collected_at": NOW.isoformat(), "raw": {}}


def gate(jobs):
    kept, dropped = keep_eligible(normalize_all(jobs, as_of=NOW).jobs)
    return kept, dropped


def verdicts(source, specs):
    """specs: list of (title, company, industries, description, posted_by). Returns {title: kept?} plus the kept records."""
    jobs = [job(source, *s) for s in specs]
    kept, _ = gate(jobs)
    ids = {r["job_id"] for r in kept}
    return {j["title"]: j["job_id"] in ids for j in jobs}, kept


# 1. clearly GCC ---------------------------------------------------------------------------------------
def test_clear_gcc_employers_are_kept_and_labelled_gcc():
    for src in SOURCES:
        ind = "Software Development" if src == "LinkedIn" else "IT Services & Consulting"
        _, kept = verdicts(src, [
            ("Software Engineer", "Northwind Global Capability Centre India", ind, "Build services. We are part of a multinational group.", None),
            ("Data Engineer", "Zeta Labs", ind, "We are a Global Capability Centre of a US group. Join our data team.", None)])
        assert len(kept) == 2, src
        assert all(r["potential_gcc"] and not r["potential_bfsi"] for r in kept), src


# 2. clearly BFSI --------------------------------------------------------------------------------------
def test_clear_bfsi_jobs_are_kept_and_labelled_bfsi():
    for src in SOURCES:
        got, kept = verdicts(src, [
            ("Relationship Manager", "Axis Bank", "Banking", "Manage clients.", None),
            ("Claims Executive", "Shield Insurance Ltd", "Insurance", "Settle claims.", None),
            ("Credit Risk Analyst", "Nova Finserv", "Financial Services", "Credit models.", None)])
        assert all(got.values()), (src, got)
        assert all(r["potential_bfsi"] for r in kept), src


# 3. HR / recruitment at unrelated employers -------------------------------------------------------------
def test_hr_and_recruitment_jobs_at_unrelated_employers_are_excluded():
    for src in SOURCES:
        got, _ = verdicts(src, [
            ("HR Recruiter", "Sunrise Textiles", "Textile Manufacturing", "Hire staff for our mills.", None),
            ("HR Manager", "Blue Star Logistics", "Transportation, Logistics", "Lead HR operations.", None),
            ("Talent Acquisition Specialist", "Pixel Games", "Computer Games", "Hire engineers.", None),
            ("Recruiter", "Fresh Foods", None, "Hire for banking and financial services clients too.", None)])
        assert not any(got.values()), (src, got)


def test_talent_acquisition_at_recruitment_consultancies_is_excluded_even_if_they_serve_banks():
    for src in SOURCES:
        got, _ = verdicts(src, [
            ("Talent Acquisition Specialist", "Apex Talent Solutions", "Staffing and Recruiting", "Source candidates for banks and GCCs.", None),
            ("Recruiter - BFSI hiring", "Prime Staffing Services", "Banking", "Banking vertical.", None),
            ("Banking Sales Executive", "Nona HR Services", "Banking", "Sell loans.", None),
            ("Credit Risk Analyst", "Quick Hire", "Financial Services", "Hiring for our client, a leading bank.", None)])
        assert not any(got.values()), (src, got)


# 4. HR / recruitment at confirmed GCC or BFSI employers ----------------------------------------------------
def test_hr_roles_at_confirmed_gcc_or_bfsi_employers_may_be_kept():
    for src in SOURCES:
        got, kept = verdicts(src, [
            ("HR Business Partner", "HDFC Bank", "Banking", "Partner with business heads.", None),
            ("Talent Acquisition Lead", "Northwind Global Capability Centre India", "Software Development", "Hire engineers. We are part of a multinational group.", None),
            ("Recruiter", "Shield Insurance Ltd", "Insurance", "Hire agents.", None)])
        assert all(got.values()), (src, got)
        by = {r["title"]: r for r in kept}
        assert by["HR Business Partner"]["potential_bfsi"] and by["Talent Acquisition Lead"]["potential_gcc"]


def test_an_hr_title_that_only_mentions_banking_does_not_qualify_the_job():
    for src in SOURCES:
        got, _ = verdicts(src, [("HR Recruiter - Banking and Insurance", "Sunrise Textiles", None, "Hire.", None),
                                ("Recruiter - Credit Risk & KYC", "Zenith Corp", None, "Hire.", None)])
        assert not any(got.values()), (src, got)


# 5. generic analyst / operations / technology / finance at unrelated employers -------------------------------
def test_generic_titles_at_unrelated_employers_are_excluded():
    titles = ("Business Analyst", "Operations Manager", "Technology Lead", "Finance Manager", "Senior Analyst - Operations",
              "Manager", "Accounts Executive")
    for src in SOURCES:
        got, _ = verdicts(src, [(t, "Sunrise Pharma", "Pharmaceutical Manufacturing", "We serve banks and payments firms too.", None)
                                for t in titles])
        assert not any(got.values()), (src, got)


def test_bfsi_words_in_a_description_alone_never_qualify():
    for src in SOURCES:
        got, _ = verdicts(src, [("Software Developer", "Pixel Soft", "Software Development",
                                 "Our clients include banks, insurance firms, lending and payments platforms and capital markets.", None)])
        assert not any(got.values()), src


# 6. employer / business category unclear -----------------------------------------------------------------------
def test_unclear_or_unnamed_employers_are_excluded():
    for src in SOURCES:
        got, _ = verdicts(src, [
            ("Operations Analyst", "Confidential", None, "Great opportunity.", None),
            ("Key Account Manager", "Confidential", "Beverage (Brewery / Distillery)", "Sell.", None),
            ("Relationship Manager", "Confidential", "Banking", "Manage clients.", "Genius Consultants"),
            ("Senior Analyst", "Nova Corp", None, "Work with data.", None),
            ("Technology Lead", "Nova Corp", "", "Lead a team.", None)])
        assert not any(got.values()), (src, got)


def test_a_bfsi_specific_role_with_no_industry_stated_is_kept_but_not_with_a_different_industry():
    for src in SOURCES:
        got, _ = verdicts(src, [("Senior Underwriter", "Nova Corp", None, "Assess risk for our bank: lending, insurance and payments products.", None),
                                ("Underwriter", "Pixel Soft", "Software Development", "Build tools.", None)])
        assert got == {"Senior Underwriter": True, "Underwriter": False}, (src, got)


def test_gulf_gcc_and_compiler_gcc_do_not_make_a_job_gcc():
    for src in SOURCES:
        got, _ = verdicts(src, [("Sales Manager", "Desert Trading", "Wholesale", "Selling across GCC countries and UAE.", None),
                                ("Embedded Engineer", "Chipworks", "Semiconductor Manufacturing", "GCC compiler and Clang toolchains.", None)])
        assert not any(got.values()), (src, got)


def test_oaknorth_style_bank_with_garbled_industry_is_kept_but_unrelated_look_alikes_are_not():
    oak = job("LinkedIn", "SVP - Business Assurance", "OakNorth", "Utilities, Accommodation and Food Services, and Administrative and Support Services",
              "We have lent over $21 billion. Experience in regulated financial services needed.")
    oak["company_url"] = "https://uk.linkedin.com/company/oaknorth-bank"
    vendor = job("LinkedIn", "Developer", "Penta", "Software Development", "Banking software for banks and financial services.")
    vendor["company_url"] = "https://www.linkedin.com/company/penta-banking-software"
    agency = job("LinkedIn", "Recruiter", "Apex Staffing", "Staffing and Recruiting", "Banks and financial services hiring.")
    agency["company_url"] = "https://www.linkedin.com/company/apex-bank-staffing"
    naukri = job("Naukri", "Banking Chat Process", "MNC", "Banking", "International banking process.", posted_by="Mywhy")
    kept, dropped = gate([oak, vendor, agency, naukri])
    assert [r["company"] for r in kept] == ["OakNorth"] and kept[0]["potential_bfsi"] and len(dropped) == 3


# the real Naukri page: unnamed employer posted by a consultancy -----------------------------------------------------
def test_real_naukri_procurement_posting_is_excluded():
    from collectors.naukri import detail_parser as nk_detail
    from collectors.naukri.source import NaukriSource
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures" / "naukri_detail_procurement.html").read_text(encoding="utf-8")
    d = nk_detail.parse_job_detail(html)
    stub = {"job_id": "280426921786", "job_url": "https://www.naukri.com/job-listings-operations-coordinator-procurement-280426921786",
            "title": "Operations Coordinator - Procurement", "company": "Confidential", "location": "Chennai",
            "posted_age_text": "Just now", "posted_date": date(2026, 10, 12), "raw": "<div/>", "skills": []}
    j = NaukriSource(client=object()).build_job(stub, d)
    kept, dropped = gate([j.to_dict()])
    assert not kept and len(dropped) == 1
    assert dropped[0]["filter_results"]["gcc_bfsi"]["passed"] is False


# same function everywhere: the filter pipeline and the dashboard view -----------------------------------------------
def test_pipeline_filter_result_explains_the_exclusion():
    rec = normalize_all([job("Naukri", "HR Recruiter", "Sunrise Textiles", "Textile Manufacturing")], as_of=NOW).jobs[0]
    res = rec["filter_results"]["gcc_bfsi"]
    assert res["passed"] is False and res["code"] == "not_gcc_or_bfsi" and res["reason"].startswith("Not eligible")


def _history_with(tmp_path, specs_by_source):
    h = JsonJobHistory(tmp_path / "h.json")
    records = []
    for src, specs in specs_by_source.items():
        jobs = [job(src, *s) for s in specs]
        for j in jobs:
            if src == "Naukri":
                j["location"] = "Mumbai, Maharashtra, India"       # a different city, so the cross-source de-duplication keeps both
        records += normalize_all(jobs, as_of=NOW).jobs
    h.ingest(records, now=NOW)
    return h


def test_old_history_saved_under_looser_rules_is_hidden_not_deleted(tmp_path):
    specs = [("HR Recruiter", "Sunrise Textiles", "Textile Manufacturing", "Hire.", None),
             ("Relationship Manager", "Axis Bank", "Banking", "Clients.", None)]
    h = _history_with(tmp_path, {"LinkedIn": specs, "Naukri": specs})
    stored = h.list_jobs()
    for e in stored:                                  # simulate records saved by the old loose rules: everything tagged BFSI
        e["record"]["potential_bfsi"] = True
    before = [dict(e["record"]) for e in stored]
    assert len(stored) == 4
    shown = vm.build_rows(stored, {}, None, only_gcc_bfsi=True)
    assert sorted((r.source, r.title) for r in shown) == [("LinkedIn", "Relationship Manager"), ("Naukri", "Relationship Manager")]
    assert all(r.potential_bfsi and r.category == "BFSI" for r in shown)
    assert len(vm.build_rows(stored, {}, None, only_gcc_bfsi=False)) == 4          # nothing deleted: still in the history
    assert [e["record"] for e in stored] == before                                    # and the stored records were not changed


def test_dashboard_numbers_count_only_eligible_jobs(tmp_path):
    specs = [("HR Recruiter", "Sunrise Textiles", "Textile Manufacturing", "Hire.", None),
             ("Business Analyst", "Sunrise Pharma", "Pharmaceutical Manufacturing", "x", None),
             ("Relationship Manager", "Axis Bank", "Banking", "Clients.", None),
             ("Software Engineer", "Northwind Global Capability Centre India", "Software Development", "We are part of a multinational group.", None)]
    h = _history_with(tmp_path, {"LinkedIn": specs, "Naukri": specs})
    rows = vm.build_rows(h.list_jobs(), {}, None, only_gcc_bfsi=True)
    assert len(rows) == 4 and {r.category for r in rows} == {"BFSI", "GCC"}
    flt = vm.apply_filters(rows, vm.Filters(scope="all"), NOW)
    assert len(flt) == 4
    assert {r.source for r in flt} == {"LinkedIn", "Naukri"}


def test_the_strict_view_filter_is_on_by_default_in_production_settings():
    import importlib
    import config.settings as s
    fresh = importlib.reload(s)
    try:
        assert fresh.DISPLAY_ONLY_GCC_BFSI is True and fresh.COLLECTION_ONLY_GCC_BFSI is True
    finally:
        settings.DISPLAY_ONLY_GCC_BFSI = False        # tests keep the fixture-friendly default
        settings.COLLECTION_CANDIDATE_POOL_FACTOR = 1   # the reload above restored the production value
        settings.COLLECTION_STRICT_WINDOW = False
        settings.REQUIRE_OVERSEAS_HQ = False
        settings.REQUIRE_INDIA_LOCATION = False


# -- tightened rules: a name is never enough (the "Electrical GCC" case) ------------------------------------------------
def test_company_names_containing_gcc_bank_finance_or_insurance_do_not_qualify_by_themselves():
    for src in SOURCES:
        got, _ = verdicts(src, [
            ("Enterprise Strategy & Planning Lead", "Electrical GCC", "IT & Software", "Drives IT strategy and enterprise planning with business leaders.", None),
            ("Enterprise Strategy & Planning Lead", "Electrical GCC", "IT Services & Consulting", "Drives IT strategy.", None),
            ("Manager", "Sunrise Bank Supplies", "Wholesale", "We sell stationery.", None),
            ("Analyst", "Greenfield Finance Training", None, "Classroom work.", None),
            ("Executive", "Safe Insurance Brokers", None, "Great team.", None),
            ("Engineer", "Acme Global Capability Centre", "Software Development", "Build things.", None)])
        assert not any(got.values()), (src, got)


def test_genuine_gcc_and_bfsi_employers_are_kept_even_without_a_keyword_in_the_name():
    for src in SOURCES:
        got, kept = verdicts(src, [
            ("Engineer", "Zeta Holdings", "Software Development", "Join our Global Capability Centre in Pune, the captive technology arm of a US group.", None),
            ("Associate", "Meridian Holdings", "Financial Services", "Client work.", None),
            ("Analyst", "Goldman Sachs", None, "Markets.", None),
            ("Engineer", "Vertex", "IT Services & Consulting", "We are the India GCC of a European bank. Join our GCC engineering teams.", None)])
        assert all(got.values()), (src, got)


def test_contradictory_or_missing_evidence_is_excluded():
    for src in SOURCES:
        got, _ = verdicts(src, [
            ("Underwriter", "Pixel Soft", "Software Development", "Build tools.", None),               # BFSI title, tech employer
            ("Analyst", "Nova Corp", None, "We serve banks.", None),                                    # no industry, thin description
            ("Manager", "Bank Street Cafe", "Restaurants", "Run the cafe.", None),                      # name says bank, industry says cafe
            ("Recruiter", "Prime Staffing Services", "Banking", "Banking vertical.", None),             # BFSI industry but a staffing firm
            ("Operations Manager", "MNC", "Banking", "International banking process.", "Mywhy")])       # unnamed employer
        assert not any(got.values()), (src, got)


def test_a_bfsi_sounding_title_at_a_healthcare_or_pharma_employer_is_not_enough():
    desc = "Mortgage underwriting of US residential loans: credit, loan, mortgage, underwriting guidelines and compliance."
    for ind in ("Medical Services / Hospital", "Pharmaceutical & Life Sciences", "Healthcare"):
        for src in SOURCES:
            kept, dropped = gate([job(src, "Mortgage Underwriter", "Starworth Global Solutions", ind, desc)])
            assert not kept and len(dropped) == 1, (src, ind)
    # the same posting with a neutral or BPO industry label is still judged on its title and description as before
    kept, _ = gate([job("Naukri", "Mortgage Underwriter", "Starworth Global Solutions", "BPM / BPO", desc)])
    assert len(kept) == 1
    # a real bank is unaffected
    kept, _ = gate([job("LinkedIn", "Mortgage Underwriter", "HDFC Bank", "Banking", desc)])
    assert len(kept) == 1
