import json
from unittest.mock import Mock

import pytest
import requests

from backend.github_client import GitHubClient


@pytest.fixture
def client():
    github_client = GitHubClient.__new__(GitHubClient)
    github_client.session = Mock()
    return github_client


@pytest.mark.parametrize(
    "owner",
    [
        "",
        " ",
        "invalid/name",
        "invalid name",
        "-invalid",
        "invalid-",
        "invalid--name",
        "a" * 40,
        "потребител",
        None,
        123,
    ],
)
def test_get_forks_rejects_invalid_owner(client, owner):
    with pytest.raises(ValueError, match="Invalid GitHub owner login"):
        client.get_forks(owner)


@pytest.mark.parametrize(
    "owner",
    [
        "",
        " ",
        "invalid/name",
        "invalid name",
        "-invalid",
        "invalid-",
        "invalid--name",
        "a" * 40,
        "потребител",
        None,
        123,
    ],
)
def test_validate_owner_login_rejects_invalid_values(owner):
    with pytest.raises(ValueError, match="Invalid GitHub owner login"):
        GitHubClient._validate_owner_login(owner)


@pytest.mark.parametrize(
    "owner, expected",
    [
        ("Dreamerol", "Dreamerol"),
        ("  Dreamerol  ", "Dreamerol"),
        ("test-user", "test-user"),
        ("user123", "user123"),
    ],
)
def test_validate_owner_login_accepts_valid_values(owner, expected):
    assert GitHubClient._validate_owner_login(owner) == expected


def test_get_forks_uses_next_url_for_pagination(client):
    account_response = Mock()
    account_response.json.return_value = {"type": "User"}

    first_response = Mock()
    first_response.json.return_value = [
        {"name": "fork-one", "fork": True},
        {"name": "original", "fork": False},
    ]
    first_response.links = {
        "next": {"url": "https://api.github.com/users/test/repos?page=2"}
    }

    second_response = Mock()
    second_response.json.return_value = [{"name": "fork-two", "fork": True}]
    second_response.links = {}

    client.session.get.side_effect = [
        account_response,
        first_response,
        second_response,
    ]

    forks = client.get_forks("test")

    assert [repo["name"] for repo in forks] == ["fork-one", "fork-two"]
    assert client.session.get.call_args_list[2].args[0] == (
        "https://api.github.com/users/test/repos?page=2"
    )
    assert client.session.get.call_args_list[2].kwargs["params"] is None


def test_get_forks_uses_organization_endpoint_and_parameters(client):
    account_response = Mock()
    account_response.json.return_value = {"type": "Organization"}
    repositories_response = Mock()
    repositories_response.json.return_value = []
    repositories_response.links = {}
    client.session.get.side_effect = [account_response, repositories_response]

    assert client.get_forks("Dreamerol") == []

    repository_call = client.session.get.call_args_list[1]
    assert repository_call.args[0] == "https://api.github.com/orgs/Dreamerol/repos"
    assert repository_call.kwargs["params"] == {
        "per_page": GitHubClient.PER_PAGE,
        "type": "all",
        "page": 1,
    }


@pytest.mark.parametrize("request_number", [1, 2])
def test_get_forks_preserves_http_errors(client, request_number):
    account_response = Mock()
    account_response.json.return_value = {"type": "User"}
    failing_response = Mock()
    error = requests.HTTPError("GitHub request failed")
    failing_response.raise_for_status.side_effect = error

    if request_number == 1:
        client.session.get.return_value = failing_response
    else:
        repositories_response = Mock()
        repositories_response.links = {}
        client.session.get.side_effect = [account_response, failing_response]

    with pytest.raises(requests.HTTPError) as exc_info:
        client.get_forks("test")

    assert exc_info.value is error


def test_get_forks_propagates_json_decode_errors(client):
    account_response = Mock()
    account_response.json.side_effect = json.JSONDecodeError(
        "Invalid JSON", "", 0
    )
    client.session.get.return_value = account_response

    with pytest.raises(json.JSONDecodeError):
        client.get_forks("test")


def test_get_forks_propagates_connection_errors(client):
    error = requests.ConnectionError("Connection failed")
    client.session.get.side_effect = error

    with pytest.raises(requests.ConnectionError) as exc_info:
        client.get_forks("test")

    assert exc_info.value is error


def test_client_requires_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(ValueError, match="GITHUB_TOKEN is not configured"):
        GitHubClient()


def test_client_sets_authentication_headers(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    github_client = GitHubClient()

    assert github_client.session.headers["Authorization"] == "Bearer test-token"
    assert github_client.session.headers["Accept"] == "application/vnd.github+json"
    assert github_client.session.headers["X-GitHub-Api-Version"] == "2022-11-28"

    github_client.session.close()
