import os
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

    def get_forks(self, owner):
        """Return all fork repositories owned by a GitHub user or organization."""
        normalized_owner = owner.strip() if isinstance(owner, str) else ""

        if (
            not isinstance(owner, str)
            or not normalized_owner
            or len(normalized_owner) > 39
            or not normalized_owner[0].isalnum()
            or not all(char.isalnum() or char == "-" for char in normalized_owner)
            or normalized_owner.endswith("-")
            or "--" in normalized_owner
        ):
            raise ValueError("Invalid GitHub owner login.")

        owner = normalized_owner
        account_url = f"{self.BASE_URL}/users/{owner}"
        account_response = self.session.get(account_url, timeout=self.TIMEOUT)
        account_response.raise_for_status()
        account_type = account_response.json().get("type")

        if account_type == "Organization":
            repositories_url = f"{self.BASE_URL}/orgs/{owner}/repos"
            params = {"per_page": self.PER_PAGE, "type": "all", "page": 1}
        elif account_type == "User":
            repositories_url = f"{self.BASE_URL}/users/{owner}/repos"
            params = {"per_page": self.PER_PAGE, "type": "owner", "page": 1}
        else:
            raise ValueError(
                f"Could not determine whether {owner!r} is a user or organization."
            )

        forks = []
        next_url = repositories_url
        next_params = params

        while next_url:
            response = self.session.get(
                next_url,
                params=next_params,
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
            repositories = response.json()

            forks.extend(
                repo for repo in repositories if repo.get("fork") is True
            )

            next_url = response.links.get("next", {}).get("url")
            next_params = None

        return forks
