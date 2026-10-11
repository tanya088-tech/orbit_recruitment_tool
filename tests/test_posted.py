from datetime import datetime, timezone

from processing.posted import evaluate_posting

AS_OF = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
COLLECTED = "2026-10-08T09:50:00+00:00"


def job(**kw):
    base = {"collected_at": COLLECTED}
    base.update(kw)
    return base


def test_minutes_ago_passes_and_estimates_time():
    r = evaluate_posting(job(posted_age_text="17 minutes ago"), AS_OF)
    assert r.passed and r.precision == "estimated_from_relative_minutes" and r.certainty == "estimated"
    assert r.posted_at == "2026-10-08T09:33:00+00:00"


def test_hours_ago_boundary_depends_on_filter_time():
    j = job(posted_age_text="23 hours ago")
    assert evaluate_posting(j, AS_OF).passed                      # ~23.2h old
    later = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    assert not evaluate_posting(j, later).passed                  # ~25.2h old by then


def test_days_ago_fails_even_one_day():
    for text in ["1 day ago", "2 days ago", "1 week ago", "3 months ago"]:
        r = evaluate_posting(job(posted_age_text=text), AS_OF)
        assert not r.passed and r.code == "posted_older_than_24h", text


def test_date_only_cases():
    today = evaluate_posting(job(posted_date="2026-10-08"), AS_OF)
    assert today.passed and today.precision == "date_only"

    yest = evaluate_posting(job(posted_date="2026-10-07"), AS_OF)
    assert not yest.passed and yest.code == "posted_date_ambiguous" and yest.certainty == "uncertain"

    allowed = evaluate_posting(job(posted_date="2026-10-07"), AS_OF, include_ambiguous_date=True)
    assert allowed.passed and allowed.certainty == "uncertain"

    old = evaluate_posting(job(posted_date="2026-10-01"), AS_OF)
    assert not old.passed and old.code == "posted_older_than_24h"


def test_exact_timestamp_wins():
    inside = evaluate_posting(job(posted_timestamp="2026-10-07T11:00:00+00:00", posted_age_text="3 days ago"), AS_OF)
    assert inside.passed and inside.certainty == "confirmed" and inside.precision == "exact_timestamp"
    outside = evaluate_posting(job(posted_timestamp="2026-10-07T09:00:00+00:00"), AS_OF)
    assert not outside.passed


def test_collected_at_is_never_used_as_posting_date():
    r = evaluate_posting(job(), AS_OF)           # collected today, but no posting info at all
    assert not r.passed and r.code == "posted_unavailable" and r.posted_at is None


def test_card_datetime_attribute_beats_wrong_phase1_posted_date():
    """Legacy Phase 1 files stored a guess one day late; the raw card attribute is the truth."""
    card = '<div><time class="x" datetime="2026-10-05">\n 2 days ago \n</time></div>'
    r = evaluate_posting(job(posted_date="2026-10-06", raw={"search_card_html": card}), AS_OF)
    assert r.posted_at == "2026-10-05"
    assert r.age_text == "2 days ago" and not r.passed
