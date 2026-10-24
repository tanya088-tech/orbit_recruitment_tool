"""Naukri is searched India-wide once (NAUKRI_SEARCH_LOCATIONS) instead of in every Indian city; LinkedIn is unchanged.
The computer is kept from sleeping while a collection runs, and set back afterwards (finished, stopped or failed)."""
from pathlib import Path

from config import locations as loc
from config import settings
from dashboard.collection import CollectionManager, naukri_places
from store.json_store import JsonJobHistory
from utils import keep_awake as ka


# -- where Naukri is searched -------------------------------------------------------------
def test_indian_cities_are_replaced_by_one_india_wide_search(monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_SEARCH_LOCATIONS", ("India",))
    assert naukri_places(loc.search_locations("india")) == ["India"]
    both = loc.search_locations("both")
    abroad = [p for p in both if not p.endswith("India")]
    assert naukri_places(both) == ["India"] + abroad                       # places outside India are kept
    assert naukri_places(loc.search_locations("international")) == loc.search_locations("international")


def test_empty_setting_searches_every_place_as_before(monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_SEARCH_LOCATIONS", ())
    assert naukri_places(loc.search_locations("india")) == loc.search_locations("india")


def test_other_india_wide_choices_are_used_once(monkeypatch):
    monkeypatch.setattr(settings, "NAUKRI_SEARCH_LOCATIONS", ("Bengaluru, Karnataka, India", "India", "India"))
    assert naukri_places(["Pune, Maharashtra, India", "Singapore", "India"]) == ["Bengaluru, Karnataka, India", "India", "Singapore"]


def _run(tmp_path, monkeypatch, sources):
    monkeypatch.setattr(settings, "NAUKRI_SEARCH_LOCATIONS", ("India",))
    calls = []

    def runner(cmd, on_line, cwd, timeout):
        src = cmd[cmd.index("--source") + 1] if "--source" in cmd else "linkedin"
        calls.append((src, cmd[cmd.index("--locations") + 1]))
        out = Path(cmd[cmd.index("--output-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"jobs_{src}_20261024_{len(calls):06d}.json"
        path.write_text('{"run": {"latest_ids": []}, "jobs": []}', encoding="utf-8")
        on_line(f"Saved 0 jobs to {path}")
        return 0
    m = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, tmp_path / "out", runner=runner, background=False)
    ok, msg = m.start("india", target=5, sources=sources)
    assert ok, msg
    return calls, m.status()


def test_a_naukri_run_makes_one_search_not_one_per_city(tmp_path, monkeypatch):
    calls, st = _run(tmp_path, monkeypatch, ["naukri"])
    assert calls == [("naukri", "India")]
    assert st["search_total"] == 1


def test_linkedin_still_searches_every_city(tmp_path, monkeypatch):
    calls, _ = _run(tmp_path, monkeypatch, ["linkedin"])
    assert [p for _, p in calls] == loc.search_locations("india")


def test_a_pass_that_saves_no_file_does_not_crash_the_run(tmp_path):
    calls = []
    m = CollectionManager(JsonJobHistory(tmp_path / "h.json"), tmp_path, tmp_path / "out",
                          runner=lambda cmd, on_line, cwd, timeout: calls.append(1) or 0, background=False)
    m.start("india", target=5, sources=["linkedin"])
    assert len(calls) == len(loc.search_locations("india"))                       # every place is still tried
    assert "No jobs file was saved" in (m.status()["last_error"] or "")        # and the real reason is reported


# -- keeping the computer awake -----------------------------------------------------------
def test_windows_holds_off_sleep_during_the_run_and_resets_after_an_error():
    states = []
    try:
        with ka.keep_awake(platform="win32", set_state=lambda f: states.append(f) or 1) as held:
            assert held
            assert states == [ka.ES_CONTINUOUS | ka.ES_SYSTEM_REQUIRED]          # system only: the display may still turn off
            raise RuntimeError("collection failed")
    except RuntimeError:
        pass
    assert states[-1] == ka.ES_CONTINUOUS


def test_macos_uses_caffeinate_for_this_process_and_stops_it():
    started = []

    class Proc:
        ended = False

        def terminate(self):
            Proc.ended = True

        def wait(self, timeout=None):
            return 0
    with ka.keep_awake(platform="darwin", which=lambda n: "/usr/bin/caffeinate",
                       popen=lambda args, **kw: started.append(args) or Proc()) as held:
        assert held and started[0][:3] == ["/usr/bin/caffeinate", "-i", "-w"]
        assert "-d" not in started[0]
    assert Proc.ended


def test_nothing_happens_without_caffeinate_elsewhere_or_when_switched_off():
    with ka.keep_awake(platform="darwin", which=lambda n: None, popen=lambda *a, **k: 1 / 0) as held:
        assert not held
    with ka.keep_awake(platform="linux", popen=lambda *a, **k: 1 / 0) as held:
        assert not held
    with ka.keep_awake(enabled=False, platform="win32", set_state=lambda f: 1 / 0) as held:
        assert not held


def test_a_failing_os_call_never_stops_the_collection():
    with ka.keep_awake(platform="win32", set_state=lambda f: 1 / 0) as held:
        assert not held


def test_the_collection_runs_inside_keep_awake(tmp_path, monkeypatch):
    import dashboard.collection as coll
    seen = []

    class Hold:
        def __init__(self, enabled):
            self.enabled = enabled

        def __enter__(self):
            seen.append(("on", self.enabled))

        def __exit__(self, *exc):
            seen.append(("off", self.enabled))
    monkeypatch.setattr(coll, "keep_awake", lambda enabled: Hold(enabled))
    monkeypatch.setattr(settings, "COLLECTION_KEEP_AWAKE", True)
    _run(tmp_path, monkeypatch, ["naukri"])
    assert seen == [("on", True), ("off", True)]
