from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import HTTPError, RequestException

from api.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_github_client():
    github = Mock()
    github.session = Mock()
    github.get_authenticated_user.return_value = {"login": "demo-user"}
    return github


def make_fork(full_name):
    return {"full_name": full_name}


def github_http_error(status_code):
    response = Mock(status_code=status_code)
    return HTTPError(f"GitHub returned {status_code}", response=response)


def patch_github(monkeypatch, github):
    monkeypatch.setattr("api.routes.GitHubClient", lambda token: github)


def patch_synchronizer(monkeypatch, synchronizer):
    monkeypatch.setattr("api.routes.ForkSynchronizer", lambda client: synchronizer)


def post_sync(client, payload, token="test-token"):
    return client.post(
        "/api/sync",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_missing_token_returns_401(client):
    response = client.post("/api/sync", json={"dry_run": True})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Token abc", "Bearer", "abc"])
def test_invalid_bearer_format_returns_401(client, authorization):
    response = client.post(
        "/api/sync",
        json={"dry_run": True},
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401


def test_invalid_github_token_returns_401_and_closes_session(client, monkeypatch):
    github = make_github_client()
    github.get_authenticated_user.side_effect = github_http_error(401)
    patch_github(monkeypatch, github)

    response = post_sync(client, {"dry_run": True})

    assert response.status_code == 401
    assert response.json()["detail"] == "The GitHub token is invalid."
    github.session.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_detail"),
    [
        (403, 403, "The GitHub token does not have sufficient permissions."),
        (429, 502, "GitHub authentication failed."),
    ],
)
def test_github_authentication_errors_return_expected_status(
    client, monkeypatch, status_code, expected_status, expected_detail
):
    github = make_github_client()
    github.get_authenticated_user.side_effect = github_http_error(status_code)
    patch_github(monkeypatch, github)

    response = post_sync(client, {"dry_run": True})

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
    github.session.close.assert_called_once_with()


def test_preview_returns_results_without_syncing(client, monkeypatch):
    github = make_github_client()
    patch_github(monkeypatch, github)

    synchronizer = Mock()
    synchronizer.preview_all.return_value = [
        {"repository": "demo/behind", "status": "behind", "behind_by": 2},
        {"repository": "demo/current", "status": "up-to-date", "behind_by": 0},
        {"repository": "demo/ahead", "status": "ahead", "behind_by": 0},
        {"repository": "demo/diverged", "status": "diverged", "behind_by": 1},
    ]
    patch_synchronizer(monkeypatch, synchronizer)

    response = post_sync(client, {"dry_run": True})

    assert response.status_code == 200
    assert response.json()["account"] == "demo-user"
    assert response.json()["total"] == 4
    assert [item["status"] for item in response.json()["results"]] == [
        "behind",
        "up-to-date",
        "ahead",
        "diverged",
    ]
    synchronizer.preview_all.assert_called_once_with()
    synchronizer.sync_all.assert_not_called()
    github.session.close.assert_called_once_with()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "dry_run": False,
            "confirmation": "NO",
            "repositories": ["demo/fork"],
        },
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": [],
        },
        {
            "dry_run": False,
            "confirmation": "SYNC",
        },
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/fork", "demo/fork"],
        },
    ],
)
def test_invalid_live_sync_requests_return_400(client, payload):
    response = post_sync(client, payload)

    assert response.status_code == 400


def test_live_sync_rejects_more_than_5000_repositories(client):
    repositories = [f"demo/fork-{index}" for index in range(5001)]

    response = post_sync(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": repositories,
        },
    )

    assert response.status_code == 400


def test_live_sync_rejects_repository_not_found_in_fresh_fork_list(
    client, monkeypatch
):
    github = make_github_client()
    patch_github(monkeypatch, github)

    synchronizer = Mock()
    synchronizer.get_forks.return_value = [make_fork("demo/available")]
    patch_synchronizer(monkeypatch, synchronizer)

    response = post_sync(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/available", "demo/not-a-fork"],
        },
    )

    assert response.status_code == 400
    synchronizer.preview_fork.assert_not_called()
    synchronizer.sync_all.assert_not_called()
    github.session.close.assert_called_once_with()


def test_rate_limit_or_permission_error_loading_forks_returns_502(
    client, monkeypatch
):
    github = make_github_client()
    patch_github(monkeypatch, github)

    synchronizer = Mock()
    synchronizer.get_forks.side_effect = github_http_error(403)
    patch_synchronizer(monkeypatch, synchronizer)

    response = post_sync(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/fork"],
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not load forks from GitHub."
    synchronizer.sync_all.assert_not_called()
    github.session.close.assert_called_once_with()


def test_live_sync_processes_only_selected_forks_that_are_behind(
    client, monkeypatch
):
    github = make_github_client()
    patch_github(monkeypatch, github)

    behind_fork = make_fork("demo/behind")
    current_fork = make_fork("demo/current")
    unselected_fork = make_fork("demo/unselected")

    synchronizer = Mock()
    synchronizer.get_forks.return_value = [
        behind_fork,
        current_fork,
        unselected_fork,
    ]
    synchronizer.preview_fork.side_effect = [
        {"repository": "demo/behind", "status": "behind", "behind_by": 3},
        {"repository": "demo/current", "status": "up-to-date", "behind_by": 0},
    ]
    synchronizer.sync_all.return_value = [
        {
            "repository": "demo/behind",
            "status": "synced",
            "message": "Synced 3 upstream commits.",
            "behind_by": 3,
        }
    ]
    patch_synchronizer(monkeypatch, synchronizer)

    response = post_sync(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/behind", "demo/current"],
        },
    )

    assert response.status_code == 200
    assert [item["repository"] for item in response.json()["results"]] == [
        "demo/behind",
        "demo/current",
    ]
    assert [item["status"] for item in response.json()["results"]] == [
        "synced",
        "up-to-date",
    ]

    assert synchronizer.preview_fork.call_count == 2
    synchronizer.preview_fork.assert_any_call(behind_fork)
    synchronizer.preview_fork.assert_any_call(current_fork)
    synchronizer.sync_all.assert_called_once_with(forks=[behind_fork])
    github.session.close.assert_called_once_with()


def test_server_rechecks_selected_repositories_before_sync(client, monkeypatch):
    """Do not trust browser status: only freshly checked behind forks may sync."""
    github = make_github_client()
    patch_github(monkeypatch, github)

    selected_now_up_to_date = make_fork("demo/current")
    selected_still_behind = make_fork("demo/behind")

    synchronizer = Mock()
    synchronizer.get_forks.return_value = [
        selected_now_up_to_date,
        selected_still_behind,
    ]
    synchronizer.preview_fork.side_effect = [
        {
            "repository": "demo/current",
            "status": "up-to-date",
            "behind_by": 0,
        },
        {"repository": "demo/behind", "status": "behind", "behind_by": 1},
    ]
    synchronizer.sync_all.return_value = [
        {"repository": "demo/behind", "status": "synced", "behind_by": 1}
    ]
    patch_synchronizer(monkeypatch, synchronizer)

    # The browser submits both repositories; server-side recheck excludes current.
    response = post_sync(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/current", "demo/behind"],
        },
    )

    assert response.status_code == 200
    synchronizer.sync_all.assert_called_once_with(forks=[selected_still_behind])
    assert [item["status"] for item in response.json()["results"]] == [
        "up-to-date",
        "synced",
    ]
    github.session.close.assert_called_once_with()


def test_authentication_network_error_returns_502_and_closes_session(
    client, monkeypatch
):
    github = make_github_client()
    github.get_authenticated_user.side_effect = RequestException(
        "network unavailable"
    )
    patch_github(monkeypatch, github)

    response = post_sync(client, {"dry_run": True})

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not reach GitHub."
    github.session.close.assert_called_once_with()
