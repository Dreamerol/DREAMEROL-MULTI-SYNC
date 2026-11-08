from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import HTTPError, RequestException

from api.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def github_http_error(status_code):
    response = Mock(status_code=status_code)
    return HTTPError(f"GitHub returned {status_code}", response=response)


def authorized_post(client, payload):
    return client.post(
        "/api/sync",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )


def install_github_client(monkeypatch, github_client):
    monkeypatch.setattr("api.routes.GitHubClient", lambda token: github_client)


def install_synchronizer(monkeypatch, synchronizer):
    monkeypatch.setattr("api.routes.ForkSynchronizer", lambda client: synchronizer)


def make_fork(name):
    return {
        "full_name": name,
        "fork": True,
        "default_branch": "main",
        "parent": {
            "full_name": "upstream/" + name.rsplit("/", 1)[-1],
            "default_branch": "main",
        },
    }


def make_github_client():
    github_client = Mock()
    github_client.session = Mock()
    github_client.get_authenticated_user.return_value = {"login": "demo-user"}
    return github_client


def test_missing_token_returns_401(client):
    response = client.post("/api/sync", json={"dry_run": True})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Token abc123", "Bearer", "Bearer   ", "abc123"])
def test_invalid_bearer_format_returns_401(client, authorization):
    response = client.post(
        "/api/sync",
        json={"dry_run": True},
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401


def test_invalid_github_token_returns_401_and_closes_session(client, monkeypatch):
    github_client = make_github_client()
    github_client.get_authenticated_user.side_effect = github_http_error(401)
    install_github_client(monkeypatch, github_client)

    response = authorized_post(client, {"dry_run": True})

    assert response.status_code == 401
    assert response.json()["detail"] == "The GitHub token is invalid."
    github_client.session.close.assert_called_once_with()


def test_preview_returns_results_without_syncing(client, monkeypatch):
    github_client = make_github_client()
    install_github_client(monkeypatch, github_client)
    synchronizer = Mock()
    synchronizer.preview_all.return_value = [
        {"repository": "demo/behind", "status": "behind", "behind_by": 2},
        {"repository": "demo/current", "status": "up-to-date", "behind_by": 0},
        {"repository": "demo/ahead", "status": "ahead", "behind_by": 0},
        {"repository": "demo/diverged", "status": "diverged", "behind_by": 1},
    ]
    install_synchronizer(monkeypatch, synchronizer)

    response = authorized_post(client, {"dry_run": True})

    assert response.status_code == 200
    assert response.json()["account"] == "demo-user"
    assert response.json()["total"] == 4
    assert [result["status"] for result in response.json()["results"]] == [
        "behind", "up-to-date", "ahead", "diverged"
    ]
    synchronizer.preview_all.assert_called_once_with()
    synchronizer.sync_all.assert_not_called()
    github_client.session.close.assert_called_once_with()


def test_live_sync_without_sync_confirmation_returns_400(client):
    response = authorized_post(
        client,
        {"dry_run": False, "confirmation": "NO", "repositories": ["demo/fork"]},
    )

    assert response.status_code == 400


def test_live_sync_without_repositories_returns_400(client):
    response = authorized_post(
        client,
        {"dry_run": False, "confirmation": "SYNC", "repositories": []},
    )

    assert response.status_code == 400


def test_live_sync_with_missing_repositories_returns_400(client):
    response = authorized_post(client, {"dry_run": False, "confirmation": "SYNC"})

    assert response.status_code == 400


def test_live_sync_with_duplicate_repositories_returns_400(client):
    response = authorized_post(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/fork", "demo/fork"],
        },
    )

    assert response.status_code == 400


def test_live_sync_with_more_than_5000_repositories_returns_400(client):
    repositories = [f"demo/fork-{index}" for index in range(5001)]
    response = authorized_post(
        client,
        {"dry_run": False, "confirmation": "SYNC", "repositories": repositories},
    )

    assert response.status_code == 400


def test_live_sync_rejects_repository_not_returned_by_fresh_fork_lookup(client, monkeypatch):
    github_client = make_github_client()
    install_github_client(monkeypatch, github_client)
    synchronizer = Mock()
    synchronizer.get_forks.return_value = [make_fork("demo/available")]
    install_synchronizer(monkeypatch, synchronizer)

    response = authorized_post(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/available", "demo/no-longer-a-fork"],
        },
    )

    assert response.status_code == 400
    synchronizer.preview_fork.assert_not_called()
    synchronizer.sync_all.assert_not_called()
    github_client.session.close.assert_called_once_with()


def test_rate_limit_during_fork_lookup_returns_502_and_closes_session(client, monkeypatch):
    github_client = make_github_client()
    install_github_client(monkeypatch, github_client)
    synchronizer = Mock()
    synchronizer.get_forks.side_effect = github_http_error(403)
    install_synchronizer(monkeypatch, synchronizer)

    response = authorized_post(
        client,
        {"dry_run": False, "confirmation": "SYNC", "repositories": ["demo/fork"]},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not load forks from GitHub."
    synchronizer.sync_all.assert_not_called()
    github_client.session.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("status_code", "expected_detail"),
    [
        (401, "The GitHub token is invalid."),
        (403, "The GitHub token does not have sufficient permissions."),
        (429, "GitHub authentication failed."),
    ],
)
def test_github_authentication_errors_return_expected_status(
    client, monkeypatch, status_code, expected_detail
):
    github_client = make_github_client()
    github_client.get_authenticated_user.side_effect = github_http_error(status_code)
    install_github_client(monkeypatch, github_client)

    response = authorized_post(client, {"dry_run": True})

    expected_status = status_code if status_code in (401, 403) else 502
    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
    github_client.session.close.assert_called_once_with()


def test_successful_live_sync_only_sends_selected_freshly_behind_forks(client, monkeypatch):
    github_client = make_github_client()
    install_github_client(monkeypatch, github_client)
    behind_fork = make_fork("demo/behind")
    current_fork = make_fork("demo/current")
    unselected_fork = make_fork("demo/unselected")

    synchronizer = Mock()
    synchronizer.get_forks.return_value = [behind_fork, current_fork, unselected_fork]
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
    install_synchronizer(monkeypatch, synchronizer)

    response = authorized_post(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["demo/behind", "demo/current"],
        },
    )

    assert response.status_code == 200
    assert [result["repository"] for result in response.json()["results"]] == [
        "demo/behind", "demo/current"
    ]
    assert [result["status"] for result in response.json()["results"]] == [
        "synced", "up-to-date"
    ]
    synchronizer.preview_fork.assert_any_call(behind_fork)
    synchronizer.preview_fork.assert_any_call(current_fork)
    assert synchronizer.preview_fork.call_count == 2
    synchronizer.sync_all.assert_called_once_with(forks=[behind_fork])
    github_client.session.close.assert_called_once_with()


def test_live_sync_rechecks_browser_selected_forks_and_excludes_no_longer_behind_fork(
    client, monkeypatch
):
    github_client = make_github_client()
    install_github_client(monkeypatch, github_client)
    selected_now_current = make_fork("demo/selected-current")
    selected_still_behind = make_fork("demo/selected-behind")

    synchronizer = Mock()
    synchronizer.get_forks.return_value = [selected_now_current, selected_still_behind]
    synchronizer.preview_fork.side_effect = [
        {"repository": "demo/selected-current", "status": "up-to-date", "behind_by": 0},
        {"repository": "demo/selected-behind", "status": "behind", "behind_by": 1},
    ]
    synchronizer.sync_all.return_value = [
        {"repository": "demo/selected-behind", "status": "synced", "behind_by": 1}
    ]
    install_synchronizer(monkeypatch, synchronizer)

    response = authorized_post(
        client,
        {
            "dry_run": False,
            "confirmation": "SYNC",
            # The request includes an up-to-date repository; server recheck must prevent its merge.
            "repositories": ["demo/selected-current", "demo/selected-behind"],
        },
    )

    assert response.status_code == 200
    assert [fork["full_name"] for fork in synchronizer.sync_all.call_args.kwargs["forks"]] == [
        "demo/selected-behind"
    ]
    assert [result["status"] for result in response.json()["results"]] == [
        "up-to-date", "synced"
    ]
    assert synchronizer.preview_fork.call_count == 2
    github_client.session.close.assert_called_once_with()


def test_network_error_during_authentication_returns_502_and_closes_session(client, monkeypatch):
    github_client = make_github_client()
    github_client.get_authenticated_user.side_effect = RequestException("network unavailable")
    install_github_client(monkeypatch, github_client)

    response = authorized_post(client, {"dry_run": True})

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not reach GitHub."
    github_client.session.close.assert_called_once_with()
