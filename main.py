"""DREAMEROL FORK SYNC - Main entry point."""

import argparse
import getpass
import os
import sys

from dotenv import load_dotenv
from requests.exceptions import RequestException

from fork_sync.accounts import AccountManager
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer, describe_summary, has_failures


def build_parser():
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Safely synchronize GitHub forks with their upstream repositories."
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--add-account",
        action="store_true",
        help="Add an account; its token is requested securely.",
    )
    actions.add_argument(
        "--list-accounts",
        action="store_true",
        help="List accounts saved in the system keyring.",
    )
    actions.add_argument(
        "--remove-account",
        metavar="USERNAME",
        help="Delete a saved account and its token from the system keyring.",
    )
    parser.add_argument(
        "--account",
        help="Use a saved account by GitHub username.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compare selected forks with upstream without changing them.",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="OWNER/REPO",
        help="Only select this fork (repeat to select multiple repositories).",
    )
    return parser


def select_skipped(skipped, requested_repositories):
    """Keep skipped-fork results relevant to the requested selection."""
    if not requested_repositories:
        return skipped
    requested = {name.strip() for name in requested_repositories}
    return [result for result in skipped if result["repository"] in requested]


def filter_repositories(forks, requested_repositories, skipped=()):
    """Select forks by exact owner/repository name; reject unknown selections."""
    if not requested_repositories:
        return forks

    requested = {name.strip() for name in requested_repositories if name.strip()}
    available = {
        repo.get("full_name")
        for repo in forks
        if isinstance(repo, dict) and isinstance(repo.get("full_name"), str)
    }
    available |= {result["repository"] for result in skipped}
    missing = sorted(requested - available)
    if missing:
        raise ValueError(
            "Not found among this account's forks: " + ", ".join(missing)
        )

    return [
        repo for repo in forks
        if isinstance(repo, dict) and repo.get("full_name") in requested
    ]


def confirm_synchronization(forks, input_fn=None, output=print):
    """Require an explicit typed confirmation before changing any fork."""
    if not forks:
        output("No fork repositories selected.")
        return False

    input_fn = input_fn or input
    output("These forks are behind upstream and their default branches will be updated:")
    for repo in forks:
        output(f" - {repo.get('full_name', 'unknown')}")
    try:
        response = input_fn("Type SYNC to continue, or anything else to cancel: ")
    except (EOFError, OSError):
        return False
    return response.strip() == "SYNC"


def _get_github_client(args, accounts):
    """Resolve the requested credential source and return a GitHub client."""
    if args.account:
        return accounts.get_client(args.account)

    token = os.getenv("GITHUB_TOKEN")
    if token:
        return GitHubClient(token)

    saved_accounts = accounts.list_accounts()
    if len(saved_accounts) == 1:
        return accounts.get_client(saved_accounts[0])
    if len(saved_accounts) > 1:
        raise ValueError(
            "More than one account is saved; select one with --account USERNAME. "
            "Saved accounts: " + ", ".join(saved_accounts)
        )
    raise ValueError(
        "No token configured. Set GITHUB_TOKEN or add an account with --add-account."
    )


def _print_results(results):
    for result in results:
        print(f"{result['repository']}: {result['status']}")
        if result.get("message"):
            print(f"  {result['message']}")


def main(argv=None):
    """Run account management or the fork synchronization workflow."""
    args = build_parser().parse_args(argv)
    load_dotenv()
    accounts = AccountManager()

    if args.add_account:
        token = getpass.getpass("GitHub token (input hidden): ").strip()
        if not token:
            print("Error: token cannot be empty.", file=sys.stderr)
            return 1
        try:
            username = accounts.add_account(token)
            print(f"Account '{username}' added to the system keyring.")
            return 0
        except Exception as error:
            print(f"Could not add account: {error}", file=sys.stderr)
            return 1

    if args.list_accounts:
        try:
            saved_accounts = accounts.list_accounts()
        except Exception as error:
            print(f"Could not read saved accounts: {error}", file=sys.stderr)
            return 1
        if not saved_accounts:
            print("No saved accounts. Add one with: python main.py --add-account")
        else:
            print("Saved accounts:")
            for username in saved_accounts:
                print(f" - {username}")
        return 0

    if args.remove_account is not None:
        try:
            accounts.remove_account(args.remove_account)
        except Exception as error:
            print(f"Could not remove account: {error}", file=sys.stderr)
            return 1
        print(f"Account '{args.remove_account}' removed from the system keyring.")
        return 0

    github = None
    try:
        github = _get_github_client(args, accounts)
        user = github.get_authenticated_user()
        if not isinstance(user, dict) or not user.get("login"):
            raise ValueError("GitHub returned invalid authenticated-user data.")
        print(f"\nGitHub account: {user['login']}")

        synchronizer = ForkSynchronizer(github)
        discovery = synchronizer.discover_forks()
        forks = filter_repositories(discovery.forks, args.repo, discovery.skipped)
        skipped = select_skipped(discovery.skipped, args.repo)
        print(f"Selected {len(forks)} fork repository/repositories.")
        if skipped:
            print(f"Skipped {len(skipped)} repository/repositories that could not be used.")
        print()

        previews = synchronizer.preview_all(forks)
        candidates = [
            fork for fork, preview in zip(forks, previews)
            if preview["status"] == "behind"
        ]

        if args.dry_run or not candidates:
            results = skipped + previews
        elif confirm_synchronization(candidates):
            # sync_fork compares again, because the prompt can wait indefinitely.
            synced = iter(synchronizer.sync_all(forks=candidates))
            results = skipped + [
                next(synced) if preview["status"] == "behind" else preview
                for preview in previews
            ]
        else:
            print("Synchronization cancelled. No repositories were changed.")
            results = skipped + previews

        if not results:
            print("No fork repositories found for this account.")
        else:
            _print_results(results)
            print(f"\nSummary: {describe_summary(results)}")
            if has_failures(results):
                print("Completed with problems; some repositories need attention.")
        return 1 if has_failures(results) else 0

    except (RequestException, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1
    finally:
        if github is not None:
            github.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
