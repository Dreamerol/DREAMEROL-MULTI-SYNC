import json

import keyring
import pytest

from fork_sync import accounts as accounts_module
from fork_sync.accounts import ACCOUNT_INDEX, SERVICE_NAME, AccountManager


@pytest.fixture

def fake_keyring(monkeypatch):
    store = {}
    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda service, username: store.get((service, username)),
    )
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda service, username, password: store.__setitem__((service, username), password),
    )
    monkeypatch.setattr(
        keyring,
        "delete_password",
        lambda service, username: store.pop((service, username)),
    )
    return store


class FakeClient:
    def __init__(self, token):
        self.token = token
        self.session = type("Session", (), {"close": lambda self: None})()

    def get_authenticated_user(self):
        return {"login": "octocat"}


def test_list_accounts_loads_persisted_index(fake_keyring):
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = json.dumps(["zoe", "octocat"])

    assert AccountManager().list_accounts() == ["octocat", "zoe"]


def test_list_accounts_handles_invalid_index(fake_keyring):
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = "not-json"

    assert AccountManager().list_accounts() == []


def test_add_account_saves_token_and_username(monkeypatch, fake_keyring):
    monkeypatch.setattr(accounts_module, "GitHubClient", FakeClient)

    username = AccountManager().add_account(" token ")

    assert username == "octocat"
    assert fake_keyring[(SERVICE_NAME, "octocat")] == "token"
    assert AccountManager().list_accounts() == ["octocat"]


def test_get_client_rejects_unregistered_account(monkeypatch, fake_keyring):
    monkeypatch.setattr(accounts_module, "GitHubClient", FakeClient)

    with pytest.raises(ValueError, match="not registered"):
        AccountManager().get_client("unknown")


def test_get_client_uses_saved_token(monkeypatch, fake_keyring):
    monkeypatch.setattr(accounts_module, "GitHubClient", FakeClient)
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = json.dumps(["octocat"])
    fake_keyring[(SERVICE_NAME, "octocat")] = "secret"

    client = AccountManager().get_client("octocat")

    assert client.token == "secret"


def test_remove_account_deletes_token_and_index(fake_keyring):
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = json.dumps(["octocat", "other"])
    fake_keyring[(SERVICE_NAME, "octocat")] = "secret"

    assert AccountManager().remove_account("octocat") is True
    assert (SERVICE_NAME, "octocat") not in fake_keyring
    assert AccountManager().list_accounts() == ["other"]
