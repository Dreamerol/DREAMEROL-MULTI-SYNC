
"""DREAMEROL FORK SYNC - Main entry point."""

import os

from dotenv import load_dotenv

from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer


def main():
    load_dotenv()

    token = os.getenv("GITHUB_TOKEN")

    if not token:
        print("Error: GITHUB_TOKEN is not configured.")
        return

    github = GitHubClient(token)

    try:
        user = github.get_authenticated_user()
        print(f"\nGitHub account: {user['login']}")

        synchronizer = ForkSynchronizer(github)
        forks = synchronizer.get_forks()

        print(f"Found {len(forks)} Fork repositories.\n")

        for result in synchronizer.sync_all():
            print(
                f"{result['repository']}: "
                f"{result['status']}"
            )

    finally:
        github.session.close()


if __name__ == "__main__":
    main()

