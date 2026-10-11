"""Storage interfaces for Phase 3.

The dashboard only talks to these two abstract classes. Today they are backed by JSON
files (store/json_store.py). To move to SQLite/Postgres later, write new classes that
implement the same methods and swap them in run_dashboard.py / run_ingest.py - nothing
else changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

STATUSES = [
    "New", "Reviewing", "Candidate Search Started", "Candidate Found",
    "Submitted", "Closed", "Not Relevant",
]
DEFAULT_STATUS = "New"
MAX_NOTE_LENGTH = 2000


class StoreError(Exception):
    """Raised for unreadable files or invalid input (bad status, empty note, bad key)."""


@dataclass
class IngestResult:
    run_id: Optional[str] = None
    total_in_file: int = 0
    new: int = 0
    existing: int = 0
    duplicates_in_file: int = 0       # same job twice inside ONE file
    unidentifiable: int = 0           # no job_id and no usable URL
    skipped_already_ingested: bool = False
    new_keys: list[str] = field(default_factory=list)
    existing_keys: list[str] = field(default_factory=list)


class JobHistoryStore(ABC):
    """Every vacancy the system has ever accepted, plus a log of ingest runs."""

    @abstractmethod
    def ingest(self, records: list[dict[str, Any]], source_file: Optional[str] = None,
               source_hash: Optional[str] = None, now: Any = None, force: bool = False) -> IngestResult: ...

    @abstractmethod
    def list_jobs(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_job(self, key: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def latest_run(self) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def runs(self) -> list[dict[str, Any]]: ...


class RecruiterStateStore(ABC):
    """Per-vacancy recruiter data: saved flag, workflow status, notes."""

    @abstractmethod
    def get(self, key: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_all(self) -> dict[str, dict[str, Any]]: ...

    @abstractmethod
    def set_saved(self, key: str, saved: bool) -> dict[str, Any]: ...

    @abstractmethod
    def set_status(self, key: str, status: str) -> dict[str, Any]: ...

    @abstractmethod
    def add_note(self, key: str, text: str) -> dict[str, Any]: ...

    @abstractmethod
    def delete_note(self, key: str, note_id: str) -> dict[str, Any]: ...
