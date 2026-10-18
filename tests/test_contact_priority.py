"""'Contact Details Available' filter, no tags in the list, and collection that prefers (but never at the cost of recency
or eligibility) postings whose poster states contact details."""
import re
from urllib.parse import parse_qsl, urlsplit

from config import settings
from dashboard import viewmodel as vm
from processing.contacts import extract_contacts, poster_contacts
from tests.factories import make_record
from tests.test_collection_and_controls import manager as make_manager, raw_job
from tests.test_dashboard_server import get, row_count, running, titles
from tests.test_vacancy_target import PLACES, Universe
from tests.test_viewmodel import rows_from

CALL = "Interested candidates can call 9876501234 for this role."
NONE = "A banking role. Apply through the website."


class pool:
    """Turn the candidate pool on for one test (the rest of the suite runs with exactly-N)."""
    def __init__(self, factor=2, tol=1):
        self.factor, self.tol = factor, tol

    def __enter__(self):
        self.old = (settings.COLLECTION_CANDIDATE_POOL_FACTOR, settings.COLLECTION_RECENCY_TOLERANCE_HOURS)
        settings.COLLECTION_CANDIDATE_POOL_FACTOR, settings.COLLECTION_RECENCY_TOLERANCE_HOURS = self.factor, self.tol

    def __exit__(self, *a):
        settings.COLLECTION_CANDIDATE_POOL_FACTOR, settings.COLLECTION_RECENCY_TOLERANCE_HOURS = self.old


def job(n, age="2 hours ago", contact=False, **kw):
    return raw_job(n, posted_age_text=age, description=CALL if contact else NONE, title=f"Job {n}", **kw)


def collect(tmp_path, listing, target):
    out = tmp_path / "out"; out.mkdir(exist_ok=True)
    uni = Universe(out, {PLACES[0]: listing})
    mgr, hist = make_manager(tmp_path, uni)
    assert mgr.start("india", target)[0]
    st = mgr.status()
    return {e["record"]["title"] for e in hist.list_jobs() if e["key"] in set(st["result_keys"])}, st, uni


# ---- collection ---------------------------------------------------------------------------------------------------------
def test_among_postings_of_similar_recency_those_with_poster_contacts_come_first(tmp_path):
    listing = [job(1), job(2), job(3), job(4, contact=True), job(5, contact=True), job(6, contact=True)]     # all posted 2 hours ago
    with pool():
        got, st, uni = collect(tmp_path, listing, 3)
    assert got == {"Job 4", "Job 5", "Job 6"} and st["collected_unique"] == 3
    assert uni.calls[0]["cap"] == 6                                              # 2 x the target was gathered, 3 kept


def test_a_newer_posting_is_never_dropped_for_an_older_one_that_has_contacts(tmp_path):
    listing = [job(1, "1 hours ago"), job(2, "1 hours ago"), job(3, "5 hours ago", True), job(4, "5 hours ago", True),
               job(5, "9 hours ago", True), job(6, "9 hours ago", True)]
    with pool():
        got, st, _ = collect(tmp_path, listing, 2)
    assert got == {"Job 1", "Job 2"}                                             # recency first, contacts do not outrank it


def test_contacts_decide_only_inside_a_recency_window_and_recency_orders_the_windows(tmp_path):
    listing = [job(1, "1 hours ago"), job(2, "1 hours ago", True), job(3, "6 hours ago", True), job(4, "6 hours ago", True)]
    with pool():
        got, _, _ = collect(tmp_path, listing, 3)
    assert got == {"Job 1", "Job 2", "Job 3"}                                    # both 1h postings, then one of the two 6h ones


def test_eligibility_still_applies_a_non_gcc_bfsi_posting_with_contacts_is_not_used(tmp_path):
    shop = [job(i, contact=True, industries="Retail", company="Corner Shop") for i in (1, 2)]
    listing = shop + [job(3), job(4), job(5)]
    with pool():
        got, st, _ = collect(tmp_path, listing, 2)
    assert got == {"Job 3", "Job 4"} and st["skipped_not_relevant"] >= 2


def test_out_of_scope_locations_are_not_used_either(tmp_path):
    listing = [job(1, contact=True, location="London, England, United Kingdom"), job(2), job(3), job(4)]
    with pool():
        got, st, _ = collect(tmp_path, listing, 2)
    assert "Job 1" not in got and len(got) == 2 and st["skipped_out_of_scope"] >= 1


def test_a_target_is_still_filled_when_few_postings_have_contacts(tmp_path):
    listing = [job(i) for i in range(1, 7)] + [job(7, contact=True)]
    with pool():
        got, st, _ = collect(tmp_path, listing, 3)
    assert len(got) == 3 and st["stop_reason"] == "target_reached"


def test_pool_factor_one_gathers_exactly_the_target(tmp_path):
    with pool(factor=1):
        got, st, uni = collect(tmp_path, [job(i) for i in range(1, 9)], 3)
    assert uni.calls[0]["cap"] == 3 and len(got) == 3


# ---- what counts as the poster's contact details -------------------------------------------------------------------------
def test_only_what_the_posting_states_for_the_poster_counts():
    assert poster_contacts("Call 9876501234").direct
    assert poster_contacts("mail hr@acme.example").direct
    assert poster_contacts("Recruiter: https://www.linkedin.com/in/jane-doe-123/ for details").linkedin == "https://www.linkedin.com/in/jane-doe-123"
    assert poster_contacts("see https://www.linkedin.com/in/jane-doe-123/").direct
    assert not poster_contacts("Apply at https://careers.acme.example/job/1").direct             # an apply link is not a contact
    assert not poster_contacts("For accommodation email accessibility@acme.example").direct       # company process line
    assert not poster_contacts("A name alone: contact Jane Doe").direct
    assert poster_contacts(None, "hr@acme.example").direct and poster_contacts(None, None, "98765 01234").direct
    assert poster_contacts(None, contact_url="https://www.linkedin.com/in/jane-doe").direct


# ---- dashboard -----------------------------------------------------------------------------------------------------------
def dataset():
    return [make_record(1, "Phone job", "Acme Bank", description="Call 9876501234 to apply."),
            make_record(2, "Mail job", "Acme Bank", description="Email hr@acme.example to apply."),
            make_record(3, "Profile job", "Acme Bank", description="Message the recruiter https://www.linkedin.com/in/jane-doe-123 today."),
            make_record(4, "Stored contact", "Acme Bank", recruiter_email="x@acme.example", description="Nothing here."),
            make_record(5, "No contact", "Acme Bank", description="Apply on the website https://careers.acme.example/5"),
            make_record(6, "Accommodation only", "Acme Bank", description="For accommodation email accessibility@acme.example")]


def selected(html, name):
    sel = re.search(rf'<select id="f-{name}".*?</select>', html, re.S).group(0)
    return re.search(r'<option value="([^"]*)" selected>', sel).group(1)


def test_the_list_no_longer_shows_contact_tags(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, _):
        h = get(port, "/")[2]
        assert "Contact directly available" not in h and "Contact not directly fetched" not in h and "data-contact" not in h
        assert row_count(h) == 6


def test_the_contact_details_available_filter(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, _):
        h = get(port, "/")[2]
        assert "Contact Details Available" in h and selected(h, "contact") == "all"
        opts = re.findall(r'<option value="([^"]*)"', re.search(r'<select id="f-contact".*?</select>', h, re.S).group(0))
        assert opts == ["all", "yes", "no"]
        t = lambda q: set(titles(get(port, "/?" + q)[2]))
        assert t("contact=yes") == {"Phone job", "Mail job", "Profile job", "Stored contact"}
        assert t("contact=no") == {"No contact", "Accommodation only"}
        assert t("contact=bogus") == t("contact=all") and len(t("contact=all")) == 6
        assert selected(get(port, "/?contact=yes")[2], "contact") == "yes"
        assert "(1 filter applied" in get(port, "/?contact=yes")[2]


def test_company_and_suggested_contacts_never_make_a_job_count_as_yes():
    rows = {r.title: r for r in rows_from([make_record(1, "Has", "Globex", description="Write to talent@globex.example"),
                                            make_record(2, "Lacks", "Globex", description="No contact here.")])}
    assert rows["Has"].contact_direct and not rows["Lacks"].contact_direct
    got = vm.apply_filters(list(rows.values()), vm.Filters(scope="all", contact="yes"), None)
    assert [r.title for r in got] == ["Has"]


def test_the_contact_filter_works_with_the_others_and_survives_sort_paging_and_details(tmp_path):
    recs = [make_record(100 + i, f"Pune {i:03d}", "Acme Bank", "Pune, Maharashtra, India", "Permanent" if i % 2 else "Contract",
                        description="Call 9876501234.") for i in range(130)] + dataset()
    with running(tmp_path, records=recs, second_run=[]) as (port, _):
        h = get(port, "/?contact=yes&state=Maharashtra&employment=Permanent&sort=title")[2]
        assert selected(h, "contact") == "yes" and selected(h, "state") == "Maharashtra" and selected(h, "employment") == "Permanent"
        links = [l.replace("&amp;", "&") for l in re.findall(r'href="(/[^"]*)"', h)]
        page2 = next(l for l in links if "page=2" in l)
        assert dict(parse_qsl(urlsplit(page2).query)).get("contact") == "yes"
        assert any("sort=" in l and "contact=yes" in l for l in links)
        h2 = get(port, page2)[2]
        assert selected(h2, "contact") == "yes"
        detail = re.search(r'href="(/job/[^"]+)"', h2).group(1).replace("&amp;", "&")
        back = re.search(r'<a href="(/\?[^"]*)">Back to vacancies</a>', get(port, detail)[2]).group(1).replace("&amp;", "&")
        assert dict(parse_qsl(urlsplit(back).query)).get("contact") == "yes"
        assert 'name="contact"' in get(port, "/")[2] and "contact=" not in re.search(r'data-reset-filters[^>]*', get(port, "/?contact=no")[2]).group(0)


def test_reset_filters_returns_the_contact_filter_to_all(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, _):
        busy = get(port, "/?contact=no")[2]
        link = re.search(r'<a class="btn btn-reset" href="([^"]*)"', busy).group(1)
        assert link == "/" and selected(get(port, link)[2], "contact") == "all"


def test_the_details_page_shows_the_linkedin_profile_written_in_the_posting(tmp_path):
    with running(tmp_path, records=dataset(), second_run=[]) as (port, _):
        d = get(port, "/job/linkedin-3")[2]
        assert 'href="https://www.linkedin.com/in/jane-doe-123"' in d and "LinkedIn profile" in d
        d = get(port, "/job/linkedin-5")[2]
        assert "LinkedIn profile" in d and "linkedin.com/in/" not in d       # nothing is looked up when the posting has none


# ---- speed: the extra candidates never mean searching more places ------------------------------------------------------------
def test_reaching_the_target_stops_the_search_even_though_the_candidate_pool_is_not_full(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: [job(1), job(2), job(3)], PLACES[1]: [job(11), job(12), job(13)]})
    mgr, hist = make_manager(tmp_path, uni)
    with pool():
        assert mgr.start("india", 3)[0]
    st = mgr.status()
    assert st["collected_unique"] == 3 and st["stop_reason"] == "target_reached"
    assert [c["place"] for c in uni.calls] == [PLACES[0]]                       # no second place was searched


def test_a_short_first_place_moves_on_only_until_the_target_is_met(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    uni = Universe(out, {PLACES[0]: [job(1)], PLACES[1]: [job(11), job(12), job(13), job(14)], PLACES[2]: [job(21)]})
    mgr, hist = make_manager(tmp_path, uni)
    with pool():
        assert mgr.start("india", 3)[0]
    assert mgr.status()["collected_unique"] == 3 and PLACES[2] not in [c["place"] for c in uni.calls]


# ---- the list order -------------------------------------------------------------------------------------------------------------
def test_the_default_list_shows_postings_with_poster_contacts_first_within_a_recency_window():
    from datetime import datetime, timezone
    base = datetime(2026, 10, 14, 6, 0, 0, tzinfo=timezone.utc)             # 06:00 - the 06:00-07:00 window
    iso = lambda h, m=0: base.replace(hour=h, minute=m).isoformat()
    recs = [make_record(1, "No contact newest", "Acme Bank", description=NONE, posted=iso(6, 50), precision="exact"),
            make_record(2, "Has contact same window", "Acme Bank", description=CALL, posted=iso(6, 10), precision="exact"),
            make_record(3, "Has contact older window", "Acme Bank", description=CALL, posted=iso(3), precision="exact"),
            make_record(4, "No contact older window", "Acme Bank", description=NONE, posted=iso(3, 30), precision="exact")]
    with pool(factor=1, tol=1):
        got = [r.title for r in vm.sort_rows(rows_from(recs), "recent")]
    assert got == ["Has contact same window", "No contact newest", "Has contact older window", "No contact older window"]


def test_the_list_shows_the_recruiter_contact_stated_in_the_posting_and_nothing_else():
    from dashboard import views
    from tests.test_viewmodel import rows_from
    rows = rows_from([make_record(1, "With contact", description="Contact Priya Shah, email priya@acme.example or call 9876501234."),
                      make_record(2, "No contact", description="Apply on the website.")])
    by = {r.title: views._contact_cell(r) for r in rows}
    assert "mailto:priya@acme.example" in by["With contact"] and "9876501234" in by["With contact"]
    assert "Not stated in the posting" in by["No contact"] and "@" not in by["No contact"]


def test_the_posted_column_shows_the_posting_date_and_contact_vacancies_lead_within_a_day():
    from dashboard import views
    from dashboard import viewmodel as vm
    from tests.factories import NOW, ago
    from tests.test_viewmodel import rows_from
    rows = rows_from([make_record(1, "Newest no contact", description="Apply online.", posted=ago(hours=1)),
                      make_record(2, "Older with contact", description="Email hr@acme.example", posted=ago(hours=10)),
                      make_record(3, "Day old with contact", description="Call 9876501234", posted=ago(hours=40))])
    titles = [r.title for r in vm.sort_rows(rows, "recent")]
    assert titles == ["Older with contact", "Newest no contact", "Day old with contact"]
    html = views._row_html(rows[0], vm.Filters(), NOW, "/")
    assert vm.format_posted_on(rows[0].posted) in html and "IST" in html
