"""Contacts stated by the posting and how the details page shows them."""
import re

from dashboard import viewmodel as vm
from processing.contacts import extract_contacts
from tests.factories import make_record
from tests.test_dashboard_server import get, running
from tests.test_viewmodel import rows_from


def test_contacts_are_read_only_from_what_the_posting_states():
    c = extract_contacts("For more details: HR Ronak Contact: 9311229386 Email ID: ronak.mishra336843@gmail.com")
    assert c.direct and c.name == "Ronak" and c.phones == ["93112 29386"] and c.emails == ["ronak.mishra336843@gmail.com"]
    # accommodation / help-desk lines are the company's process, not the job poster's contact details
    c = extract_contacts("If you need an accommodation please contact Capital One Recruiting at 1-800-304-9102 or via email at RecruitingAccommodation@capitalone.com.")
    assert not c.direct and c.emails == [] and c.phones == []
    c = extract_contacts("For HR help email our HR Service Center at MyHRHelp@ntrs.com. Send your CV to guy@theedge.example")
    assert c.emails == ["guy@theedge.example"]
    c = extract_contacts("welcome to contact Swati Pal (Swati.pal@simcorp.com), Talent Acquisition Partner.")
    assert c.name == "Swati Pal" and c.emails == ["swati.pal@simcorp.com"]
    c = extract_contacts("Call Hr Wahab 8828571104 Saba 9892872209 or apply at https://careers.acme.example/job/9")
    assert c.name == "Wahab" and c.phones == ["88285 71104", "98928 72209"] and c.urls == ["https://careers.acme.example/job/9"]


def test_numbers_that_are_not_phones_and_postings_without_contacts_give_nothing():
    for text in (None, "", "A great role with a salary of ₹ 9876543210 per year", "Experience 5-8 years, budget 1200000", "logo.png@2x.png",
                 "Build models. Work with the team. No contact details here."):
        c = extract_contacts(text)
        assert not c.direct and c.name is None, text


def rows_for(recs):
    return {r.title: r for r in rows_from(recs)}


def test_rows_are_tagged_directly_available_or_not_directly_fetched():
    rows = rows_for([make_record(1, "Has contact", description="Please call 9876501234 to apply."),
                     make_record(2, "No contact", description="A role. Apply on the site."),
                     make_record(3, "Stored contact", recruiter_email="hr@acme.example", description="No contact in text.")])
    assert rows["Has contact"].contact_direct and rows["Has contact"].contact_phones == ["98765 01234"]
    assert not rows["No contact"].contact_direct
    assert rows["Stored contact"].contact_direct and rows["Stored contact"].contact_emails == ["hr@acme.example"]   # stored value wins / is used


def test_list_and_details_show_the_right_tag_and_the_contacts(tmp_path):
    recs = [make_record(11, "Has contact", "Acme Bank", description="Please email careers@acme.example or call 9876501234."),
            make_record(12, "No contact", "Other Bank", "Pune, Maharashtra, India", description="Apply through the site.")]
    with running(tmp_path, records=recs, second_run=[]) as (port, _):
        lst = get(port, "/")[2]
        assert "Contact directly available" not in lst and "Contact not directly fetched" not in lst and "data-contact" not in lst
        d = get(port, "/job/linkedin-11")[2]
        assert "Contact directly available" in d and 'href="mailto:careers@acme.example"' in d and "98765 01234" in d
        d = get(port, "/job/linkedin-12")[2]
        assert "Contact not directly fetched" in d and "Suggested contacts" not in d and "Suggested Recruiter</span>" not in d      # nothing is suggested without a directory entry
        assert "This is a search shortcut, not a contact" in d                  # the only LinkedIn link is a labelled search shortcut
