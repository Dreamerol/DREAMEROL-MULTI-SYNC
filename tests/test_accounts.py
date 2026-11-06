import pytest

from fork_sync import accounts as accounts_module
from fork_sync.accounts import AccountManager, SERVICE_NAME


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeGitHubClient:
    def __init__(self, token):
        self.token = token
        self.session = FakeSession()

    def get_authenticated_user(self):
        return {"login": "octocat"}


@pytest.fixture
def fake_keyring(monkeypatch):
    store = {}

    monkeypatch.setattr(
        accounts_module.keyring,
        "get_password",
        lambda service, username: store.get((service, username)),
    )
    monkeypatch.setattr(
        accounts_module.keyring,
        "set_password",
        lambda service, username, password: store.__setitem__(
            (service, username), password
        ),
    )
    monkeypatch.setattr(
        accounts_module.keyring,
        "delete_password",
        lambda service, username: store.pop((service, username)),
    )
    monkeypatch.setattr(
        accounts_module,
        "GitHubClient",
        FakeGitHubClient,
    )
    return store


def test_add_account_validates_and_stores_token(fake_keyring):
    manager = AccountManager()

    username = manager.add_account("test-token")

    assert username == "octocat"
    assert fake_keyring[(SERVICE_NAME, "octocat")] == "test-token"
    assert manager.list_accounts() == ["octocat"]


def test_add_account_closes_validation_client(fake_keyring, monkeypatch):
    clients = []

    class TrackingClient(FakeGitHubClient):
        def __init__(self, token):
            super().__init__(token)
            clients.append(self)

    monkeypatch.setattr(accounts_module, "GitHubClient", TrackingClient)

    AccountManager().add_account("test-token")

    assert clients[0].session.closed


def test_get_client_uses_token_from_keyring(fake_keyring):
    fake_keyring[(SERVICE_NAME, "octocat")] = "stored-token"

    client = AccountManager().get_client("octocat")

    assert client.token == "stored-token"


def test_get_client_raises_when_token_is_missing(fake_keyring):
    with pytest.raises(ValueError, match="No credentials"):
        AccountManager().get_client("unknown")


def test_remove_account_deletes_saved_token(fake_keyring):
    manager = AccountManager()
    manager.accounts["octocat"] = "octocat"
    fake_keyring[(SERVICE_NAME, "octocat")] = "stored-token"

    assert manager.remove_account("octocat") is True
    assert (SERVICE_NAME, "octocat") not in fake_keyring
    assert manager.list_accounts() == []


def test_remove_account_rejects_unknown_username(fake_keyring):
    with pytest.raises(ValueError, match="Account not found"):
        AccountManager().remove_account("unknown")
