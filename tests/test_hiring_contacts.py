"""Job poster (only what the posting page shows) and Suggested Recruiters (from an authorised directory) - kept distinct."""
import json

from collectors.linkedin.detail_parser import parse_job_detail
from dashboard import export, views
from dashboard import viewmodel as vm
from processing import hiring_contacts as hc
from tests.factories import NOW, make_record
from tests.test_viewmodel import rows_from

PAGE_WITH_POSTER = """<html><body><h1>Credit Analyst</h1><a class="topcard__org-name-link" href="https://www.linkedin.com/company/acme">Acme Bank</a>
<div class="show-more-less-html__markup">Great job in Pune.</div>
<div class="message-the-recruiter"><a href="https://in.linkedin.com/in/priya-shah-123?trk=x"><span class="base-name">Priya Shah</span></a>
<div class="hirer-card__headline">Talent Acquisition Lead</div></div></body></html>"""
PAGE_PLAIN = """<html><body><h1>Credit Analyst</h1><a class="topcard__org-name-link" href="x">Acme Bank</a>
<div class="show-more-less-html__markup">Great job. See <a href="https://www.linkedin.com/in/someone-else">this profile</a></div></body></html>"""


def test_the_poster_is_read_only_from_a_poster_block_on_the_public_page():
    p = parse_job_detail(PAGE_WITH_POSTER)["raw"]["poster"]
    assert p == {"name": "Priya Shah", "designation": "Talent Acquisition Lead", "profile_url": "https://in.linkedin.com/in/priya-shah-123"}
    assert parse_job_detail(PAGE_PLAIN)["raw"]["poster"] is None          # a profile link inside the description is not "the poster"


def test_profile_links_must_be_person_profiles():
    assert hc.clean_profile_url("https://www.linkedin.com/in/jane-doe-1?x=1") == "https://www.linkedin.com/in/jane-doe-1"
    for bad in ("https://www.linkedin.com/company/acme", "https://evil.example/in/jane", "javascript:alert(1)", "", None):
        assert hc.clean_profile_url(bad) is None


def test_directory_entries_need_company_name_and_source_and_are_matched_by_company_only(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"contacts": [
        {"company": "Acme Bank Pvt Ltd", "name": "Ravi Rao", "designation": "Senior Recruiter", "location": "Pune, India",
         "linkedin_url": "https://www.linkedin.com/in/ravi-rao", "source": "Licensed export", "email": "ravi@acme.example"},
        {"company": "Acme Bank", "name": "Meena", "designation": "Finance Manager", "location": "Delhi", "source": "Licensed export"},
        {"company": "Acme Bank", "name": "No Source"},
        {"company": "Acme Bank", "name": "Bad Link", "source": "x", "linkedin_url": "https://evil.example/in/x"},
        {"company": "Other Co", "name": "Elsewhere", "source": "x"}]}))
    d = hc.ContactDirectory.load(f)
    got = d.suggest("ACME BANK", "Pune, Maharashtra, India")
    assert [c.name for c in got] == ["Ravi Rao", "Meena"]
    assert all(c.kind == hc.SUGGESTED and "not confirmed" in c.note for c in got)
    assert got[0].email == "ravi@acme.example" and d.suggest("Unknown Corp") == [] and d.suggest(None) == []


def test_import_csv_rejects_unsourced_rows_and_never_duplicates(tmp_path):
    csv_file, out = tmp_path / "r.csv", tmp_path / "c.json"
    csv_file.write_text("company,name,designation,linkedin_url,source\nAcme,Ravi,Recruiter,https://www.linkedin.com/in/ravi,Licensed export\n"
                        "Acme,NoSource,Recruiter,,\nAcme,Ravi,Recruiter,https://www.linkedin.com/in/ravi,Licensed export\n")
    assert hc.import_csv(csv_file, out) == {"added": 1, "rejected": 1, "duplicate": 1, "total": 1}
    assert hc.import_csv(csv_file, out)["added"] == 0


def test_dashboard_shows_poster_and_suggested_recruiter_with_distinct_labels(tmp_path):
    from config import settings
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"contacts": [{"company": "Acme Bank", "name": "Ravi Rao", "designation": "Senior Recruiter",
                                           "linkedin_url": "https://www.linkedin.com/in/ravi-rao", "source": "Licensed export"}]}))
    old, settings.HIRING_CONTACTS_FILE = settings.HIRING_CONTACTS_FILE, f
    try:
        poster = {"poster": {"name": "Priya Shah", "designation": "TA Lead", "profile_url": "https://www.linkedin.com/in/priya-shah"}}
        rows = rows_from([make_record(1, "With poster", "Acme Bank", raw_data=poster, description="Apply online."),
                          make_record(2, "No poster", "Acme Bank", description="Apply online.")])
    finally:
        settings.HIRING_CONTACTS_FILE = old
    by = {r.title: r for r in rows}
    d1 = views.render_detail(by["With poster"], "", NOW, None)
    assert "Job Poster" in d1 and "Priya Shah" in d1 and "linkedin.com/in/priya-shah" in d1 and by["With poster"].contact_direct
    assert "Suggested Recruiter" in d1 and "Ravi Rao" in d1 and "Not confirmed as the person who posted" in d1
    d2 = views.render_detail(by["No poster"], "", NOW, None)
    assert "Not shown on the posting" in d2 and "Suggested Recruiter" in d2 and not by["No poster"].contact_direct
    assert by["No poster"].poster is None and by["No poster"].suggested_contacts[0].kind == hc.SUGGESTED
    csv_text = export.build_csv(rows).decode("utf-8-sig")
    assert "Job poster LinkedIn" in csv_text and "https://www.linkedin.com/in/priya-shah" in csv_text and "Ravi Rao" in csv_text


def test_no_directory_file_means_no_suggestions():
    rows = rows_from([make_record(1, "Any", "Nobody Ltd", description="Apply online.")])
    assert rows[0].suggested_contacts == [] and rows[0].poster is None


# ---- poster added by the team -----------------------------------------------------------------------------------------------------
def _post(port, path, data):
    import urllib.parse, urllib.request, urllib.error
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Origin": f"http://127.0.0.1:{port}", "Host": f"127.0.0.1:{port}"})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def test_team_added_poster_needs_every_confirmation_and_is_stored_apart(tmp_path):
    from store.base import StoreError
    from store.json_store import JsonPosterEntries
    s = JsonPosterEntries(tmp_path / "p.json")
    good = dict(key="linkedin-1", name="Priya Shah", designation="TA Lead", profile_url="https://www.linkedin.com/in/priya-shah",
                entered_by="Tanya", confirmed=True)
    for bad in ({"confirmed": False}, {"profile_url": "https://www.linkedin.com/company/acme"}, {"name": ""}, {"entered_by": ""}):
        try:
            s.set(**{**good, **bad})
            raise AssertionError(f"accepted {bad}")
        except StoreError:
            pass
    assert s.get_all() == {}                                   # nothing was saved by the rejected attempts
    s.set(**good)
    e = s.get_all()["linkedin-1"]
    assert e["confirmed"] is True and e["entered_by"] == "Tanya" and e["entered_at"] and e["profile_url"].endswith("/in/priya-shah")
    s.remove("linkedin-1")
    assert s.get_all() == {}


def test_team_poster_is_shown_as_job_poster_added_by_your_team_and_beats_nothing_else(tmp_path):
    from store.json_store import JsonPosterEntries
    s = JsonPosterEntries(tmp_path / "p.json")
    s.set("linkedin-1", "Priya Shah", "TA Lead", "https://www.linkedin.com/in/priya-shah", "Tanya", True)
    recs = [make_record(1, "Has team poster", "Acme Bank", description="Apply online."), make_record(2, "None", "Acme Bank", description="Apply online.")]
    entries = [{"key": f"linkedin-{r['job_id']}", "first_seen_run_id": "run_1", "first_ingested_at": "2026-10-08T10:00:00+00:00",
                "last_seen_at": "2026-10-08T10:00:00+00:00", "times_seen": 1, "record": r} for r in recs]
    rows = {r.title: r for r in vm.build_rows(entries, {}, None, team_posters=s.get_all())}
    d = views.render_detail(rows["Has team poster"], "", NOW, None)
    assert "Job Poster" in d and "Added by your team: Tanya" in d and "Meet the hiring team" in d and "linkedin.com/in/priya-shah" in d
    assert rows["Has team poster"].contact_direct and rows["Has team poster"].poster.kind == hc.TEAM_POSTER
    assert rows["None"].poster is None and "Add job poster" not in views.render_detail(rows["None"], "", NOW, None)


def test_the_add_job_poster_form_is_gone_and_its_route_is_refused(tmp_path):
    from tests.test_contacts import get, running
    with running(tmp_path, records=[make_record(1, "Job", "Acme Bank", description="Apply online.")], second_run=[]) as (port, _):
        d = get(port, "/job/linkedin-1")[2]
        assert "Add job poster" not in d and "I saw the poster on LinkedIn" not in d
        assert _post(port, "/job/linkedin-1/poster", {"name": "X"}) == 404
