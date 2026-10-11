from datetime import timedelta

from tests.factories import NOW
from store.base import MAX_NOTE_LENGTH, STATUSES, StoreError
from store.json_store import JsonRecruiterState

KEY = "linkedin-1001"


def raises(fn, *args):
    try:
        fn(*args)
    except StoreError:
        return True
    return False


def test_defaults_for_unknown_job_and_nothing_written(tmp_path):
    path = tmp_path / "s.json"
    s = JsonRecruiterState(path, now_fn=lambda: NOW)
    assert s.get(KEY) == {"saved": False, "saved_at": None, "status": "New", "notes": [], "updated_at": None}
    assert not path.exists()


def test_save_and_unsave(tmp_path):
    s = JsonRecruiterState(tmp_path / "s.json", now_fn=lambda: NOW)
    assert s.set_saved(KEY, True)["saved"] is True and s.get(KEY)["saved_at"] is not None
    assert s.set_saved(KEY, False)["saved"] is False and s.get(KEY)["saved_at"] is None


def test_all_seven_statuses_are_accepted_and_others_rejected(tmp_path):
    assert STATUSES == ["New", "Reviewing", "Candidate Search Started", "Candidate Found", "Submitted", "Closed", "Not Relevant"]
    s = JsonRecruiterState(tmp_path / "s.json", now_fn=lambda: NOW)
    for status in STATUSES:
        assert s.set_status(KEY, status)["status"] == status
    assert raises(s.set_status, KEY, "Hired")
    assert raises(s.set_status, KEY, "")
    assert s.get(KEY)["status"] == "Not Relevant"          # unchanged by the rejected values


def test_notes_add_trim_validate_delete(tmp_path):
    clock = {"t": NOW}
    s = JsonRecruiterState(tmp_path / "s.json", now_fn=lambda: clock["t"])
    n1 = s.add_note(KEY, "  Called the hiring manager  ")["notes"][0]
    assert n1["text"] == "Called the hiring manager" and n1["id"] and n1["created_at"]
    clock["t"] = NOW + timedelta(minutes=5)
    s.add_note(KEY, "Second note")
    assert [n["text"] for n in s.get(KEY)["notes"]] == ["Called the hiring manager", "Second note"]
    assert raises(s.add_note, KEY, "   ") and raises(s.add_note, KEY, "x" * (MAX_NOTE_LENGTH + 1))
    s.delete_note(KEY, n1["id"])
    assert [n["text"] for n in s.get(KEY)["notes"]] == ["Second note"]
    s.delete_note(KEY, "doesnotexist")                      # harmless
    assert len(s.get(KEY)["notes"]) == 1


def test_everything_persists_across_restart(tmp_path):
    path = tmp_path / "s.json"
    s = JsonRecruiterState(path, now_fn=lambda: NOW)
    s.set_saved(KEY, True); s.set_status(KEY, "Reviewing"); s.add_note(KEY, "remember me")
    again = JsonRecruiterState(path).get(KEY)
    assert again["saved"] and again["status"] == "Reviewing" and again["notes"][0]["text"] == "remember me"


def test_invalid_keys_rejected(tmp_path):
    s = JsonRecruiterState(tmp_path / "s.json")
    for bad in ["", "../etc/passwd", "a b", "x" * 200, None]:
        assert raises(s.set_saved, bad, True)
