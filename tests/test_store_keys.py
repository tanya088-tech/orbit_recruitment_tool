from store.keys import job_key, normalize_job_url


def test_job_id_is_the_preferred_identifier():
    assert job_key({"source": "LinkedIn", "job_id": "4438121997", "job_url": "https://x.com/other"}) == "linkedin-4438121997"
    assert job_key({"source": "LinkedIn", "job_id": 4438121997}) == "linkedin-4438121997"


def test_url_normalization_ignores_tracking_and_regional_domains():
    a = normalize_job_url("https://in.linkedin.com/jobs/view/senior-analyst-at-acme-bank-4001111111?position=1&refId=abc")
    b = normalize_job_url("https://www.linkedin.com/jobs/view/4001111111/")
    c = normalize_job_url("http://uk.linkedin.com/jobs/view/4001111111?trackingId=zzz#frag")
    assert a == b == c == "https://www.linkedin.com/jobs/view/4001111111"


def test_job_without_id_uses_normalized_url_and_matches_id_based_key_for_linkedin():
    with_id = job_key({"source": "LinkedIn", "job_id": "4001111111"})
    url_only = job_key({"source": "LinkedIn", "job_url": "https://in.linkedin.com/jobs/view/foo-bar-4001111111?x=1"})
    assert with_id == url_only            # the same posting can never become two vacancies


def test_non_linkedin_url_fallback_is_stable():
    k1 = job_key({"source": "Other", "job_url": "https://careers.example.com/jobs/12/?utm=a"})
    k2 = job_key({"source": "Other", "job_url": "https://CAREERS.example.com/jobs/12"})
    assert k1 == k2 and k1.startswith("other-url-")


def test_same_id_from_different_sources_does_not_collide():
    assert job_key({"source": "LinkedIn", "job_id": "123456"}) != job_key({"source": "Naukri", "job_id": "123456"})


def test_unidentifiable_job_raises():
    for rec in [{"source": "LinkedIn"}, {"source": "LinkedIn", "job_url": "not a url"},
                {"source": "LinkedIn", "job_url": "javascript:alert(1)"}, {"source": "LinkedIn", "job_id": "   "}]:
        try:
            job_key(rec)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {rec}")


def test_bad_urls_normalize_to_none():
    for url in [None, "", "   ", "ftp://x.com/a", "javascript:alert(1)", "//no-scheme.com/a"]:
        assert normalize_job_url(url) is None
