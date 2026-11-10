"""Rate limits, retries, timeouts and partial failure."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests
from fastapi.testclient import TestClient

import main
from api.app import app
from fake_github import FakeGitHub, list_item, response
from fork_sync.github import GitHubClient, GitHubRateLimitError
from fork_sync.synchronizer import ForkSynchronizer, has_failures

TOKEN = "SECRET-TEST-TOKEN-91c2"
NOW = 1_000_000


def limited(status=403, wait=3600, **headers):
    values = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(NOW + wait), **headers}
    return response(status, {"message": "API rate limit exceeded"}, values)


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setattr("fork_sync.github.time.time", lambda: NOW)
    return FakeGitHub().install(monkeypatch)


@pytest.fixture
def client():
    return GitHubClient(TOKEN)


def post(payload):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        return test_client.post(
            "/api/sync", json=payload, headers={"Authorization": f"Bearer {TOKEN}"}
        )


def fail_listing(github, *pages):
    github.pages = [list(pages)]


# Detection and wait calculation

@pytest.mark.parametrize(
    "reply",
    [
        response(429, {"message": "slow down"}),
        response(403, {"message": "x"}, {"x-ratelimit-remaining": "0"}),
        response(403, {"message": "x"}, {"Retry-After": "999"}),
        response(403, {"message": "You have exceeded a secondary rate limit"}),
    ],
)
def test_rate_limit_responses_are_detected(github, client, reply):
    fail_listing(github, reply)

    with pytest.raises(GitHubRateLimitError):
        client.get_authenticated_user() and client.list_repositories()


def test_permission_403_is_not_a_rate_limit(github, client):
    fail_listing(github, response(403, {"message": "Resource not accessible"}))

    with pytest.raises(requests.HTTPError):
        client.list_repositories()
    assert github.count("GET", "/user/repos") == 1


def test_short_retry_after_is_honoured_for_reads(github, client, sleeps):
    fail_listing(github, response(429, {}, {"Retry-After": "7"}), (200, []))

    assert client.list_repositories() == []
    assert sleeps == [7]


def test_short_reset_is_honoured_for_reads(github, client, sleeps):
    fail_listing(github, limited(wait=10), (200, []))

    assert client.list_repositories() == []
    assert sleeps == [11]


def test_retry_after_takes_priority_over_reset(github, client, sleeps):
    fail_listing(github, limited(wait=30, **{"Retry-After": "2"}), (200, []))

    client.list_repositories()

    assert sleeps == [2]


def test_http_date_retry_after_is_understood(github, client, sleeps):
    moment = datetime.now(timezone.utc) + timedelta(seconds=30)
    fail_listing(github, response(429, {}, {"Retry-After": format_datetime(moment)}), (200, []))

    client.list_repositories()

    assert 25 <= sleeps[0] <= 31


def test_secondary_limit_without_timing_waits_a_minute(github, client, sleeps):
    fail_listing(github, response(403, {"message": "secondary rate limit"}), (200, []))

    client.list_repositories()

    assert sleeps == [60]


@pytest.mark.parametrize("bad", ["soon", ""])
def test_malformed_timing_headers_fall_back_safely(github, client, sleeps, bad):
    headers = {"Retry-After": bad, "x-ratelimit-remaining": "0", "x-ratelimit-reset": "later"}
    fail_listing(github, response(429, {}, headers), (200, []))

    client.list_repositories()

    assert sleeps == [60]


def test_long_wait_fails_immediately_with_retry_time(github, client, sleeps):
    fail_listing(github, limited(wait=3600))

    with pytest.raises(GitHubRateLimitError) as caught:
        client.list_repositories()

    assert sleeps == []
    assert caught.value.retry_after == 3601
    assert "3601 seconds" in str(caught.value)


def test_read_is_retried_only_once_for_rate_limits(github, client, sleeps):
    fail_listing(github, response(429, {}, {"Retry-After": "1"}))

    with pytest.raises(GitHubRateLimitError):
        client.list_repositories()

    assert github.count("GET", "/user/repos") == 2


# Transient failures

@pytest.mark.parametrize(
    "failure",
    [requests.exceptions.ReadTimeout("t"), requests.exceptions.ConnectionError("c"), 502, 503, 504],
)
def test_transient_read_failures_are_retried_with_backoff(github, client, sleeps, failure):
    fail_listing(github, failure, failure, (200, []))

    assert client.list_repositories() == []
    assert sleeps == [1, 2]


@pytest.mark.parametrize(
    "failure, expected",
    [
        (requests.exceptions.ReadTimeout("t"), requests.exceptions.ReadTimeout),
        (503, requests.HTTPError),
    ],
)
def test_transient_read_failures_eventually_raise(github, client, failure, expected):
    fail_listing(github, failure)

    with pytest.raises(expected):
        client.list_repositories()

    assert github.count("GET", "/user/repos") == 3


@pytest.mark.parametrize("status", [400, 401, 404, 422, 500])
def test_non_transient_read_failures_are_not_retried(github, client, status):
    fail_listing(github, status)

    with pytest.raises(requests.HTTPError):
        client.list_repositories()

    assert github.count("GET", "/user/repos") == 1


def test_every_request_has_a_timeout(monkeypatch):
    seen = []

    def capture(_session, method, url, **kwargs):
        seen.append(kwargs.get("timeout"))
        return response(200, {"login": "demo"})

    monkeypatch.setattr(requests.Session, "request", capture)
    GitHubClient(TOKEN).get_authenticated_user()

    assert seen == [30]


# Merges are never repeated

@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ReadTimeout("t"),
        requests.exceptions.ConnectionError("c"),
        502,
        503,
        response(429, {}, {"Retry-After": "1"}),
        limited(wait=1),
    ],
)
def test_merge_requests_are_never_retried(github, client, sleeps, failure):
    name = github.add_fork("x", compare=(0, 2), merge=failure)

    ForkSynchronizer(client).sync_fork(github.details[name])

    assert len(github.merged) == 1
    assert sleeps == []


def test_rate_limited_merge_is_reported(github, client):
    name = github.add_fork("x", compare=(0, 2), merge=limited())

    result = ForkSynchronizer(client).sync_fork(github.details[name])

    assert result["status"] == "rate-limited"
    assert "Merge refused" in result["message"]
    assert has_failures([result])


# Stopping and partial failure

def test_preview_stops_requesting_after_rate_limit(github, client):
    names = [github.add_fork(f"r{i}", compare=(0, 1)) for i in range(4)]
    github.compares[names[1]] = limited()

    results = ForkSynchronizer(client).preview_all([github.details[n] for n in names])

    assert [r["status"] for r in results] == ["behind", "rate-limited", "rate-limited", "rate-limited"]
    assert results[2]["message"].startswith("Not attempted:")
    assert github.count("GET", "/compare/") == 2


def test_sync_stops_merging_after_rate_limit_and_reports_partial_result(github, client):
    names = [github.add_fork(f"r{i}", compare=(0, 1)) for i in range(3)]
    github.merges[names[1]] = limited()

    results = ForkSynchronizer(client).sync_all([github.details[n] for n in names])

    assert [r["status"] for r in results] == ["synced", "rate-limited", "rate-limited"]
    assert github.merged == [names[0], names[1]]
    assert has_failures(results)


def test_discovery_stops_loading_details_after_rate_limit(github, client):
    names = [github.add_fork(f"r{i}") for i in range(3)]
    github.details[names[1]] = limited()

    discovery = ForkSynchronizer(client).discover_forks()

    assert [fork["full_name"] for fork in discovery.forks] == [names[0]]
    assert [result["status"] for result in discovery.skipped] == ["rate-limited", "rate-limited"]
    assert github.count("GET", f"/repos/{names[2]}") == 0


def test_ordinary_error_does_not_stop_other_forks(github, client):
    names = [github.add_fork("a", compare=404), github.add_fork("b", compare=(0, 1))]

    results = ForkSynchronizer(client).sync_all([github.details[n] for n in names])

    assert [r["status"] for r in results] == ["error", "synced"]


def test_cli_reports_listing_rate_limit(github, capsys):
    fail_listing(github, limited())

    assert main.main(["--dry-run"]) == 1
    assert "rate limit" in capsys.readouterr().err


def test_cli_reports_partial_failure(github, capsys):
    github.add_fork("a", compare=(0, 0))
    github.add_fork("b", compare=limited())

    assert main.main(["--dry-run"]) == 1
    output = capsys.readouterr().out
    assert "1 up-to-date, 1 rate-limited" in output
    assert "Completed with problems" in output


def test_web_returns_429_with_retry_after_for_listing(github):
    fail_listing(github, limited())

    reply = post({"dry_run": True})

    assert reply.status_code == 429
    assert reply.headers["Retry-After"] == "3601"


def test_web_preview_reports_partial_rate_limit(github):
    github.add_fork("a", compare=(0, 0))
    github.add_fork("b", compare=limited())

    body = post({"dry_run": True}).json()

    assert body["summary"] == {"up-to-date": 1, "rate-limited": 1}
    assert body["has_failures"] is True


def test_web_live_refuses_when_discovery_was_rate_limited(github):
    github.add_fork("a", compare=(0, 1))
    github.add_fork("b", details=limited())

    # Live sync looks up only the selection, so the selected fork must be the
    # one whose lookup is rate limited.
    reply = post({"dry_run": False, "confirmation": "SYNC", "repositories": ["demo/a", "demo/b"]})

    assert reply.status_code == 429
    assert github.merged == []


# Other

def test_branch_names_are_encoded_in_compare_urls(github, client):
    github.compares["demo/x"] = (0, 0)
    client.compare_upstream("demo/x", "up/x", "fea#t/1", "fea#t/1")

    assert github.calls[-1][1].endswith("/compare/up:fea%23t/1...demo:fea%23t/1")


def test_token_never_appears_in_output(github, capsys, monkeypatch):
    github.add_fork("a", compare=500)
    github.add_fork("b", compare=(0, 1), merge=500)
    github.add_fork("c", details=500)
    github.listing.append(list_item("demo/odd", fork="?"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "SYNC")

    main.main([])
    captured = capsys.readouterr()
    web = post({"dry_run": True}).text

    assert github.merged == ["demo/b"]
    assert TOKEN not in captured.out + captured.err + web
