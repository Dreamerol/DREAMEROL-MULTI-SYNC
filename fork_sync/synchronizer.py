
"""GitHub Fork discovery and upstream synchronization."""

from requests import HTTPError


class ForkSynchronizer:
    """Synchronize GitHub forks with their upstream repositories."""

    def __init__(self, github_client):
        self.github = github_client

    def get_forks(self):
        """Find all forks belonging to the authenticated account."""
        repositories = self.github.list_repositories()

        return [
            repository
            for repository in repositories
            if isinstance(repository, dict)
            and repository.get("fork")
            and repository.get("parent")
        ]

    def sync_fork(self, repository):
        """Synchronize one fork with its upstream repository."""

        if not isinstance(repository, dict):
            return {
                "repository": "unknown",
                "status": "error",
                "message": "Invalid repository data.",
            }

        full_name = repository.get("full_name")
        branch = repository.get("default_branch")

        if not isinstance(full_name, str) or full_name.count("/") != 1:
            return {
                "repository": "unknown",
                "status": "error",
                "message": "Missing or invalid repository full_name.",
            }

        if not isinstance(branch, str) or not branch.strip():
            return {
                "repository": full_name,
                "status": "error",
                "message": "Missing or invalid default branch.",
            }

        try:
            result = self.github.merge_upstream(full_name, branch)

            if result is None:
                status = "up-to-date"
            else:
                status = "synced"

            return {
                "repository": full_name,
                "status": status,
            }

        except HTTPError as error:
            response = error.response
            status_code = response.status_code if response is not None else None

            if status_code == 409:
                return {
                    "repository": full_name,
                    "status": "conflict",
                    "message": "Upstream synchronization conflict.",
                }

            return {
                "repository": full_name,
                "status": "error",
                "message": str(error),
            }

        except (ValueError, KeyError, TypeError) as error:
            return {
                "repository": full_name,
                "status": "error",
                "message": str(error),
            }

    def sync_all(self):
        """Synchronize all discovered forks sequentially."""
        results = []

        for repository in self.get_forks():
            results.append(self.sync_fork(repository))

        return results
