"""Run the existing LinkedIn collection from the dashboard, safely, in the background.

What a run does (the same three steps you would run by hand):
  1. collect   - run_collect.py (the unchanged Phase 1 scraper) as a separate process
  2. normalize - Phase 2 rules on every collected job (nothing removed)
  3. ingest    - add to the job history with deduplication

Safety
  * one run at a time: an in-process flag AND a lock file (data/collection.lock), so a second
    browser tab, a second Orbit window, or a double click cannot start a duplicate run
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
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from config import locations as loc_config
from config import settings
from processing.pipeline import load_jobs, normalize_all, save_normalized
from store.base import JobHistoryStore
from store.ingest import ingest_filtered_file
from store.keys import normalize_job_url
from store.recovery import recover_unprocessed

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

IDLE, RUNNING, SUCCEEDED, PARTIAL, FAILED = "idle", "running", "succeeded", "partial", "failed"
EXIT_BLOCKED = 2            # run_collect.py: the source blocked us (it still saves what it had)
_SEARCH_LINE = re.compile(r"\[(\w+)\] Search (\d+)/(\d+): (.*)$")
_SAVED_LINE = re.compile(r"Saved (\d+) jobs to (.+)$")
_PAGE_LINE = re.compile(r"Search page (\d+): (\d+) listings")
_INTERRUPT_LINE = "Interrupted by user"
_ERROR_LINE = re.compile(r"\|\s*(ERROR|CRITICAL)\s*\|\s*(.*)$")
LOG_TAIL = 30
STALE_LOCK_SECONDS = 600      # a live run refreshes its lock with every progress save; older than this = left behind

Runner = Callable[[list[str], Callable[[str], None], Path, float], int]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_target(value: Any) -> Optional[int]:
    """The vacancy count typed into the form: a whole number from 1 to COLLECTION_TARGET_MAX, else None."""
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[0-9]{1,6}", text):
        return None
    n = int(text)
    return n if 1 <= n <= settings.COLLECTION_TARGET_MAX else None


def build_command(scope: str, output_dir: Path, locations: Optional[list[str]] = None,
                  skip_ids_file: Optional[Path] = None, max_jobs: Optional[int] = None,
                  count_known: bool = False, exclude_ids_file: Optional[Path] = None, days: Optional[int] = None) -> list[str]:
    """The exact run_collect.py command. Only values from config files go in.

    The dashboard runs it once per place (locations=[place]) so jobs are saved after every place
    and a problem in one place never loses the others."""
    return [
        sys.executable, str(ROOT / "run_collect.py"),
        "--keywords", *settings.COLLECTION_KEYWORDS,
        "--locations", *(locations if locations is not None else loc_config.search_locations(scope)),
        "--days", str(days if days is not None else settings.COLLECTION_DAYS),
        "--max-jobs-per-search", str(max_jobs if max_jobs is not None else settings.COLLECTION_MAX_JOBS_PER_SEARCH),
        "--max-pages", str(settings.COLLECTION_MAX_PAGES),
        "--output-dir", str(output_dir),
        *(["--skip-ids-file", str(skip_ids_file)] if skip_ids_file else []),
        *(["--count-known"] if count_known and skip_ids_file else []),
        *(["--exclude-ids-file", str(exclude_ids_file)] if count_known and skip_ids_file and exclude_ids_file else []),
    ]


def subprocess_runner(cmd: list[str], on_line: Callable[[str], None], cwd: Path, timeout_s: float) -> int:
    """Run the scraper, feeding each output line to on_line. Kills it after timeout_s."""
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    timer = threading.Timer(timeout_s, proc.kill)
    timer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            on_line(line.rstrip("\n"))
        return proc.wait()
    finally:
        timer.cancel()


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
        self.runner = runner or subprocess_runner
        self.now = now_fn
        self.background = background
        self._mutex = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status_path = self.data_dir / "collection_status.json"
        self._lock_path = self.data_dir / "collection.lock"
        self._last_write = 0.0
        self._interrupted_since: Optional[datetime] = None
        self._s: dict[str, Any] = self._load()
        if self._interrupted_since is not None:
            self._recover_after_interruption()

    # ------------------------------------------------------------ status
    def _blank(self) -> dict[str, Any]:
        return {"state": IDLE, "scope": None, "step": None, "message": "No collection has been run from the dashboard yet.",
                "target": None, "window": None, "collected_unique": 0, "new_added": 0, "already_had": 0, "duplicates_skipped": 0,
                "stop_reason": None, "result_keys": [], "result_at": None,
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
                               pending_recovery_since=self._s.get("started_at"),
                               last_error="The collection was interrupted because the app was closed. "
                                          "Jobs already saved are added the next time the app starts.",
                               message="The collection was interrupted.")
                self._save(force=True)
        self._release_lock()

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

    def _write_known_ids(self, extra: Any = ()) -> Optional[Path]:
        """List the LinkedIn job IDs already in the history so the scraper does not fetch their pages again.
        `extra` adds IDs already fetched in this run (so a repeat of a cross-source duplicate is not fetched again).
        Returns None (skip nothing) when disabled or when the list cannot be written."""
        if not settings.COLLECTION_SKIP_KNOWN_IDS:
            return None
        try:
            ids = sorted({str((j.get("record") or {}).get("job_id")) for j in self.history.list_jobs()
                          if str((j.get("record") or {}).get("source") or "").lower() == "linkedin"
                          and (j.get("record") or {}).get("job_id")} | {str(x) for x in extra})
            path = self.data_dir / "known_job_ids.txt"
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(ids), encoding="utf-8")
            os.replace(tmp, path)
            return path
        except Exception as exc:
            log.warning("could not write the known job IDs list (%s); collecting without it", exc)
            return None

    def _write_taken_ids(self, keys: list[str]) -> Optional[Path]:
        """IDs of the vacancies already in this request's result, so a later place does not count them twice."""
        try:
            wanted = set(keys)
            ids = sorted({str((e.get("record") or {}).get("job_id")) for e in self.history.list_jobs()
                          if e.get("key") in wanted and (e.get("record") or {}).get("job_id")})
            path = self.data_dir / "taken_job_ids.txt"
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(ids), encoding="utf-8")
            os.replace(tmp, path)
            return path
        except Exception as exc:
            log.warning("could not write the taken job IDs list (%s)", exc)
            return None

    # ------------------------------------------------------------ start
    def start(self, scope: str, target: Optional[int] = None, window: Optional[str] = None) -> tuple[bool, str]:
        """target: how many unique new vacancies to collect (None = collect everything, the original behaviour)."""
        if scope not in loc_config.SCOPES:
            return False, "Choose one of the listed collection scopes."
        if target is not None and (not isinstance(target, int) or isinstance(target, bool)
                                   or not 1 <= target <= settings.COLLECTION_TARGET_MAX):
            return False, f"Enter a number of vacancies between 1 and {settings.COLLECTION_TARGET_MAX}."
        if target is not None:
            window = window or settings.COLLECTION_DEFAULT_WINDOW
            if window not in settings.COLLECTION_WINDOWS:
                return False, "Choose one of the listed posting windows."
        else:
            window = None
        with self._mutex:
            if self._s["state"] == RUNNING:
                return False, "A collection is already running. Wait for it to finish."
            if not self._acquire_lock():
                return False, "A collection is already running in another Orbit window."
            total = len(loc_config.search_locations(scope))
            self._s.update(state=RUNNING, scope=scope, step="collecting", search_done=0, search_total=total,
                           target=target, window=window, collected_unique=0, new_added=0, already_had=0, duplicates_skipped=0, result_keys=[], result_at=None,
                           stop_reason=None, last_summary=None,
                           current_search=None, started_at=self.now().isoformat(timespec="seconds"), finished_at=None,
                           last_error=None, warnings=[], log_tail=[],
                           message=(f"Collecting the {target} most recent vacancies ({settings.COLLECTION_WINDOWS[window][1].lower()}, {loc_config.SCOPES[scope]}). This can take a while."
                                    if target else f"Collecting jobs ({loc_config.SCOPES[scope]}). This can take a while."))
            self._save(force=True)
        if self.background:
            self._thread = threading.Thread(target=self._run, args=(scope, target, window), name="orbit-collection", daemon=True)
            self._thread.start()
        else:
            self._run(scope, target, window)
        return True, "Collection started."

    # ------------------------------------------------------------ the run
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
            m = _SAVED_LINE.search(line)
            if m:
                captured["file"] = m.group(2).strip()
                captured["count"] = int(m.group(1))
            m = _ERROR_LINE.search(line)
            if m and len(self._s["warnings"]) < 8:
                self._s["warnings"].append(m.group(2)[:240])
            self._save()

    def _run(self, scope: str, target: Optional[int] = None, window: Optional[str] = None) -> None:
        """One scraper process per place; each place is normalized and added to the history as soon as it finishes.

        With a target N the result is "the N most recent vacancies on the source": the scraper walks the newest-first
        search results and stops after N unique postings. A posting already in the history still counts as one of the
        N (it is not fetched or stored again); a posting repeated within the run counts once. The N keys are saved
        in the status file so the dashboard can show exactly those. Nothing in the history is removed."""
        places = loc_config.search_locations(scope)
        days, window_label = (settings.COLLECTION_WINDOWS[window] if window else (settings.COLLECTION_DAYS, ""))
        within = f" posted in the {window_label.lower()}" if window_label else ""
        totals = {"collected": 0, "new": 0, "existing": 0, "duplicates_in_file": 0}
        problems: list[str] = []
        blocked = interrupted = timed_out = False
        files = 0
        n = 0
        run_seen: set[str] = set()
        result_keys: list[str] = []
        deadline = time.time() + settings.COLLECTION_TIMEOUT_MINUTES * 60.0

        def reached() -> bool:
            return bool(target) and len(result_keys) >= target

        def counts() -> dict[str, Any]:
            return dict(collected_unique=len(result_keys), new_added=totals["new"],
                        already_had=max(len(result_keys) - totals["new"], 0),
                        duplicates_skipped=totals["existing"] + totals["duplicates_in_file"], result_keys=list(result_keys))

        def add_results(latest_ids: list[str], fetched_jobs: list[dict[str, Any]]) -> int:
            """Map the postings the scraper took to their history keys; return how many were new to the result.
            A posting stored under another vacancy's key (the same URL under a different id) maps to that key."""
            entries = self.history.list_jobs()
            idmap = {str((e.get("record") or {}).get("job_id")): e["key"] for e in entries
                     if str((e.get("record") or {}).get("source") or "").lower() == "linkedin"}
            urlmap = {normalize_job_url((e.get("record") or {}).get("job_url")): e["key"] for e in entries}
            url_of = {str(j.get("job_id")): normalize_job_url(j.get("job_url")) for j in fetched_jobs}
            added = 0
            for jid in latest_ids:
                key = idmap.get(str(jid)) or (urlmap.get(url_of.get(str(jid))) if url_of.get(str(jid)) else None)
                if key and key not in result_keys and len(result_keys) < (target or 0):
                    result_keys.append(key)
                    added += 1
            return added

        try:
            for n, place in enumerate(places):
                if reached():
                    break
                rounds = 0
                while not (blocked or interrupted or timed_out or reached()):
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        timed_out = True
                        problems.append("The time limit was reached before every place was searched.")
                        break
                    want = (target - len(result_keys)) if target else None
                    progress = f" - {len(result_keys)} of {target} vacancies so far" if target else ""
                    self._update(search_done=n, search_total=len(places), current_search=place, step="collecting",
                                 current_page=0, listings_on_page=0,
                                 message=f"Collecting jobs ({loc_config.SCOPES[scope]}): {place}{progress}")
                    captured: dict[str, Any] = {}
                    started = time.time()
                    known = self._write_known_ids(run_seen)    # rebuilt for every pass: earlier jobs are already in the history
                    taken = self._write_taken_ids(result_keys) if (target and result_keys) else None
                    code = self.runner(build_command(scope, self.output_dir, [place], known, max_jobs=want, count_known=bool(target),
                                                     exclude_ids_file=taken, days=days),
                                       lambda ln: self._on_line(ln, captured), ROOT, remaining)
                    rounds += 1
                    path = self._find_output(captured, started)
                    fetched = added = 0
                    latest: list[str] = []
                    if path is not None and code in (0, EXIT_BLOCKED):
                        self._update(step="saving")
                        _, jobs = load_jobs(path)
                        files += 1
                        fetched = len(jobs)
                        run_seen.update(str(j.get("job_id")) for j in jobs if j.get("job_id"))
                        if jobs:                       # nothing new for this place: do not create an empty history run
                            normalized = normalize_all(jobs)
                            norm_path = save_normalized(normalized, self.output_dir, "linkedin", input_file=path)
                            result = ingest_filtered_file(norm_path, self.history)
                            totals["collected"] += len(jobs)
                            totals["new"] += result.new
                            totals["existing"] += result.existing
                            totals["duplicates_in_file"] += result.duplicates_in_file
                        if target:
                            try:
                                run_info = json.loads(path.read_text(encoding="utf-8")).get("run") or {}
                                latest = [str(x) for x in run_info.get("latest_ids") or []]
                            except (OSError, ValueError):
                                latest = []
                            added = add_results(latest, jobs)
                        self._update(last_summary=dict(totals, scope=scope, jobs_file=path.name), **counts())
                    elif code not in (0, EXIT_BLOCKED):
                        problems.append(f"{place}: the collector stopped with an error (exit code {code}).")
                    elif path is None:
                        problems.append(f"{place}: no jobs file was saved.")
                    if code == EXIT_BLOCKED:
                        blocked = True
                    if captured.get("interrupted"):
                        interrupted = True
                    # Search the same place again only when this pass hit its cap yet some postings could not be
                    # matched to a stored vacancy (a repeat under another id), so the target is still short.
                    again = (bool(target) and code == 0 and want is not None and len(latest) >= want and added > 0
                             and not reached() and rounds <= settings.COLLECTION_ROUNDS_PER_PLACE)
                    if not again:
                        break

            finished = self.now().isoformat(timespec="seconds")
            summary = dict(totals, scope=scope, jobs_file=None)
            extra = dict(counts(), result_at=finished if target else None)
            got = f"{len(result_keys)} of {target}" if target else str(totals["new"])
            if blocked:
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=n, stop_reason="blocked",
                             last_error="LinkedIn started refusing requests, so the run stopped early. "
                                        "Jobs collected before that were added. Try again later.",
                             message=f"Collection could not continue: LinkedIn refused further requests. Got {got} vacancies.", **extra)
            elif interrupted:
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=n, stop_reason="interrupted",
                             last_error="The collection was interrupted. Jobs saved before the interruption were added.",
                             message=f"Interrupted. The collection could not continue; got {got} vacancies.", **extra)
            elif timed_out:
                self._update(state=PARTIAL, step=None, finished_at=finished, last_summary=summary, search_done=n, stop_reason="time_limit",
                             last_error="The time limit was reached before the collection finished.",
                             message=f"Collection could not continue: time limit reached. Got {got} vacancies.", **extra)
            elif files == 0:
                raise RuntimeError("No jobs file was saved for any place. " + " ".join(problems[:3]) +
                                   " See the log lines below for the reason.")
            elif reached():
                self._update(state=SUCCEEDED, step=None, finished_at=finished, last_success_at=finished, last_summary=summary,
                             search_done=n + 1, stop_reason="target_reached", warnings=(self._s["warnings"] + problems)[:12],
                             message=(f"Target reached: the {len(result_keys)} most recent vacancies{within} are ready "
                                      f"({extra['new_added']} new to your history, {extra['already_had']} already collected)."), **extra)
            else:
                note = f" {len(problems)} place(s) had problems (see Details)." if problems else ""
                if target:
                    why = ("Some places could not be searched, so fewer vacancies were collected than requested."
                           if problems else
                           f"Results were exhausted: all {len(places)} search locations were searched and no more vacancies{within} were found.")
                    msg = f"Collected {len(result_keys)} of {target} requested vacancies{within}. {why}"
                else:
                    msg = f"Finished. {totals['new']} new vacancies, {totals['existing']} already in the history.{note}"
                self._update(state=SUCCEEDED, step=None, finished_at=finished, last_success_at=finished, last_summary=summary,
                             search_done=len(places), stop_reason="incomplete" if (target and problems) else "exhausted",
                             warnings=(self._s["warnings"] + problems)[:12], message=msg, **extra)
        except Exception as exc:
            log.exception("collection failed")
            self._update(state=FAILED, step=None, finished_at=self.now().isoformat(timespec="seconds"), stop_reason="error",
                         last_error=f"{type(exc).__name__}: {exc}"[:600], message="The collection did not finish.")
        finally:
            self._release_lock()
            with self._mutex:
                self._save(force=True)

    def _find_output(self, captured: dict[str, Any], started: float) -> Optional[Path]:
        if captured.get("file"):
            p = Path(captured["file"])
            p = p if p.is_absolute() else ROOT / p
            if p.exists():
                return p
        files = [p for p in self.output_dir.glob("jobs_*_*.json") if p.stat().st_mtime >= started - 1]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
