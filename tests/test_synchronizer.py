"""Tests for GitHub fork discovery and upstream synchronization."""

from unittest.mock import Mock

import pytest
import requests

from fork_sync.synchronizer import ForkSynchronizer


@pytest.fixture
def github():
    client = Mock()
    client.list_repositories.return_value = []
    client.compare_upstream.return_value = {
        "status": "behind",
        "ahead_by": 0,
        "behind_by": 3,
    }
    client.merge_upstream.return_value = None
    return client


@pytest.fixture
def synchronizer(github):
    return ForkSynchronizer(github)


@pytest.fixture
def fork():
    return {
        "full_name": "Dreamerol/AI-STUDIO",
        "fork": True,
        "default_branch": "main",
        "parent": {
            "full_name": "original/AI-STUDIO",
            "default_branch": "main",
        },
    }


@pytest.fixture
def differently_named_fork():
    return {
        "full_name": "octocat/demo-fork",
        "fork": True,
        "default_branch": "master",
        "parent": {
            "full_name": "octodemo/upstream-repo",
            "default_branch": "main",
        },
    }


def test_get_forks_returns_only_forks(synchronizer, github):
    github.list_repositories.return_value = [
        {
            "full_name": "user/fork",
            "fork": True,
            "parent": {
                "full_name": "original/fork",
                "default_branch": "main",
            },
        },
        {"full_name": "user/original", "fork": False},
        {"full_name": "user/another", "fork": True},
        {"full_name": "user/incomplete-parent", "fork": True, "parent": {}},
        "invalid",
    ]

    result = synchronizer.get_forks()

    assert len(result) == 1
    assert result[0]["full_name"] == "user/fork"


def test_get_forks_rejects_invalid_response(synchronizer, github):
    github.list_repositories.return_value = None

    with pytest.raises(ValueError):
        synchronizer.get_forks()


def test_sync_fork_when_up_to_date(synchronizer, github, fork):
    github.compare_upstream.return_value = {
        "ahead_by": 0,
        "behind_by": 0,
        "status": "identical",
    }

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "up-to-date"
    assert result["repository"] == "Dreamerol/AI-STUDIO"
    github.compare_upstream.assert_called_once_with(
        fork_full_name="Dreamerol/AI-STUDIO",
        upstream_full_name="original/AI-STUDIO",
        upstream_branch="main",
        fork_branch="main",
    )
    github.merge_upstream.assert_not_called()


def test_sync_fork_when_behind_upstream_targets_fork_default_branch(
    synchronizer, github, differently_named_fork
):
    github.compare_upstream.return_value = {
        "ahead_by": 0,
        "behind_by": 3,
        "status": "behind",
    }

    result = synchronizer.sync_fork(differently_named_fork)

    assert result["status"] == "synced"
    assert result["repository"] == "octocat/demo-fork"
    assert "3 upstream commits" in result["message"]
    github.compare_upstream.assert_called_once_with(
        fork_full_name="octocat/demo-fork",
        upstream_full_name="octodemo/upstream-repo",
        upstream_branch="main",
        fork_branch="master",
    )
    github.merge_upstream.assert_called_once_with("octocat/demo-fork", "master")


def test_sync_fork_rechecks_comparison_after_preview(
    synchronizer, github, differently_named_fork
):
    github.compare_upstream.side_effect = [
        {"ahead_by": 0, "behind_by": 2, "status": "behind"},
        {"ahead_by": 1, "behind_by": 2, "status": "diverged"},
    ]

    preview = synchronizer.preview_fork(differently_named_fork)
    result = synchronizer.sync_fork(differently_named_fork)

    assert preview["status"] == "behind"
    assert result["status"] == "diverged"
    assert github.compare_upstream.call_count == 2
    github.merge_upstream.assert_not_called()


@pytest.mark.parametrize(
    "comparison, expected_status",
    [
        ({"ahead_by": 2, "behind_by": 0, "status": "ahead"}, "ahead"),
        ({"ahead_by": 2, "behind_by": 0, "status": "ahead"}, "ahead"),
        ({"ahead_by": 2, "behind_by": 3, "status": "diverged"}, "diverged"),
    ],
)
def test_sync_fork_does_not_merge_fork_with_local_commits(
    synchronizer, github, fork, comparison, expected_status
):
    github.compare_upstream.return_value = comparison

    result = synchronizer.sync_fork(fork)

    assert result["status"] == expected_status
    github.merge_upstream.assert_not_called()


@pytest.mark.parametrize(
    "comparison",
    [
        {},
        {"behind_by": 3},
        {"ahead_by": None, "behind_by": 3},
        {"ahead_by": "0", "behind_by": 3},
        {"ahead_by": -1, "behind_by": 3},
        {"ahead_by": True, "behind_by": 3},
        {"ahead_by": 0, "behind_by": None},
        {"ahead_by": 0, "behind_by": "3"},
        {"ahead_by": 0, "behind_by": -1},
        {"ahead_by": 0, "behind_by": False},
    ],
)
def test_sync_fork_rejects_invalid_comparison_counts(
    synchronizer, github, fork, comparison
):
    github.compare_upstream.return_value = comparison

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "error"
    github.merge_upstream.assert_not_called()


def test_sync_fork_handles_conflict(synchronizer, github, fork):
    github.compare_upstream.return_value = {
        "ahead_by": 0,
        "behind_by": 2,
        "status": "behind",
    }
    response = Mock()
    response.status_code = 409
    error = requests.HTTPError("Merge conflict", response=response)
    github.merge_upstream.side_effect = error

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "conflict"
    assert result["repository"] == "Dreamerol/AI-STUDIO"


def test_sync_fork_handles_github_api_error(synchronizer, github, fork):
    github.compare_upstream.side_effect = requests.ConnectionError("Connection failed")

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "error"
    assert "Connection failed" in result["message"]
    github.merge_upstream.assert_not_called()


def test_sync_all_continues_after_repository_error(synchronizer, github, fork):
    second_fork = {
        "full_name": "Dreamerol/PORTFOLIO",
        "fork": True,
        "default_branch": "main",
        "parent": {
            "full_name": "original/PORTFOLIO",
            "default_branch": "main",
        },
    }
    github.compare_upstream.side_effect = [
        RuntimeError("Unexpected failure"),
        {"behind_by": 2, "ahead_by": 0, "status": "behind"},
    ]

    results = synchronizer.sync_all(forks=[fork, second_fork])

    assert len(results) == 2
    assert results[0]["status"] == "error"
    assert results[1]["status"] == "synced"
    assert results[1]["repository"] == "Dreamerol/PORTFOLIO"
    github.merge_upstream.assert_called_once_with("Dreamerol/PORTFOLIO", "main")


def test_sync_all_handles_repository_discovery_error(synchronizer, github):
    github.list_repositories.side_effect = requests.ConnectionError("GitHub unavailable")

    results = synchronizer.sync_all()

    assert len(results) == 1
    assert results[0]["repository"] == "account"
    assert results[0]["status"] == "error"


@pytest.mark.parametrize(
    "ahead_by, behind_by, expected_status",
    [
        (0, 0, "up-to-date"),
        (0, 3, "would-sync"),
        (2, 0, "ahead"),
        (2, 3, "diverged"),
    ],
)
def test_sync_all_dry_run_previews_actual_status_without_merging(
    synchronizer, github, differently_named_fork, ahead_by, behind_by, expected_status
):
    github.compare_upstream.return_value = {
        "ahead_by": ahead_by,
        "behind_by": behind_by,
        "status": "unused",
    }

    results = synchronizer.sync_all(forks=[differently_named_fork], dry_run=True)

    assert results[0]["status"] == expected_status
    assert results[0]["repository"] == "octocat/demo-fork"
    assert results[0]["ahead_by"] == ahead_by
    assert results[0]["behind_by"] == behind_by
    github.compare_upstream.assert_called_once_with(
        fork_full_name="octocat/demo-fork",
        upstream_full_name="octodemo/upstream-repo",
        upstream_branch="main",
        fork_branch="master",
    )
    github.merge_upstream.assert_not_called()


def test_sync_all_dry_run_reports_invalid_compare_response(synchronizer, github, fork):
    github.compare_upstream.return_value = {"ahead_by": 0, "behind_by": "invalid"}

    results = synchronizer.sync_all(forks=[fork], dry_run=True)

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["repository"] == "Dreamerol/AI-STUDIO"
    github.merge_upstream.assert_not_called()


def test_sync_all_dry_run_reports_github_api_error(synchronizer, github, fork):
    github.compare_upstream.side_effect = requests.ConnectionError("Connection failed")

    results = synchronizer.sync_all(forks=[fork], dry_run=True)

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "Connection failed" in results[0]["message"]
    github.merge_upstream.assert_not_called()


def test_sync_all_dry_run_does_not_merge(synchronizer, github, fork):
    results = synchronizer.sync_all(forks=[fork], dry_run=True)

    assert results[0]["status"] == "would-sync"
    github.compare_upstream.assert_called_once()
    github.merge_upstream.assert_not_called()
