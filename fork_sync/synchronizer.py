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

    def _compare_fork(self, repo):
        """Validate fork metadata and compare its branch with its upstream."""
        if not isinstance(repo, dict):
            raise ValueError("Invalid repository data.")

        full_name = repo.get("full_name")
        fork_branch = repo.get("default_branch")
        parent = repo.get("parent")
        upstream_full_name = parent.get("full_name") if isinstance(parent, dict) else None
        upstream_branch = parent.get("default_branch") if isinstance(parent, dict) else None

        if not isinstance(full_name, str) or not full_name.strip():
            raise ValueError("Missing or invalid repository full_name.")
        full_name = full_name.strip()
        if full_name.count("/") != 1 or not all(full_name.split("/", 1)):
            raise ValueError("Invalid repository full_name.")
        if not isinstance(fork_branch, str) or not fork_branch.strip():
            raise ValueError("Missing or invalid default branch.")
        if (
            not isinstance(upstream_full_name, str)
            or not upstream_full_name.strip()
            or upstream_full_name.count("/") != 1
            or not all(upstream_full_name.strip().split("/", 1))
            or not isinstance(upstream_branch, str)
            or not upstream_branch.strip()
        ):
            raise ValueError("Missing upstream branch information.")

        comparison = self.github.compare_upstream(
            fork_full_name=full_name,
            upstream_full_name=upstream_full_name.strip(),
            upstream_branch=upstream_branch.strip(),
            fork_branch=fork_branch.strip(),
        )
        if not isinstance(comparison, dict):
            raise ValueError("Invalid comparison data returned by GitHub.")

        ahead_by = comparison.get("ahead_by")
        behind_by = comparison.get("behind_by")
        if (
            isinstance(ahead_by, bool)
            or not isinstance(ahead_by, int)
            or ahead_by < 0
            or isinstance(behind_by, bool)
            or not isinstance(behind_by, int)
            or behind_by < 0
        ):
            raise ValueError("Invalid comparison counts returned by GitHub.")

        return full_name, fork_branch.strip(), upstream_branch.strip(), ahead_by, behind_by

    @staticmethod
    def _error_result(repo, error):
        full_name = (
            repo.get("full_name", "unknown")
            if isinstance(repo, dict)
            else "unknown"
        )
        return {
            "repository": full_name,
            "status": "error",
            "message": str(error),
        }

    def preview_fork(self, repo):
        """Read-only status check for one fork; no synchronization request is sent."""
        try:
            full_name, _, _, ahead_by, behind_by = self._compare_fork(repo)
            if behind_by == 0 and ahead_by == 0:
                return {
                    "repository": full_name,
                    "status": "up-to-date",
                    "message": "No changes.",
                    "behind_by": 0,
                    "ahead_by": 0,
                }
            if behind_by > 0 and ahead_by == 0:
                return {
                    "repository": full_name,
                    "status": "behind",
                    "message": f"{behind_by} upstream commit(s) available.",
                    "behind_by": behind_by,
                    "ahead_by": ahead_by,
                }
            if ahead_by > 0 and behind_by == 0:
                return {
                    "repository": full_name,
                    "status": "ahead",
                    "message": "Fork has local commits and is not safe to merge.",
                    "behind_by": behind_by,
                    "ahead_by": ahead_by,
                }
            return {
                "repository": full_name,
                "status": "diverged",
                "message": "Fork and upstream have diverged; no automatic sync.",
                "behind_by": behind_by,
                "ahead_by": ahead_by,
            }
        except (
            requests.exceptions.RequestException,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            return self._error_result(repo, error)

    def preview_all(self, forks=None):
        """Discover and compare forks without changing any repository."""
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

        return [self.preview_fork(repository) for repository in selected_forks]

    def sync_fork(self, repo):
        """Sync a fork only when its default branch is behind upstream and safe to update."""
        try:
            full_name, fork_branch, _, ahead_by, behind_by = self._compare_fork(repo)
            if behind_by == 0 and ahead_by == 0:
                return {
                    "repository": full_name,
                    "status": "up-to-date",
                    "message": "No changes.",
                    "behind_by": 0,
                    "ahead_by": 0,
                }
            if ahead_by > 0 and behind_by == 0:
                return {
                    "repository": full_name,
                    "status": "ahead",
                    "message": "Fork has local commits and is not safe to merge.",
                    "behind_by": behind_by,
                    "ahead_by": ahead_by,
                }
            if behind_by > 0 and ahead_by > 0:
                return {
                    "repository": full_name,
                    "status": "diverged",
                    "message": "Fork and upstream have diverged; no automatic sync.",
                    "behind_by": behind_by,
                    "ahead_by": ahead_by,
                }
            if behind_by <= 0:
                return {
                    "repository": full_name,
                    "status": "up-to-date",
                    "message": "No synchronized refresh required.",
                    "behind_by": behind_by,
                    "ahead_by": ahead_by,
                }

            self.github.merge_upstream(full_name, fork_branch)
            return {
                "repository": full_name,
                "status": "synced",
                "message": f"Synced {behind_by} upstream commits.",
                "behind_by": behind_by,
                "ahead_by": ahead_by,
            }
        except requests.exceptions.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            full_name = repo.get("full_name", "unknown") if isinstance(repo, dict) else "unknown"
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
            return self._error_result(repo, error)

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
            results = []
            for repository in selected_forks:
                try:
                    results.append(self.preview_fork(repository))
                except Exception as error:
                    results.append(self._error_result(repository, error))
            return results

        results = []
        for repository in selected_forks:
            try:
                results.append(self.sync_fork(repository))
            except Exception as error:
                results.append(self._error_result(repository, error))
        return results
