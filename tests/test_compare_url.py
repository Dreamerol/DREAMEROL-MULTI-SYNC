"""Compare URLs: direction, same-owner forks and URL encoding."""

from urllib.parse import quote

import pytest

from fake_github import DEFAULT_SHA, FakeGitHub, full_repository
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer

API = "https://api.github.com"
SPECIAL = "feat#1%+&é/x"
SPECIAL_ENCODED = "feat%231%25%2B%26%C3%A9/x"


@pytest.fixture
def github(monkeypatch):
    return FakeGitHub().install(monkeypatch)


def same_owner_fork(github, name="x", parent="demo/original", branch="main", **extra):
    full_name = f"demo/{name}"
    upstream = {"full_name": parent, "default_branch": branch}
    github.details[full_name] = full_repository(
        full_name, default_branch=branch, parent=upstream, source=upstream, **extra
    )
    github.listing.append({"full_name": full_name, "fork": True})
    github.merges[full_name] = (200, {"merge_type": "fast-forward"})
    return full_name


def urls(github):
    return [url.removeprefix(API) for _method, url in github.calls]


def test_different_owners_compare_upstream_base_with_fork_head(github):
    github.compares["demo/x"] = (0, 0)

    GitHubClient("t").compare_upstream("demo/x", "up/x", "main", "main")

    assert urls(github) == ["/repos/demo/x/compare/up:main...demo:main"]


@pytest.mark.parametrize(
    "counts, status",
    [((0, 3), "behind"), ((2, 0), "ahead"), ((2, 3), "diverged"), ((0, 0), "up-to-date")],
)
def test_direction_maps_ahead_to_fork_and_behind_to_upstream(github, counts, status):
    name = github.add_fork("x", compare=counts)

    result = ForkSynchronizer(GitHubClient("t")).preview_fork(github.details[name])

    assert result["status"] == status
    assert (result["ahead_by"], result["behind_by"]) == counts


def test_same_owner_resolves_upstream_branch_to_a_commit(github):
    name = same_owner_fork(github)
    github.compares[name] = (0, 2)

    result = ForkSynchronizer(GitHubClient("t")).preview_fork(github.details[name])

    assert urls(github) == [
        "/repos/demo/original/branches/main",
        f"/repos/demo/x/compare/{DEFAULT_SHA}...main",
    ]
    assert result["status"] == "behind"


def test_same_owner_match_ignores_login_case(github):
    name = same_owner_fork(github, parent="Demo/original")
    github.compares[name] = (0, 0)

    ForkSynchronizer(GitHubClient("t")).preview_fork(github.details[name])

    assert urls(github)[0] == "/repos/Demo/original/branches/main"
    assert "/compare/" + DEFAULT_SHA + "...main" in urls(github)[1]


@pytest.mark.parametrize(
    "counts, status", [((2, 0), "ahead"), ((2, 3), "diverged"), ((0, 0), "up-to-date")]
)
def test_same_owner_fork_not_behind_is_never_merged(github, counts, status):
    name = same_owner_fork(github)
    github.compares[name] = counts

    result = ForkSynchronizer(GitHubClient("t")).sync_fork(github.details[name])

    assert result["status"] == status
    assert github.merged == []


def test_same_owner_fork_behind_is_merged_once_with_its_branch(github):
    name = same_owner_fork(github)
    github.compares[name] = (0, 2)

    result = ForkSynchronizer(GitHubClient("t")).sync_fork(github.details[name])

    assert result["status"] == "synced"
    assert github.merged == [name]
    assert github.merge_bodies == [{"branch": "main"}]


@pytest.mark.parametrize(
    "head",
    [404, 500, (200, {"commit": {"sha": "not-a-sha"}}), (200, {"commit": None}), (200, ["x"])],
)
def test_same_owner_without_a_valid_upstream_commit_is_an_error(github, head):
    name = same_owner_fork(github)
    github.branch_heads["demo/original"] = head
    github.compares[name] = (0, 2)

    result = ForkSynchronizer(GitHubClient("t")).sync_fork(github.details[name])

    assert result["status"] == "error"
    assert github.count("GET", "/compare/") == 0
    assert github.merged == []


def test_sha256_commit_ids_are_accepted(github):
    name = same_owner_fork(github)
    github.branch_heads["demo/original"] = "a" * 64
    github.compares[name] = (0, 0)

    result = ForkSynchronizer(GitHubClient("t")).preview_fork(github.details[name])

    assert result["status"] == "up-to-date"


def test_special_branch_characters_are_encoded_for_different_owners(github):
    github.compares["demo/x"] = (0, 0)

    GitHubClient("t").compare_upstream("demo/x", "up/x", SPECIAL, SPECIAL)

    assert quote(SPECIAL, safe="/") == SPECIAL_ENCODED
    assert urls(github) == [f"/repos/demo/x/compare/up:{SPECIAL_ENCODED}...demo:{SPECIAL_ENCODED}"]


def test_special_branch_characters_are_encoded_for_same_owner(github):
    name = same_owner_fork(github, branch=SPECIAL)
    github.compares[name] = (0, 0)

    ForkSynchronizer(GitHubClient("t")).preview_fork(github.details[name])

    assert urls(github) == [
        f"/repos/demo/original/branches/{SPECIAL_ENCODED}",
        f"/repos/demo/x/compare/{DEFAULT_SHA}...{SPECIAL_ENCODED}",
    ]


def test_repository_names_with_dots_and_dashes_are_kept(github):
    github.compares["my-org/my.repo"] = (0, 0)
    github.merges["my-org/my.repo"] = (200, {"merge_type": "none"})

    client = GitHubClient("t")
    client.compare_upstream("my-org/my.repo", "up-stream/my.repo", "main", "main")
    client.merge_upstream("my-org/my.repo", "main")

    assert urls(github) == [
        "/repos/my-org/my.repo/compare/up-stream:main...my-org:main",
        "/repos/my-org/my.repo/merge-upstream",
    ]


def test_owner_and_repository_are_encoded_as_single_path_segments(github):
    github.compares["o%/r?"] = (0, 0)

    GitHubClient("t").compare_upstream("o%/r?", "u#/r", "main", "main")

    assert urls(github) == ["/repos/o%25/r%3F/compare/u%23:main...o%25:main"]
