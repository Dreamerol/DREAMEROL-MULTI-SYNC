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
