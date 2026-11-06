import main


def test_parser_accepts_dry_run_and_repeatable_repository_filter():
    args = main.build_parser().parse_args([
        "--dry-run",
        "--repo", "octocat/one",
        "--repo", "octocat/two",
        "--account", "octocat",
    ])

    assert args.dry_run is True
    assert args.repo == ["octocat/one", "octocat/two"]
    assert args.account == "octocat"


def test_filter_repositories_selects_exact_matches():
    forks = [
        {"full_name": "octocat/one"},
        {"full_name": "octocat/two"},
    ]

    assert main.filter_repositories(forks, ["octocat/two"]) == [forks[1]]


def test_filter_repositories_rejects_unknown_name():
    import pytest

    with pytest.raises(ValueError, match="Not found"):
        main.filter_repositories([{"full_name": "octocat/one"}], ["octocat/missing"])


def test_confirmation_requires_exact_sync_phrase():
    forks = [{"full_name": "octocat/one"}]

    assert main.confirm_synchronization(forks, input_fn=lambda _: "SYNC", output=lambda _: None)
    assert not main.confirm_synchronization(forks, input_fn=lambda _: "sync", output=lambda _: None)


def test_confirmation_cancels_when_input_is_unavailable():
    def eof(_prompt):
        raise EOFError

    assert not main.confirm_synchronization(
        [{"full_name": "octocat/one"}], input_fn=eof, output=lambda _: None
    )


def test_add_and_list_account_actions_are_mutually_exclusive():
    import pytest

    with pytest.raises(SystemExit):
        main.build_parser().parse_args(["--add-account", "--list-accounts"])
