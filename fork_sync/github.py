
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

    def _request(self, method: str, endpoint: str, **kwargs):
        """Send an authenticated request to GitHub."""
        response = self.session.request(
            method,
            f"{self.BASE_URL}{endpoint}",
            timeout=30,
            **kwargs,
        )

        response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return None

        return response.json()

    def get_authenticated_user(self):
        """Return the authenticated GitHub account."""
        return self._request("GET", "/user")

    def list_repositories(self):
        """Return all repositories owned by the authenticated account."""
        repositories = []
        page = 1

        while True:
            batch = self._request(
                "GET",
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

    def compare_upstream(
        self,
        fork_full_name: str,
        upstream_full_name: str,
        upstream_branch: str,
        fork_branch: str,
    ):
        """Compare a fork branch with its upstream branch."""
        fork_owner, fork_name = fork_full_name.split("/", 1)
        upstream_owner, _ = upstream_full_name.split("/", 1)
        comparison = (
            f"{upstream_owner}:{upstream_branch}..."
            f"{fork_owner}:{fork_branch}"
        )
        return self._request(
            "GET",
            f"/repos/{fork_owner}/{fork_name}/compare/{comparison}",
        )

    def merge_upstream(self, full_name: str, branch: str):
        """Merge the upstream branch into a fork."""
        owner, name = full_name.split("/", 1)

        return self._request(
            "POST",
            f"/repos/{owner}/{name}/merge-upstream",
            json={"branch": branch},
        )
