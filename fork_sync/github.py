
"""GitHub API client for repository management."""

import requests


class GitHubClient:
    """Handles authenticated communication with the GitHub API."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str):
        if not token:
            raise ValueError("A GitHub token is required.")

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, endpoint: str, params=None):
        response = self.session.get(
            f"{self.BASE_URL}{endpoint}",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_authenticated_user(self):
        """Return the authenticated GitHub account."""
        return self._get("/user")

    def list_repositories(self):
        """Return all repositories accessible as the authenticated owner."""
        repositories = []
        page = 1

        while True:
            batch = self._get(
                "/user/repos",
                params={
                    "type": "owner",
                    "sort": "updated",
                    "per_page": 100,
                    "page": page,
                },
            )

            repositories.extend(batch)

            if len(batch) < 100:
                break

            page += 1

        return repositories

