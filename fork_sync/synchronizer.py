"""GitHub Fork discovery and upstream synchronization."""

import requests


class ForkSynchronizer:
    """Synchronize GitHub forks with their upstream repositories."""

    def __init__(self, github_client):
        self.github = github_client

    def get_forks(self):
        """Find valid forks belonging to the authenticated account."""
        repositories = self.github.list_repositories()
        if not isinstance(repositories, list):
            raise ValueError("Invalid repository list returned by GitHub.")

        forks = []
        for repository in repositories:
            if not isinstance(repository, dict) or not repository.get("fork"):
                continue

            parent = repository.get("parent")
            if not isinstance(parent, dict):
                continue

            upstream_full_name = parent.get("full_name")
            upstream_branch = parent.get("default_branch")
            if (
                not isinstance(upstream_full_name, str)
                or not upstream_full_name.strip()
                or not isinstance(upstream_branch, str)
                or not upstream_branch.strip()
            ):
                continue

            forks.append(repository)

        return forks

    def sync_fork(self, repo):
        """Sync a fork only when its default branch is behind upstream."""
        if not isinstance(repo, dict):
            return {
                "repository": "unknown",
                "status": "error",
                "message": "Invalid repository data.",
            }

        full_name = repo.get("full_name")
        fork_branch = repo.get("default_branch")
        parent = repo.get("parent")
        upstream_full_name = (
            parent.get("full_name") if isinstance(parent, dict) else None
        )
        upstream_branch = (
            parent.get("default_branch") if isinstance(parent, dict) else None
        )

        if not isinstance(full_name, str) or not full_name.strip():
            return {
                "repository": "unknown",
                "status": "error",
                "message": "Missing or invalid repository full_name.",
            }
        full_name = full_name.strip()
        if full_name.count("/") != 1 or not all(full_name.split("/", 1)):
            return {
                "repository": full_name,
                "status": "error",
                "message": "Invalid repository full_name.",
            }

        if not isinstance(fork_branch, str) or not fork_branch.strip():
            return {
                "repository": full_name,
                "status": "error",
                "message": "Missing or invalid default branch.",
            }
        fork_branch = fork_branch.strip()

        if (
            not isinstance(upstream_full_name, str)
            or not upstream_full_name.strip()
            or upstream_full_name.count("/") != 1
            or not all(upstream_full_name.strip().split("/", 1))
            or not isinstance(upstream_branch, str)
            or not upstream_branch.strip()
        ):
            return {
                "repository": full_name,
                "status": "error",
                "message": "Missing upstream branch information.",
            }
        upstream_full_name = upstream_full_name.strip()
        upstream_branch = upstream_branch.strip()

        try:
            comparison = self.github.compare_upstream(
                fork_full_name=full_name,
                upstream_full_name=upstream_full_name,
                upstream_branch=upstream_branch,
                fork_branch=fork_branch,
            )
            if not isinstance(comparison, dict):
                raise ValueError("Invalid comparison data returned by GitHub.")

            behind_by = comparison.get("behind_by")
            if (
                isinstance(behind_by, bool)
                or not isinstance(behind_by, int)
                or behind_by < 0
            ):
                raise ValueError(
                    "Invalid behind_by value returned by GitHub."
                )
            if behind_by == 0:
                return {
                    "repository": full_name,
                    "status": "up-to-date",
                    "message": "No changes.",
                }

            self.github.merge_upstream(full_name, upstream_branch)
            return {
                "repository": full_name,
                "status": "synced",
                "message": f"Synced {behind_by} upstream commits.",
            }
        except requests.exceptions.HTTPError as error:
            status_code = (
                error.response.status_code
                if error.response is not None
                else None
            )
            return {
                "repository": full_name,
                "status": "conflict" if status_code == 409 else "error",
                "message": str(error),
            }
        except (
            requests.exceptions.RequestException,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            return {
                "repository": full_name,
                "status": "error",
                "message": str(error),
            }

    def sync_all(self, forks=None, dry_run=False):
        """Process each fork independently so one failure cannot stop others."""
        try:
            selected_forks = forks if forks is not None else self.get_forks()
        except (
            requests.exceptions.RequestException,
            ValueError,
            TypeError,
        ) as error:
            return [{
                "repository": "account",
                "status": "error",
                "message": str(error),
            }]

        if dry_run:
            return [
                {
                    "repository": repo.get("full_name", "unknown"),
                    "status": "dry-run",
                    "message": "Would synchronize fork with upstream.",
                }
                for repo in selected_forks
                if isinstance(repo, dict)
            ]

        results = []
        for repository in selected_forks:
            try:
                results.append(self.sync_fork(repository))
            except Exception as error:
                # Keep an unexpected per-repository failure from stopping the batch.
                full_name = (
                    repository.get("full_name", "unknown")
                    if isinstance(repository, dict)
                    else "unknown"
                )
                results.append({
                    "repository": full_name,
                    "status": "error",
                    "message": str(error),
                })
        return results
