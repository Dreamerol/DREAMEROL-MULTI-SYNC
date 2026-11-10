import json

import keyring
import pytest
from keyring.errors import PasswordDeleteError

import main
from fake_github import FakeGitHub
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


def test_remove_account_command_deletes_saved_account(fake_keyring, capsys):
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = json.dumps(["octocat"])
    fake_keyring[(SERVICE_NAME, "octocat")] = "secret"

    assert main.main(["--remove-account", "octocat"]) == 0

    assert (SERVICE_NAME, "octocat") not in fake_keyring
    output = capsys.readouterr().out
    assert "removed" in output
    assert "secret" not in output


def test_remove_account_command_rejects_unknown_account(fake_keyring, capsys):
    assert main.main(["--remove-account", "nobody"]) == 1
    assert "not registered" in capsys.readouterr().err


def test_remove_account_clears_index_when_token_is_already_gone(fake_keyring, monkeypatch):
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = json.dumps(["octocat"])

    def already_gone(_service, _username):
        raise PasswordDeleteError("missing")

    monkeypatch.setattr(keyring, "delete_password", already_gone)

    assert AccountManager().remove_account("octocat") is True
    assert AccountManager().list_accounts() == []


def test_empty_remove_account_value_never_starts_a_sync(fake_keyring, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("x", compare=(0, 1))
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "SYNC")

    assert main.main(["--remove-account", ""]) == 1

    assert "Could not remove account" in capsys.readouterr().err
    assert prompts == []
    assert github.calls == []


def test_remove_account_is_exclusive_with_other_actions():
    with pytest.raises(SystemExit):
        main.build_parser().parse_args(["--remove-account", "a", "--list-accounts"])


def test_remove_account_deletes_token_and_index(fake_keyring):
    fake_keyring[(SERVICE_NAME, ACCOUNT_INDEX)] = json.dumps(["octocat", "other"])
    fake_keyring[(SERVICE_NAME, "octocat")] = "secret"

    assert AccountManager().remove_account("octocat") is True
    assert (SERVICE_NAME, "octocat") not in fake_keyring
    assert AccountManager().list_accounts() == ["other"]
