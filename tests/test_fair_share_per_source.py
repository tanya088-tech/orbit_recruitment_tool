"""Several sources: each gets a fair share of the requested number, and the summary shows what each source did."""
from tests.test_cross_source import make_mgr
from tests.test_collection_and_controls import make_app, serve
from tests.test_dashboard_server import get


def jobs(prefix, n, day="2026-10-12"):
    return [(f"{prefix}{i}", f"{prefix.upper()} Credit Analyst {i}", f"{prefix.upper()} Bank {i}", day) for i in range(1, n + 1)]


def run(tmp_path, per, target, sources=("linkedin", "naukri")):
    h, m = make_mgr(tmp_path, per, [])
    ok, msg = m.start("india", target=target, sources=list(sources))
    assert ok, msg
    return h, m, m.status()


def by_source(h, st):
    keys = set(st["result_keys"])
    return {s: sum(1 for e in h.list_jobs() if e["key"] in keys and e["key"].startswith(s)) for s in ("linkedin", "naukri")}


def test_each_source_gets_a_fair_share_instead_of_the_newest_source_taking_everything(tmp_path):
    # LinkedIn postings are older (an earlier date) than Naukri's, as in the real run; a pure newest-first merge would drop them all
    per = {"linkedin": jobs("l", 6, "2026-10-11"), "naukri": jobs("n", 6, "2026-10-12")}
    h, m, st = run(tmp_path, per, 4)
    assert st["collected_unique"] == 4 and by_source(h, st) == {"linkedin": 2, "naukri": 2}


def test_a_source_that_found_less_lets_the_other_fill_the_gap(tmp_path):
    per = {"linkedin": jobs("l", 1, "2026-10-11"), "naukri": jobs("n", 8, "2026-10-12")}
    h, m, st = run(tmp_path, per, 5)
    assert st["collected_unique"] == 5 and by_source(h, st) == {"linkedin": 1, "naukri": 4}


def test_an_odd_number_is_split_without_losing_or_inventing_vacancies(tmp_path):
    per = {"linkedin": jobs("l", 9), "naukri": jobs("n", 9)}
    h, m, st = run(tmp_path, per, 5)
    assert st["collected_unique"] == 5 and sorted(by_source(h, st).values()) == [2, 3]


def test_a_single_source_is_unchanged(tmp_path):
    h, m, st = run(tmp_path, {"naukri": jobs("n", 8)}, 5, sources=("naukri",))
    assert st["collected_unique"] == 5 and by_source(h, st) == {"linkedin": 0, "naukri": 5}


def test_the_summary_reports_each_source_separately(tmp_path):
    per = {"linkedin": jobs("l", 1, "2026-10-11"), "naukri": jobs("n", 6)}
    h, m, st = run(tmp_path, per, 4)
    ps = st["per_source"]
    assert set(ps) == {"LinkedIn", "Naukri"}
    assert ps["LinkedIn"]["in_result"] == 1 and ps["Naukri"]["in_result"] == 3
    assert ps["LinkedIn"]["found"] >= 1 and ps["Naukri"]["found"] >= 3
    assert "By source:" in st["message"] and "LinkedIn 1 shown" in st["message"]


def test_blank_count_also_reports_each_source(tmp_path):
    per = {"linkedin": jobs("l", 2), "naukri": jobs("n", 3)}
    h, m, st = run(tmp_path, per, None)
    ps = st["per_source"]
    assert ps["LinkedIn"]["new"] == 2 and ps["Naukri"]["new"] == 3 and ps["LinkedIn"]["in_result"] is None
    import re
    # (a repeat of the same fake file in a later clock second is counted as "already had", so the exact figure is not asserted)
    assert "By source:" in st["message"] and re.search(r"LinkedIn \d+ collected of \d+ found", st["message"])


def test_the_panel_shows_the_per_source_lines_only_for_several_sources(tmp_path):
    app, mgr = make_app(tmp_path)
    mgr._update(state="succeeded", target=4, window="24h", collected_unique=4, new_added=4, already_had=0,
                per_source={"LinkedIn": {"found": 1, "new": 1, "existing": 0, "not_relevant": 3, "out_of_scope": 0, "in_result": 1},
                            "Naukri": {"found": 9, "new": 3, "existing": 0, "not_relevant": 2, "out_of_scope": 1, "in_result": 3}})
    srv = serve(app)
    try:
        h = get(srv.server_address[1], "/")[2]
        assert "data-collect-persource" in h and "<b>LinkedIn</b>: 1 found, 1 in your list, 3 not GCC/BFSI" in h
        assert "<b>Naukri</b>: 9 found, 3 in your list, 2 not GCC/BFSI, 1 outside the location scope" in h
        mgr._update(per_source={"Naukri": {"found": 2, "new": 2, "existing": 0, "not_relevant": 0, "out_of_scope": 0, "in_result": 2}})
        assert "data-collect-persource" not in get(srv.server_address[1], "/")[2]
    finally:
        srv.shutdown(); srv.server_close()


def test_vacancies_already_in_the_history_count_as_found_and_as_already_collected(tmp_path):
    """They are counted towards the number but not fetched again, so 'found' must still include them."""
    from processing.pipeline import normalize_all
    from tests.factories import NOW
    from tests.test_collection_and_controls import manager as make_manager, raw_job
    from tests.test_vacancy_target import PLACES, Universe
    out = tmp_path / "out"; out.mkdir()
    listing = [raw_job(i) for i in range(1, 6)]
    mgr, hist = make_manager(tmp_path, Universe(out, {PLACES[0]: listing}))
    hist.ingest(normalize_all(listing[:3], as_of=NOW).jobs, now=NOW)
    assert mgr.start("india", 5, sources=["linkedin"])[0]
    st = mgr.status()
    c = st["per_source"]["LinkedIn"]
    assert st["collected_unique"] == 5 and st["already_had"] == 3 and st["new_added"] == 2
    assert c["found"] == 2 and c["already"] == 3 and c["in_result"] == 5
