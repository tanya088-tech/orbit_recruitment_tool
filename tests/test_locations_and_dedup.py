from config import locations as loc
from config import settings
from store.json_store import JsonJobHistory
from store.keys import job_key, match_url
from tests.factories import NOW, make_record
from datetime import timedelta


# ------------------------------------------------------------------ pan-India / international seed locations
def test_search_locations_cover_many_indian_cities_and_countries():
    india = loc.search_locations("india")
    assert india[0] == "India" and len(india) >= 30
    for city in ("Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Chennai", "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Kochi", "Gurugram", "Noida"):
        assert any(x.startswith(city) for x in india), city
    assert any("Bengaluru" in x for x in india) and sum("Bengaluru" in x for x in india) == 1
    intl = loc.search_locations("international")
    for country in ("United Arab Emirates", "Singapore", "United Kingdom", "United States"):
        assert country in intl, country
    assert not any(x.endswith("India") for x in intl)
    assert loc.search_locations("both") == india + intl
    assert len(set(india + intl)) == len(india + intl)             # no duplicates


def test_unknown_scope_is_rejected_and_scopes_are_labelled():
    try:
        loc.search_locations("mars")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert set(loc.SCOPES) == {"india", "both", "international"} and settings.COLLECTION_DEFAULT_SCOPE in loc.SCOPES


# ------------------------------------------------------------------ dedup
def test_match_url_ignores_tracking_and_generic_pages():
    a = match_url({"job_url": "https://in.linkedin.com/jobs/view/foo-4001111111?trk=x"})
    b = match_url({"job_url": "https://www.linkedin.com/jobs/view/4001111111/"})
    assert a == b and a is not None
    for generic in ("https://www.linkedin.com/jobs", "https://www.linkedin.com/jobs/search", "https://example.com/", "", None):
        assert match_url({"job_url": generic}) is None
    assert match_url({}) is None


def test_same_job_from_another_source_with_the_same_url_is_one_vacancy(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    url = "https://careers.example.com/jobs/risk-analyst-77"
    first = make_record(1, source="Naukri", job_url=url, work_mode="Unknown")
    h.ingest([first], now=NOW)
    twin = make_record(900, source="Indeed", job_url=url + "?utm_source=indeed", work_mode="Hybrid", recruiter_name="R. Rao")
    r = h.ingest([twin], now=NOW + timedelta(days=1))
    assert len(h.list_jobs()) == 1 and r.new == 0
    kept = h.get_job(job_key(first))
    assert kept["record"]["source"] == "Naukri"                        # the first record is kept
    assert kept["record"]["work_mode"] == "Hybrid" and kept["record"]["recruiter_name"] == "R. Rao"   # gaps are filled
    assert kept["times_seen"] == 2


def test_different_jobs_are_not_merged_and_same_source_id_dedup_still_works(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([make_record(1), make_record(2)], now=NOW)
    h.ingest([make_record(1), make_record(2), make_record(3)], now=NOW + timedelta(hours=3))
    jobs = h.list_jobs()
    assert len(jobs) == 3 and {j["times_seen"] for j in jobs} == {1, 2}
    # same company and title but a different city, or a different title in the same city, stay separate: no guessing
    h2 = JsonJobHistory(tmp_path / "h2.json")
    h2.ingest([make_record(1, source="A", job_url="https://a.example/1"),
               make_record(2, source="B", job_url="https://b.example/2", location="Mumbai, Maharashtra, India"),
               make_record(3, source="C", job_url="https://c.example/3", title="Treasury Analyst")], now=NOW)
    assert len(h2.list_jobs()) == 3


def test_first_and_last_seen_are_stored(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([make_record(1)], now=NOW)
    h.ingest([make_record(1)], now=NOW + timedelta(days=2))
    j = h.get_job("linkedin-1")
    assert j["first_ingested_at"].startswith("2026-10-08") and j["last_seen_at"].startswith("2026-10-10")
    assert j["record"]["source"] == "LinkedIn" and j["record"]["job_url"]
