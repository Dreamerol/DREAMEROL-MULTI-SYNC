"""GitHub Fork discovery and upstream synchronization."""

from requests.exceptions import HTTPError, RequestException


class ForkSynchronizer:
    """Synchronize GitHub forks with their upstream repositories."""

    def __init__(self, github_client):
        self.github = github_client

    def get_forks(self):
        """Find all forks belonging to the authenticated account."""
        repositories = self.github.list_repositories()
        if not isinstance(repositories, list):
            raise ValueError("Invalid repository list returned by GitHub.")
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
        if not isinstance(full_name, str):
            return {
                "repository": "unknown",
                "status": "error",
                "message": "Missing or invalid repository full_name.",
            }

        parts = full_name.strip().split("/")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            return {
                "repository": "unknown",
                "status": "error",
                "message": "Invalid repository full_name.",
            }
        full_name = "/".join(part.strip() for part in parts)

        if not isinstance(branch, str) or not branch.strip():
            return {
                "repository": full_name,
                "status": "error",
                "message": "Missing or invalid default branch.",
            }
        branch = branch.strip()

        try:
            result = self.github.merge_upstream(full_name, branch)
            return {
                "repository": full_name,
                "status": "up-to-date" if result is None else "synced",
            }
        except HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
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
        except RequestException as error:
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

    def sync_all(self, forks=None, dry_run=False):
        """Process supplied forks, or discover them if none were supplied."""
        try:
            selected_forks = forks if forks is not None else self.get_forks()
        except (RequestException, ValueError, TypeError) as error:
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

        return [self.sync_fork(repository) for repository in selected_forks]
