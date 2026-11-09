"""Explicit tokens win over .netrc, stay with their own request, and never leak.

These tests run the real requests session stack and replace only the transport
adapter, so credential handling inside requests itself is exercised. All tokens
and .netrc files are dummies created in a temporary directory.
"""

import io
import json
import threading
import time

import pytest
import requests
from fastapi.testclient import TestClient

import main
from api.app import app
from fork_sync import accounts as accounts_module
from fork_sync.accounts import ACCOUNT_INDEX, SERVICE_NAME
from fork_sync.github import GitHubClient, NoNetrcSession

TOKEN_A = "dummy-token-user-a-5f1e"
TOKEN_B = "dummy-token-user-b-9c3d"
NETRC_PASSWORD = "netrc-password-should-never-be-sent"


class Transport:
    """Stands in for the network. Each token sees its own GitHub account."""

    def __init__(self, redirect_to=None, failure=None, delay=0.0):
        self.sent = []
        self.redirect_to = redirect_to
        self.failure = failure
        self.delay = delay
        self.lock = threading.Lock()

    def __call__(self, request, **kwargs):
        # Installed as HTTPAdapter.send; an instance is not bound, so no adapter arg.
        authorization = request.headers.get("Authorization")
        with self.lock:
            self.sent.append((request.method, request.url, authorization))
            first = len(self.sent) == 1
        if self.delay:
            time.sleep(self.delay)
        if self.failure is not None:
            if isinstance(self.failure, Exception):
                raise self.failure
            return self._reply(request, self.failure, {"message": "Bad credentials"})
        if self.redirect_to and first:
            return self._reply(request, 302, {}, {"Location": self.redirect_to})
        if request.url.endswith("/user"):
            login = "anonymous"
            if authorization and authorization.startswith("Bearer "):
                login = "login-for-" + authorization.removeprefix("Bearer ")[-4:]
            return self._reply(request, 200, {"login": login})
        if "/user/repos" in request.url:
            return self._reply(request, 200, [])
        return self._reply(request, 200, {"ok": True})

    @staticmethod
    def _reply(request, status, body, headers=None):
        response = requests.Response()
        response.status_code = status
        response.request = request
        response.url = request.url
        response.raw = io.BytesIO(json.dumps(body).encode())
        response.encoding = "utf-8"
        response.headers.update(headers or {})
        return response

    def authorizations(self):
        return [authorization for _method, _url, authorization in self.sent]


@pytest.fixture
def transport(monkeypatch):
    fake = Transport()
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake)
    return fake


@pytest.fixture
def netrc(tmp_path, monkeypatch):
    """A server-level .netrc, both via NETRC and in the home directory."""
    content = "".join(
        f"machine {host} login server-user password {NETRC_PASSWORD}\n"
        for host in ("api.github.com", "redirect.example.invalid", "public.example.invalid")
    )
    path = tmp_path / ".netrc"
    path.write_text(content)
    (tmp_path / "_netrc").write_text(content)
    monkeypatch.setenv("NETRC", str(path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return path


def test_netrc_fixture_would_be_used_by_a_plain_session(netrc, transport):
    """Guards the other tests: without the fix, requests really does use it."""
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {TOKEN_A}"

    session.get("https://api.github.com/user")

    assert transport.authorizations()[0].startswith("Basic ")


def test_explicit_token_is_used_for_reads_and_merges_despite_netrc(netrc, transport):
    client = GitHubClient(TOKEN_A)

    client.get_authenticated_user()
    client.list_repositories()
    client.merge_upstream("demo/x", "main")

    assert transport.authorizations() == [f"Bearer {TOKEN_A}"] * 3
    assert [method for method, _url, _auth in transport.sent] == ["GET", "GET", "POST"]


def test_netrc_credentials_are_never_sent(netrc, transport):
    client = GitHubClient(TOKEN_A)

    client.get_authenticated_user()

    assert not any("Basic" in str(auth) for auth in transport.authorizations())
    assert NETRC_PASSWORD not in json.dumps(transport.sent)


def test_unauthenticated_session_does_not_inherit_netrc(netrc, transport):
    response = NoNetrcSession().get("https://public.example.invalid/data")

    assert response.status_code == 200
    assert transport.authorizations() == [None]


def test_public_unauthenticated_request_still_works_without_netrc(transport, monkeypatch, tmp_path):
    monkeypatch.setenv("NETRC", str(tmp_path / "missing"))

    response = NoNetrcSession().get("https://public.example.invalid/data")

    assert response.json() == {"ok": True}
    assert transport.authorizations() == [None]


def test_redirect_to_another_host_drops_token_and_adds_no_netrc(netrc, monkeypatch):
    fake = Transport(redirect_to="https://redirect.example.invalid/elsewhere")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake)

    GitHubClient(TOKEN_A).get_authenticated_user()

    assert fake.authorizations() == [f"Bearer {TOKEN_A}", None]


def test_redirect_on_same_host_keeps_explicit_token(netrc, monkeypatch):
    fake = Transport(redirect_to="https://api.github.com/user")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake)

    GitHubClient(TOKEN_A).get_authenticated_user()

    assert fake.authorizations() == [f"Bearer {TOKEN_A}"] * 2


def test_environment_proxy_settings_still_apply(netrc, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:3128")
    session = GitHubClient(TOKEN_A).session

    settings = session.merge_environment_settings("https://api.github.com/user", {}, None, None, None)

    assert settings["proxies"]["https"] == "http://proxy.example.invalid:3128"


def test_clients_never_share_sessions_or_credentials(netrc, transport):
    first, second = GitHubClient(TOKEN_A), GitHubClient(TOKEN_B)

    second.get_authenticated_user()
    first.get_authenticated_user()

    assert first.session is not second.session
    assert transport.authorizations() == [f"Bearer {TOKEN_B}", f"Bearer {TOKEN_A}"]
    assert "Authorization" not in first.session.headers


def test_token_is_not_exposed_by_object_representations():
    client = GitHubClient(TOKEN_A)

    assert TOKEN_A not in repr(client.session.auth)
    assert TOKEN_A not in repr(vars(client.session).get("headers"))


# Web


def web(token, payload=None):
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            "/api/sync",
            json=payload or {"dry_run": True},
            headers={"Authorization": f"Bearer {token}"},
        )


def test_web_users_keep_their_own_tokens_despite_server_netrc(netrc, transport):
    reply_a = web(TOKEN_A)
    reply_b = web(TOKEN_B)

    assert reply_a.json()["account"] == "login-for-" + TOKEN_A[-4:]
    assert reply_b.json()["account"] == "login-for-" + TOKEN_B[-4:]
    sent = transport.authorizations()
    assert sent[:2] == [f"Bearer {TOKEN_A}"] * 2
    assert sent[2:] == [f"Bearer {TOKEN_B}"] * 2


def test_concurrent_web_users_never_receive_each_others_credentials(netrc, monkeypatch):
    fake = Transport(delay=0.02)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake)
    tokens = [f"dummy-concurrent-{index:02d}" for index in range(8)]
    replies = {}

    def run(token):
        replies[token] = web(token).json()["account"]

    threads = [threading.Thread(target=run, args=(token,)) for token in tokens]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert replies == {token: "login-for-" + token[-4:] for token in tokens}
    by_token = {}
    for _method, _url, authorization in fake.sent:
        by_token.setdefault(authorization, 0)
        by_token[authorization] += 1
    assert by_token == {f"Bearer {token}": 2 for token in tokens}


def test_web_still_rejects_missing_or_non_bearer_credentials(netrc, transport):
    with TestClient(app) as client:
        missing = client.post("/api/sync", json={"dry_run": True})
        basic = client.post(
            "/api/sync", json={"dry_run": True}, headers={"Authorization": "Basic abc"}
        )

    assert missing.status_code == 401
    assert basic.status_code == 401
    assert transport.sent == []


@pytest.mark.parametrize(
    "failure, status",
    [(401, 401), (403, 403), (500, 502), (requests.ConnectionError(f"refused {TOKEN_A[:6]}"), 502)],
)
def test_web_errors_do_not_expose_credentials(netrc, monkeypatch, failure, status):
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", Transport(failure=failure))

    reply = web(TOKEN_A)

    assert reply.status_code == status
    assert TOKEN_A not in reply.text
    assert "Authorization" not in reply.text
    assert NETRC_PASSWORD not in reply.text


# CLI


@pytest.mark.parametrize("failure", [401, 500, requests.ConnectionError("refused")])
def test_cli_errors_do_not_expose_credentials(netrc, monkeypatch, capsys, failure):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN_A)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", Transport(failure=failure))

    assert main.main(["--dry-run"]) == 1

    output = "".join(capsys.readouterr())
    assert TOKEN_A not in output
    assert "Authorization" not in output
    assert NETRC_PASSWORD not in output


def test_cli_environment_token_is_used_despite_netrc(netrc, transport, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN_A)

    assert main.main(["--dry-run"]) == 0

    assert set(transport.authorizations()) == {f"Bearer {TOKEN_A}"}
    assert TOKEN_A not in capsys.readouterr().out


def test_cli_saved_account_token_is_used_despite_netrc(netrc, transport, monkeypatch):
    store = {
        (SERVICE_NAME, ACCOUNT_INDEX): json.dumps(["octocat"]),
        (SERVICE_NAME, "octocat"): TOKEN_B,
    }
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(accounts_module.keyring, "get_password", lambda s, u: store.get((s, u)))

    assert main.main(["--dry-run", "--account", "octocat"]) == 0

    assert set(transport.authorizations()) == {f"Bearer {TOKEN_B}"}


def test_cli_add_account_validates_with_the_entered_token(netrc, transport, monkeypatch):
    store = {}
    monkeypatch.setattr(accounts_module.keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(
        accounts_module.keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p)
    )
    monkeypatch.setattr("getpass.getpass", lambda prompt: TOKEN_A)

    assert main.main(["--add-account"]) == 0

    assert transport.authorizations() == [f"Bearer {TOKEN_A}"]
    assert store[(SERVICE_NAME, "login-for-" + TOKEN_A[-4:])] == TOKEN_A
