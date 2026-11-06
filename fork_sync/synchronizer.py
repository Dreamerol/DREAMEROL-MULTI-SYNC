
"""GitHub Fork discovery and upstream synchronization."""

from requests import HTTPError


class ForkSynchronizer:
    """Synchronize GitHub forks with their upstream repositories."""

    def __init__(self, github_client):
        self.github = github_client

    def get_forks(self):
        """Find all forks owned by the authenticated account."""
        repositories = self.github.list_repositories()

        return [
            repository
            for repository in repositories
            if repository.get("fork") and repository.get("parent")
        ]

    def sync_fork(self, repository):
        """Synchronize a fork with its upstream default branch."""
        full_name = repository["full_name"]
        branch = repository.get("default_branch")

        if not branch:
            return {
                "repository": full_name,
                "status": "error",
                "message": "Default branch not found.",
            }

        try:
            result = self.github.merge_upstream(full_name, branch)

            return {
                "repository": full_name,
                "status": "success",
                "details": result,
            }

        except HTTPError as error:
            status_code = (
                error.response.status_code
                if error.response is not None
                else None
            )

            return {
                "repository": full_name,
                "status": (
                    "conflict" if status_code == 409 else "error"
                ),
                "message": str(error),
            }

    def sync_all(self):
        """Synchronize all discovered forks sequentially."""
        results = []

        for repository in self.get_forks():
            results.append(self.sync_fork(repository))

        return results
