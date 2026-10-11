from pathlib import Path

import pytest

from collectors.collector import Collector
from collectors.errors import BlockedError, FetchError, NotFoundError
from collectors.linkedin.client import HttpClient
from collectors.linkedin.source import LinkedInSource
from collectors.registry import available_sources, get_source
from models.job import SearchParams

FIX = Path(__file__).parent / "fixtures"
read = lambda name: (FIX / name).read_text(encoding="utf-8")


class FakeClient:
    """Stands in for HttpClient so tests never touch the network."""
    def __init__(self, detail_behaviour):
        self.detail_behaviour = detail_behaviour   # job_id -> html or Exception
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)
        if "seeMoreJobPostings" in url:
            return read("search_results.html") if params["start"] == 0 else "<html></html>"
        job_id = url.rsplit("/", 1)[-1]
        result = self.detail_behaviour[job_id]
        if isinstance(result, Exception):
            raise result
        return result


def run(client, **kw):
    params = SearchParams(keywords="bank", location="India", days=kw.pop("days", 30), **kw)
    return Collector(LinkedInSource(client)).run([params])


def test_happy_path_collects_all():
    client = FakeClient({"4001111111": read("job_detail_ld.html"), "4002222222": read("job_detail_html.html")})
    res = run(client)
    assert res.stats.found == 2 and res.stats.collected == 2 and res.stats.failed == 0
    assert {j.job_id for j in res.jobs} == {"4001111111", "4002222222"}
    assert all(j.source == "LinkedIn" for j in res.jobs)


def test_one_failed_job_does_not_stop_the_run(tmp_path):
    client = FakeClient({"4001111111": NotFoundError("HTTP 404"), "4002222222": read("job_detail_html.html")})
    res = Collector(LinkedInSource(client)).run(
        [SearchParams(keywords="bank", days=30)], output_dir=tmp_path)
    assert res.stats.collected == 1 and res.stats.failed == 1
    assert res.stats.failures[0]["url"].endswith("4001111111")
    assert res.output_file and res.output_file.exists()


def test_block_stops_run_but_keeps_earlier_jobs():
    client = FakeClient({"4001111111": read("job_detail_ld.html"), "4002222222": BlockedError("HTTP 429")})
    res = run(client)
    assert res.stats.blocked is True
    assert len(res.jobs) == 1


def test_max_jobs_cap_and_duplicate_skipping():
    client = FakeClient({"4001111111": read("job_detail_ld.html"), "4002222222": read("job_detail_html.html")})
    res = run(client, max_jobs=1)
    assert res.stats.collected == 1

    # same job found by a second search must not be fetched twice
    client2 = FakeClient({"4001111111": read("job_detail_ld.html"), "4002222222": read("job_detail_html.html")})
    p = SearchParams(keywords="bank", days=30)
    res2 = Collector(LinkedInSource(client2)).run([p, p])
    assert res2.stats.collected == 2 and res2.stats.skipped_duplicate == 2


def test_date_range_trimming():
    client = FakeClient({"4001111111": read("job_detail_ld.html"), "4002222222": read("job_detail_html.html")})
    res = run(client, days=1)   # fixtures are dated 2026 (past) -> out of range
    assert res.stats.skipped_out_of_range >= 1


class _Resp:
    def __init__(self, status, url="https://x", text="ok", headers=None):
        self.status_code, self.url, self.text, self.headers = status, url, text, headers or {}

class _Session:
    def __init__(self, responses): self.responses, self.headers = list(responses), {}
    def get(self, *a, **k): return self.responses.pop(0)


def make_client(responses):
    return HttpClient(delay_min=0, delay_max=0, backoff_base=0, session=_Session(responses), sleep=lambda s: None)

def test_client_retries_then_succeeds():
    assert make_client([_Resp(500), _Resp(200, text="hello")]).get("https://x") == "hello"

def test_client_429_raises_blocked_after_retries():
    with pytest.raises(BlockedError):
        make_client([_Resp(429)] * 3).get("https://x")

def test_client_login_wall_is_blocked_immediately():
    with pytest.raises(BlockedError):
        make_client([_Resp(200, url="https://www.linkedin.com/authwall?x=1")]).get("https://x")

def test_client_404_not_found():
    with pytest.raises(NotFoundError):
        make_client([_Resp(404)]).get("https://x")

def test_registry_has_linkedin():
    assert "linkedin" in available_sources()
    assert isinstance(get_source("linkedin"), LinkedInSource)
