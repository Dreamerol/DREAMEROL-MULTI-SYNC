import os
import requests


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")

        if not self.token:
            raise ValueError("GITHUB_TOKEN is not configured.")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_forks(self, owner):
        url = f"{self.BASE_URL}/users/{owner}/repos"

        response = requests.get(
            url,
            headers=self.headers,
            params={"per_page": 100, "type": "owner"},
            timeout=15,
        )

        response.raise_for_status()

        repositories = response.json()

        return [
            repo for repo in repositories
            if repo.get("fork") is True
        ]
