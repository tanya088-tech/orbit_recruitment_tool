"""A vacancy re-posted on the SAME source under a new job id (e.g. Capital One "Senior Associate, Business Analysis",
Bengaluru, on LinkedIn twice) is one vacancy: stored once with the second listing kept as "also listed on", and shown once."""
from datetime import timedelta

from dashboard.viewmodel import build_rows
from store.json_store import JsonJobHistory
from store.keys import REPOST_MIN_DESCRIPTION, is_repost
from tests.factories import NOW, entry, make_record

LONG = ("Capital One India is looking for a Senior Associate in Business Analysis to join the card partnerships team. "
        "You will turn data into insight, build dashboards, work with product and engineering partners, and present "
        "recommendations to leaders. Experience with SQL, Python and statistics is expected; banking exposure helps.")
OTHER = ("This role sits in the fraud strategy team and owns the rules engine roadmap. The analyst designs experiments, "
         "monitors loss rates, partners with operations in Nottingham and Richmond, and writes policy documents for the "
         "risk committee. Strong communication and a background in credit or fraud analytics are required for the job.")
VACANCY = dict(company="Capital One", title="Senior Associate, Business Analysis", location="Bengaluru, Karnataka, India")


def rec(job_id, description=LONG, source="LinkedIn", **kw):
    r = make_record(job_id, description=description, **{**VACANCY, **kw})
    r["source"] = source
    return r


def test_descriptions_are_long_enough_for_the_rule():
    assert len(LONG) >= REPOST_MIN_DESCRIPTION and len(OTHER) >= REPOST_MIN_DESCRIPTION


def test_same_source_same_vacancy_with_near_identical_description_is_a_repost():
    assert is_repost(rec(1), rec(2))
    assert is_repost(rec(1), rec(2, description=LONG.replace("helps.", "is a plus.")))     # small edit, still >= 0.9


def test_not_a_repost_when_description_differs_is_short_or_source_or_vacancy_differs():
    assert not is_repost(rec(1), rec(2, description=OTHER))                              # two real openings, same title
    assert not is_repost(rec(1, description="Short text."), rec(2, description="Short text."))
    assert not is_repost(rec(1), rec(2, source="Naukri"))                               # other source: the cross-source rule handles it
    assert not is_repost(rec(1), rec(2, location="Hyderabad, Telangana, India"))
    assert not is_repost(rec(1), rec(2, title="Manager, Business Analysis"))
    assert not is_repost(rec(1, location="India"), rec(2, location="India"))             # no city: no fingerprint


def test_ingest_stores_a_repost_once_and_keeps_its_link(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([rec(4464996406)], now=NOW)
    r = h.ingest([rec(4465395063)], now=NOW + timedelta(hours=1))
    assert (r.new, r.existing) == (0, 1)
    jobs = h.list_jobs()
    assert [j["key"] for j in jobs] == ["linkedin-4464996406"]
    alts = jobs[0]["record"]["also_listed_on"]
    assert [(a["source"], a["job_id"]) for a in alts] == [("LinkedIn", "4465395063")]
    h.ingest([rec(4465395063)], now=NOW + timedelta(hours=2))                           # seen again later: still one row, one link
    jobs = h.list_jobs()
    assert len(jobs) == 1 and len(jobs[0]["record"]["also_listed_on"]) == 1


def test_ingest_keeps_two_openings_with_different_descriptions(tmp_path):
    h = JsonJobHistory(tmp_path / "h.json")
    h.ingest([rec(1), rec(2, description=OTHER)], now=NOW)
    assert len(h.list_jobs()) == 2


def test_dashboard_folds_a_stored_repost_into_the_earlier_row():
    rows = build_rows([entry(1, description=LONG, **VACANCY), entry(2, description=LONG, **VACANCY)], {}, None, only_gcc_bfsi=False)
    assert [r.key for r in rows] == ["linkedin-1"]
    assert rows[0].also_listed_on == [{"source": "LinkedIn", "job_id": "2", "job_url": "https://www.linkedin.com/jobs/view/2"}]


def test_dashboard_keeps_a_repost_someone_has_worked_on():
    jobs = [entry(1, description=LONG, **VACANCY), entry(2, description=LONG, **VACANCY)]
    for state in ({"saved": True}, {"notes": [{"id": "n1", "text": "called"}]}):
        rows = build_rows(jobs, {"linkedin-2": state}, None, only_gcc_bfsi=False)
        assert [r.key for r in rows] == ["linkedin-1", "linkedin-2"], state


def test_dashboard_keeps_a_repost_whose_status_was_changed():
    from store.base import DEFAULT_STATUS, STATUSES
    other = next(s for s in STATUSES if s != DEFAULT_STATUS)
    jobs = [entry(1, description=LONG, **VACANCY), entry(2, description=LONG, **VACANCY)]
    assert len(build_rows(jobs, {"linkedin-2": {"status": other}}, None, only_gcc_bfsi=False)) == 2


def test_dashboard_does_not_fold_different_or_short_descriptions():
    assert len(build_rows([entry(1, description=LONG, **VACANCY), entry(2, description=OTHER, **VACANCY)], {}, None, only_gcc_bfsi=False)) == 2
    assert len(build_rows([entry(1, description="Short.", **VACANCY), entry(2, description="Short.", **VACANCY)], {}, None, only_gcc_bfsi=False)) == 2
