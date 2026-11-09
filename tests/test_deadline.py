"""The overall time limit, driven by a controlled clock. Nothing waits in real time."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

import main
from api import routes
from api.app import app
from fake_github import FakeGitHub, response
from fork_sync.deadline import (
    DEFAULT_CLI_TIME_LIMIT,
    DEFAULT_WEB_TIME_LIMIT,
    Deadline,
    DeadlineExceeded,
    parse_time_limit,
)
from fork_sync.github import GitHubClient, GitHubRateLimitError
from fork_sync.synchronizer import ForkSynchronizer, has_failures


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr("fork_sync.deadline._now", fake)
    return fake


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return FakeGitHub().install(monkeypatch)


def costs(github, clock, get=10, post=10):
    """Make every request take a fixed amount of controlled time."""
    def advance(method, _url):
        clock.now += post if method == "POST" else get
    github.on_request = advance


def client_with(seconds):
    client = GitHubClient("test-token")
    client.deadline = Deadline(seconds)
    return client


class Drip:
    """A response body that arrives one byte per second of controlled time."""

    def __init__(self, clock, body):
        self.clock = clock
        self.body = body
        self.reads = 0

    def read(self, _size=-1):
        if not self.body:
            return b""
        self.reads += 1
        self.clock.now += 1
        chunk, self.body = self.body[:1], self.body[1:]
        return chunk

    def close(self):
        pass


def dripping(clock, body):
    reply = requests.Response()
    reply.status_code = 200
    reply.raw = Drip(clock, body)
    return reply


# The deadline itself


def test_deadline_counts_down_with_its_clock(clock):
    deadline = Deadline(10)
    clock.now = 4

    assert deadline.remaining() == 6
    assert not deadline.expired()
    clock.now = 10
    assert deadline.expired()


@pytest.mark.parametrize("value", ["0", "-5", "nan", "inf", "soon", ""])
def test_invalid_time_limits_are_rejected(value):
    with pytest.raises(ValueError):
        parse_time_limit(value)


def test_defaults_are_thirty_minutes_for_cli_and_five_for_web():
    assert DEFAULT_CLI_TIME_LIMIT == 1800
    assert DEFAULT_WEB_TIME_LIMIT == 300
    assert main.build_parser().parse_args([]).time_limit == 1800


def test_deadline_is_distinct_from_a_request_timeout():
    assert not issubclass(DeadlineExceeded, requests.exceptions.RequestException)


# Requests


def test_reads_never_wait_longer_than_the_time_left(github, clock):
    client_with(12).get_authenticated_user()
    client_with(100).get_authenticated_user()

    assert github.timeouts == [12, 30]


def test_no_request_starts_after_the_deadline(github, clock):
    client = client_with(5)
    clock.now = 5

    with pytest.raises(DeadlineExceeded, match="5 seconds"):
        client.get_authenticated_user()

    assert github.calls == []


def test_retry_wait_that_would_overrun_stops_instead(github, clock, sleeps):
    github.pages = [[502, 502, (200, [])]]

    with pytest.raises(DeadlineExceeded, match="before a retry"):
        client_with(1.5).list_repositories()

    assert sleeps == [1]
    assert github.count("GET", "/user/repos") == 2


def test_rate_limit_wait_longer_than_time_left_is_reported_without_waiting(github, clock, sleeps):
    github.pages = [response(429, {}, {"Retry-After": "10"})]

    with pytest.raises(GitHubRateLimitError):
        client_with(5).list_repositories()

    assert sleeps == []


def test_slow_response_body_is_cut_off_at_the_deadline(github, clock):
    drip = Drip(clock, b"[" + b" " * 100 + b"]")
    reply = requests.Response()
    reply.status_code = 200
    reply.raw = drip
    github.pages = [reply]

    with pytest.raises(DeadlineExceeded, match="while reading"):
        client_with(5).list_repositories()

    assert drip.reads <= 6


def test_merge_is_not_sent_without_enough_time_to_finish(github, clock):
    name = github.add_fork("x", compare=(0, 2))

    result = ForkSynchronizer(client_with(29)).sync_fork(github.details[name])

    assert result["status"] == "deadline-exceeded"
    assert result["message"].startswith("Merge not sent")
    assert github.merged == []
    assert has_failures([result])


def test_merge_gets_its_full_timeout_and_complete_reply(github, clock):
    name = github.add_fork("x", compare=(0, 2))
    github.merges[name] = dripping(clock, b'{"merge_type": "fast-forward"}' + b" " * 10)

    result = ForkSynchronizer(client_with(31)).sync_fork(github.details[name])

    assert github.timeouts[-1] == 30
    assert result["status"] == "synced"
    assert clock.now > 31  # The reply finished arriving after the deadline.


# Runs


def test_preview_stops_at_the_deadline_and_reports_the_rest(github, clock):
    names = [github.add_fork(f"r{i}", compare=(0, 1)) for i in range(5)]
    costs(github, clock)

    # Requests run 0-10, 10-20, 20-30 and 30-40; the fourth reply arrives after
    # the 35-second limit and is discarded, and the fifth is never sent.
    results = ForkSynchronizer(client_with(35)).preview_all([github.details[n] for n in names])

    assert [r["status"] for r in results] == ["behind"] * 3 + ["deadline-exceeded"] * 2
    assert results[3]["message"].startswith("Overall time limit")
    assert results[4]["message"].startswith("Not attempted:")
    assert github.count("GET", "/compare/") == 4


def test_sync_keeps_finished_merges_and_sends_no_more(github, clock):
    names = [github.add_fork(f"r{i}", compare=(0, 1)) for i in range(4)]
    costs(github, clock)

    results = ForkSynchronizer(client_with(75)).sync_all([github.details[n] for n in names])

    assert [r["status"] for r in results] == [
        "synced", "synced", "deadline-exceeded", "deadline-exceeded",
    ]
    assert results[2]["message"].startswith("Merge not sent")
    assert github.merged == names[:2]


def test_unconfirmed_merge_at_the_deadline_is_unknown_and_not_retried(github, clock):
    first = github.add_fork("a", compare=(0, 1), merge=requests.exceptions.ReadTimeout("t"))
    second = github.add_fork("b", compare=(0, 1))
    costs(github, clock, get=10, post=40)

    results = ForkSynchronizer(client_with(45)).sync_all(
        [github.details[first], github.details[second]]
    )

    assert [r["status"] for r in results] == ["unknown", "deadline-exceeded"]
    assert "could not be checked" in results[0]["message"]
    assert github.merged == [first]


def test_discovery_reports_forks_it_had_no_time_to_load(github, clock):
    for i in range(4):
        github.add_fork(f"r{i}")
    costs(github, clock)

    # Listing 0-10, r0 10-20, r1 20-30, r2 30-40 (past the limit), r3 never sent.
    discovery = ForkSynchronizer(client_with(35)).discover_forks()

    assert [f["full_name"] for f in discovery.forks] == ["demo/r0", "demo/r1"]
    assert [s["status"] for s in discovery.skipped] == ["deadline-exceeded"] * 2
    assert discovery.skipped[1]["message"].startswith("Not checked:")


def test_request_timeout_is_still_reported_as_an_error(github, clock):
    name = github.add_fork("x", compare=requests.exceptions.ReadTimeout("read timed out"))

    result = ForkSynchronizer(client_with(1000)).sync_fork(github.details[name])

    assert result["status"] == "error"
    assert "Overall time limit" not in result["message"]


# CLI and web


def test_cli_reports_deadline_during_listing(github, clock, capsys):
    costs(github, clock, get=20)

    assert main.main(["--dry-run", "--time-limit", "15"]) == 1

    error = capsys.readouterr().err
    assert "Overall time limit of 15 seconds reached" in error
    assert "Unexpected" not in error


def test_cli_live_run_reports_partial_results(github, clock, capsys, monkeypatch):
    for i in range(3):
        github.add_fork(f"r{i}", compare=(0, 1))
    monkeypatch.setattr("builtins.input", lambda _prompt: "SYNC")
    costs(github, clock, get=1, post=1)
    # Slow down only the merges, once the prompt has been answered.
    github.on_request = lambda method, _url: setattr(
        clock, "now", clock.now + (40 if method == "POST" else 1)
    )

    assert main.main(["--time-limit", "100"]) == 1

    output = capsys.readouterr().out
    assert "deadline-exceeded" in output
    assert len(github.merged) == 2


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "inf"])
def test_cli_rejects_invalid_time_limits(bad, capsys):
    with pytest.raises(SystemExit):
        main.build_parser().parse_args(["--time-limit", bad])


def post(payload):
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            "/api/sync", json=payload, headers={"Authorization": "Bearer test-token"}
        )


def test_web_returns_504_when_listing_runs_out_of_time(github, clock, monkeypatch):
    monkeypatch.setattr(routes, "WEB_TIME_LIMIT", 15)
    costs(github, clock, get=20)

    reply = post({"dry_run": True})

    assert reply.status_code == 504
    assert "Overall time limit of 15 seconds" in reply.json()["detail"]


def test_web_preview_reports_forks_left_unchecked(github, clock, monkeypatch):
    monkeypatch.setattr(routes, "WEB_TIME_LIMIT", 45)
    for i in range(4):
        github.add_fork(f"r{i}", compare=(0, 1))
    costs(github, clock)

    body = post({"dry_run": True}).json()

    assert body["has_failures"] is True
    assert body["summary"]["deadline-exceeded"] >= 1


def test_web_live_refuses_when_lookup_runs_out_of_time(github, clock, monkeypatch):
    monkeypatch.setattr(routes, "WEB_TIME_LIMIT", 15)
    name = github.add_fork("x", compare=(0, 1))
    costs(github, clock)

    reply = post({"dry_run": False, "confirmation": "SYNC", "repositories": [name]})

    assert reply.status_code == 504
    assert "Nothing was merged" in reply.json()["detail"]
    assert github.merged == []


@pytest.mark.parametrize("value, ok", [("120", True), ("0", False), ("soon", False)])
def test_web_time_limit_is_validated_at_startup(value, ok, tmp_path):
    root = Path(__file__).resolve().parent.parent
    # Inherit the normal environment so the interpreter writes nothing into the
    # repository; only the setting under test changes.
    env = {
        key: item for key, item in os.environ.items()
        if key not in {"GITHUB_TOKEN", "GH_TOKEN", "NETRC"}
    }
    env.update({"DREAMEROL_WEB_TIME_LIMIT": value, "PYTHONDONTWRITEBYTECODE": "1"})
    run = subprocess.run(
        [sys.executable, "-B", "-c", "import api.routes as r; print(r.WEB_TIME_LIMIT)"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert (run.returncode == 0) is ok
    if ok:
        assert run.stdout.strip() == "120.0"
    else:
        assert "Time limit must be" in run.stderr or "could not convert" in run.stderr
