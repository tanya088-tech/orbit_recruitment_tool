"""Revision: New-vacancies KPI by posting date, Employment type x Work mode, no status filter,
full details page, contact fields, historical data and dedup."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard import viewmodel as vm
from models.job import Job
from processing.pipeline import normalize_all
from processing.work_mode import classify_work_mode, work_mode_for
from store.json_store import JsonJobHistory, JsonRecruiterState
from tests.factories import NOW, ago, entry, make_record
from tests.test_dashboard_server import get, row_count, running, titles
from tests.test_viewmodel import apply, ids, rows_from

ROOT = Path(__file__).resolve().parent.parent


def fig(html, label):
    return int(re.search(rf"<b>(\d+)</b><span>{re.escape(label)}</span>", html).group(1))


# ------------------------------------------------------------------ A. the three KPI cards
def test_kpis_over_http_follow_the_selected_filters(tmp_path):
    recs = [make_record(1, posted=ago(hours=5), employment="Permanent"), make_record(2, posted=ago(days=2), employment="Contract"),
            make_record(3, posted=ago(days=20), employment="Permanent")]
    labels = ("Total openings", "Permanent openings", "Contract openings")
    with running(tmp_path, records=recs, second_run=[]) as (port, _):
        h = get(port, "/")[2]
        assert [fig(h, x) for x in labels] == [3, 2, 1]
        assert h.count('class="fig"') == 3                                   # only three cards
        h = get(port, "/?employment=Permanent")[2]
        assert [fig(h, x) for x in labels] == [2, 2, 0]
        h = get(port, "/?employment=Contract")[2]
        assert [fig(h, x) for x in labels] == [1, 0, 1]


# ------------------------------------------------------------------ B-D. work mode, employment type, combinations
def test_work_mode_rules():
    c = lambda *t: classify_work_mode(*t).mode
    assert c("Pune, Maharashtra, India (Hybrid)") == "Hybrid" and c("Hybrid - Mumbai") == "Hybrid"
    assert c("Remote, India") == "Remote" and c("India (Work from home)") == "Remote" and c("WFH") == "Remote"
    assert c("Bengaluru - On-site") == "On-site" and c("Onsite, Chennai") == "On-site" and c("Pune (In office)") == "On-site"
    assert c("Hybrid remote") == "Hybrid"                                   # a mix is Hybrid
    assert c("Pune, Maharashtra, India") == "Unknown"                        # a plain city says nothing about work mode
    assert c(None) == "Unknown" and c("") == "Unknown" and c(None, "  ") == "Unknown"       # missing location is not Remote
    assert c("Pune", "TELECOMMUTE") == "Remote"                              # schema.org jobLocationType


def test_work_mode_is_read_from_stored_value_or_derived_for_old_records():
    assert work_mode_for({"work_mode": "Hybrid", "location": "Pune"}) == "Hybrid"
    assert work_mode_for({"location": "Remote, India"}) == "Remote"                        # old history record, no work_mode field
    assert work_mode_for({"location": "Pune", "raw_data": {"json_ld": {"jobLocationType": "TELECOMMUTE"}}}) == "Remote"
    assert work_mode_for({"work_mode": "garbage", "location": "Pune"}) == "Unknown"


MATRIX = [(emp, mode) for emp in ("Permanent", "Contract") for mode in ("On-site", "Hybrid", "Remote")]


def matrix_rows():
    suffix = {"On-site": "(On-site)", "Hybrid": "(Hybrid)", "Remote": "(Remote)"}
    recs = [make_record(100 + i, f"{emp} {mode}", location=f"Pune, Maharashtra, India {suffix[mode]}", employment=emp)
            for i, (emp, mode) in enumerate(MATRIX)]
    recs.append(make_record(200, "Permanent Unknown", location="Pune, Maharashtra, India", employment="Permanent"))
    recs.append(make_record(201, "Contract NoLocation", location=None, employment="Contract"))
    return rows_from(recs)


def test_employment_type_filter():
    rows = matrix_rows()
    assert {r.display_title for r in apply(rows, employment="Permanent")} == {f"Permanent {m}" for m in ("On-site", "Hybrid", "Remote")} | {"Permanent Unknown"}
    assert {r.display_title for r in apply(rows, employment="Contract", scope="all")} == {f"Contract {m}" for m in ("On-site", "Hybrid", "Remote")} | {"Contract NoLocation"}
    assert len(apply(rows, employment="all", scope="all")) == 8


def test_work_mode_filter_and_unknown_stays_under_all():
    rows = matrix_rows()
    for mode in ("On-site", "Hybrid", "Remote"):
        assert {r.display_title for r in apply(rows, work_mode=mode)} == {f"Permanent {mode}", f"Contract {mode}"}
    assert len(apply(rows, work_mode="all", scope="all")) == 8                              # the two Unknown jobs are visible under All
    assert {r.work_mode for r in rows if r.display_title in ("Permanent Unknown", "Contract NoLocation")} == {"Unknown"}
    assert len(apply(rows, work_mode="Unknown", scope="all")) == 8                          # not a filter option: ignored, shows everything


def test_all_six_employment_by_work_mode_combinations():
    rows = matrix_rows()
    for emp, mode in MATRIX:
        got = apply(rows, employment=emp, work_mode=mode)
        assert [r.display_title for r in got] == [f"{emp} {mode}"], (emp, mode)    # exactly one job, never mutually exclusive
        assert got[0].employment_type == emp and got[0].work_mode == mode


def test_combinations_over_http(tmp_path):
    recs = [make_record(100 + i, f"{e} {m}", location=f"Pune, Maharashtra, India ({m})", employment=e) for i, (e, m) in enumerate(MATRIX)]
    with running(tmp_path, records=recs, second_run=[]) as (port, _):
        for e, m in MATRIX:
            assert titles(get(port, f"/?employment={e}&work_mode={m}")[2]) == [f"{e} {m}"]
        assert row_count(get(port, "/?work_mode=Hybrid")[2]) == 2 and row_count(get(port, "/?employment=Contract")[2]) == 3


# ------------------------------------------------------------------ E. no recruitment-status filter
def test_recruitment_status_filter_is_gone():
    assert not hasattr(vm.Filters(), "status")
    f = vm.Filters.from_query({"status": "Reviewing", "work_mode": "Hybrid"})
    assert f.work_mode == "Hybrid" and "status" not in f.to_query()
    assert vm.Filters.from_query({"work_mode": "Sideways"}).work_mode == "all"
    assert f.active_count == 1


def test_status_filter_not_in_the_page_but_details_still_work(tmp_path):
    with running(tmp_path) as (port, _):
        html = get(port, "/")[2]
        filters = html[html.index('<form class="filters"'):html.index("</form>", html.index('<form class="filters"'))]
        assert "Recruitment status" not in filters and 'name="status"' not in filters


# ------------------------------------------------------------------ F. job details page
LONG_DESC = "About the role\n\n" + "\n".join(f"• Responsibility number {i}: manage <regulatory> reporting & controls" for i in range(1, 201)) + "\n\nThe very last line."


def test_details_page_sections_and_complete_description(tmp_path):
    rec = make_record(3001, "Head of Risk", "Acme Bank", "Pune, Maharashtra, India (Hybrid)", "Permanent", description=LONG_DESC,
                      seniority_level="Director", job_function=None, job_role=None)
    with running(tmp_path, records=[rec], second_run=[]) as (port, _):
        status, _, h = get(port, "/job/linkedin-3001")
        assert status == 200
        assert h.count('<table class="details"') == 1                       # one compact table, not many panels
        labels = ["Company name", "Job title", "Designation", "Industry", "Location", "Work mode", "Employment type", "Posting date",
                  "Source", "Original job URL", "Job summary", "Full job description", "Key responsibilities",
                  "Required qualifications and skills", "Experience required", "Recruiter / contact name", "Phone number", "Email",
                  "Contact URL"]
        for label in labels:
            assert f'<th scope="row">{label}</th>' in h, label
        order = [h.index(f'<th scope="row">{x}</th>') for x in labels]
        assert order == sorted(order) and ">Actions</h2>" in h
        dd = lambda label: re.search(rf'<th scope="row">{re.escape(label)}</th><td>(.*?)</td></tr>', h, re.S).group(1)
        assert dd("Job title") == "Head of Risk" and "Acme Bank" in dd("Company name") and dd("Location") == "Pune, Maharashtra, India (Hybrid)"
        assert dd("Employment type") == "Permanent" and dd("Work mode") == "Hybrid"
        assert "Director" in dd("Designation") and "Banking, Financial Services &amp; Insurance (BFSI)" in dd("Industry") and "LinkedIn" in dd("Source")
        assert "GCC" not in h and "BFSI" not in h.replace("Insurance (BFSI)", "")
        assert "Not available" in dd("Phone number")
        # every line of the description is there (escaped), including the last one: nothing is cut off
        assert "Responsibility number 1:" in h and "Responsibility number 200:" in h and "The very last line." in h
        full = h[h.index("Full job description"):h.index("Key responsibilities")]
        assert full.count("Responsibility number") == 200 and "manage &lt;regulatory&gt; reporting &amp; controls" in h
        assert '<p class="description">About the role\n\n• Responsibility' in h                         # paragraphs / bullets kept


def test_contact_information_shown_when_present_and_not_available_when_absent(tmp_path):
    with_contact = make_record(3002, "With contact", recruiter_name="A. Recruiter", recruiter_email="a.recruiter@acme.example",
                               recruiter_phone="+91 99999 00000", contact_url="https://www.linkedin.com/in/a-recruiter")
    without = make_record(3003, "Without contact", company="Lonely Co")
    hostile = make_record(3004, "Hostile contact", recruiter_email="<script>x</script>", contact_url="javascript:alert(1)", recruiter_name="<b>N</b>")
    with running(tmp_path, records=[with_contact, without, hostile], second_run=[]) as (port, _):
        h = get(port, "/job/linkedin-3002")[2]
        assert "A. Recruiter" in h and "+91 99999 00000" in h
        assert 'href="mailto:a.recruiter@acme.example"' in h and 'href="https://www.linkedin.com/in/a-recruiter"' in h
        sect = h[h.index("Recruiter and contact</th>"):h.index("</table>")]
        assert sect.count("Not available") == 1 and "LinkedIn profile" in sect       # only the Contact URL is empty; the profile link is shown
        h = get(port, "/job/linkedin-3003")[2]
        section = h[h.index("Recruiter and contact</th>"):h.index("</table>")]
        assert section.count("Not available") == 5 and "mailto:" not in section and "@" not in section      # nothing invented
        h = get(port, "/job/linkedin-3004")[2]
        assert "<script>x" not in h and "&lt;script&gt;x&lt;/script&gt;" in h and 'href="javascript:' not in h and "mailto:" not in h


def test_original_job_button_opens_the_source_url(tmp_path):
    with running(tmp_path) as (port, _):
        h = get(port, "/job/linkedin-1001")[2]
        assert '<a class="btn btn-primary" href="https://www.linkedin.com/jobs/view/1001" target="_blank" rel="noopener noreferrer">Open Original Job</a>' in h
        assert ">Save job<" in h and h.index(">Actions</h2>") < h.index("Open Original Job")


def test_old_history_records_without_new_fields_still_open(tmp_path):
    legacy = {"source": "LinkedIn", "job_id": "4001", "title": "Legacy job", "company": "Old Co", "location": "Remote, India",
              "country": "India", "employment_type": "Permanent", "job_url": "https://www.linkedin.com/jobs/view/4001",
              "potential_gcc": False, "potential_bfsi": True, "description": "Old description"}
    with running(tmp_path, records=[legacy], second_run=[]) as (port, _):
        status, _, h = get(port, "/job/linkedin-4001")
        assert status == 200 and "Old description" in h and "Not available" in h
        assert titles(get(port, "/?work_mode=Remote")[2]) == ["Legacy job"]          # work mode derived on the fly


# ------------------------------------------------------------------ data model / pipeline
def test_job_model_and_pipeline_carry_the_new_fields_as_null():
    d = Job(source="LinkedIn", job_id="1", title="t", company="c", location="Pune, India", job_url="https://x/1").to_dict()
    for k in ("designation", "job_role", "recruiter_name", "recruiter_email", "recruiter_phone", "contact_url"):
        assert k in d and d[k] is None
    rec = normalize_all([d], as_of=NOW).jobs[0]
    assert rec["work_mode"] == "Unknown" and rec["recruiter_email"] is None and rec["recruiter_phone"] is None and rec["designation"] is None
    d.update(location="Pune, India (Hybrid)", recruiter_email="r@x.example", job_function="Finance")
    rec = normalize_all([d], as_of=NOW).jobs[0]
    assert rec["work_mode"] == "Hybrid" and rec["recruiter_email"] == "r@x.example" and rec["job_role"] == "Finance"


def test_later_sighting_can_fill_unknown_work_mode(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([make_record(1, work_mode="Unknown")], now=NOW)
    h.ingest([make_record(1, work_mode="Hybrid", recruiter_name="R")], now=NOW + timedelta(days=1))
    rec = h.get_job("linkedin-1")["record"]
    assert rec["work_mode"] == "Hybrid" and rec["recruiter_name"] == "R"
    h.ingest([make_record(1, work_mode="Remote")], now=NOW + timedelta(days=2))
    assert h.get_job("linkedin-1")["record"]["work_mode"] == "Hybrid"        # a known value is never overwritten


# ------------------------------------------------------------------ G. historical data
def test_all_means_every_job_in_history_including_very_old_ones(tmp_path):
    recs = [make_record(1, posted=ago(minutes=30)), make_record(2, posted="2026-09-30", precision="date_only"),
            make_record(3, posted="2026-01-15", precision="date_only"), make_record(4, posted="2019-05-01", precision="date_only"),
            make_record(7, posted="2026-09-12", precision="date_only"),
            make_record(5, posted=ago(days=400)), make_record(6, posted=None, precision="unknown")]
    rows = rows_from(recs)
    assert len(apply(rows, posted="all")) == 7                                  # nothing before or after any cut-off is hidden
    assert set(ids(apply(rows, posted="15d"))) == {"1", "2"} and set(ids(apply(rows, posted="1m"))) == {"1", "2", "7"}   # undated / old never qualify
    with running(tmp_path, records=recs, second_run=[]) as (port, _):
        assert row_count(get(port, "/")[2]) == 7 and row_count(get(port, "/?posted=all")[2]) == 7


def test_no_hard_coded_start_date_in_the_dashboard_or_history_code():
    pattern = re.compile(r"2026\W{0,3}0?10\W{0,3}0?1\b|oct(ober)?\.?\s*1\b|min_date|earliest_date|HISTORY_START|START_DATE", re.I)
    offenders = []
    for folder in ("dashboard", "store", "processing", "config"):
        for path in (ROOT / folder).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert offenders == []


# ------------------------------------------------------------------ H. deduplication
def test_same_linkedin_job_scraped_again_is_one_vacancy(tmp_path):
    a = make_record(5001, "Repeated job")
    b = make_record(5001, "Repeated job")
    b["job_url"] = "https://in.linkedin.com/jobs/view/repeated-job-5001?trk=x"
    with running(tmp_path, records=[a, make_record(5002)], second_run=[b, a]) as (port, app):
        assert titles(get(port, "/")[2]).count("Repeated job") == 1 and row_count(get(port, "/")[2]) == 2
        assert app.history.get_job("linkedin-5001")["times_seen"] == 2
        assert len(app.history.list_jobs()) == 2
