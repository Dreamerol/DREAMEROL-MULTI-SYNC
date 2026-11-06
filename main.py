"""DREAMEROL FORK SYNC - Main entry point."""

import argparse
import getpass
import os
import sys

from dotenv import load_dotenv
from requests.exceptions import RequestException

from fork_sync.accounts import AccountManager
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer


def build_parser():
    parser = argparse.ArgumentParser(
        description="Synchronize GitHub forks with their upstream repositories."
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
    parser.add_argument(
        "--account",
        help="Use a saved account by GitHub username.",
    )
    return parser


def main():
    args = build_parser().parse_args()
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
        except (RequestException, ValueError, KeyError) as error:
            print(f"Could not add account: {error}", file=sys.stderr)
            return 1

    if args.list_accounts:
        saved_accounts = accounts.list_accounts()
        if not saved_accounts:
            print("No saved accounts. Add one with: python main.py --add-account")
        else:
            print("Saved accounts:")
            for username in saved_accounts:
                print(f" - {username}")
        return 0

    github = None
    try:
        if args.account:
            github = accounts.get_client(args.account)
        else:
            token = os.getenv("GITHUB_TOKEN")
            if token:
                github = GitHubClient(token)
            else:
                saved_accounts = accounts.list_accounts()
                if len(saved_accounts) == 1:
                    github = accounts.get_client(saved_accounts[0])
                elif len(saved_accounts) > 1:
                    print(
                        "More than one account is saved. Select one with "
                        "--account USERNAME:",
                        file=sys.stderr,
                    )
                    for username in saved_accounts:
                        print(f" - {username}", file=sys.stderr)
                    return 2
                else:
                    print(
                        "No token configured. Set GITHUB_TOKEN or add an account "
                        "with --add-account.",
                        file=sys.stderr,
                    )
                    return 1

        user = github.get_authenticated_user()
        print(f"\nGitHub account: {user['login']}")

        synchronizer = ForkSynchronizer(github)
        for result in synchronizer.sync_all():
            print(f"{result['repository']}: {result['status']}")

        return 0

    except (RequestException, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if github is not None:
            github.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
