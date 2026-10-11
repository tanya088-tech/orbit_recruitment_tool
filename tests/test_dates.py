from datetime import date
from utils.dates import is_within_days, parse_posted_date

TODAY = date(2026, 10, 8)

def test_iso_and_timestamp():
    assert parse_posted_date("2026-10-06", TODAY) == date(2026, 10, 6)
    assert parse_posted_date("2026-10-06T08:30:00.000Z", TODAY) == date(2026, 10, 6)

def test_relative():
    assert parse_posted_date("3 hours ago", TODAY) == TODAY
    assert parse_posted_date("2 days ago", TODAY) == date(2026, 10, 6)
    assert parse_posted_date("1 week ago", TODAY) == date(2026, 10, 1)
    assert parse_posted_date("Just now", TODAY) == TODAY

def test_unknown():
    assert parse_posted_date(None, TODAY) is None
    assert parse_posted_date("sometime", TODAY) is None

def test_within_days():
    assert is_within_days(date(2026, 10, 1), 7, TODAY)
    assert not is_within_days(date(2026, 9, 30), 7, TODAY)
    assert is_within_days(None, 7, TODAY)


def test_relative_age_and_iso_datetime():
    from utils.dates import parse_iso_datetime, parse_relative_age, relative_age_seconds
    assert parse_relative_age("17 minutes ago") == (17, "minute")
    assert parse_relative_age("Reposted 2 days ago") == (2, "day")
    assert parse_relative_age("Just now") == (0, "minute")
    assert parse_relative_age("garbage") is None
    assert relative_age_seconds((5, "hour")) == 18000
    dt = parse_iso_datetime("2026-10-06T08:30:00.000Z")
    assert dt.isoformat() == "2026-10-06T08:30:00+00:00"
    assert parse_iso_datetime("2026-10-06") is None   # date-only has no time


def test_source_prefers_card_date_over_relative_guess():
    """Regression for the Phase 1 one-day bug seen in the live run."""
    from collectors.linkedin.source import LinkedInSource

    stub = {"job_id": "1", "job_url": "u", "title": "t", "company": "c", "company_url": None,
            "location": "Pune, India", "posted_date": date(2026, 10, 5),
            "posted_age_text": "2 days ago", "raw": "<div/>"}

    class C:
        def get(self, url, params=None):
            return ('<h2 class="top-card-layout__title">T</h2>'
                    '<span class="posted-time-ago__text">2 days ago</span>'
                    '<div class="show-more-less-html__markup">desc</div>')

    job = LinkedInSource(C())._collect_one(stub)
    assert job.posted_date == date(2026, 10, 5)        # card attribute, not today-2
    assert job.posted_age_text == "2 days ago"
