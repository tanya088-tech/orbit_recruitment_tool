from processing.employment import map_employment_type


def test_allowed_types_are_mapped():
    assert map_employment_type("Full-time").normalized == "Permanent"
    assert map_employment_type("Full time").normalized == "Permanent"
    assert map_employment_type("Contract").normalized == "Contract"
    assert map_employment_type("Full-time").passed and map_employment_type("Contract").passed


def test_other_types_excluded():
    for raw in ["Part-time", "Internship", "Temporary", "Volunteer", "Other", "Per diem"]:
        r = map_employment_type(raw)
        assert not r.passed and r.code == "employment_not_allowed", raw
        assert r.normalized is None


def test_missing_type_is_not_assumed_permanent():
    for raw in [None, "", "   "]:
        r = map_employment_type(raw)
        assert not r.passed and r.code == "employment_unavailable" and r.normalized is None
