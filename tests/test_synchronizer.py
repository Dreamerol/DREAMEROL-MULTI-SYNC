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
        "status": "diverged",
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


def test_sync_fork_when_up_to_date(
    synchronizer, github, fork
):
    github.compare_upstream.return_value = {
        "ahead_by": 0,
        "behind_by": 0,
        "status": "identical",
    }

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "up-to-date"
    assert result["repository"] == "Dreamerol/AI-STUDIO"

    github.compare_upstream.assert_called_once()
    github.merge_upstream.assert_not_called()


def test_sync_fork_when_behind_upstream(
    synchronizer, github, fork
):
    github.compare_upstream.return_value = {
        "ahead_by": 0,
        "behind_by": 3,
        "status": "behind",
    }

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "synced"
    assert "3 upstream commits" in result["message"]

    github.merge_upstream.assert_called_once_with(
        "Dreamerol/AI-STUDIO",
        "main",
    )


@pytest.mark.parametrize(
    "comparison",
    [
        {},
        {"behind_by": None},
        {"behind_by": "3"},
        {"behind_by": -1},
        {"behind_by": True},
        {"behind_by": False},
    ],
)
def test_sync_fork_rejects_invalid_behind_by(
    synchronizer, github, fork, comparison
):
    github.compare_upstream.return_value = comparison

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "error"
    github.merge_upstream.assert_not_called()


def test_sync_fork_handles_conflict(
    synchronizer, github, fork
):
    github.compare_upstream.return_value = {
        "behind_by": 2,
    }

    response = Mock()
    response.status_code = 409

    error = requests.HTTPError(
        "Merge conflict",
        response=response,
    )

    github.merge_upstream.side_effect = error

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "conflict"
    assert result["repository"] == "Dreamerol/AI-STUDIO"


def test_sync_fork_handles_github_api_error(
    synchronizer, github, fork
):
    github.compare_upstream.side_effect = (
        requests.ConnectionError("Connection failed")
    )

    result = synchronizer.sync_fork(fork)

    assert result["status"] == "error"
    assert "Connection failed" in result["message"]

    github.merge_upstream.assert_not_called()


def test_sync_all_continues_after_repository_error(
    synchronizer, github, fork
):
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
        {
            "behind_by": 2,
            "ahead_by": 0,
        },
    ]

    results = synchronizer.sync_all(
        forks=[fork, second_fork]
    )

    assert len(results) == 2
    assert results[0]["status"] == "error"
    assert results[1]["status"] == "synced"

    assert results[1]["repository"] == (
        "Dreamerol/PORTFOLIO"
    )


def test_sync_all_handles_repository_discovery_error(
    synchronizer, github
):
    github.list_repositories.side_effect = (
        requests.ConnectionError("GitHub unavailable")
    )

    results = synchronizer.sync_all()

    assert len(results) == 1
    assert results[0]["repository"] == "account"
    assert results[0]["status"] == "error"


def test_sync_all_dry_run_does_not_merge(
    synchronizer, github, fork
):
    results = synchronizer.sync_all(
        forks=[fork],
        dry_run=True,
    )

    assert results[0]["status"] == "dry-run"
    github.compare_upstream.assert_not_called()
    github.merge_upstream.assert_not_called()
