"""Scraper-output accuracy: nothing the posting states may be lost between the page and the dashboard.

The fixtures in fixtures/real_descriptions.json are real LinkedIn descriptions copied from collected history
(including the IDFC FIRST Bank "Senior Database Administrator" vacancy whose experience showed "Not available").
"""
import json
import re
from pathlib import Path

from collectors.linkedin.detail_parser import parse_job_detail
from dashboard import viewmodel as vm
from models.job import Job
from processing.description_sections import clean_description, extract_designation, extract_sections
from processing.pipeline import normalize_all
from store.json_store import JsonJobHistory
from tests.factories import entry, make_record
from tests.test_dashboard_server import get, running

FIX = Path(__file__).resolve().parent / "fixtures"
REAL = json.loads((FIX / "real_descriptions.json").read_text(encoding="utf-8"))
IDFC = REAL["4403365382"]["description"]


# ---- the reported bug -------------------------------------------------------------------------------------
def test_idfc_experience_heading_with_a_bullet_range_is_extracted():
    sec = extract_sections(IDFC)
    assert sec.experience == ["10 – 18 years."]            # wording copied exactly, nothing invented
    assert sec.designation == "Senior Database Administrator"
    assert sec.qualifications and not any(q.lower().startswith("experience") for q in sec.qualifications)


def test_show_more_less_button_text_is_removed_but_wording_is_untouched():
    assert "Show more" in IDFC and "Show less" in IDFC       # as stored by the earlier scraper
    cleaned = clean_description(IDFC)
    assert "Show more" not in cleaned and "Show less" not in cleaned
    assert cleaned.rstrip().endswith("10 – 18 years.")
    assert clean_description("Plain text.\n\nShow more\n\nShow less") == "Plain text."
    assert clean_description("We show more of the same.") == "We show more of the same."   # only whole button lines
    assert clean_description(None) is None and clean_description("  ") is None


# ---- layouts seen in real listings ------------------------------------------------------------------------
def test_real_layouts():
    ex = lambda i: extract_sections(REAL[i]["description"]).experience
    assert any("Years of experience: 0 to 3" in x for x in ex("4474687029"))          # "Required Work Experience" bullet block
    assert ex("4472755612") and any("6-8 years in handling Branch" in x for x in ex("4472755612"))
    assert any(x.startswith("0-2 years") for x in ex("4469005341"))                   # bare range line
    assert any("Over 8 years of experience in project management" in x for x in ex("4474609165"))
    assert any(x.startswith("8+ years in credit operations") for x in ex("4469434141"))
    assert any("Minimum of 4 years in Banking" in x for x in ex("4474623285"))        # "Minimum of N years" without the word experience


def test_company_history_and_boilerplate_are_not_experience():
    assert extract_sections(REAL["4477868553"]["description"]).experience == []        # "one of the oldest financial institutions"
    text = "We are a bank with over 170 years of history.\n\nMUFG has 360 years of heritage and was founded long ago."
    assert extract_sections(text).experience == []
    edu = "- Bachelor of Applied Science - BASc, Bachelor of Arts - BA (4 years), Master of Science"
    assert extract_sections(edu).experience == []


def test_genuinely_missing_experience_stays_empty():
    sec = extract_sections(REAL["4476938159"]["description"])       # heading "Experience" with only "As per hierarchy."
    assert not any(re.search(r"\d", x) for x in sec.experience)
    assert extract_sections("").experience == [] and extract_sections(None).designation is None


def test_experience_heading_variants():
    for text, want in [("Experience: 5-8 yrs", "5-8 yrs"),
                       ("Total Experience\n\n3+ years in retail lending", "3+ years in retail lending"),
                       ("Experience Required:\n- Minimum 4 years\n- In credit risk\n\nAbout us\nWe are a bank.", "Minimum 4 years"),
                       ("Years of experience required: five to seven years", "five to seven years")]:
        got = extract_sections(text).experience
        assert want in got, (text, got)
        assert not any("We are a bank" in x for x in got)


def test_designation_from_labelled_lines_only():
    assert extract_designation("Designation: Assistant Vice President\nLocation: Pune") == "Assistant Vice President"
    assert extract_designation("Job Title:\nCredit Manager\n\nAbout") == "Credit Manager"
    assert extract_designation("Role/ Job Title: Relationship Manager.") == "Relationship Manager"
    assert extract_designation("Position Description: manage the branch") is None      # not a title label
    assert extract_designation("Job title: " + "x" * 200) is None
    assert extract_designation("We are hiring a Manager") is None


# ---- parser / normalization / storage keep the data -------------------------------------------------------
LD_PAGE = """<script type="application/ld+json">{"@type":"JobPosting","title":"DBA","description":"<p>Run databases.</p><ul><li>Tune queries</li></ul><button>Show more</button><button>Show less</button>",
"hiringOrganization":{"name":"IDFC FIRST Bank"},"datePosted":"2026-10-06T08:30:00Z","employmentType":"FULL_TIME",
"jobLocation":{"address":{"addressLocality":"Navi Mumbai","addressCountry":"IN"}},
"experienceRequirements":{"@type":"OccupationalExperienceRequirements","monthsOfExperience":120},
"educationRequirements":{"@type":"EducationalOccupationalCredential","credentialCategory":"bachelor degree"}}</script>
<div class="show-more-less-html__markup"><p>Run databases.</p><ul><li>Tune queries</li></ul>
<button>Show more</button><button>Show less</button></div>"""


def test_parser_keeps_json_ld_experience_and_education_and_drops_button_text():
    d = parse_job_detail(LD_PAGE)
    assert d["raw"]["experience_requirements"] == "10 years" and d["raw"]["education_requirements"] == "bachelor degree"
    assert "Show more" not in d["description"] and "Show less" not in d["description"] and "- Tune queries" in d["description"]
    html_only = parse_job_detail('<h2 class="top-card-layout__title">DBA</h2><div class="show-more-less-html__markup">'
                                 '<p>Experience:</p><ul><li>10 – 18 years.</li></ul> Show more Show less</div>')
    assert html_only["raw"]["experience_requirements"] is None            # not on the page -> None, never guessed
    page = '<h2 class="top-card-layout__title">DBA</h2><div class="show-more-less-html__markup"><p>Hi</p><p>Show less</p></div>'
    assert "Show less" not in parse_job_detail(page)["description"]


def test_structured_values_survive_normalization():
    from datetime import datetime, timezone
    from processing.pipeline import evaluate_job
    job = {"source": "LinkedIn", "job_id": "9", "title": "DBA", "company": "IDFC FIRST Bank", "location": "Navi Mumbai, Maharashtra, India",
           "job_url": "https://www.linkedin.com/jobs/view/9", "description": IDFC, "employment_type": "Full-time",
           "industries": "Banking", "posted_age_text": "2 hours ago", "collected_at": "2026-10-08T09:50:00+00:00",
           "raw": {"experience_requirements": "10 years", "education_requirements": "bachelor degree"}}
    rec = evaluate_job(job, datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)).record
    assert rec["experience_requirements"] == "10 years" and rec["education_requirements"] == "bachelor degree"
    assert rec["description"] == IDFC                                   # the stored description is the scraped text, unaltered
    bare = evaluate_job({**job, "raw": {"k": "v"}}, datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)).record
    assert bare["experience_requirements"] is None and bare["education_requirements"] is None


# ---- dashboard --------------------------------------------------------------------------------------------
def _dd(h, label):
    return re.search(rf'<th scope="row">{re.escape(label)}</th><td>(.*?)</td></tr>', h, re.S).group(1)


def test_details_page_shows_experience_designation_and_clean_description(tmp_path):
    idfc = make_record(4403365382, "Senior Database Administrator", "IDFC FIRST Bank", "Navi Mumbai, Maharashtra, India",
                       description=IDFC, seniority_level="Not Applicable")
    nothing = make_record(4403365383, "Clerk", "Acme Bank", description="A short role with no stated requirements at all here today.")
    structured = make_record(4403365384, "Analyst", "Acme Bank", description="Do analysis work for the bank every day.",
                             experience_requirements="10 years", education_requirements="bachelor degree")
    with running(tmp_path, records=[idfc, nothing, structured], second_run=[]) as (port, _):
        h = get(port, "/job/linkedin-4403365382")[2]
        assert "10 – 18 years." in _dd(h, "Experience required") and "Not available" not in _dd(h, "Experience required")
        assert "Senior Database Administrator" in _dd(h, "Designation") and "Stated in the job description" in _dd(h, "Designation")
        assert "Show more" not in _dd(h, "Full job description") and "Show less" not in _dd(h, "Full job description")
        h2 = get(port, "/job/linkedin-4403365383")[2]
        assert "Not available" in _dd(h2, "Experience required") and "Not available" in _dd(h2, "Designation")
        h3 = get(port, "/job/linkedin-4403365384")[2]
        assert "10 years" in _dd(h3, "Experience required") and "bachelor degree" in _dd(h3, "Required qualifications and skills")


def test_rows_prefer_source_designation_then_description_then_seniority():
    rows = vm.build_rows([
        entry(1, designation="Vice President", description="Designation: Other"),
        entry(2, description="Designation: Credit Manager", seniority_level="Director"),
        entry(3, description="Nothing labelled.", seniority_level="Director"),
        entry(4, description="Nothing labelled.", seniority_level="Not Applicable")], {}, None)
    got = {r.job_id: (r.designation, r.designation_source) for r in rows}
    assert got == {"1": ("Vice President", "source"), "2": ("Credit Manager", "description"),
                   "3": ("Director", "seniority"), "4": (None, "")}


def test_all_stored_real_jobs_extract_without_error_and_find_more_than_before():
    """Run the extractor over every job in the bundled real fixtures; a malformed description must never raise."""
    for rec in REAL.values():
        sec = extract_sections(rec["description"])
        assert isinstance(sec.experience, list) and len(sec.experience) <= 6
