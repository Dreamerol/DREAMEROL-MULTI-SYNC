import pytest
from unittest.mock import Mock

from github_client import GitHubClient


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
    second_response.json.return_value = [
        {"name": "fork-two", "fork": True}
    ]
    second_response.links = {}

    client.session.get.side_effect = [
        account_response,
        first_response,
        second_response,
    ]

    forks = client.get_forks("test")

    assert [repo["name"] for repo in forks] == [
        "fork-one",
        "fork-two",
    ]

    assert client.session.get.call_args_list[2].args[0] == (
        "https://api.github.com/users/test/repos?page=2"
    )
    assert client.session.get.call_args_list[2].kwargs["params"] is None


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
