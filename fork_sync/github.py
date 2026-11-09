"""GitHub API client for repository management."""

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests


# GitHub advises waiting at least a minute when it gives no retry time.
DEFAULT_RATE_LIMIT_WAIT = 60


class GitHubRateLimitError(requests.exceptions.RequestException):
    """GitHub refused a request because of a primary or secondary rate limit."""

    def __init__(self, message, retry_after, response=None):
        super().__init__(message, response=response)
        self.retry_after = retry_after


def _is_rate_limited(response):
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    return (
        response.headers.get("x-ratelimit-remaining") == "0"
        or "retry-after" in response.headers
        or "rate limit" in response.text.lower()
    )


def _seconds_from_retry_after(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        pass
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, int((moment - datetime.now(timezone.utc)).total_seconds()))


def _rate_limit_wait(response):
    """Apply GitHub's documented order: retry-after, then the reset time."""
    wait = _seconds_from_retry_after(response.headers.get("retry-after"))
    if wait is not None:
        return wait

    if response.headers.get("x-ratelimit-remaining") == "0":
        try:
            reset = int(response.headers.get("x-ratelimit-reset"))
        except (TypeError, ValueError):
            return DEFAULT_RATE_LIMIT_WAIT
        return max(0, reset - int(time.time())) + 1

    return DEFAULT_RATE_LIMIT_WAIT


class GitHubClient:
    """Handles authenticated communication with the GitHub API."""

    BASE_URL = "https://api.github.com"
    MAX_PAGES = 1000
    TIMEOUT = 30
    READ_RETRIES = 2
    RETRYABLE_STATUS_CODES = {502, 503, 504}
    MAX_RATE_LIMIT_WAIT = 60

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
        """Send an authenticated request to GitHub.

        Only GET requests are retried. A merge request is sent exactly once,
        because repeating one after an unclear failure could apply it twice.
        """
        retries_left = self.READ_RETRIES if method == "GET" else 0
        rate_limit_retries_left = 1 if method == "GET" else 0

        while True:
            try:
                response = self.session.request(
                    method,
                    f"{self.BASE_URL}{endpoint}",
                    timeout=self.TIMEOUT,
                    **kwargs,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if retries_left <= 0:
                    raise
                time.sleep(2 ** (self.READ_RETRIES - retries_left))
                retries_left -= 1
                continue

            if _is_rate_limited(response):
                wait = _rate_limit_wait(response)
                if rate_limit_retries_left <= 0 or wait > self.MAX_RATE_LIMIT_WAIT:
                    raise GitHubRateLimitError(
                        f"GitHub rate limit reached; try again in about {wait} seconds.",
                        retry_after=wait,
                        response=response,
                    )
                time.sleep(wait)
                rate_limit_retries_left -= 1
                continue

            if response.status_code in self.RETRYABLE_STATUS_CODES and retries_left > 0:
                time.sleep(2 ** (self.READ_RETRIES - retries_left))
                retries_left -= 1
                continue

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

        for page in range(1, self.MAX_PAGES + 1):
            # Sorted by name because "updated" order can shift between pages.
            batch = self._request(
                "GET",
                "/user/repos",
                params={
                    "type": "owner",
                    "sort": "full_name",
                    "per_page": 100,
                    "page": page,
                },
            )

            if not isinstance(batch, list):
                raise ValueError(
                    f"GitHub returned an invalid repository list on page {page}."
                )

            repositories.extend(batch)

            if len(batch) < 100:
                return repositories

        raise ValueError(f"Repository listing exceeded {self.MAX_PAGES} pages.")

    def get_repository(self, full_name: str):
        """Return one repository; only this endpoint includes fork parent data."""
        owner, name = full_name.split("/", 1)
        return self._request("GET", f"/repos/{owner}/{name}")

    def compare_upstream(
        self,
        fork_full_name: str,
        upstream_full_name: str,
        upstream_branch: str,
        fork_branch: str,
    ):
        """Compare a fork branch with its upstream branch.

        GitHub compare API expects the `basehead` form:
        "UPSTREAM_OWNER:BRANCH...FORK_OWNER:BRANCH"
        when comparing a fork against its parent repository.
        """
        if not isinstance(fork_full_name, str) or not fork_full_name.strip():
            raise ValueError("Fork full_name is required.")
        if not isinstance(upstream_full_name, str) or not upstream_full_name.strip():
            raise ValueError("Upstream full_name is required.")
        if not isinstance(upstream_branch, str) or not upstream_branch.strip():
            raise ValueError("Upstream branch is required.")
        if not isinstance(fork_branch, str) or not fork_branch.strip():
            raise ValueError("Fork branch is required.")

        fork_owner, fork_name = fork_full_name.split("/", 1)
        upstream_owner, _ = upstream_full_name.split("/", 1)

        basehead = (
            f"{upstream_owner}:{quote(upstream_branch.strip(), safe='/')}..."
            f"{fork_owner}:{quote(fork_branch.strip(), safe='/')}"
        )

        return self._request(
            "GET",
            f"/repos/{fork_owner}/{fork_name}/compare/{basehead}",
        )

    def merge_upstream(self, full_name: str, branch: str):
        """Merge the upstream branch into a fork."""
        owner, name = full_name.split("/", 1)

        return self._request(
            "POST",
            f"/repos/{owner}/{name}/merge-upstream",
            json={"branch": branch},
        )
