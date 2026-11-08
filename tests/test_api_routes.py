from unittest.mock import Mock

from fastapi.testclient import TestClient

import api.routes
from api.app import app


client = TestClient(app)


class FakeGitHubClient:
    def __init__(self, token):
        self.token = token
        self.session = Mock()

    def get_authenticated_user(self):
        return {"login": "octocat"}


class FakeForkSynchronizer:
    def __init__(self, client):
        self.client = client

    def preview_all(self):
        return [
            {"repository": "octocat/demo-fork", "status": "behind", "behind_by": 2},
            {"repository": "octocat/clean-fork", "status": "up-to-date", "behind_by": 0},
        ]

    def get_forks(self):
        return [
            {"full_name": "octocat/demo-fork", "default_branch": "main"},
            {"full_name": "octocat/clean-fork", "default_branch": "main"},
        ]

    def preview_fork(self, fork):
        if fork["full_name"] == "octocat/demo-fork":
            return {"repository": "octocat/demo-fork", "status": "behind", "behind_by": 2}
        return {"repository": fork["full_name"], "status": "up-to-date", "behind_by": 0}

    def sync_all(self, forks):
        return [
            {"repository": "octocat/demo-fork", "status": "synced", "message": "Synced 2 upstream commits."}
            for _ in forks
        ]


def test_sync_route_requires_bearer_token(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post("/api/sync", json={"dry_run": True})

    assert response.status_code == 401
    assert response.json()["detail"] == "Provide a GitHub token using the Bearer authorization scheme."


def test_sync_route_rejects_invalid_bearer_scheme(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={"dry_run": True},
        headers={"Authorization": "Token abc123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Provide a GitHub token using the Bearer authorization scheme."


def test_sync_route_dry_run_reports_preview_results(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={"dry_run": True},
        headers={"Authorization": "Bearer abc123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"] == "octocat"
    assert payload["total"] == 2
    assert [item["repository"] for item in payload["results"]] == [
        "octocat/demo-fork",
        "octocat/clean-fork",
    ]
    assert payload["results"][0]["status"] == "behind"
    assert payload["results"][1]["status"] == "up-to-date"


def test_sync_route_requires_confirmation_for_live_sync(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={"dry_run": False},
        headers={"Authorization": "Bearer abc123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == 'Live synchronization requires confirmation="SYNC".'


def test_sync_route_requires_selected_repositories_for_live_sync(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={"dry_run": False, "confirmation": "SYNC"},
        headers={"Authorization": "Bearer abc123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Select at least one repository from the preview before syncing."


def test_live_sync_only_updates_selected_behind_forks(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["octocat/demo-fork"],
        },
        headers={"Authorization": "Bearer abc123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"] == "octocat"
    assert payload["total"] == 1
    assert payload["results"][0]["repository"] == "octocat/demo-fork"
    assert payload["results"][0]["status"] == "synced"


def test_live_sync_rejects_repository_not_in_available_forks(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["octocat/ghost-fork"],
        },
        headers={"Authorization": "Bearer abc123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "A selected repository is no longer an available fork for this account. Preview again."


def test_live_sync_rejects_duplicate_repositories(monkeypatch):
    monkeypatch.setattr(api.routes, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={
            "dry_run": False,
            "confirmation": "SYNC",
            "repositories": ["octocat/demo-fork", "octocat/demo-fork"],
        },
        headers={"Authorization": "Bearer abc123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Duplicate repositories were selected."


def test_sync_route_handles_invalid_github_token(monkeypatch):
    class InvalidTokenGitHubClient(FakeGitHubClient):
        def get_authenticated_user(self):
            raise api.routes.HTTPException(status_code=401, detail="The GitHub token is invalid.")

    monkeypatch.setattr(api.routes, "GitHubClient", InvalidTokenGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={"dry_run": True},
        headers={"Authorization": "Bearer bad-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "The GitHub token is invalid."


def test_sync_route_handles_github_auth_failure(monkeypatch):
    class FailingGitHubClient(FakeGitHubClient):
        def get_authenticated_user(self):
            raise api.routes.requests.exceptions.HTTPError(response=Mock(status_code=403))

    monkeypatch.setattr(api.routes, "GitHubClient", FailingGitHubClient)
    monkeypatch.setattr(api.routes, "ForkSynchronizer", FakeForkSynchronizer)

    response = client.post(
        "/api/sync",
        json={"dry_run": True},
        headers={"Authorization": "Bearer bad-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "The GitHub token does not have sufficient permissions."
