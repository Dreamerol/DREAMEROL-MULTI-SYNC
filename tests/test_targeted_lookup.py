"""--repo and web live sync look up only the selected forks."""

import pytest
import requests
from fastapi.testclient import TestClient

import main
from api.app import app
from fake_github import FakeGitHub, full_repository, response
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return FakeGitHub().install(monkeypatch)


def detail_requests(github):
    return [
        url.split("/repos/")[1]
        for method, url in github.calls
        if method == "GET" and "/repos/" in url and "/compare/" not in url
        and "/branches/" not in url and not url.endswith("/user/repos")
    ]


def cli(*argv):
    return main.main(["--dry-run", *argv])


def post(payload):
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            "/api/sync", json=payload, headers={"Authorization": "Bearer test-token"}
        )


def live(names):
    return post({"dry_run": False, "confirmation": "SYNC", "repositories": names})


def test_one_selection_does_not_load_every_fork(github, capsys):
    for i in range(300):
        github.add_fork(f"r{i}", compare=(0, 1))

    assert cli("--repo", "demo/r7") == 0

    assert github.count("GET", "/user/repos") == 0
    assert detail_requests(github) == ["demo/r7"]
    assert github.count("GET", "/compare/") == 1
    assert "demo/r7: behind" in capsys.readouterr().out


def test_several_selections_are_each_loaded_once(github):
    for name in ("a", "b", "c"):
        github.add_fork(name)

    cli("--repo", "demo/b", "--repo", "demo/a", "--repo", "demo/b")

    assert detail_requests(github) == ["demo/b", "demo/a"]


def test_live_cli_selection_merges_only_that_fork(github, monkeypatch):
    github.add_fork("a", compare=(0, 1))
    github.add_fork("b", compare=(0, 1))
    monkeypatch.setattr("builtins.input", lambda _prompt: "SYNC")

    assert main.main(["--repo", "demo/b"]) == 0

    assert github.merged == ["demo/b"]
    assert github.count("GET", "/user/repos") == 0


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(lambda g: None, id="missing"),
        pytest.param(lambda g: g.add_fork("x", details=full_repository("demo/x", fork=False)), id="not-a-fork"),
        pytest.param(
            lambda g: g.add_fork("x", details=full_repository("demo/x", owner={"login": "someone"})),
            id="owned-by-someone-else",
        ),
        pytest.param(lambda g: g.add_fork("x", details=full_repository("demo/renamed")), id="renamed"),
    ],
)
def test_unavailable_selection_is_not_found(github, capsys, setup):
    setup(github)

    assert cli("--repo", "demo/x") == 1

    assert "Not found among this account's forks: demo/x" in capsys.readouterr().err
    assert github.count("GET", "/compare/") == 0


def test_other_owners_forks_are_never_selected(github, capsys):
    github.details["other/x"] = full_repository("other/x")
    github.compares["other/x"] = (0, 1)

    assert cli("--repo", "other/x") == 1

    assert "Not found" in capsys.readouterr().err
    assert github.count("GET", "/compare/") == 0


def test_owner_login_comparison_ignores_case(github):
    github.add_fork("x", details=full_repository("demo/x", owner={"login": "Demo"}))

    assert cli("--repo", "demo/x") == 0


def test_selection_name_must_match_exactly(github, capsys):
    github.add_fork("x")

    assert cli("--repo", "demo/X") == 1
    assert "Not found" in capsys.readouterr().err


def test_invalid_name_makes_no_request(github, capsys):
    assert cli("--repo", "not-a-full-name") == 1

    assert detail_requests(github) == []
    assert "Not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "details, message",
    [
        (403, "Could not load fork details"),
        (500, "Could not load fork details"),
        (requests.ConnectionError("offline"), "Could not load fork details"),
        ((200, ["not", "a", "repository"]), "malformed"),
        ((200, "text"), "malformed"),
        ({**full_repository("demo/x"), "owner": None}, "no owner"),
        ({**full_repository("demo/x"), "parent": None}, "no upstream parent"),
    ],
)
def test_inaccessible_or_malformed_selection_is_skipped(github, capsys, details, message):
    github.add_fork("x", details=details)

    assert cli("--repo", "demo/x") == 1

    output = capsys.readouterr().out
    assert "demo/x: skipped" in output
    assert message in output


def test_fork_of_fork_selection_is_still_refused(github, monkeypatch, capsys):
    github.add_fork("x", compare=(0, 2), source={"full_name": "root/x"})
    monkeypatch.setattr("builtins.input", lambda _prompt: "SYNC")

    assert main.main(["--repo", "demo/x"]) == 0

    assert "demo/x: upstream-unverified" in capsys.readouterr().out
    assert github.merged == []


def test_rate_limit_stops_further_lookups(github, capsys):
    github.add_fork("a", details=response(429, {}, {"Retry-After": "3600"}))
    github.add_fork("b")

    assert cli("--repo", "demo/a", "--repo", "demo/b") == 1

    assert detail_requests(github) == ["demo/a"]
    output = capsys.readouterr().out
    assert "demo/a: rate-limited" in output
    assert "demo/b: rate-limited" in output


@pytest.mark.parametrize("returned", ["demo/renamed", "Demo/X"])
def test_lookup_itself_rejects_a_different_returned_name(github, returned):
    github.add_fork("x", details=full_repository(returned, owner={"login": "demo"}))

    discovery = ForkSynchronizer(GitHubClient("t")).discover_forks(
        only=["demo/x"], owner_login="demo"
    )

    assert discovery == ([], [])


def test_lookup_requires_the_authenticated_account(github):
    with pytest.raises(ValueError):
        ForkSynchronizer(GitHubClient("t")).discover_forks(only=["demo/x"], owner_login="")


# Web


def test_web_live_sync_looks_up_only_the_selection(github):
    for i in range(50):
        github.add_fork(f"r{i}", compare=(0, 1))

    reply = live(["demo/r3"])

    assert reply.status_code == 200
    assert github.count("GET", "/user/repos") == 0
    assert detail_requests(github) == ["demo/r3"]
    assert github.merged == ["demo/r3"]


@pytest.mark.parametrize(
    "setup",
    [
        lambda g: None,
        lambda g: g.add_fork("x", details=full_repository("demo/x", fork=False)),
        lambda g: g.add_fork("x", details=full_repository("demo/x", owner={"login": "someone"})),
        lambda g: g.add_fork("x", details=403),
        lambda g: g.add_fork("x", details={**full_repository("demo/x"), "parent": None}),
    ],
)
def test_web_live_rejects_unavailable_selection(github, setup):
    setup(github)

    reply = live(["demo/x"])

    assert reply.status_code == 400
    assert github.merged == []


def test_web_preview_still_lists_every_fork(github):
    github.add_fork("a")
    github.add_fork("b")

    body = post({"dry_run": True}).json()

    assert github.count("GET", "/user/repos") == 1
    assert {item["repository"] for item in body["results"]} == {"demo/a", "demo/b"}


def test_cli_and_web_agree_on_selected_results(github, monkeypatch, capsys):
    github.add_fork("a", compare=(0, 1))
    github.add_fork("b", compare=(1, 1))
    github.add_fork("c", compare=(0, 1), source={"full_name": "root/c"})
    monkeypatch.setattr("builtins.input", lambda _prompt: "SYNC")
    main.main(["--repo", "demo/a", "--repo", "demo/b", "--repo", "demo/c"])
    cli_statuses = {
        line.split(": ")[0]: line.split(": ")[1]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("demo/")
    }

    fresh = FakeGitHub().install(monkeypatch)
    fresh.add_fork("a", compare=(0, 1))
    fresh.add_fork("b", compare=(1, 1))
    fresh.add_fork("c", compare=(0, 1), source={"full_name": "root/c"})
    body = live(["demo/a", "demo/b", "demo/c"]).json()

    assert {item["repository"]: item["status"] for item in body["results"]} == cli_statuses
    assert cli_statuses == {
        "demo/a": "synced", "demo/b": "diverged", "demo/c": "upstream-unverified",
    }
