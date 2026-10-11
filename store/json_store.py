"""JSON-file implementations of the two stores (a stand-in for a real database).

* Writes are atomic (temp file + rename), so a crash can't leave a half-written file.
* An unreadable file raises StoreError instead of being silently overwritten.
* Files are re-read when they change on disk, so running run_ingest.py while the
  dashboard is open just works.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from store.base import (DEFAULT_STATUS, MAX_NOTE_LENGTH, STATUSES, IngestResult,
                        JobHistoryStore, RecruiterStateStore, StoreError)
from store.keys import match_url, job_key

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class _JsonFile:
    def __init__(self, path: Any, default: Callable[[], dict]) -> None:
        self.path = Path(path)
        self.default = default
        self.lock = threading.RLock()
        self._cache: Optional[dict] = None
        self._token: Any = None

    def load(self) -> dict:
        with self.lock:
            try:
                st = self.path.stat()
            except FileNotFoundError:
                self._cache, self._token = None, None
                return self.default()
            token = (st.st_mtime_ns, st.st_size)
            if self._cache is None or token != self._token:
                try:
                    self._cache = json.loads(self.path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    raise StoreError(f"Cannot read {self.path}: {exc}. Fix or move the file; it was not overwritten.")
                self._token = token
            return self._cache

    def save(self, data: dict) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            st = self.path.stat()
            self._cache, self._token = data, (st.st_mtime_ns, st.st_size)


def _fill_missing(target: dict, newer: dict) -> None:
    """Later sightings may only fill gaps; they never overwrite what we first recorded."""
    for k, v in newer.items():
        if k in ("raw_data", "filter_results"):
            continue
        empty = target.get(k) in (None, "", [], {}) or (k == "work_mode" and target.get(k) == "Unknown")
        if empty and v not in (None, "", [], {}, "Unknown"):
            target[k] = copy.deepcopy(v)


class JsonJobHistory(JobHistoryStore):
    def __init__(self, path: Any) -> None:
        self._f = _JsonFile(path, lambda: {"version": 1, "runs": [], "jobs": {}})

    def ingest(self, records, source_file=None, source_hash=None, now=None, force=False) -> IngestResult:
        now = now or _utcnow()
        with self._f.lock:
            data = copy.deepcopy(self._f.load())
            result = IngestResult(total_in_file=len(records))

            if source_hash and not force and any(r.get("source_hash") == source_hash for r in data["runs"]):
                result.skipped_already_ingested = True
                return result

            taken = {r["run_id"] for r in data["runs"]}
            base = f"run_{now.astimezone(timezone.utc):%Y%m%d_%H%M%S}"
            run_id, n = base, 2
            while run_id in taken:
                run_id, n = f"{base}_{n}", n + 1
            result.run_id = run_id

            seen_in_file: set[str] = set()
            # A posting can reappear under another source with the same real URL. Index the stored URLs so
            # such a match is recognised as the SAME vacancy instead of becoming a second row.
            by_url: dict[str, str] = {}
            for existing_key, stored in data["jobs"].items():
                u = match_url(stored.get("record") or {})
                if u:
                    by_url.setdefault(u, existing_key)
            for rec in records:
                try:
                    key = job_key(rec)
                except (ValueError, AttributeError):
                    result.unidentifiable += 1
                    continue
                if key not in data["jobs"]:
                    twin = by_url.get(match_url(rec) or "")
                    if twin:
                        key = twin                      # same URL already stored under another source's key
                if key in seen_in_file:
                    result.duplicates_in_file += 1
                    continue
                seen_in_file.add(key)

                entry = data["jobs"].get(key)
                if entry is None:
                    data["jobs"][key] = {
                        "key": key, "first_seen_run_id": run_id, "first_ingested_at": _iso(now),
                        "last_seen_run_id": run_id, "last_seen_at": _iso(now), "times_seen": 1,
                        "record": copy.deepcopy(rec),
                    }
                    u = match_url(rec)
                    if u:
                        by_url.setdefault(u, key)
                    result.new += 1
                    result.new_keys.append(key)
                else:
                    entry["last_seen_run_id"], entry["last_seen_at"] = run_id, _iso(now)
                    entry["times_seen"] = entry.get("times_seen", 1) + 1
                    _fill_missing(entry["record"], rec)
                    result.existing += 1
                    result.existing_keys.append(key)

            data["runs"].append({
                "run_id": run_id, "ingested_at": _iso(now), "source_file": source_file, "source_hash": source_hash,
                "total_in_file": result.total_in_file, "new": result.new, "existing": result.existing,
                "duplicates_in_file": result.duplicates_in_file, "unidentifiable": result.unidentifiable,
                "new_keys": result.new_keys, "existing_keys": result.existing_keys,
            })
            self._f.save(data)
            return result

    def list_jobs(self):
        return list(self._f.load()["jobs"].values())

    def get_job(self, key):
        return self._f.load()["jobs"].get(key)

    def runs(self):
        return list(self._f.load()["runs"])

    def latest_run(self):
        runs = self._f.load()["runs"]
        return runs[-1] if runs else None


class JsonRecruiterState(RecruiterStateStore):
    def __init__(self, path: Any, now_fn: Callable[[], datetime] = _utcnow) -> None:
        self._f = _JsonFile(path, lambda: {"version": 1, "jobs": {}})
        self._now = now_fn

    @staticmethod
    def _blank() -> dict[str, Any]:
        return {"saved": False, "saved_at": None, "status": DEFAULT_STATUS, "notes": [], "updated_at": None}

    def get(self, key):
        self._check_key(key)
        entry = self._f.load()["jobs"].get(key)
        return copy.deepcopy(entry) if entry else self._blank()

    def get_all(self):
        return copy.deepcopy(self._f.load()["jobs"])

    @staticmethod
    def _check_key(key: str) -> None:
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise StoreError("invalid job key")

    def _mutate(self, key: str, fn: Callable[[dict], None]) -> dict[str, Any]:
        self._check_key(key)
        with self._f.lock:
            data = copy.deepcopy(self._f.load())
            entry = data["jobs"].setdefault(key, self._blank())
            fn(entry)
            entry["updated_at"] = _iso(self._now())
            self._f.save(data)
            return copy.deepcopy(entry)

    def set_saved(self, key, saved):
        def fn(e):
            e["saved"] = bool(saved)
            e["saved_at"] = _iso(self._now()) if saved else None
        return self._mutate(key, fn)

    def set_status(self, key, status):
        if status not in STATUSES:
            raise StoreError(f"invalid status {status!r}; choose one of: {', '.join(STATUSES)}")
        return self._mutate(key, lambda e: e.__setitem__("status", status))

    def add_note(self, key, text):
        text = (text or "").strip()
        if not text:
            raise StoreError("note is empty")
        if len(text) > MAX_NOTE_LENGTH:
            raise StoreError(f"note is too long (max {MAX_NOTE_LENGTH} characters)")
        note = {"id": uuid.uuid4().hex[:10], "text": text, "created_at": _iso(self._now())}
        return self._mutate(key, lambda e: e["notes"].append(note))

    def delete_note(self, key, note_id):
        def fn(e):
            e["notes"] = [n for n in e["notes"] if n.get("id") != note_id]
        return self._mutate(key, fn)
