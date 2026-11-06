"""DREAMEROL FORK SYNC - Main entry point."""

import argparse
import os
import sys

from dotenv import load_dotenv

from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer


def build_parser():
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Synchronize GitHub forks with their upstream repositories."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the repositories that would be synchronized without making changes.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip the interactive confirmation prompt before synchronizing.",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Only synchronize the provided repository name(s), e.g. --repo owner/repo.",
    )
    return parser


def prompt_for_confirmation(forks):
    """Ask the user to confirm a synchronization run."""
    if not forks:
        print("No fork repositories found to synchronize.")
        return False

    print("Repositories to synchronize:")
    for repo in forks:
        full_name = repo.get("full_name", "unknown")
        print(f" - {full_name}")

    response = input("Type 'SYNC' to continue, or anything else to cancel: ").strip()
    return response == "SYNC"


def filter_repositories(forks, requested_repos):
    """Filter repositories by full name when the user passes --repo."""
    if not requested_repos:
        return forks

    normalized = {repo_name.strip() for repo_name in requested_repos if repo_name and repo_name.strip()}
    return [
        repo
        for repo in forks
        if repo.get("full_name") in normalized
    ]


def main():
    """Run the fork synchronization workflow."""
    parser = build_parser()
    args = parser.parse_args()
    load_dotenv()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not configured.")
        return 1

    github = GitHubClient(token)

    try:
        user = github.get_authenticated_user()
        print(f"\nGitHub account: {user['login']}")

        synchronizer = ForkSynchronizer(github)
        forks = synchronizer.get_forks()
        forks = filter_repositories(forks, args.repo)

        print(f"Found {len(forks)} fork repositories.\n")

        if args.dry_run:
            for result in synchronizer.sync_all(forks=forks, dry_run=True):
                print(f"{result['repository']}: {result['status']}")
            return 0

        if not args.confirm and not prompt_for_confirmation(forks):
            print("Synchronization cancelled.")
            return 0

        for result in synchronizer.sync_all(forks=forks):
            print(f"{result['repository']}: {result['status']}")

        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    finally:
        github.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
