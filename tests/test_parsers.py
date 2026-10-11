from datetime import date
from pathlib import Path

import pytest

from collectors.errors import ParseError
from collectors.linkedin.detail_parser import parse_job_detail
from collectors.linkedin.search_parser import parse_search_results

FIX = Path(__file__).parent / "fixtures"
read = lambda name: (FIX / name).read_text(encoding="utf-8")


def test_search_parser_extracts_cards_and_skips_broken_one():
    stubs = parse_search_results(read("search_results.html"))
    assert [s["job_id"] for s in stubs] == ["4001111111", "4002222222"]
    first = stubs[0]
    assert first["title"] == "Senior Analyst - Risk"
    assert first["company"] == "Acme Bank GCC"
    assert first["company_url"] == "https://in.linkedin.com/company/acme-bank"
    assert first["location"] == "Bengaluru, Karnataka, India"
    assert first["posted_date"] == date(2026, 10, 6)          # from the datetime attribute
    assert first["posted_age_text"] == "2 days ago"
    # second card has no datetime attribute: date stays unknown, relative text is kept
    assert stubs[1]["posted_date"] is None
    assert stubs[1]["posted_age_text"] == "3 hours ago"
    assert first["job_url"] == "https://www.linkedin.com/jobs/view/4001111111"


def test_detail_parser_prefers_json_ld():
    d = parse_job_detail(read("job_detail_ld.html"))
    assert d["title"] == "Senior Analyst - Risk"
    assert d["company"] == "Acme Bank GCC"
    assert d["company_url"] == "https://www.linkedin.com/company/acme-bank"
    assert d["location"] == "Bengaluru, Karnataka, India"
    assert d["employment_type"] == "Full-time"
    assert d["posted_date"] == date(2026, 10, 6)
    assert d["posted_timestamp"] == "2026-10-06T08:30:00+00:00"
    assert d["seniority_level"] == "Mid-Senior level"
    assert d["industries"] == "Banking"
    assert "Join our GCC." in d["description"] and "- Model credit risk" in d["description"]
    assert d["raw"]["json_ld"]["@type"] == "JobPosting"


def test_detail_parser_html_fallback():
    d = parse_job_detail(read("job_detail_html.html"))
    assert d["title"] == "Data Engineer"
    assert d["company"] == "Globex Financial"
    assert d["location"] == "Hyderabad, Telangana, India"
    assert d["employment_type"] == "Contract"
    assert "- Spark" in d["description"]
    # relative text must NOT be turned into a date in the detail parser (can be a day off)
    assert d["posted_date"] is None
    assert d["posted_age_text"] == "1 week ago"
    assert d["posted_timestamp"] is None


def test_detail_parser_raises_on_empty_page():
    with pytest.raises(ParseError):
        parse_job_detail("<html><body>Sign in to LinkedIn</body></html>")
