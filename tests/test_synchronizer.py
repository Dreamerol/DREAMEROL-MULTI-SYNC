from requests.exceptions import HTTPError

from fork_sync.synchronizer import ForkSynchronizer


def repo_data():
    return [
        {
            "full_name": "octocat/demo-fork",
            "default_branch": "main",
            "fork": True,
            "parent": {"full_name": "octodemo/upstream-repo"},
        },
        {
            "full_name": "octocat/regular-repo",
            "default_branch": "main",
            "fork": False,
            "parent": None,
        },
    ]


def test_get_forks_filters_only_forks():
    class FakeGitHubClient:
        def list_repositories(self):
            return repo_data()

    forks = ForkSynchronizer(FakeGitHubClient()).get_forks()

    assert [repo["full_name"] for repo in forks] == ["octocat/demo-fork"]


def test_sync_fork_marks_up_to_date_when_response_is_none():
    class FakeGitHubClient:
        def merge_upstream(self, full_name, branch):
            assert (full_name, branch) == ("octocat/demo-fork", "main")
            return None

    result = ForkSynchronizer(FakeGitHubClient()).sync_fork(repo_data()[0])

    assert result["status"] == "up-to-date"


def test_sync_fork_reports_conflict_on_http_error():
    class ResponseStub:
        status_code = 409

    class FakeGitHubClient:
        def merge_upstream(self, full_name, branch):
            raise HTTPError(response=ResponseStub())

    result = ForkSynchronizer(FakeGitHubClient()).sync_fork(repo_data()[0])

    assert result["status"] == "conflict"


def test_dry_run_does_not_call_merge_api():
    class FakeGitHubClient:
        def merge_upstream(self, full_name, branch):
            raise AssertionError("dry-run must not send a merge request")

    results = ForkSynchronizer(FakeGitHubClient()).sync_all(
        forks=repo_data()[:1], dry_run=True
    )

    assert results[0]["status"] == "dry-run"
    assert results[0]["repository"] == "octocat/demo-fork"


def test_sync_all_uses_precomputed_forks_without_discovery_again():
    class FakeGitHubClient:
        def list_repositories(self):
            raise AssertionError("should reuse provided fork list")

        def merge_upstream(self, full_name, branch):
            return {"merged": True}

    results = ForkSynchronizer(FakeGitHubClient()).sync_all(forks=repo_data()[:1])

    assert results[0]["status"] == "synced"


def test_sync_fork_invalid_repository_data_returns_error():
    result = ForkSynchronizer(None).sync_fork({})

    assert result["status"] == "error"
    assert result["repository"] == "unknown"
