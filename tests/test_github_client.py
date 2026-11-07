import os
import re
from typing import Any

import requests


class GitHubClient:
    BASE_URL = "https://api.github.com"
    PER_PAGE = 100
    TIMEOUT = 15

    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GITHUB_TOKEN is not configured.")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    @staticmethod
    def _validate_owner_login(owner: str) -> str:
        if not isinstance(owner, str):
            raise ValueError("Invalid GitHub owner login")

        owner = owner.strip()
        if (
            not owner
            or len(owner) > 39
            or owner.startswith("-")
            or owner.endswith("-")
            or "--" in owner
            or not re.fullmatch(r"[A-Za-z0-9-]+", owner)
        ):
            raise ValueError("Invalid GitHub owner login")

        return owner

    def get_forks(self, owner: str) -> list[dict[str, Any]]:
        owner = self._validate_owner_login(owner)

        account_url = f"{self.BASE_URL}/users/{owner}"
        try:
            account_response = self.session.get(account_url, timeout=self.TIMEOUT)
            account_response.raise_for_status()
        except requests.RequestException as exc:
            raise ValueError(f"Could not resolve GitHub account for owner {owner!r}.") from exc

        account_type = account_response.json().get("type")

        if account_type == "Organization":
            repositories_url = f"{self.BASE_URL}/orgs/{owner}/repos"
            params = {"per_page": self.PER_PAGE, "type": "all", "page": 1}
        elif account_type == "User":
            repositories_url = f"{self.BASE_URL}/users/{owner}/repos"
            params = {"per_page": self.PER_PAGE, "type": "owner", "page": 1}
        else:
            raise ValueError(f"Could not determine whether {owner!r} is a user or organization.")

        forks: list[dict[str, Any]] = []
        next_url = repositories_url
        next_params = params

        while next_url:
            try:
                response = self.session.get(next_url, params=next_params, timeout=self.TIMEOUT)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ValueError(f"Failed to fetch repositories for owner {owner!r}.") from exc

            repositories = response.json()
            if not isinstance(repositories, list):
                raise ValueError(f"Unexpected response format for owner {owner!r}.")

            forks.extend(repo for repo in repositories if repo.get("fork") is True)

            next_url = response.links.get("next", {}).get("url")
            next_params = None

        return forks
