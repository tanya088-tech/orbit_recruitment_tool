from datetime import date, datetime, timezone
from urllib.parse import parse_qsl

from dashboard import viewmodel as vm
from tests.factories import NOW, ago, entry, make_record, standard_records

ST = {}


def rows_from(records, new_ids=(), saved=(), statuses=None):
    entries = [{"key": f"linkedin-{r['job_id']}", "first_seen_run_id": "run_2" if r["job_id"] in new_ids else "run_1",
                "first_ingested_at": ago(hours=1), "last_seen_at": ago(hours=1), "times_seen": 1, "record": r} for r in records]
    states = {f"linkedin-{i}": {"saved": True, "status": "New", "notes": []} for i in saved}
    for i, s in (statuses or {}).items():
        states.setdefault(f"linkedin-{i}", {"saved": False, "notes": []})["status"] = s
    return vm.build_rows(entries, states, "run_2")


def std():
    s = standard_records()
    return s, rows_from(s.values(), new_ids={"1005", "1006"})


def ids(rows):
    return [r.job_id for r in rows]


def apply(rows, **q):
    f = vm.Filters.from_query(q)
    return vm.sort_rows(vm.apply_filters(rows, f, NOW), f.sort)


# ------------------------------------------------------------------ posting time
def test_posted_parsing_and_labels():
    est = vm.parse_posted({"posted_at": ago(minutes=17), "posted_at_precision": "estimated_from_relative_minutes"})
    assert est.moment and not est.day and est.estimated
    assert vm.format_age(est, NOW) == "about 17 minutes ago" and vm.format_precision(est) == "estimated time"
    exact = vm.parse_posted({"posted_at": ago(hours=3), "posted_at_precision": "exact_timestamp"})
    assert vm.format_age(exact, NOW) == "3 hours ago" and vm.format_precision(exact) == "exact time"
    day = vm.parse_posted({"posted_at": "2026-10-05", "posted_at_precision": "date_only"})
    assert day.day == date(2026, 10, 5) and day.moment is None
    assert vm.format_age(day, NOW) == "5 Oct 2026" and vm.format_precision(day) == "date only"
    assert "no time available" in vm.format_moment(day)         # a date-only job never gets a made-up time
    for bad in [{}, {"posted_at": None}, {"posted_at": "garbage"}, {"posted_at": "2026-13-45"}]:
        p = vm.parse_posted(bad)
        assert not p.known and vm.format_age(p, NOW) == "Not available"


def test_windows_for_exact_and_date_only_jobs():
    p = lambda **kw: vm.parse_posted({"posted_at": ago(**kw), "posted_at_precision": "estimated_from_relative_hours"})
    assert vm.is_within(p(hours=23), NOW, 24) and not vm.is_within(p(hours=25), NOW, 24)
    assert vm.is_within(p(hours=71), NOW, 72) and not vm.is_within(p(hours=73), NOW, 72)
    assert vm.is_within(p(days=6), NOW, 168) and not vm.is_within(p(days=8), NOW, 168)
    d = lambda s: vm.parse_posted({"posted_at": s, "posted_at_precision": "date_only"})
    assert vm.is_within(d("2026-10-08"), NOW, 24) and not vm.is_within(d("2026-10-07"), NOW, 24)   # yesterday: cannot be sure
    assert vm.is_within(d("2026-10-06"), NOW, 72) and not vm.is_within(d("2026-10-05"), NOW, 72)
    assert vm.is_within(d("2026-10-02"), NOW, 168) and not vm.is_within(d("2026-10-01"), NOW, 168)
    assert not vm.is_within(vm.parse_posted({}), NOW, 168)


def test_freshness_levels_and_ring():
    f = lambda **kw: vm.freshness(vm.parse_posted({"posted_at": ago(**kw)}), NOW)
    assert f(minutes=20) == "just_posted" and f(hours=3) == "fresh" and f(hours=10) == "today"
    assert f(hours=40) == "recent" and f(days=5) == "older"
    assert vm.freshness(vm.parse_posted({}), NOW) == "unknown"
    ring = lambda **kw: vm.ring_fraction(vm.parse_posted({"posted_at": ago(**kw)}), NOW)
    assert ring(minutes=1) > 0.99 and abs(ring(hours=12) - 0.5) < 0.01 and ring(hours=30) == 0.0


def test_links_only_http():
    assert vm.safe_http_url("https://www.linkedin.com/jobs/view/1") == "https://www.linkedin.com/jobs/view/1"
    for bad in ["javascript:alert(1)", "data:text/html,x", "ftp://x.com", "//x.com", "", None, "linkedin.com/jobs/1"]:
        assert vm.safe_http_url(bad) is None


# ------------------------------------------------------------------ New vs existing
def test_new_means_first_seen_in_latest_run():
    _, rows = std()
    assert {r.job_id for r in rows if r.is_new} == {"1005", "1006"}
    assert not any(r.is_new for r in vm.build_rows([], {}, None))
    no_run = vm.build_rows([entry(1)], {}, None)
    assert not no_run[0].is_new


# ------------------------------------------------------------------ filters
def test_posted_filter():
    _, rows = std()
    assert set(ids(apply(rows, posted="24h"))) == {"1001", "1002", "1005"}
    assert set(ids(apply(rows, posted="3d"))) == {"1001", "1002", "1003", "1005"}
    assert set(ids(apply(rows, posted="7d"))) == {"1001", "1002", "1003", "1004", "1005"}
    assert len(apply(rows, posted="all")) == 6               # unknown posting time only appears under "All"


def test_default_sort_is_most_recently_posted_first():
    _, rows = std()
    assert ids(apply(rows)) == ["1001", "1002", "1005", "1003", "1004", "1006"]   # unknown posting time last


def test_other_sorts():
    _, rows = std()
    assert ids(apply(rows, sort="oldest")) == ["1004", "1003", "1005", "1002", "1001", "1006"]
    assert ids(apply(rows, sort="title")) == ["1001", "1004", "1003", "1005", "1002", "1006"]
    comp = [r.company for r in apply(rows, sort="company")]
    assert comp == sorted(comp, key=str.lower)


def test_sorting_handles_missing_fields():
    recs = [make_record(1, title=None, company=None, posted=None), make_record(2, title="Zeta", company="Zed"),
            make_record(3, title="Alpha", company="Alp")]
    rows = rows_from(recs)
    assert ids(vm.sort_rows(rows, "title")) == ["3", "2", "1"]
    assert ids(vm.sort_rows(rows, "company")) == ["3", "2", "1"]
    assert ids(vm.sort_rows(rows, "recent"))[-1] == "1" and ids(vm.sort_rows(rows, "oldest"))[-1] == "1"


# ------------------------------------------------------------------ cards, options, paging
def test_pagination():
    rows = rows_from([make_record(i) for i in range(1, 121)])
    p1 = vm.paginate(rows, 1, 50)
    assert (p1.pages, p1.total, len(p1.rows), p1.start, p1.end) == (3, 120, 50, 1, 50)
    p3 = vm.paginate(rows, 3, 50)
    assert (len(p3.rows), p3.start, p3.end) == (20, 101, 120)
    assert vm.paginate(rows, 99, 50).page == 3 and vm.paginate(rows, 0, 50).page == 1
    empty = vm.paginate([], 1, 50)
    assert (empty.pages, empty.total, empty.rows) == (1, 0, [])


# ------------------------------------------------------------------ missing data
def test_longer_posted_windows():
    recs = [make_record(1, posted=ago(days=14)), make_record(2, posted=ago(days=16)), make_record(3, posted=ago(days=29)),
            make_record(4, posted=ago(days=31)), make_record(5, posted="2026-10-01", precision="date_only"),
            make_record(6, posted="2026-09-20", precision="date_only"), make_record(7, posted=None, precision="unknown")]
    rows = rows_from(recs)
    assert set(ids(apply(rows, posted="15d"))) == {"1", "5"}
    assert set(ids(apply(rows, posted="1m"))) == {"1", "2", "3", "5", "6"}
    assert len(apply(rows, posted="all")) == 7                         # unknown posting time only under All
    assert vm.POSTED_LABELS["15d"] == "Last 15 days" and vm.POSTED_LABELS["1m"] == "Last 1 month"
    assert list(vm.POSTED_OPTIONS) == ["24h", "3d", "7d", "15d", "1m", "all"]


def test_source_filter_lists_whatever_sources_exist():
    recs = [make_record(1), make_record(2, source="Naukri")]
    rows = rows_from(recs)
    assert vm.filter_options(rows)["sources"] == ["LinkedIn", "Naukri"]
    assert ids(apply(rows, source="Naukri")) == ["2"] and len(apply(rows, source="")) == 2




# ------------------------------------------------------------------ the five filters
def test_location_scope_filter():
    recs = [make_record(1, location="Pune, Maharashtra, India"),
            make_record(2, location="London, England, United Kingdom", country="United Kingdom"),
            make_record(3, location="Dubai, United Arab Emirates", country="United Arab Emirates"),
            make_record(4, location=None, country=None)]
    rows = rows_from(recs)
    assert len(rows) == 4                                              # history keeps everything
    assert ids(apply(rows)) == ["1"] and vm.Filters().scope == "india"  # default: within India
    assert ids(apply(rows, scope="india")) == ["1"]
    assert set(ids(apply(rows, scope="outside"))) == {"2", "3"}
    assert len(apply(rows, scope="all")) == 4                          # unknown country appears only under All
    assert len(apply(rows, scope="mars")) == 1                         # a bad value falls back to the default


def test_pan_india_locations_are_all_in_scope_and_names_are_normalized():
    cities = ["Bangalore, Karnataka, India", "Gurgaon, Haryana, India", "Bombay, Maharashtra, India", "Kochi, Kerala, India",
              "Jaipur, Rajasthan, India", "Guwahati, Assam, India", "Chandigarh, India"]
    rows = rows_from([make_record(i + 1, location=c) for i, c in enumerate(cities)])
    assert len(apply(rows, scope="india")) == 7 and apply(rows, scope="outside") == []
    shown = {r.location for r in rows}
    assert "Bengaluru, Karnataka, India" in shown and "Gurugram, Haryana, India" in shown and "Mumbai, Maharashtra, India" in shown
    assert not any("Bangalore" in x or "Gurgaon" in x or "Bombay" in x for x in shown)


def test_employment_source_posted_and_work_mode_filters():
    _, rows = std()
    assert set(ids(apply(rows, employment="Contract"))) == {"1003", "1004"}
    assert set(ids(apply(rows, employment="Permanent"))) == {"1001", "1002", "1005", "1006"}
    assert len(apply(rows, employment="Remote")) == 6                  # not an employment type: ignored
    assert len(apply(rows, source="LinkedIn")) == 6 and apply(rows, source="Naukri") == []
    assert ids(apply(rows, work_mode="Remote")) == ["1005"]
    rows2 = rows_from([make_record(1, location="Pune, India (Hybrid)"), make_record(2, location="Pune, India (On-site)"),
                       make_record(3, location="Pune, India")])
    assert ids(apply(rows2, work_mode="Hybrid")) == ["1"] and ids(apply(rows2, work_mode="On-site")) == ["2"]
    assert len(apply(rows2, work_mode="all")) == 3                     # a plain city is never assumed On-site


def test_removed_filters_are_ignored_and_combined_filters_work():
    _, rows = std()
    for removed in ({"classification": "gcc"}, {"company": "acme"}, {"keyword": "zzz"}, {"location": "Maharashtra"},
                    {"status": "Hired"}, {"saved": "1"}):
        assert len(apply(rows, **removed)) == 6, removed
    assert ids(apply(rows, posted="3d", employment="Contract")) == ["1003"]
    assert apply(rows, posted="24h", employment="Contract") == []


def test_query_parsing_round_trips_and_only_five_filters_count():
    assert vm.Filters.from_query({"posted": "forever", "employment": "Intern", "sort": "random", "page": "-3"}) == vm.Filters()
    g = vm.Filters.from_query({"scope": "all", "employment": "Contract", "source": "LinkedIn", "posted": "3d",
                               "work_mode": "Hybrid", "page": "2"})
    assert g.active_count == 5
    assert vm.Filters.from_query(dict(parse_qsl(g.to_query()))) == g
    assert vm.Filters().to_query() == "" and vm.Filters().active_count == 0


# ------------------------------------------------------------------ KPI cards
def test_summary_cards_are_total_permanent_contract_and_follow_filters():
    _, rows = std()
    assert vm.summary_cards(rows) == {"total": 6, "permanent": 4, "contract": 2}
    assert vm.summary_cards(apply(rows, employment="Contract")) == {"total": 2, "permanent": 0, "contract": 2}
    assert vm.summary_cards(apply(rows, posted="24h")) == {"total": 3, "permanent": 3, "contract": 0}
    assert vm.summary_cards([]) == {"total": 0, "permanent": 0, "contract": 0}
    unknown = rows_from([make_record(1, employment=None)])
    assert vm.summary_cards(unknown) == {"total": 1, "permanent": 0, "contract": 0}


def test_filter_options_offer_sources_found_in_the_data():
    rows = rows_from([make_record(1), make_record(2, source="Naukri"), make_record(3, source=None)])
    assert vm.filter_options(rows) == {"sources": ["LinkedIn", "Naukri"]}


# ------------------------------------------------------------------ industry on rows, missing data
def test_industry_comes_from_the_source_label_or_is_unknown():
    rows = rows_from([make_record(1, industries="Software Development"), make_record(2, industries="Hospitals and Health Care"),
                      make_record(3, industries=None), make_record(4, industries="Underwater Basket Weaving")])
    by = {r.job_id: r.industry for r in rows}
    assert by == {"1": "IT & Software", "2": "Healthcare & Pharma", "3": "Unknown", "4": "Other"}
    assert [r.industry_label for r in rows if r.job_id == "3"] == [None]


def test_rows_survive_completely_empty_and_old_format_records():
    bare = {"source": None, "job_id": None, "title": None, "company": None, "location": None, "job_url": "javascript:x",
            "potential_gcc": None, "potential_bfsi": None, "classification_signals": None}
    entries = [{"key": "linkedin-x1", "first_seen_run_id": "r", "record": bare}, {"key": "linkedin-x2", "record": {}}]
    rows = vm.build_rows(entries, {}, "r")
    for r in rows:
        assert r.display_title == "Untitled vacancy" and r.job_url is None and r.industry == "Unknown"
        assert r.status == "New" and not r.posted.known and r.scope == "unknown"
    assert len(vm.apply_filters(rows, vm.Filters(scope="all"), NOW)) == 2
    assert vm.apply_filters(rows, vm.Filters(), NOW) == []             # unknown location: only under All locations
    assert vm.summary_cards(rows)["total"] == 2
