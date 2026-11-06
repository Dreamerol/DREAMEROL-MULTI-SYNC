"""CLI workflow tests with GitHub API calls replaced by fakes."""

import main


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeGitHubClient:
    instances = []

    def __init__(self, token):
        self.token = token
        self.session = FakeSession()
        type(self).instances.append(self)

    def get_authenticated_user(self):
        return {"login": "octocat"}


class FakeSynchronizer:
    instances = []

    def __init__(self, github_client):
        self.github = github_client
        type(self).instances.append(self)

    def get_forks(self):
        return [
            {"full_name": "octocat/demo-fork", "fork": True, "parent": {}},
        ]

    def sync_all(self):
        return [{"repository": "octocat/demo-fork", "status": "synced"}]


def setup_fake_cli(monkeypatch, token="fake-token"):
    FakeGitHubClient.instances.clear()
    FakeSynchronizer.instances.clear()

    monkeypatch.setattr(main, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(main, "ForkSynchronizer", FakeSynchronizer)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)

    if token is None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_TOKEN", token)


def test_cli_runs_successful_workflow_without_network(monkeypatch, capsys):
    setup_fake_cli(monkeypatch)

    result = main.main()

    output = capsys.readouterr().out
    client = FakeGitHubClient.instances[0]

    assert result is None
    assert "GitHub account: octocat" in output
    assert "Found 1 Fork repositories." in output
    assert "octocat/demo-fork: synced" in output
    assert len(FakeSynchronizer.instances) == 1
    assert client.session.closed


def test_cli_exits_when_token_is_missing(monkeypatch, capsys):
    setup_fake_cli(monkeypatch, token=None)

    result = main.main()

    assert result is None
    assert "GITHUB_TOKEN is not configured" in capsys.readouterr().out
    assert FakeGitHubClient.instances == []


def test_cli_closes_session_if_authentication_fails(monkeypatch):
    setup_fake_cli(monkeypatch)

    def fail_authentication():
        raise RuntimeError("fake API failure")

    client = FakeGitHubClient.instances[0] if FakeGitHubClient.instances else None
    # The client is constructed by main(), so replace the class with a tracking fake.
    class FailingGitHubClient(FakeGitHubClient):
        def __init__(self, token):
            super().__init__(token)
            self.get_authenticated_user = fail_authentication

    monkeypatch.setattr(main, "GitHubClient", FailingGitHubClient)

    try:
        main.main()
    except RuntimeError as error:
        assert str(error) == "fake API failure"
    else:
        raise AssertionError("Expected the mocked authentication failure")

    assert FailingGitHubClient.instances[-1].session.closed
