"""Merge outcomes, unconfirmed merges and refusal cases, through the real client."""

import pytest
import requests

from fake_github import FakeGitHub, response
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer, has_failures


@pytest.fixture
def github(monkeypatch):
    return FakeGitHub().install(monkeypatch)


def sync(github, **kwargs):
    name = github.add_fork("x", **kwargs)
    return ForkSynchronizer(GitHubClient("test-token")).sync_fork(github.details[name])


@pytest.mark.parametrize(
    "merge_type, status, failure",
    [("fast-forward", "synced", False), ("merge", "merged", False), ("none", "no-change", False)],
)
def test_result_reports_what_github_did(github, merge_type, status, failure):
    result = sync(github, compare=(0, 2), merge=(200, {"merge_type": merge_type}))

    assert result["status"] == status
    assert result["merge_type"] == merge_type
    assert has_failures([result]) is failure


def test_merge_commit_is_not_described_as_a_clean_sync(github):
    result = sync(github, compare=(0, 2), merge=(200, {"merge_type": "merge"}))

    assert "merge commit" in result["message"]


def test_no_change_does_not_claim_commits_were_synced(github):
    result = sync(github, compare=(0, 2), merge=(200, {"merge_type": "none"}))

    assert "merged nothing" in result["message"]


@pytest.mark.parametrize("body", [{}, {"merge_type": "squash"}, {"merge_type": None}, ["x"], None])
def test_unrecognized_merge_reply_is_unknown(github, body):
    result = sync(github, compare=(0, 2), merge=(200, body))

    assert result["status"] == "unknown"
    assert has_failures([result])
    assert len(github.merged) == 1


def test_merge_conflict(github):
    result = sync(github, compare=(0, 2), merge=409)

    assert result["status"] == "conflict"
    assert has_failures([result])


@pytest.mark.parametrize("code", [403, 404, 422])
def test_merge_rejection_is_an_error_and_not_rechecked(github, code):
    result = sync(github, compare=(0, 2), merge=code)

    assert result["status"] == "error"
    assert github.count("GET", "/compare/") == 1


def test_comparison_409_is_not_called_a_merge_conflict(github):
    result = sync(github, compare=409)

    assert result["status"] == "error"
    assert github.merged == []


UNCONFIRMED = [
    requests.exceptions.ReadTimeout("timed out"),
    requests.exceptions.ConnectionError("dropped"),
    502,
    503,
]


@pytest.mark.parametrize("failure", UNCONFIRMED)
def test_unconfirmed_merge_that_applied_is_synced(github, failure):
    result = sync(github, compare=[(0, 2), (0, 0)], merge=failure)

    assert result["status"] == "synced"
    assert "not retried" in result["message"]
    assert "now matches upstream" in result["message"]
    assert len(github.merged) == 1


@pytest.mark.parametrize("failure", UNCONFIRMED)
def test_unconfirmed_merge_still_behind_is_unknown_and_not_retried(github, failure):
    result = sync(github, compare=[(0, 2), (0, 2)], merge=failure)

    assert result["status"] == "unknown"
    assert has_failures([result])
    assert len(github.merged) == 1


def test_unconfirmed_merge_that_cannot_be_checked_is_unknown(github):
    result = sync(
        github,
        compare=[(0, 2), 404],
        merge=requests.exceptions.ReadTimeout("timed out"),
    )

    assert result["status"] == "unknown"
    assert "could not be checked" in result["message"]


def test_unreadable_success_reply_is_checked(github):
    bad = response(200)
    bad._content = b"not json"

    result = sync(github, compare=[(0, 2), (1, 2)], merge=bad)

    assert result["status"] == "unknown"
    assert "diverged" in result["message"]


@pytest.mark.parametrize(
    "compare, status",
    [((0, 0), "up-to-date"), ((2, 0), "ahead"), ((2, 3), "diverged")],
)
def test_forks_that_are_not_behind_are_never_merged(github, compare, status):
    result = sync(github, compare=compare)

    assert result["status"] == status
    assert github.merged == []


def test_state_change_between_preview_and_sync_prevents_merge(github):
    name = github.add_fork("x", compare=[(0, 2), (1, 2)])
    synchronizer = ForkSynchronizer(GitHubClient("test-token"))

    assert synchronizer.preview_fork(github.details[name])["status"] == "behind"
    assert synchronizer.sync_fork(github.details[name])["status"] == "diverged"
    assert github.merged == []


@pytest.mark.parametrize("flag", ["archived", "disabled"])
def test_inactive_forks_are_not_attempted(github, flag):
    result = sync(github, compare=(0, 2), **{flag: True})

    assert result["status"] == "unavailable"
    assert not has_failures([result])
    assert github.calls == []


class UnexpectedFailure(Exception):
    """An exception type the merge path has no specific handling for."""


@pytest.mark.parametrize(
    "after, status",
    [((0, 0), "synced"), ((0, 2), "unknown"), ((1, 2), "unknown")],
)
def test_unexpected_merge_exception_gets_one_recheck_and_no_retry(github, after, status):
    result = sync(github, compare=[(0, 2), after], merge=UnexpectedFailure("boom"))

    assert result["status"] == status
    assert "not retried" in result["message"]
    assert len(github.merged) == 1
    assert github.count("GET", "/compare/") == 2


def test_unexpected_failure_during_recheck_is_unknown(github):
    result = sync(
        github,
        compare=[(0, 2), UnexpectedFailure("recheck")],
        merge=UnexpectedFailure("boom"),
    )

    assert result["status"] == "unknown"
    assert "could not be checked" in result["message"]
    assert len(github.merged) == 1


def test_unexpected_merge_exception_is_not_reported_as_plain_error_by_sync_all(github):
    name = github.add_fork("x", compare=[(0, 2), (0, 2)], merge=UnexpectedFailure("boom"))

    results = ForkSynchronizer(GitHubClient("t")).sync_all([github.details[name]])

    assert results[0]["status"] == "unknown"
    assert has_failures(results)


def test_merge_commit_message_does_not_claim_a_definite_cause(github):
    result = sync(github, compare=(0, 2), merge=(200, {"merge_type": "merge"}))

    assert "may have changed" in result["message"]
    assert "so the fork changed" not in result["message"]


@pytest.mark.parametrize("method", ["preview_fork", "sync_fork"])
@pytest.mark.parametrize(
    "source, expected_text",
    [
        ({"full_name": "root/x", "default_branch": "main"}, "differs from its source 'root/x'"),
        (None, "did not report"),
        ({}, "did not report"),
        ("root/x", "did not report"),
        ({"full_name": "invalid"}, "did not report"),
    ],
)
def test_unverifiable_upstream_is_refused_before_any_request(github, method, source, expected_text):
    name = github.add_fork("x", compare=(0, 2), source=source)
    synchronizer = ForkSynchronizer(GitHubClient("t"))

    result = getattr(synchronizer, method)(github.details[name])

    assert result["status"] == "upstream-unverified"
    assert expected_text in result["message"]
    assert not has_failures([result])
    assert github.calls == []


def test_missing_source_key_is_refused(github):
    name = github.add_fork("x", compare=(0, 2))
    del github.details[name]["source"]

    result = ForkSynchronizer(GitHubClient("t")).sync_fork(github.details[name])

    assert result["status"] == "upstream-unverified"
    assert github.calls == []


def test_matching_parent_and_source_can_still_sync(github):
    result = sync(github, compare=(0, 2))

    assert result["status"] == "synced"
    assert len(github.merged) == 1


def test_mismatched_branches_make_no_requests(github):
    result = sync(github, compare=(0, 2), default_branch="master")

    assert result["status"] == "branch-mismatch"
    assert not has_failures([result])
    assert github.calls == []


def test_equal_branch_names_are_merged_with_that_name(github):
    name = github.add_fork("x", compare=(0, 1), default_branch="trunk", upstream_branch="trunk")

    ForkSynchronizer(GitHubClient("t")).sync_fork(github.details[name])

    assert github.merge_bodies == [{"branch": "trunk"}]
