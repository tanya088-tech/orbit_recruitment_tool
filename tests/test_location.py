from processing.location import check_location


def test_india_variants_pass():
    for loc in ["Bengaluru, Karnataka, India", "Bangalore", "Gurugram, Haryana, India", "Gurgaon",
                "Remote - India", "India (Remote)", "Hybrid - Pune", "India", "Greater Delhi Area",
                "Kochi, Kerala, India", "Noida, Uttar Pradesh", "Pune, MH, IN", "Navi Mumbai",
                "Ahmedabad", "Jaipur, Rajasthan", "Kolkata, West Bengal, India", "Chennai"]:
        r = check_location(loc)
        assert r.is_india and r.country == "India", loc


def test_remote_and_hybrid_flags():
    assert check_location("Remote - India").is_remote_or_hybrid
    assert check_location("Hybrid - Pune").is_remote_or_hybrid
    assert not check_location("Pune, India").is_remote_or_hybrid


def test_foreign_and_lookalike_places_fail():
    for loc, country in [("Hyderabad, Sindh, Pakistan", "Pakistan"), ("Salem, Oregon, United States", "United States"),
                         ("London, United Kingdom", "United Kingdom"), ("Dubai, United Arab Emirates", "United Arab Emirates"),
                         ("Singapore", "Singapore"), ("Kochi, Japan", "Japan")]:
        r = check_location(loc)
        assert not r.is_india and r.code == "location_not_india", loc
        if country:
            assert r.country == country, (loc, r.country)


def test_bare_remote_and_missing_fail():
    assert not check_location("Remote").is_india
    assert check_location(None).code == "location_unavailable"
    assert check_location("  ").code == "location_unavailable"
