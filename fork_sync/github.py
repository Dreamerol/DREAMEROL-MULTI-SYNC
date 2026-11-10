"""GitHub API client for repository management."""

import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
from requests.auth import AuthBase
from urllib3.exceptions import DecodeError, ProtocolError, ReadTimeoutError, SSLError
from urllib3.response import HTTPResponse as RawResponse


# GitHub advises waiting at least a minute when it gives no retry time.
DEFAULT_RATE_LIMIT_WAIT = 60


class GitHubRateLimitError(requests.exceptions.RequestException):
    """GitHub refused a request because of a primary or secondary rate limit."""

    def __init__(self, message, retry_after, response=None):
        super().__init__(message, response=response)
        self.retry_after = retry_after


class BearerAuth(AuthBase):
    """Attach one explicit GitHub token to every request this session sends."""

    def __init__(self, token):
        self._token = token

    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    def __repr__(self):
        return "<BearerAuth token=***>"


def _without_credentials(request):
    return request


class NoNetrcSession(requests.Session):
    """A session that never takes credentials from a .netrc file.

    By default, requests replaces a request's Authorization header with .netrc
    credentials when the session has no auth object, and adds .netrc
    credentials after a redirect to another host. Both are disabled here.
    Proxy and certificate settings from the environment still apply.
    """

    def prepare_request(self, request):
        if request.auth is None and self.auth is None:
            # Any explicit auth value stops requests from consulting .netrc.
            request.auth = _without_credentials
        return super().prepare_request(request)

    def rebuild_auth(self, prepared_request, response):
        # requests' own behaviour minus the .netrc lookup: keep the token on the
        # same host and drop it when a redirect leaves that host.
        headers = prepared_request.headers
        if "Authorization" in headers and self.should_strip_auth(
            response.request.url, prepared_request.url
        ):
            del headers["Authorization"]


_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _repo_path(full_name):
    owner, name = full_name.split("/", 1)
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _quote_ref(branch):
    # Slashes are part of branch names; everything else unsafe is encoded.
    return quote(branch, safe="/")


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
    MERGE_TIME_RESERVE = 30
    BODY_CHUNK_SIZE = 65536

    def __init__(self, token: str):
        if not token:
            raise ValueError("A GitHub token is required.")

        # One session per client, so a token never outlives or crosses its client.
        self.session = NoNetrcSession()
        self.session.auth = BearerAuth(token)
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        # Optional fork_sync.deadline.Deadline covering every request of a run.
        self.deadline = None

    def _request(self, method: str, endpoint: str, **kwargs):
        """Send an authenticated request to GitHub.

        Only GET requests are retried. A merge request is sent exactly once,
        because repeating one after an unclear failure could apply it twice.
        With a deadline set, no request, retry or wait starts once it has passed.
        """
        retries_left = self.READ_RETRIES if method == "GET" else 0
        rate_limit_retries_left = 1 if method == "GET" else 0

        while True:
            try:
                response = self.session.request(
                    method,
                    f"{self.BASE_URL}{endpoint}",
                    timeout=self._timeout_for(method),
                    stream=True,
                    **kwargs,
                )
                self._read_body(response, method)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if retries_left <= 0:
                    raise
                self._wait_before_retry(2 ** (self.READ_RETRIES - retries_left))
                retries_left -= 1
                continue

            if _is_rate_limited(response):
                wait = _rate_limit_wait(response)
                if (
                    rate_limit_retries_left <= 0
                    or wait > self.MAX_RATE_LIMIT_WAIT
                    or (self.deadline is not None and wait >= self.deadline.remaining())
                ):
                    raise GitHubRateLimitError(
                        f"GitHub rate limit reached; try again in about {wait} seconds.",
                        retry_after=wait,
                        response=response,
                    )
                time.sleep(wait)
                rate_limit_retries_left -= 1
                continue

            if response.status_code in self.RETRYABLE_STATUS_CODES and retries_left > 0:
                self._wait_before_retry(2 ** (self.READ_RETRIES - retries_left))
                retries_left -= 1
                continue

            response.raise_for_status()

            if response.status_code == 204 or not response.content:
                return None

            return response.json()

    def _timeout_for(self, method):
        if self.deadline is None:
            return self.TIMEOUT
        remaining = self.deadline.remaining()
        if method == "GET":
            if remaining <= 0:
                raise self.deadline.error("before the next GitHub request")
            return min(self.TIMEOUT, remaining)
        # A merge is never cut short once sent, so only start one that can finish.
        if remaining < self.MERGE_TIME_RESERVE:
            raise self.deadline.error("with too little time left to send a merge safely")
        return self.TIMEOUT

    def _read_body(self, response, method):
        """Read the whole body, giving up at the deadline while it arrives.

        The request timeout only limits each wait for data, so a reply that
        trickles in could otherwise take indefinitely long. A reply abandoned
        at the deadline raises DeadlineExceeded and is never used. Merge
        replies are always read in full.
        """
        if method != "GET" or self.deadline is None:
            response.content
            return
        chunks = []
        try:
            for chunk in self._body_chunks(response):
                if self.deadline.expired():
                    raise self.deadline.error("while reading a GitHub response")
                chunks.append(chunk)
            # Store the body where requests keeps it once response.content is read.
            response._content = b"".join(chunks)
            response._content_consumed = True
        finally:
            # After a complete read this only returns the connection to the
            # pool; after a failure it closes the connection.
            response.close()

    def _body_chunks(self, response):
        """Yield the body as it arrives, never waiting past the deadline.

        A normal read waits until its whole buffer is filled, however slowly
        the bytes come. read1 returns whatever has arrived after at most one
        wait, and each wait is first limited to the time left.
        """
        raw = response.raw
        if (
            response._content_consumed
            or not isinstance(raw, RawResponse)
            or not hasattr(raw, "read1")
        ):
            # Test doubles, and older urllib3 releases without read1.
            yield from response.iter_content(self.BODY_CHUNK_SIZE)
            return
        while True:
            limited_by_deadline = self._limit_next_wait(raw)
            # Errors are translated as requests' own iter_content does.
            try:
                chunk = raw.read1(self.BODY_CHUNK_SIZE, decode_content=True)
            except ReadTimeoutError as error:
                if limited_by_deadline:
                    raise self.deadline.error("while reading a GitHub response") from error
                raise requests.exceptions.ConnectionError(error) from error
            except ProtocolError as error:
                raise requests.exceptions.ChunkedEncodingError(error) from error
            except DecodeError as error:
                raise requests.exceptions.ContentDecodingError(error) from error
            except SSLError as error:
                raise requests.exceptions.SSLError(error) from error
            if not chunk:
                return
            yield chunk

    def _limit_next_wait(self, raw):
        """Shorten the next socket wait to the time left.

        Returns True when the deadline, not the usual timeout, sets the wait.
        """
        remaining = self.deadline.remaining()
        if remaining <= 0:
            raise self.deadline.error("while reading a GitHub response")
        sock = getattr(raw.connection, "sock", None)
        if sock is None:
            # Already released: the rest of the body is buffered locally.
            return False
        wait = min(self.TIMEOUT, remaining)
        sock.settimeout(wait)
        return wait < self.TIMEOUT

    def _wait_before_retry(self, seconds):
        if self.deadline is not None and seconds >= self.deadline.remaining():
            raise self.deadline.error("before a retry could be made")
        time.sleep(seconds)

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
        return self._request("GET", _repo_path(full_name))

    def get_branch_head(self, full_name: str, branch: str):
        """Return the commit SHA at the tip of a branch."""
        reply = self._request("GET", f"{_repo_path(full_name)}/branches/{_quote_ref(branch)}")
        commit = reply.get("commit") if isinstance(reply, dict) else None
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValueError(f"GitHub returned no valid commit for branch '{branch}'.")
        return sha

    def compare_upstream(
        self,
        fork_full_name: str,
        upstream_full_name: str,
        upstream_branch: str,
        fork_branch: str,
    ):
        """Compare a fork branch (head) with its upstream branch (base).

        GitHub documents "OWNER:BRANCH...OWNER:BRANCH" for comparing across a
        repository network. That form cannot tell two repositories with the
        same owner apart, so in that case the upstream branch is first resolved
        to a commit SHA, which identifies it unambiguously within the network.
        """
        if not isinstance(fork_full_name, str) or not fork_full_name.strip():
            raise ValueError("Fork full_name is required.")
        if not isinstance(upstream_full_name, str) or not upstream_full_name.strip():
            raise ValueError("Upstream full_name is required.")
        if not isinstance(upstream_branch, str) or not upstream_branch.strip():
            raise ValueError("Upstream branch is required.")
        if not isinstance(fork_branch, str) or not fork_branch.strip():
            raise ValueError("Fork branch is required.")

        fork_owner, _ = fork_full_name.split("/", 1)
        upstream_owner, _ = upstream_full_name.split("/", 1)

        if fork_owner.lower() == upstream_owner.lower():
            base = self.get_branch_head(upstream_full_name, upstream_branch.strip())
            head = _quote_ref(fork_branch.strip())
        else:
            base = f"{quote(upstream_owner, safe='')}:{_quote_ref(upstream_branch.strip())}"
            head = f"{quote(fork_owner, safe='')}:{_quote_ref(fork_branch.strip())}"

        return self._request(
            "GET",
            f"{_repo_path(fork_full_name)}/compare/{base}...{head}",
        )

    def merge_upstream(self, full_name: str, branch: str):
        """Merge the upstream branch into a fork."""
        return self._request(
            "POST",
            f"{_repo_path(full_name)}/merge-upstream",
            json={"branch": branch},
        )
