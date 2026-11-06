from requests.exceptions import HTTPError

from fork_sync.synchronizer import ForkSynchronizer


def _repo_test_data():
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
            return _repo_test_data()

    synchronizer = ForkSynchronizer(FakeGitHubClient())
    forks = synchronizer.get_forks()

    assert len(forks) == 1
    assert forks[0]["full_name"] == "octocat/demo-fork"


def test_sync_fork_marks_up_to_date_when_response_is_none():
    class FakeGitHubClient:
        def merge_upstream(self, full_name, branch):
            assert full_name == "octocat/demo-fork"
            assert branch == "main"
            return None

    synchronizer = ForkSynchronizer(FakeGitHubClient())
    result = synchronizer.sync_fork({
        "full_name": "octocat/demo-fork",
        "default_branch": "main",
    })

    assert result["status"] == "up-to-date"
    assert result["repository"] == "octocat/demo-fork"


def test_sync_fork_reports_conflict_on_http_error():
    class ResponseStub:
        status_code = 409

    class FakeGitHubClient:
        def merge_upstream(self, full_name, branch):
            raise HTTPError(response=ResponseStub())

    synchronizer = ForkSynchronizer(FakeGitHubClient())
    result = synchronizer.sync_fork({
        "full_name": "octocat/demo-fork",
        "default_branch": "main",
    })

    assert result["status"] == "conflict"
    assert result["repository"] == "octocat/demo-fork"


def test_sync_all_can_take_precomputed_forks_in_dry_run_mode():
    class FakeGitHubClient:
        def list_repositories(self):
            return []

    synchronizer = ForkSynchronizer(FakeGitHubClient())
    results = synchronizer.sync_all(forks=_repo_test_data(), dry_run=True)

    assert results[0]["status"] == "dry-run"
    assert results[0]["repository"] == "octocat/demo-fork"


def test_sync_fork_invalid_repository_data_returns_error():
    synchronizer = ForkSynchronizer(None)
    result = synchronizer.sync_fork({})

    assert result["status"] == "error"
    assert result["repository"] == "unknown"
