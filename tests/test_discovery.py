"""Fork discovery against GitHub-shaped responses."""

import pytest
import requests
from fastapi.testclient import TestClient

import main
from api.app import app
from fake_github import FakeGitHub, full_repository, list_item, response
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return FakeGitHub().install(monkeypatch)


@pytest.fixture
def synchronizer():
    return ForkSynchronizer(GitHubClient("test-token"))


def run_cli(*argv):
    return main.main(["--dry-run", *argv])


def web_preview():
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            "/api/sync",
            json={"dry_run": True},
            headers={"Authorization": "Bearer test-token"},
        )


def test_forks_are_found_from_list_items_without_parent(github, synchronizer):
    github.add_fork("one")
    github.add_fork("two")

    discovery = synchronizer.discover_forks()

    assert "parent" not in github.listing[0]
    assert [fork["full_name"] for fork in discovery.forks] == ["demo/one", "demo/two"]
    assert discovery.forks[0]["parent"]["full_name"] == "upstream/one"
    assert discovery.skipped == []
    assert github.count("GET", "/repos/demo/one") == 1


def test_non_forks_are_ignored_without_detail_requests(github, synchronizer):
    github.listing.append(list_item("demo/original", fork=False))

    assert synchronizer.discover_forks() == ([], [])
    assert github.count("GET", "/repos/demo/original") == 0


def test_duplicate_listing_entries_are_processed_once(github, synchronizer):
    name = github.add_fork("one")
    github.listing.append(list_item(name))

    assert len(synchronizer.discover_forks().forks) == 1
    assert github.count("GET", "/repos/demo/one") == 1


@pytest.mark.parametrize(
    "item",
    ["text", None, 7, ["list"], {"fork": True}, {"full_name": 5, "fork": True},
     {"full_name": "no-slash", "fork": True}, {"full_name": "a/b/c", "fork": True},
     {"full_name": "demo/x"}, {"full_name": "demo/x", "fork": "yes"}],
)
def test_malformed_list_items_are_reported(github, synchronizer, item):
    github.listing.append(item)

    discovery = synchronizer.discover_forks()

    assert discovery.forks == []
    assert [result["status"] for result in discovery.skipped] == ["skipped"]
    assert discovery.skipped[0]["message"]


@pytest.mark.parametrize(
    "details",
    [
        ["not-a-repository"],
        full_repository("demo/x", fork=False),
        {**full_repository("demo/x"), "full_name": None},
        full_repository("demo/x", default_branch=""),
        full_repository("demo/x", parent=None),
        full_repository("demo/x", parent={}),
        full_repository("demo/x", parent={"full_name": "up/x"}),
        full_repository("demo/x", parent={"full_name": "bad", "default_branch": "main"}),
        {key: value for key, value in full_repository("demo/x").items() if key != "parent"},
    ],
)
def test_incomplete_details_are_reported(github, synchronizer, details):
    github.add_fork("x", details=(200, details) if isinstance(details, list) else details)

    discovery = synchronizer.discover_forks()

    assert discovery.forks == []
    assert discovery.skipped[0]["repository"] == "demo/x"
    assert discovery.skipped[0]["status"] == "skipped"


@pytest.mark.parametrize("failure", [404, 500, requests.ConnectionError("offline")])
def test_failed_detail_request_is_reported_and_others_continue(github, synchronizer, failure):
    github.add_fork("broken", details=failure)
    github.add_fork("fine")

    discovery = synchronizer.discover_forks()

    assert [fork["full_name"] for fork in discovery.forks] == ["demo/fine"]
    assert discovery.skipped[0]["repository"] == "demo/broken"
    assert "Could not load fork details" in discovery.skipped[0]["message"]


@pytest.mark.parametrize("count, requests_made", [(0, 1), (99, 1), (100, 2), (101, 2), (200, 3)])
def test_pagination_returns_everything(github, count, requests_made):
    github.listing = [list_item(f"demo/r{index}", fork=False) for index in range(count)]

    repositories = GitHubClient("test-token").list_repositories()

    assert len(repositories) == count
    assert github.count("GET", "/user/repos") == requests_made


@pytest.mark.parametrize("body", [{"message": "odd"}, None, "text", 5])
def test_non_list_page_is_rejected(github, body):
    github.pages = [response(200, body)]

    with pytest.raises((ValueError, TypeError)):
        GitHubClient("test-token").list_repositories()


def test_endless_pagination_is_stopped(github):
    github.pages = [response(200, [list_item(f"demo/r{i}", fork=False) for i in range(100)])]
    client = GitHubClient("test-token")
    client.MAX_PAGES = 3

    with pytest.raises(ValueError, match="exceeded 3 pages"):
        client.list_repositories()


def test_failed_later_page_never_returns_partial_results(github):
    github.pages = [response(200, [list_item(f"demo/r{i}", fork=False) for i in range(100)]), 404]

    with pytest.raises(requests.HTTPError):
        GitHubClient("test-token").list_repositories()


def test_cli_fails_when_listing_is_malformed(github, capsys):
    github.pages = [response(200, {"message": "odd"})]

    assert run_cli() == 1
    assert "invalid repository list" in capsys.readouterr().err


def test_cli_fails_when_every_fork_is_unusable(github, capsys):
    github.add_fork("x", details=500)

    assert run_cli() == 1
    assert "demo/x: skipped" in capsys.readouterr().out


def test_cli_live_reports_skipped_forks_when_nothing_is_selectable(github, capsys):
    github.add_fork("x", details=500)

    assert main.main([]) == 1
    output = capsys.readouterr().out
    assert "demo/x: skipped" in output
    assert "Type SYNC" not in output


def test_cli_zero_forks_is_success_only_for_a_valid_empty_account(github, capsys):
    assert run_cli() == 0
    assert "No fork repositories found" in capsys.readouterr().out


def test_cli_repo_filter_reports_a_skipped_fork_instead_of_not_found(github, capsys):
    github.add_fork("x", details=500)

    assert run_cli("--repo", "demo/x") == 1
    captured = capsys.readouterr()
    assert "demo/x: skipped" in captured.out
    assert "Not found" not in captured.err


@pytest.mark.parametrize("page", [response(200, {"message": "odd"}), 502, requests.ConnectionError("x")])
def test_web_preview_propagates_listing_failures(github, page):
    github.pages = [page]

    reply = web_preview()

    assert reply.status_code == 502
    assert reply.json()["detail"] == "Could not load forks from GitHub."


def test_web_preview_includes_skipped_forks(github):
    github.add_fork("x", details=500)

    reply = web_preview()

    assert reply.status_code == 200
    assert reply.json()["results"][0]["status"] == "skipped"
