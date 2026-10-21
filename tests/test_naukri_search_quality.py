"""Naukri: searched by employer name, its location text read as India, and clearly irrelevant cards not opened.
The examples are real Naukri values from the 18 Oct 2026 collection."""
from pathlib import Path

import pytest

from collectors.naukri.source import keyword_terms, naukri_location
from config import settings
from dashboard.collection import build_command, source_keywords
from processing.classifier import skip_before_fetch_reason
from processing.location import check_location


# ---- A. Naukri-specific searches ----------------------------------------------------------------------------------
def test_naukri_searches_the_employer_list_and_linkedin_keeps_its_keywords():
    naukri = build_command("india", Path("/tmp/o"), ["India"], source="naukri")
    words = naukri[naukri.index("--keywords") + 1]
    assert keyword_terms(words) == [t.strip() for t in settings.NAUKRI_SEARCH_TERMS]
    assert "Barclays" in keyword_terms(words) and "GCC" not in keyword_terms(words)
    linkedin = build_command("india", Path("/tmp/o"), ["India"])
    assert linkedin[linkedin.index("--keywords") + 1] == settings.COLLECTION_KEYWORDS[0]


def test_an_empty_naukri_list_falls_back_to_the_shared_keywords(monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_SEARCH_TERMS", [])
    assert source_keywords("naukri") == list(settings.COLLECTION_KEYWORDS)


def test_each_naukri_term_reads_only_a_few_result_pages(monkeypatch):
    from collectors.browser_source import BrowserListSource
    from collectors.naukri.source import NaukriSource
    from models.job import RunStats, SearchParams
    pages = []
    monkeypatch.setattr(BrowserListSource, "search", lambda self, p, s, skip_ids=None: pages.append(p.max_pages) or iter(()))
    list(NaukriSource(client=object()).search(SearchParams(keywords="HSBC OR Citi", max_pages=100), RunStats(), set()))
    assert pages == [settings.NAUKRI_MAX_PAGES_PER_KEYWORD] * 2


# ---- B. Naukri locations -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Pune( Shivaji Nagar, Kothrud, Pimpri Chinchwad, Viman Nagar, Hadapsar, Peth )",
    "Mumbai Suburban( Goregaon ), Navi Mumbai, Mumbai (All Areas)( Jogeshwari, Jogeshwari East, Jogeshwari West, Bhayandar, "
    "Mira Bhayandar, Dahisar, Dahisar East, Dahisar West, Pali Hill, Dindoshi, Goregaon, Goregaon East, Goregaon West, Borivali )",
    "Varanasi, Kanpur, Lucknow", "Tirupati, Vijayawada, Hyderabad, Chennai, Bengaluru, Vellore",
    "Kotputli, Bhiwadi", "Sonipat( Kundli )", "Bharuch, Vapi, Bardoli", "Dhanbad( Hirapur )", "Latur( Khadgaon )", "Tumakuru",
])
def test_naukri_indian_places_are_read_as_india(text):
    assert check_location(naukri_location(text)).country == "India"


@pytest.mark.parametrize("text, country", [
    ("Saudi Arabia", "Saudi Arabia"), ("Qatar, GCC, Gulf", "Qatar"), ("Oman", "Oman"), ("Kuwait", "Kuwait"), ("Nigeria", "Nigeria"),
    ("Riyadh", "Riyadh"), ("Doha", "Doha"),
])
def test_naukri_foreign_places_stay_foreign(text, country):
    assert check_location(naukri_location(text)).country == country


def test_a_naukri_location_naming_india_and_another_country_is_left_unchanged():
    text = "Hyderabad, Chennai, Saudi Arabia, Bengaluru, Delhi / NCR, Mumbai (All Areas)"
    assert naukri_location(text) == text


# ---- C. card titles that are not worth opening ---------------------------------------------------------------------
@pytest.mark.parametrize("company, title", [
    ("Petpooja", "Telecaller - Inside Sales"), ("NoBroker", "Property Advisor"), ("Sutherland", "International Voice Process - Hiring"),
    ("Some Realty", "Real Estate Sales Executive"), ("Hotel Co", "Restaurant Manager"),
])
def test_clearly_irrelevant_cards_are_not_opened(company, title):
    assert "not a GCC / BFSI role" in (skip_before_fetch_reason(company, title) or "")


@pytest.mark.parametrize("company, title", [
    ("HSBC", "AVP Premier Relationship Manager"), ("DBS Bank", "Officer, Branch Relationship Manager, Consumer Banking Group"),
    ("Barclays", "Customer Service & Operations Analyst"), ("Chubb", "FinLines & Cyber Technology Lead"),
    ("Acme Bank", "Credit Risk Analyst"), ("Acme Insurance", "Claims Associate"), ("Acme Finance", "Collections Officer"),
    ("Barclays", "BPO Operations Analyst"),             # a known GCC employer is always opened, whatever the title says
    ("Wells Fargo", "Call Centre Quality Lead"),
])
def test_real_bfsi_and_gcc_roles_are_still_opened(company, title):
    assert skip_before_fetch_reason(company, title) is None


def test_an_employer_search_opens_only_that_kind_of_employer():
    """Live check, 18 Oct: a 24-hour 'Barclays' search listed two cards, both from BSL Consulting; over 7 days 16 of 20 were Barclays."""
    from collectors.naukri.source import NaukriSource
    from models.job import SearchParams
    src = NaukriSource(client=object())
    barclays = SearchParams(keywords="Barclays")
    assert "not one of the listed employers" in src.card_skip_reason({"company": "BSL Consulting"}, barclays)
    assert src.card_skip_reason({"company": "Barclays"}, barclays) is None
    assert src.card_skip_reason({"company": "Wells Fargo"}, barclays) is None        # any listed employer is worth opening
    assert src.card_skip_reason({"company": "Acme Pvt Ltd"}, SearchParams(keywords="global capability centre")) is None


def test_a_company_that_only_contains_a_bank_name_is_not_that_bank():
    from processing.classifier import classify, is_known_overseas_employer
    assert not is_known_overseas_employer("Mipalloy Nomura Plating Company")      # live result, 18 Oct: was tagged as Nomura
    assert is_known_overseas_employer("Nomura") and is_known_overseas_employer("Nomura Services India")
    assert not classify("Mipalloy Nomura Plating Company", "Driver", "Drive company vehicles.", "Automotive", location="Chennai").eligible
