"""The CLI and the web API must agree, because they share one decision path."""

import pytest
from fastapi.testclient import TestClient

import main
from api.app import app
from fake_github import FakeGitHub

STATES = {
    "behind": ((0, 4), "behind"),
    "same": ((0, 0), "up-to-date"),
    "ahead": ((2, 0), "ahead"),
    "split": ((2, 3), "diverged"),
    "gone": (404, "error"),
}


def populated(monkeypatch):
    github = FakeGitHub().install(monkeypatch)
    for name, (compare, _status) in STATES.items():
        github.add_fork(name, compare=compare)
    github.add_fork("renamed", default_branch="master")
    github.add_fork("old", archived=True)
    github.add_fork("broken", details=500)
    return github


EXPECTED = {
    **{f"demo/{name}": status for name, (_compare, status) in STATES.items()},
    "demo/renamed": "branch-mismatch",
    "demo/old": "unavailable",
    "demo/broken": "skipped",
}


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")


def post(payload):
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            "/api/sync", json=payload, headers={"Authorization": "Bearer test-token"}
        )


def parse_cli(output):
    results = {}
    for line in output.splitlines():
        name, separator, status = line.partition(": ")
        if separator and name.startswith("demo/"):
            results[name] = status
    return results


def type_at_prompt(monkeypatch, answer):
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_cli_dry_run_reports_real_states(monkeypatch, capsys):
    github = populated(monkeypatch)

    assert main.main(["--dry-run"]) == 1

    assert parse_cli(capsys.readouterr().out) == EXPECTED
    assert github.merged == []


def test_cli_dry_run_cannot_reach_live_sync_even_if_input_says_sync(monkeypatch, capsys):
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("x", compare=(0, 2))
    prompts = type_at_prompt(monkeypatch, "SYNC")

    assert main.main(["--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "demo/x: behind" in output
    assert "will be updated" not in output
    assert prompts == []
    assert github.merged == []
    assert github.merge_bodies == []


FORK_OF_FORK = {"source": {"full_name": "root/x", "default_branch": "main"}}


def test_fork_of_fork_is_refused_consistently_by_cli_and_web(monkeypatch, capsys):
    prompts = type_at_prompt(monkeypatch, "SYNC")
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("x", compare=(0, 2), **FORK_OF_FORK)

    assert main.main([]) == 0
    assert parse_cli(capsys.readouterr().out) == {"demo/x": "upstream-unverified"}
    assert prompts == []
    assert github.merged == []

    github = FakeGitHub().install(monkeypatch)
    github.add_fork("x", compare=(0, 2), **FORK_OF_FORK)
    preview = post({"dry_run": True}).json()
    live = post({"dry_run": False, "confirmation": "SYNC", "repositories": ["demo/x"]}).json()

    assert preview["results"][0]["status"] == "upstream-unverified"
    assert live["results"][0]["status"] == "upstream-unverified"
    assert github.merged == []
    assert github.count("GET", "/compare/") == 0


def test_cli_and_web_preview_agree(monkeypatch, capsys):
    populated(monkeypatch)
    main.main(["--dry-run"])
    cli_results = parse_cli(capsys.readouterr().out)

    populated(monkeypatch)
    reply = post({"dry_run": True}).json()

    assert {item["repository"]: item["status"] for item in reply["results"]} == cli_results


def test_web_preview_exposes_ahead_by_and_summary(monkeypatch):
    populated(monkeypatch)

    reply = post({"dry_run": True}).json()
    by_name = {item["repository"]: item for item in reply["results"]}

    assert by_name["demo/split"]["ahead_by"] == 2
    assert by_name["demo/split"]["behind_by"] == 3
    assert reply["summary"]["diverged"] == 1
    assert reply["summary"]["ahead"] == 1
    assert sum(reply["summary"].values()) == reply["total"] == len(EXPECTED)
    assert reply["has_failures"] is True


def test_cli_prompt_lists_only_behind_forks(monkeypatch, capsys):
    github = populated(monkeypatch)
    type_at_prompt(monkeypatch, "cancel")

    assert main.main([]) == 1

    output = capsys.readouterr().out
    prompt_section = output.split("will be updated:")[1].split("Synchronization cancelled")[0]
    assert "demo/behind" in prompt_section
    for name in ("same", "ahead", "split", "gone", "renamed", "old"):
        assert f"demo/{name}" not in prompt_section
    assert "No repositories were changed" in output
    assert github.merged == []


def test_cli_live_merges_only_behind_and_preserves_other_statuses(monkeypatch, capsys):
    github = populated(monkeypatch)
    type_at_prompt(monkeypatch, "SYNC")

    assert main.main([]) == 1

    results = parse_cli(capsys.readouterr().out)
    assert github.merged == ["demo/behind"]
    assert results == {**EXPECTED, "demo/behind": "synced"}


def test_cli_does_not_prompt_when_nothing_is_behind(monkeypatch, capsys):
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("same")
    prompts = type_at_prompt(monkeypatch, "SYNC")

    assert main.main([]) == 0
    assert prompts == []
    assert github.merged == []


def test_cli_rechecks_after_the_prompt(monkeypatch, capsys):
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("x", compare=[(0, 2), (1, 2)])
    type_at_prompt(monkeypatch, "SYNC")

    assert main.main([]) == 0
    assert "demo/x: diverged" in capsys.readouterr().out
    assert github.merged == []


@pytest.mark.parametrize("merge_type, status", [("fast-forward", "synced"), ("merge", "merged")])
def test_cli_and_web_live_results_agree(monkeypatch, capsys, merge_type, status):
    def build():
        github = FakeGitHub().install(monkeypatch)
        github.add_fork("x", compare=(0, 2), merge=(200, {"merge_type": merge_type}))
        return github

    build()
    type_at_prompt(monkeypatch, "SYNC")
    main.main([])
    assert parse_cli(capsys.readouterr().out) == {"demo/x": status}

    build()
    reply = post({"dry_run": False, "confirmation": "SYNC", "repositories": ["demo/x"]}).json()
    assert reply["results"][0]["status"] == status
    assert reply["results"][0]["merge_type"] == merge_type
    assert reply["summary"] == {status: 1}


def test_web_live_processes_only_selection_in_requested_order(monkeypatch):
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("a", compare=(0, 1))
    github.add_fork("b", compare=(0, 1))
    github.add_fork("c", compare=(1, 1))

    reply = post({"dry_run": False, "confirmation": "SYNC", "repositories": ["demo/c", "demo/a"]}).json()

    assert [item["repository"] for item in reply["results"]] == ["demo/c", "demo/a"]
    assert [item["status"] for item in reply["results"]] == ["diverged", "synced"]
    assert github.merged == ["demo/a"]


@pytest.mark.parametrize(
    "payload",
    [
        {"dry_run": False},
        {"dry_run": False, "confirmation": "sync", "repositories": ["demo/a"]},
        {"dry_run": False, "confirmation": "SYNC"},
        {"dry_run": False, "confirmation": "SYNC", "repositories": []},
        {"dry_run": False, "confirmation": "SYNC", "repositories": ["demo/a", "demo/a"]},
        {"dry_run": False, "confirmation": "SYNC", "repositories": ["other/repo"]},
    ],
)
def test_web_live_rejections_never_merge(monkeypatch, payload):
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("a", compare=(0, 1))

    assert post(payload).status_code == 400
    assert github.merged == []


def test_wrong_confirmation_in_cli_never_merges(monkeypatch, capsys):
    github = FakeGitHub().install(monkeypatch)
    github.add_fork("a", compare=(0, 1))
    type_at_prompt(monkeypatch, "sync")

    assert main.main([]) == 0
    assert github.merged == []
