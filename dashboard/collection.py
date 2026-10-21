"""Run the existing LinkedIn collection from the dashboard, safely, in the background.

What a run does (the same three steps you would run by hand):
  1. collect   - run_collect.py (the unchanged Phase 1 scraper) as a separate process
  2. normalize - Phase 2 rules on every collected job (nothing removed)
  3. ingest    - add to the job history with deduplication

Safety
  * one run at a time: an in-process flag AND a lock file (data/collection.lock), so a second
    browser tab, a second Ace Talent Consulting window, or a double click cannot start a duplicate run
  * a stale lock (the process that made it has gone) is cleared automatically
  * the scraper keeps its own politeness delays and stops if LinkedIn starts refusing requests
  * a run longer than COLLECTION_TIMEOUT_MINUTES is stopped
  * the command is built only from config/settings.py and config/locations.py, never from web input
    (the page can only choose one of the named scopes)

Progress and the last result are saved in data/collection_status.json so they survive a page
reload or an app restart.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from collectors.registry import is_location_independent
from config import locations as loc_config
from config import settings
from dashboard import viewmodel as vm
from collectors.browser_host import BrowserHost, ENV_VAR as BROWSER_ENV
from processing.classifier import classify
from processing.contacts import poster_contacts
from processing.location import check_location
from processing.pipeline import keep_eligible, keep_in_scope, load_jobs, location_in_scope, normalize_all, save_normalized
from store.base import JobHistoryStore
from store.ingest import ingest_filtered_file
from store.keys import normalize_job_url
from utils.dates import parse_iso_datetime
from store.recovery import recover_unprocessed

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

IDLE, RUNNING, SUCCEEDED, PARTIAL, FAILED = "idle", "running", "succeeded", "partial", "failed"
EXIT_BLOCKED = 2            # run_collect.py: the source blocked us (it still saves what it had)
EXIT_SETUP = 3              # run_collect.py: the source cannot run here yet (e.g. browser support not installed)
_SEARCH_LINE = re.compile(r"\[(\w+)\] Search (\d+)/(\d+): (.*)$")
_SAVED_LINE = re.compile(r"Saved (\d+) jobs to (.+)$")
_PAGE_LINE = re.compile(r"Search page (\d+): (\d+) listings")
_INTERRUPT_LINE = "Interrupted by user"
_BLOCKED_LINE = re.compile(r"SOURCE BLOCKED US - stopping run\. Reason:\s*(.*)$")
_SETUP_LINE = re.compile(r"SETUP REQUIRED:\s*(.*)$")
_ERROR_LINE = re.compile(r"\|\s*(ERROR|CRITICAL)\s*\|\s*(.*)$")
LOG_TAIL = 30
STOP_GRACE_SECONDS = 20       # after Stop, a scraper gets this long to save what it collected before it is ended
STALE_LOCK_SECONDS = 600     # a live run refreshes its lock with every progress save; older than this = left behind

Runner = Callable[[list[str], Callable[[str], None], Path, float], int]


def short_reason(text: Optional[str]) -> str:
    """What the site said, in a few words: 'HTTP 403 - Access Denied' (from the scraper's block message)."""
    text = text or ""
    status = re.search(r"\b(?:HTTP|status=)\s*(\d{3})", text)
    page = re.search(r"page='([^|']*?)(?:\s*\||')", text)
    bits = ([f"HTTP {status.group(1)}"] if status else []) + ([page.group(1).strip()] if page and page.group(1).strip() else [])
    if bits:
        return " - ".join(bits)
    return (text[:100] + "...") if len(text) > 100 else (text or "no reason given")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_target(value: Any) -> Optional[int]:
    """The vacancy count typed into the form: a whole number from 1 to COLLECTION_TARGET_MAX, else None."""
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[0-9]{1,6}", text):
        return None
    n = int(text)
    return n if 1 <= n <= settings.COLLECTION_TARGET_MAX else None


def source_keywords(source: str) -> list[str]:
    """What is searched on each source. Naukri searches the employers and role terms in NAUKRI_SEARCH_TERMS (one combined
    entry, so the source merges the terms newest first); every other source uses COLLECTION_KEYWORDS."""
    terms = [t.strip() for t in getattr(settings, "NAUKRI_SEARCH_TERMS", []) if t and t.strip()]
    if source == "naukri" and terms:
        return [" OR ".join(terms)]
    return list(settings.COLLECTION_KEYWORDS)


def build_command(scope: str, output_dir: Path, locations: Optional[list[str]] = None,
                  skip_ids_file: Optional[Path] = None, max_jobs: Optional[int] = None,
                  count_known: bool = False, exclude_ids_file: Optional[Path] = None, days: Optional[int] = None,
                  source: str = "linkedin") -> list[str]:
    """The exact run_collect.py command. Only values from config files go in.

    The dashboard runs it once per place (locations=[place]) so jobs are saved after every place
    and a problem in one place never loses the others."""
    return [
        sys.executable, str(ROOT / "run_collect.py"),
        *(["--source", source] if source != "linkedin" else []),
        "--keywords", *source_keywords(source),
        "--locations", *(locations if locations is not None else loc_config.search_locations(scope)),
        "--days", str(days if days is not None else settings.COLLECTION_DAYS),
        "--max-jobs-per-search", str(max_jobs if max_jobs is not None else settings.COLLECTION_MAX_JOBS_PER_SEARCH),
        "--max-pages", str(settings.COLLECTION_MAX_PAGES),
        "--output-dir", str(output_dir),
        *(["--skip-ids-file", str(skip_ids_file)] if skip_ids_file else []),
        *(["--count-known"] if count_known and skip_ids_file else []),
        *(["--exclude-ids-file", str(exclude_ids_file)] if count_known and skip_ids_file and exclude_ids_file else []),
    ]


def subprocess_runner(cmd: list[str], on_line: Callable[[str], None], cwd: Path, timeout_s: float,
                      on_start: Optional[Callable[[subprocess.Popen], None]] = None) -> int:
    """Run the scraper, feeding each output line to on_line. Kills it after timeout_s. on_start receives the process
    (so the Stop button can reach it). On Windows it gets its own process group so it can be asked to stop with
    Ctrl+Break without the dashboard receiving it too."""
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
    if on_start is not None:
        on_start(proc)
    timer = threading.Timer(timeout_s, proc.kill)
    timer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            on_line(line.rstrip("\n"))
        return proc.wait()
    finally:
        timer.cancel()


def ask_to_stop(proc: subprocess.Popen) -> None:
    """Ask a running scraper to stop the way Ctrl+C would: it saves the jobs collected so far, then exits."""
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)     # run_collect.py turns this into KeyboardInterrupt
        else:
            proc.send_signal(signal.SIGINT)
    except (OSError, ValueError):
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class CollectionManager:
    def __init__(self, history: JobHistoryStore, data_dir: Any, output_dir: Any = None,
                 runner: Optional[Runner] = None, now_fn: Callable[[], datetime] = utcnow,
                 background: bool = True) -> None:
        self.history = history
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir or settings.OUTPUT_DIR)
        self.runner = runner or self._tracked_runner
        self._stop_event = threading.Event()        # set by the Stop button; the run ends after the current step
        self._procs: set[subprocess.Popen] = set()  # scraper processes running now (only with the real runner)
        self._procs_lock = threading.Lock()
        # one browser for the whole run (real runs only; tests with fake runners opt in explicitly)
        self.share_browser: bool = runner is None
        self.browser_host_factory: Callable[[], Any] = lambda: BrowserHost(settings.BROWSER_PROFILE_DIR)
        self.now = now_fn
        self.background = background
        self._mutex = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status_path = self.data_dir / "collection_status.json"
        self._lock_path = self.data_dir / "collection.lock"
        self._cooldown_path = self.data_dir / "source_cooldown.json"
        self._last_write = 0.0
        self._interrupted_since: Optional[datetime] = None
        self._s: dict[str, Any] = self._load()
        if self._interrupted_since is not None:
            self._recover_after_interruption()

    # ------------------------------------------------------------ status
    def _blank(self) -> dict[str, Any]:
        return {"state": IDLE, "scope": None, "step": None, "message": "No collection has been run from the dashboard yet.",
                "target": None, "window": None, "collected_unique": 0, "new_added": 0, "already_had": 0, "duplicates_skipped": 0, "skipped_not_relevant": 0, "skipped_out_of_scope": 0,
                "per_source": {}, "skipped_filters": 0, "fetch_filters": {}, "stop_reason": None, "result_keys": [], "result_at": None,
                "search_done": 0, "search_total": 0, "current_search": None, "started_at": None, "finished_at": None,
                "last_success_at": None, "last_summary": None, "last_error": None, "warnings": [], "log_tail": []}

    def _load(self) -> dict[str, Any]:
        s = self._blank()
        try:
            s.update(json.loads(self._status_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return s
        started = s.get("started_at")
        pending = s.get("pending_recovery_since")          # set by mark_interrupted() on a clean shutdown
        if s.get("state") == RUNNING and not self._lock_is_live():
            s.update(state=FAILED, step=None, finished_at=self.now().isoformat(timespec="seconds"),
                     last_error="The previous collection was interrupted (the app was closed or restarted while it was running).",
                     message="The previous collection was interrupted.")
            pending = pending or started
        if pending:
            try:
                self._interrupted_since = datetime.fromisoformat(pending)
            except ValueError:
                self._interrupted_since = None
        return s

    def _recover_after_interruption(self) -> None:
        """The last run was cut off. Add any jobs it had already saved to disk, once, and clear its stale lock."""
        since, self._interrupted_since = self._interrupted_since, None
        self._s.pop("pending_recovery_since", None)
        try:
            if not self._lock_is_live():
                self._release_lock()
            r = recover_unprocessed(self.history, self.output_dir, since)
        except Exception as exc:                    # recovery must never stop the dashboard from starting
            log.exception("startup recovery failed")
            self._s["warnings"] = (self._s.get("warnings") or []) + [f"Recovery failed: {type(exc).__name__}: {exc}"[:240]]
            self._save(force=True)
            return
        if r.files_recovered:
            summary = {"collected": r.jobs_in_files, "new": r.new, "existing": r.existing, "duplicates_in_file": 0,
                       "scope": self._s.get("scope"), "jobs_file": r.recovered_files[-1]}
            self._s.update(state=PARTIAL, last_summary=summary,
                           message=f"The previous collection was interrupted. Recovered {r.jobs_in_files} saved jobs: "
                                   f"{r.new} new, {r.existing} already in the history.")
        if r.errors:
            self._s["warnings"] = (self._s.get("warnings") or []) + r.errors
        self._save(force=True)

    def mark_interrupted(self) -> None:
        """Called when the dashboard is shutting down: never leave the status saying 'running'."""
        with self._mutex:
            if self._s["state"] == RUNNING:
                self._s.update(state=FAILED, step=None, finished_at=self.now().isoformat(timespec="seconds"),
                               pending_recovery_since=self._s.get("started_at"), stop_requested=False,
                               last_error="The collection was interrupted because the app was closed. "
                                          "Jobs already saved are added the next time the app starts.",
                               message="The collection was interrupted.")
                self._save(force=True)
        self._end_processes(grace_s=5.0)        # the scraper runs in its own process group, so it would not see Ctrl+C
        self._release_lock()

    # ------------------------------------------------------------ stop button
    def _tracked_runner(self, cmd: list[str], on_line: Callable[[str], None], cwd: Path, timeout_s: float) -> int:
        holder: dict[str, subprocess.Popen] = {}

        def started(proc: subprocess.Popen) -> None:
            holder["proc"] = proc
            with self._procs_lock:
                self._procs.add(proc)
            if self._stop_event.is_set():           # Stop was pressed while this one was starting
                ask_to_stop(proc)
        try:
            return subprocess_runner(cmd, on_line, cwd, timeout_s, on_start=started)
        finally:
            with self._procs_lock:
                self._procs.discard(holder.get("proc"))

    def _end_processes(self, grace_s: float) -> None:
        """Ask every running scraper to save and stop; end any that is still running after grace_s seconds."""
        with self._procs_lock:
            procs = list(self._procs)
        for p in procs:
            ask_to_stop(p)
        deadline = time.monotonic() + grace_s
        for p in procs:
            try:
                p.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
            except OSError:
                pass

    def stop(self) -> bool:
        """The Stop button: end the running collection. Each scraper saves what it collected so far, those jobs are
        added as usual, and no further place or source is searched. False when nothing is running."""
        with self._mutex:
            if self._s["state"] != RUNNING:
                return False
            self._stop_event.set()
            self._s.update(stop_requested=True, message="Stopping the search. Saving the vacancies found so far...")
            self._save(force=True)
        threading.Thread(target=self._end_processes, args=(STOP_GRACE_SECONDS,), name="orbit-stop", daemon=True).start()
        return True

    def _save(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_write < 1.0:
            return
        self._last_write = time.monotonic()
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if self._s.get("state") == RUNNING:
                try:
                    os.utime(self._lock_path)        # heartbeat: proves this run is still alive
                except OSError:
                    pass
            tmp = self._status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._s, indent=2), encoding="utf-8")
            os.replace(tmp, self._status_path)
        except OSError as exc:                      # status is a convenience; never break a run over it
            log.warning("could not save collection status: %s", exc)

    def status(self) -> dict[str, Any]:
        with self._mutex:
            return json.loads(json.dumps(self._s))

    @property
    def running(self) -> bool:
        with self._mutex:
            return self._s["state"] == RUNNING

    # ------------------------------------------------------------ lock file
    def _lock_is_live(self) -> bool:
        try:
            info = json.loads(self._lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        pid = int(info.get("pid") or 0)
        try:
            if time.time() - self._lock_path.stat().st_mtime > STALE_LOCK_SECONDS:
                return False                          # nobody has refreshed it: the run is gone (and the pid may be reused)
        except OSError:
            return False
        if pid == os.getpid():
            return self._thread is not None and self._thread.is_alive()
        return pid > 0 and _pid_alive(pid)

    def _acquire_lock(self) -> bool:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._lock_is_live():
                    return False
                try:
                    self._lock_path.unlink()          # stale lock from a process that is gone
                except OSError:
                    return False
                continue
            with os.fdopen(fd, "w") as fh:
                json.dump({"pid": os.getpid(), "started_at": self.now().isoformat(timespec="seconds")}, fh)
            return True
        return False

    def _release_lock(self) -> None:
        try:
            self._lock_path.unlink()
        except OSError:
            pass

    def _write_known_ids(self, extra: Any = (), source: str = "linkedin") -> Optional[Path]:
        """List the LinkedIn job IDs already in the history so the scraper does not fetch their pages again.
        `extra` adds IDs already fetched in this run (so a repeat of a cross-source duplicate is not fetched again).
        Returns None (skip nothing) when disabled or when the list cannot be written."""
        if not settings.COLLECTION_SKIP_KNOWN_IDS:
            return None
        try:
            ids = sorted({str((j.get("record") or {}).get("job_id")) for j in self.history.list_jobs()
                          if str((j.get("record") or {}).get("source") or "").lower() == source
                          and (j.get("record") or {}).get("job_id")}
                         | {str(a.get("job_id")) for j in self.history.list_jobs() for a in (j.get("record") or {}).get("also_listed_on") or []
                            if str(a.get("source") or "").lower() == source and a.get("job_id")}
                         | {str(x) for x in extra})
            path = self.data_dir / ("known_job_ids.txt" if source == "linkedin" else f"known_job_ids_{source}.txt")
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(ids), encoding="utf-8")
            os.replace(tmp, path)
            return path
        except Exception as exc:
            log.warning("could not write the known job IDs list (%s); collecting without it", exc)
            return None

    def _write_taken_ids(self, keys: list[str], source: str = "linkedin", extra: Any = ()) -> Optional[Path]:
        """IDs of the vacancies already in this request's result, so a later place does not count them twice."""
        try:
            wanted = set(keys)
            ids = set()
            for e in self.history.list_jobs():
                if e.get("key") not in wanted:
                    continue
                rec = e.get("record") or {}
                for r in [rec] + [a for a in rec.get("also_listed_on") or [] if isinstance(a, dict)]:
                    if str(r.get("source") or "").lower() == source and r.get("job_id"):
                        ids.add(str(r["job_id"]))
            ids = sorted(ids | {str(x) for x in extra})
            path = self.data_dir / ("taken_job_ids.txt" if source == "linkedin" else f"taken_job_ids_{source}.txt")
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(ids), encoding="utf-8")
            os.replace(tmp, path)
            return path
        except Exception as exc:
            log.warning("could not write the taken job IDs list (%s)", exc)
            return None

    # ------------------------------------------------------------ start
    def start(self, scope: str, target: Optional[int] = None, window: Optional[str] = None,
              sources: Optional[list[str]] = None, filters: Optional[dict[str, str]] = None) -> tuple[bool, str]:
        """filters: optional employment / work_mode / state / contact choices applied while fetching (same rules as the dashboard).
        target: how many unique new vacancies to collect (None = collect everything, the original behaviour)."""
        if scope not in loc_config.SCOPES:
            return False, "Choose one of the listed collection scopes."
        if target is not None and (not isinstance(target, int) or isinstance(target, bool)
                                   or not 1 <= target <= settings.COLLECTION_TARGET_MAX):
            return False, f"Enter a number of vacancies between 1 and {settings.COLLECTION_TARGET_MAX}."
        window = window or settings.COLLECTION_DEFAULT_WINDOW           # the period applies with or without a number
        if window not in settings.COLLECTION_WINDOWS:
            return False, "Choose one of the listed posting windows."
        names = {n.lower(): n for n in settings.SUPPORTED_SOURCES}
        asked = {str(x).strip().lower() for x in (sources or ["linkedin"])}
        if not asked or any(c not in names for c in asked):
            return False, "Choose one or more of the listed sources."
        fetch_filters = vm.clean_fetch_filters(filters)
        chosen = [n for n in names if n in asked]          # always run in the order the form lists them
        cooling = {c: self.cooling_until(c) for c in chosen}
        wait_note = ""
        if any(cooling.values()):
            fmt = lambda t: vm.to_display_tz(t).strftime("%H:%M") + f" {settings.DISPLAY_TZ_LABEL}"
            held = [f"{names[c]} (until {fmt(u)})" for c, u in cooling.items() if u]
            chosen = [c for c in chosen if not cooling[c]]
            if not chosen:
                return False, (f"{', '.join(held)} is being rested for a short while before the next search. "
                               "Use Show saved vacancies meanwhile.")
            wait_note = f" Not searched, resting after a block: {', '.join(held)}."
        chosen_display = [names[c] for c in chosen]
        label_map = {"employment": "Employment", "work_mode": "Work mode", "state": "State", "contact": "Contact details"}
        match_note = (" Only vacancies matching: " + ", ".join(f"{label_map[k]} = {v}" for k, v in fetch_filters.items()) + ".") if fetch_filters else ""
        with self._mutex:
            if self._s["state"] == RUNNING:
                return False, "A collection is already running. Wait for it to finish."
            if not self._acquire_lock():
                return False, "A collection is already running in another Ace Talent Consulting window."
            self._stop_event.clear()
            total = len(loc_config.search_locations(scope)) * len(chosen)
            self._s.update(state=RUNNING, scope=scope, sources=chosen_display, step="collecting", search_done=0, search_total=total,
                           target=target, window=window, collected_unique=0, new_added=0, already_had=0, duplicates_skipped=0, result_keys=[], result_at=None,
                           skipped_not_relevant=0, skipped_out_of_scope=0, skipped_filters=0, fetch_filters=fetch_filters, per_source={}, stop_reason=None, last_summary=None,
                           stop_requested=False, current_search=None, started_at=self.now().isoformat(timespec="seconds"), finished_at=None,
                           last_error=None, warnings=[], log_tail=[],
                           message=(f"Collecting the {target} most recent vacancies ({settings.COLLECTION_WINDOWS[window][1].lower()}, {loc_config.SCOPES[scope]}).{match_note}{wait_note} This can take a while."
                                    if target else f"Collecting all eligible vacancies ({settings.COLLECTION_WINDOWS[window][1].lower()}, {loc_config.SCOPES[scope]}), within the dashboard's search limits.{match_note}{wait_note} This can take a while."))
            self._save(force=True)
        if self.background:
            self._thread = threading.Thread(target=self._run, args=(scope, target, window, chosen, fetch_filters), name="orbit-collection", daemon=True)
            self._thread.start()
        else:
            self._run(scope, target, window, chosen, fetch_filters)
        return True, "Collection started."

    # ------------------------------------------------------------ the run
    # ------------------------------------------------------------ cooldown after a block
    def _cooldowns(self) -> dict[str, datetime]:
        try:
            raw = json.loads(self._cooldown_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for src, iso in (raw if isinstance(raw, dict) else {}).items():
            when = parse_iso_datetime(iso) if isinstance(iso, str) else None
            if when is not None:
                out[str(src).lower()] = when
        return out

    def cooling_until(self, src: str) -> Optional[datetime]:
        """When this source may be tried again after it refused us, or None when it is free to run. Trying sooner only keeps the block alive."""
        blocked_at = self._cooldowns().get(src.lower())
        if blocked_at is None:
            return None
        until = blocked_at + timedelta(minutes=float(settings.SOURCE_COOLDOWN_MINUTES))
        return until if until > self.now() else None

    def _record_block(self, src: str) -> None:
        data = {k: v.isoformat(timespec="seconds") for k, v in self._cooldowns().items()}
        data[src.lower()] = self.now().isoformat(timespec="seconds")
        try:
            self._cooldown_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cooldown_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self._cooldown_path)
        except OSError as exc:
            log.warning("Could not record the cooldown: %s", exc)

    def _update(self, **kw: Any) -> None:
        with self._mutex:
            self._s.update(kw)
            self._save(force="step" in kw or "state" in kw)

    def _on_line(self, line: str, captured: dict[str, Any]) -> None:
        with self._mutex:
            self._s["log_tail"] = (self._s["log_tail"] + [line[-300:]])[-LOG_TAIL:]
            m = _PAGE_LINE.search(line)
            if m:
                self._s.update(current_page=int(m.group(1)), listings_on_page=int(m.group(2)))
            if _INTERRUPT_LINE in line:
                captured["interrupted"] = True
            m = _SETUP_LINE.search(line)
            if m:
                captured["setup"] = m.group(1).strip()
            m = _BLOCKED_LINE.search(line)
            if m:
                captured["blocked"] = m.group(1).strip()
            m = _SAVED_LINE.search(line)
            if m:
                captured["file"] = m.group(2).strip()
                captured["count"] = int(m.group(1))
            m = _ERROR_LINE.search(line)
            if m and len(self._s["warnings"]) < 8:
                self._s["warnings"].append(m.group(2)[:240])
            self._save()

    def _run(self, scope: str, target: Optional[int] = None, window: Optional[str] = None,
             sources: Optional[list[str]] = None, fetch_filters: Optional[dict[str, str]] = None) -> None:
        """One scraper process per place and per source; each is normalized and added to the history as soon as it finishes.

        With a target N the result is "the N most recent vacancies": for every chosen source the scraper walks the
        newest-first search results and stops after N unique postings. A posting already in the history still counts
        as one of the N (it is not fetched or stored again); a posting repeated within the run counts once. With
        several sources the per-source lists are merged (an opening listed on two sources counts once) and the N
        most recently posted are kept. The N keys are saved in the status file so the dashboard can show exactly
        those. Nothing in the history is removed."""
        sources = sources or ["linkedin"]
        pretty = {n.lower(): n for n in settings.SUPPORTED_SOURCES}
        places = loc_config.search_locations(scope)

        def places_for(src: str) -> list[str]:
            """A source that reads companies' careers pages does not depend on the city, so it is searched once, not once per place."""
            return places[:1] if is_location_independent(src) else places
        days, window_label = (settings.COLLECTION_WINDOWS[window] if window else (settings.COLLECTION_DAYS, ""))
        within = f" posted in the {window_label.lower()}" if window_label else ""
        totals = {"collected": 0, "new": 0, "existing": 0, "duplicates_in_file": 0}
        problems: list[str] = []
        blocked_srcs: list[str] = []
        blocked_why: dict[str, str] = {}
        setup_srcs: list[str] = []
        interrupted = timed_out = False
        files = 0
        n = 0
        run_seen: dict[str, set[str]] = {src: set() for src in sources}
        rejected: dict[str, set[str]] = {src: set() for src in sources}      # fetched, but not a GCC/BFSI opening
        only_relevant = bool(settings.COLLECTION_ONLY_GCC_BFSI)
        # Saved jobs that fail today's GCC/BFSI rules, or whose own location is not in the chosen scope (India only /
        # International only), are hidden on the dashboard, so they must not count towards "N vacancies" either (otherwise
        # the page shows fewer than requested). They stay in the history; they are only left out of the count.
        ineligible_keys: set[str] = set()
        filtered_ids: set[tuple[str, str]] = set()
        for e in self.history.list_jobs():
            rec = e.get("record") or {}
            bad = False
            if only_relevant and not classify(rec.get("company"), rec.get("title"), rec.get("description"), rec.get("industries"),
                                              posted_by=rec.get("posted_by"), company_url=rec.get("company_url"),
                                              location=rec.get("location")).eligible:
                bad = True
            if not bad and scope in ("india", "international"):
                loc_text = rec.get("location")
                if not loc_text or not location_in_scope(check_location(loc_text).country, scope):
                    bad = True
            strict_hours = days * 24.0 if (window and settings.COLLECTION_STRICT_WINDOW) else None
            if not bad and (fetch_filters or strict_hours) and not vm.fetch_filter_matches([rec], fetch_filters, max_age_hours=strict_hours)[0]:
                bad = True
            if bad:
                ineligible_keys.add(e.get("key"))
                for r in [rec] + [a for a in rec.get("also_listed_on") or [] if isinstance(a, dict)]:
                    rs = str(r.get("source") or "").lower()
                    if rs in rejected and r.get("job_id"):
                        rejected[rs].add(str(r["job_id"]))
        per_src: dict[str, list[str]] = {src: [] for src in sources}
        # With a target N the scraper gathers a few more candidates than N (newest first) so that, among postings of
        # similar recency, the ones that state the poster's contact details can be preferred. Factor 1 = exactly N.
        pool = min((target or 0) * max(1, int(settings.COLLECTION_CANDIDATE_POOL_FACTOR)), settings.COLLECTION_TARGET_MAX * max(1, int(settings.COLLECTION_CANDIDATE_POOL_FACTOR)))
        prior_keys = {e["key"] for e in self.history.list_jobs()}           # what the history held before this run
        deadline = time.time() + settings.COLLECTION_TIMEOUT_MINUTES * 60.0

        def rank_candidates(keys: list[str]) -> list[str]:
            """Most recently posted first. Postings from the same recency window (settings.COLLECTION_RECENCY_TOLERANCE_HOURS)
            are ordered with the ones that state the poster's own contact details first, then by exact time. Recency is never
            traded for contact details: a newer window always comes before an older one. Undated postings go last."""
            if len(keys) < 2:
                return list(keys)
            info = {e["key"]: (e.get("record") or {}) for e in self.history.list_jobs() if e["key"] in set(keys)}
            tol = max(float(settings.COLLECTION_RECENCY_TOLERANCE_HOURS), 0.01) * 3600.0

            def sort_key(k: str):
                rec = info.get(k) or {}
                dt = parse_iso_datetime(rec.get("posted_at")) if rec.get("posted_at") else None
                if dt is None:
                    return (1, 0, 1, 0.0)
                ts = dt.timestamp()
                has = poster_contacts(rec.get("description"), rec.get("recruiter_email"), rec.get("recruiter_phone"),
                                      rec.get("recruiter_name"), rec.get("contact_url")).direct
                return (0, -int(ts // tol), 0 if has else 1, -ts)
            return sorted(keys, key=sort_key)

        def picks() -> list[tuple[str, str]]:
            """The (key, source) pairs of the result. One source: its N newest. Several sources: a fair share of each,
            taken in turn (newest first within a source); a source that found fewer than its share lets the others fill
            the gap. The same opening listed on two sources counts once."""
            if not target:
                return []
            order = [src for src in sources if per_src[src]]
            ranked = {src: rank_candidates(per_src[src]) for src in order}
            chosen: list[tuple[str, str]] = []
            seen_keys: set[str] = set()
            idx = {src: 0 for src in order}
            while len(chosen) < target and any(idx[x] < len(ranked[x]) for x in order):
                for src in order:
                    while idx[src] < len(ranked[src]) and ranked[src][idx[src]] in seen_keys:
                        idx[src] += 1                                  # already taken via another source: skip, uncounted
                    if idx[src] < len(ranked[src]) and len(chosen) < target:
                        key = ranked[src][idx[src]]
                        seen_keys.add(key); chosen.append((key, src)); idx[src] += 1
            return chosen

        def merged() -> list[str]:
            chosen = picks()
            if len(sources) == 1:
                return [k for k, _ in chosen]
            posted = {e["key"]: str((e.get("record") or {}).get("posted_at") or "") for e in self.history.list_jobs()}
            return [k for k, _ in sorted(chosen, key=lambda kv: posted.get(kv[0], ""), reverse=True)]    # shown newest first

        src_totals: dict[str, dict[str, int]] = {src: {"found": 0, "new": 0, "existing": 0, "already": 0, "not_relevant": 0, "out_of_scope": 0} for src in sources}

        def per_source_counts() -> dict[str, Any]:
            used: dict[str, int] = {}
            for _, src in picks():
                used[src] = used.get(src, 0) + 1
            return {pretty.get(src, src): dict(src_totals[src], in_result=used.get(src, 0) if target else None)
                    for src in sources}

        def src_reached(src: str) -> bool:
            # Moving on to the next place only depends on the TARGET. The extra candidates (the pool) are taken from the
            # places already being searched, so asking for 2 vacancies never means walking every place to find 4.
            return bool(target) and len(per_src[src]) >= target

        def counts() -> dict[str, Any]:
            keys = merged()
            if not target:       # no number requested: report what this run found (nothing is capped or ranked)
                return dict(collected_unique=totals["new"] + totals["existing"], new_added=totals["new"], already_had=totals["existing"],
                            duplicates_skipped=totals["duplicates_in_file"], result_keys=[], per_source=per_source_counts())
            had = sum(1 for k in keys if k in prior_keys)       # in the list and already stored before this run
            return dict(collected_unique=len(keys), new_added=len(keys) - had,
                        already_had=had,
                        duplicates_skipped=totals["existing"] + totals["duplicates_in_file"], result_keys=keys,
                        per_source=per_source_counts())

        def add_results(src: str, latest_ids: list[str], fetched_jobs: list[dict[str, Any]]) -> int:
            """Map the postings the scraper took to their history keys; return how many were new to the result.
            A posting stored under another vacancy's key (the same URL under a different id, or the same opening
            first collected from another source) maps to that key."""
            entries = self.history.list_jobs()
            idmap: dict[str, str] = {}
            for e in entries:
                rec = e.get("record") or {}
                if str(rec.get("source") or "").lower() == src:
                    idmap[str(rec.get("job_id"))] = e["key"]
                for alt in rec.get("also_listed_on") or []:
                    if isinstance(alt, dict) and str(alt.get("source") or "").lower() == src:
                        idmap.setdefault(str(alt.get("job_id")), e["key"])
            urlmap = {normalize_job_url((e.get("record") or {}).get("job_url")): e["key"] for e in entries}
            url_of = {str(j.get("job_id")): normalize_job_url(j.get("job_url")) for j in fetched_jobs}
            added = 0
            for jid in latest_ids:
                key = idmap.get(str(jid)) or (urlmap.get(url_of.get(str(jid))) if url_of.get(str(jid)) else None)
                if key in ineligible_keys:
                    continue
                if key and key not in per_src[src] and len(per_src[src]) < pool:
                    per_src[src].append(key)
                    added += 1
            return added

        proc_lock = threading.RLock()              # one source at a time reads results into the history / counters
        done_by: dict[str, int] = {src: 0 for src in sources}

        def run_one_source(si: int, src: str) -> None:
            nonlocal files, interrupted, timed_out
            if True:
                label = pretty.get(src, src)
                src_stop = False
                for n, place in enumerate(places_for(src)):
                    if src_reached(src) or src_stop or interrupted or timed_out or self._stop_event.is_set():
                        break
                    rounds = 0
                    while not (src_stop or interrupted or timed_out or src_reached(src) or self._stop_event.is_set()):
                        remaining = deadline - time.time()
                        if remaining <= 0:
                            timed_out = True
                            problems.append("The time limit was reached before every place was searched.")
                            break
                        want = (pool - len(per_src[src])) if target else None
                        progress = f" - {len(merged())} of {target} vacancies so far" if target else ""
                        where = f"{label}: " if len(sources) > 1 else ""
                        done_by[src] = n
                        self._update(search_done=sum(done_by.values()), search_total=sum(len(places_for(s)) for s in sources), current_search=place,
                                     step="collecting", current_page=0, listings_on_page=0,
                                     message=f"Collecting jobs ({loc_config.SCOPES[scope]}): {where}{place}{progress}")
                        captured: dict[str, Any] = {}
                        started = time.time()
                        known = self._write_known_ids(run_seen[src], src)    # rebuilt for every pass: earlier jobs are already in the history
                        taken = self._write_taken_ids(per_src[src], src, rejected[src]) if (target and (per_src[src] or rejected[src])) else None
                        code = self.runner(build_command(scope, self.output_dir, [place], known, max_jobs=want, count_known=bool(target),
                                                         exclude_ids_file=taken, days=days, source=src),
                                           lambda ln: self._on_line(ln, captured), ROOT, remaining)
                        rounds += 1
                        if code == EXIT_SETUP:
                            setup_srcs.append(label)
                            problems.append(f"{label} could not run: {captured.get('setup') or 'browser support is not installed.'}"[:300])
                            src_stop = True
                            break
                        path = self._find_output(captured, started, src)
                        fetched = added = 0
                        latest: list[str] = []
                        if path is not None and code in (0, EXIT_BLOCKED):
                            with proc_lock:
                                self._update(step="saving")
                                _, jobs = load_jobs(path)
                                files += 1
                                fetched = len(jobs)
                                src_totals[src]["found"] += fetched
                                run_seen[src].update(str(j.get("job_id")) for j in jobs if j.get("job_id"))
                                rej_new = 0
                                if jobs:                       # nothing new for this place: do not create an empty history run
                                    normalized = normalize_all(jobs)
                                    if only_relevant:
                                        kept, dropped_records = keep_eligible(normalized.jobs)
                                        dropped = {str(r.get("job_id")) for r in dropped_records}
                                        rej_new = len(dropped - rejected[src])
                                        rejected[src] |= dropped
                                        normalized.jobs = kept
                                        totals["not_relevant"] = totals.get("not_relevant", 0) + len(dropped)
                                        src_totals[src]["not_relevant"] += len(dropped)
                                        self._update(skipped_not_relevant=totals["not_relevant"])
                                    if scope in ("india", "international"):
                                        in_scope, out_records = keep_in_scope(normalized.jobs, scope)
                                        out_ids = {str(r.get("job_id")) for r in out_records}
                                        rej_new += len(out_ids - rejected[src])
                                        rejected[src] |= out_ids
                                        normalized.jobs = in_scope
                                        totals["out_of_scope"] = totals.get("out_of_scope", 0) + len(out_ids)
                                        src_totals[src]["out_of_scope"] += len(out_ids)
                                        self._update(skipped_out_of_scope=totals["out_of_scope"])
                                    if fetch_filters or (window and settings.COLLECTION_STRICT_WINDOW):
                                        flags = vm.fetch_filter_matches(normalized.jobs, fetch_filters, max_age_hours=days * 24.0 if (window and settings.COLLECTION_STRICT_WINDOW) else None)
                                        no_match = [r for r, ok in zip(normalized.jobs, flags) if not ok]
                                        out_ids = {str(r.get("job_id")) for r in no_match}
                                        rej_new += len(out_ids - rejected[src])
                                        rejected[src] |= out_ids
                                        normalized.jobs = [r for r, ok in zip(normalized.jobs, flags) if ok]
                                        filtered_ids.update((src, i) for i in out_ids)          # each posting counted once
                                        totals["filtered_out"] = len(filtered_ids)
                                        self._update(skipped_filters=totals["filtered_out"])
                                if jobs:
                                    totals["collected"] += len(jobs)
                                if jobs and normalized.jobs:
                                    norm_path = save_normalized(normalized, self.output_dir, src, input_file=path)
                                    result = ingest_filtered_file(norm_path, self.history)
                                    totals["new"] += result.new
                                    totals["existing"] += result.existing
                                    src_totals[src]["new"] += result.new
                                    src_totals[src]["existing"] += result.existing
                                    totals["duplicates_in_file"] += result.duplicates_in_file
                                if target:
                                    try:
                                        run_info = json.loads(path.read_text(encoding="utf-8")).get("run") or {}
                                        latest = [str(x) for x in run_info.get("latest_ids") or []]
                                    except (OSError, ValueError):
                                        latest = []
                                    added = add_results(src, latest, jobs)
                                    fetched_ids = {str(j.get("job_id")) for j in jobs}
                                    src_totals[src]["already"] += len([i for i in latest if i not in fetched_ids])   # counted but not re-fetched
                                self._update(last_summary=dict(totals, scope=scope, jobs_file=path.name), **counts())
                        elif self._stop_event.is_set():
                            pass                       # ended by the Stop button: not a problem with the place
                        elif code not in (0, EXIT_BLOCKED):
                            problems.append(f"{(label + ' - ') if len(sources) > 1 else ''}{place}: the collector stopped with an error (exit code {code}).")
                        elif path is None:
                            problems.append(f"{(label + ' - ') if len(sources) > 1 else ''}{place}: no jobs file was saved.")
                        if code == EXIT_BLOCKED:
                            blocked_srcs.append(label)
                            self._record_block(src)
                            blocked_why[label] = short_reason(captured.get("blocked"))
                            problems.append(f"{label} blocked: {blocked_why[label]}. Not retried.")
                            src_stop = True
                        if captured.get("interrupted") and not self._stop_event.is_set():
                            interrupted = True
                        # Search the same place again only when this pass hit its cap yet some postings could not be
                        # matched to a stored vacancy (a repeat under another id), so the target is still short.
                        again = (bool(target) and code == 0 and want is not None and len(latest) + rej_new >= want and (added > 0 or rej_new > 0)
                                 and not src_reached(src) and rounds <= settings.COLLECTION_ROUNDS_PER_PLACE)
                        if not again:
                            break

        host = None
        if (self.share_browser and settings.BROWSER_SHARED_ACROSS_PLACES and not settings.BROWSER_HEADLESS
                and any(x in settings.BROWSER_SOURCES for x in sources)):
            self._update(message="Starting the browser for this collection...")
            host = self.browser_host_factory()
            url = host.start()
            if url:
                os.environ[BROWSER_ENV] = url
            else:
                host = None                      # fall back: each place starts its own browser, as before
        try:
            if settings.COLLECTION_PARALLEL_SOURCES and len(sources) > 1:
                # LinkedIn and Naukri are different sites, so searching them at the same time does not raise the rate on either
                # one; it just stops the second source waiting for the first. Each source keeps its own throttling.
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="orbit-source") as pool_ex:
                    futures = [pool_ex.submit(run_one_source, si, src) for si, src in enumerate(sources)]
                    for fut in futures:
                        fut.result()                       # re-raises a failure so the run reports it
            else:
                for si, src in enumerate(sources):
                    run_one_source(si, src)

            blocked = bool(blocked_srcs)
            names = ", ".join(dict.fromkeys(blocked_srcs))
            finished = self.now().isoformat(timespec="seconds")
            summary = dict(totals, scope=scope, jobs_file=None)
            extra = dict(counts(), result_at=finished if target else None)
            got = f"{extra['collected_unique']} of {target}" if target else str(totals["new"])
            met = bool(target) and extra["collected_unique"] >= target
            skipped_note = f" Not collected: {', '.join(dict.fromkeys(setup_srcs))} (see Details)." if setup_srcs else ""
            if totals.get("not_relevant"):
                skipped_note += f" {totals['not_relevant']} posting(s) were skipped because they did not look like GCC or BFSI openings."
            if totals.get("out_of_scope"):
                where = "in India" if scope == "india" else "outside India"
                skipped_note += (f" {totals['out_of_scope']} posting(s) were skipped because their own location is not confidently {where}"
                                 " (missing, unclear or in more than one country).")
            if totals.get("not_relevant") or totals.get("out_of_scope"):
                skipped_note += " Skipped postings are not counted towards your number."
            if len(sources) > 1:
                ps = per_source_counts()
                skipped_note += " By source: " + "; ".join(
                    f"{name} {c['in_result']} shown of {c['found'] + c['already']} found" if target else f"{name} {c['new'] + c['existing']} collected of {c['found'] + c['already']} found"
                    for name, c in ps.items()) + "."
            total_places = sum(len(places_for(s)) for s in sources)
            if self._stop_event.is_set():
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=sum(done_by.values()), stop_reason="stopped",
                             stop_requested=False, last_error=None, warnings=(self._s["warnings"] + problems)[:12],
                             message=f"Stopped by you. Got {got} vacancies; the ones found before stopping were added.{skipped_note}", **extra)
            elif blocked:
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=sum(done_by.values()), stop_reason="blocked",
                             last_error=(f"{names} started refusing requests, so that source stopped ({'; '.join(f'{k}: {v}' for k, v in blocked_why.items())}). "
                                         "The tool does not retry or work around a block; jobs collected before it were added. "
                                         "Other sources you selected were still run. "
                                         + " ".join(settings.SOURCE_BLOCK_ADVICE.get(b, "") for b in dict.fromkeys(blocked_srcs)).strip()
                                         + ("" if any(b in settings.SOURCE_BLOCK_ADVICE for b in blocked_srcs)
                                            else " Try again later, or check with verify_sources.py --visible.")),
                             warnings=(self._s["warnings"] + problems)[:12],
                             message=f"Collection finished. Got {got} vacancies.{skipped_note}", **extra)
            elif interrupted:
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=sum(done_by.values()), stop_reason="interrupted",
                             last_error="The collection was interrupted. Jobs saved before the interruption were added.",
                             message=f"Interrupted. The collection could not continue; got {got} vacancies.", **extra)
            elif timed_out:
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=sum(done_by.values()), stop_reason="time_limit",
                             last_error="The time limit was reached before the collection finished.",
                             message=f"Collection could not continue: time limit reached. Got {got} vacancies.", **extra)
            elif files == 0:
                raise RuntimeError("No jobs file was saved for any place. " + " ".join(problems[:3]) +
                                   " See the log lines below for the reason.")
            elif met:
                self._update(state=SUCCEEDED, step=None, finished_at=finished, last_success_at=finished, last_summary=summary,
                             search_done=total_places, stop_reason="target_reached", warnings=(self._s["warnings"] + problems)[:12],
                             message=(f"Target reached: the {extra['collected_unique']} most recent vacancies{within} are ready "
                                      f"({extra['new_added']} new to your history, {extra['already_had']} already collected).{skipped_note}"), **extra)
            else:
                note = f" {len(problems)} place(s) had problems (see Details)." if problems else ""
                if target:
                    why = ("Some places or sources could not be searched, so fewer vacancies were collected than requested."
                           if problems else
                           f"Results were exhausted: all {len(places)} search locations were searched and no more vacancies{within} were found.")
                    msg = f"Collected {got} requested vacancies{within}. {why}{skipped_note}"
                else:
                    msg = (f"Finished collecting all eligible vacancies{within} (no number requested; the dashboard's search limits applied). "
                           f"{totals['new']} new, {totals['existing']} already in the history.{note}{skipped_note}")
                self._update(state=SUCCEEDED, step=None, finished_at=finished, last_success_at=finished, last_summary=summary,
                             search_done=total_places, stop_reason="incomplete" if (target and problems) else "exhausted",
                             warnings=(self._s["warnings"] + problems)[:12], message=msg, **extra)
        except Exception as exc:
            log.exception("collection failed")
            self._update(state=FAILED, step=None, finished_at=self.now().isoformat(timespec="seconds"), stop_reason="error", stop_requested=False,
                         last_error=f"{type(exc).__name__}: {exc}"[:600], message="The collection did not finish.")
        finally:
            if host is not None:
                try:
                    host.stop()
                except Exception:  # noqa: BLE001
                    pass
                os.environ.pop(BROWSER_ENV, None)
            self._release_lock()
            with self._mutex:
                self._save(force=True)

    def show_saved(self, scope: str, target: Optional[int] = None, window: Optional[str] = None,
                   sources: Optional[list[str]] = None, filters: Optional[dict[str, str]] = None) -> tuple[bool, str]:
        """No searching: list the vacancies ALREADY in the history that match the same request (location scope, sources,
        posted-within window, State / Employment / Work mode / Contact filters), newest first. Nothing is fetched or changed
        in the history; the dashboard then shows exactly these vacancies, like the result of a collection."""
        if scope not in loc_config.SCOPES:
            return False, "Choose one of the listed collection scopes."
        window = window or settings.COLLECTION_DEFAULT_WINDOW
        if window not in settings.COLLECTION_WINDOWS:
            return False, "Choose one of the listed posting windows."
        names = {n.lower(): n for n in settings.SUPPORTED_SOURCES}
        asked = [str(x).strip().lower() for x in (sources or list(names))]
        if not asked or any(c not in names for c in asked):
            return False, "Choose one or more of the listed sources."
        fetch_filters = vm.clean_fetch_filters(filters)
        with self._mutex:
            if self._s["state"] == RUNNING:
                return False, "A collection is already running. Wait for it to finish."
        days, label = settings.COLLECTION_WINDOWS[window]
        rows = vm.saved_vacancies(self.history.list_jobs(), scope, asked, days * 24.0, fetch_filters, target)
        now = self.now().isoformat(timespec="seconds")
        label_map = {"employment": "Employment", "work_mode": "Work mode", "state": "State", "contact": "Contact details"}
        note = (" Matching: " + ", ".join(f"{label_map[k]} = {v}" for k, v in fetch_filters.items()) + ".") if fetch_filters else ""
        asked_n = f"{target} " if target else ""
        short = bool(target) and len(rows) < target
        msg = (f"Showing {len(rows)} saved {'vacancy' if len(rows) == 1 else 'vacancies'} posted in the {label.lower()}{note} "
               f"(from the vacancies already collected; no new search was run)."
               + (f" Only {len(rows)} of the {asked_n}requested match - run a collection to look for more." if short else ""))
        self._update(state=SUCCEEDED, step=None, scope=scope, sources=[names[c] for c in asked], target=target, window=window,
                     fetch_filters=fetch_filters, result_keys=[r.key for r in rows], result_at=now, finished_at=now,
                     collected_unique=len(rows), new_added=0, already_had=len(rows), duplicates_skipped=0, per_source={},
                     skipped_not_relevant=0, skipped_out_of_scope=0, skipped_filters=0, stop_reason="saved", last_error=None,
                     warnings=[], message=msg)
        return True, msg

    def _find_output(self, captured: dict[str, Any], started: float, src: str = "") -> Optional[Path]:
        if captured.get("file"):
            p = Path(captured["file"])
            p = p if p.is_absolute() else ROOT / p
            if p.exists():
                return p
        # only this source's own files: with sources running side by side, another source's file may be half written
        files = [p for p in self.output_dir.glob(f"jobs_{src}_*.json" if src else "jobs_*_*.json") if p.stat().st_mtime >= started - 1]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
