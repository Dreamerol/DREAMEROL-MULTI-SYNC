
"""GitHub Fork discovery and upstream synchronization."""

from requests import HTTPError


class ForkSynchronizer:
    """Synchronizes GitHub forks with their upstream repositories."""

    def __init__(self, github_client):
        self.github = github_client

    def get_forks(self):
        """Find all forks belonging to the authenticated account."""
        repositories = self.github.list_repositories()

        return [
            repository
            for repository in repositories
            if repository.get("fork") and repository.get("parent")
        ]

    def sync_fork(self, repository):
        """Synchronize a fork with its upstream repository."""
        owner, name = repository["full_name"].split("/", 1)
        branch = repository["default_branch"]

        endpoint = (
            f"{self.github.BASE_URL}/repos/"
            f"{owner}/{name}/merge-upstream"
        )

        try:
            response = self.github.session.post(
                endpoint,
                json={"branch": branch},
                timeout=30,
            )

            if response.status_code == 204:
                return {
                    "repository": repository["full_name"],
                    "status": "up-to-date",
                }

            if response.status_code == 409:
                return {
                    "repository": repository["full_name"],
                    "status": "conflict",
                }

            response.raise_for_status()

            return {
                "repository": repository["full_name"],
                "status": "synced",
                "details": response.json(),
            }

        except HTTPError as error:
            return {
                "repository": repository["full_name"],
                "status": "error",
                "message": str(error),
            }

    def sync_all(self):
        """Synchronize all discovered forks sequentially."""
        results = []

        for repository in self.get_forks():
            results.append(self.sync_fork(repository))

        return results

