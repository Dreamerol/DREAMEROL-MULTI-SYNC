"""A fake of GitHub's HTTP layer, shaped like the real REST responses.

Forks in repository lists have no ``parent``; only single-repository responses
do. Project code runs unmodified on top of this, and nothing touches the network.
"""

import json
import re
from urllib.parse import unquote

import requests

BASE = "https://api.github.com"


def response(status=200, body=None, headers=None, url=BASE):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result._content = b"" if body is None else json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


def list_item(full_name, fork=True, default_branch="main"):
    """A repository as returned by GET /user/repos (no parent)."""
    return {"full_name": full_name, "fork": fork, "default_branch": default_branch}


def full_repository(full_name, default_branch="main", upstream_branch="main", **extra):
    """A fork as returned by GET /repos/{owner}/{repo}."""
    name = full_name.split("/", 1)[1]
    return {
        **list_item(full_name, default_branch=default_branch),
        "archived": False,
        "disabled": False,
        "parent": {"full_name": f"upstream/{name}", "default_branch": upstream_branch},
        "source": {"full_name": f"upstream/{name}", "default_branch": upstream_branch},
        **extra,
    }


def _next(value):
    """A list of outcomes is consumed in order; its last entry then repeats."""
    if isinstance(value, list):
        return value.pop(0) if len(value) > 1 else value[0]
    return value


class FakeGitHub:
    """Callable replacement for requests.Session.request."""

    def __init__(self):
        self.listing = []
        self.pages = None
        self.details = {}
        self.compares = {}
        self.merges = {}
        self.calls = []
        self.merge_bodies = []

    def install(self, monkeypatch):
        monkeypatch.setattr(requests.Session, "request", self)
        return self

    def add_fork(self, name, compare=(0, 0), merge=None, details=None, **repository):
        """Add a fork; compare is (ahead_by, behind_by) or a canned outcome."""
        full_name = f"demo/{name}"
        self.listing.append(list_item(full_name))
        self.details[full_name] = (
            details if details is not None else full_repository(full_name, **repository)
        )
        self.compares[full_name] = compare
        self.merges[full_name] = (
            merge if merge is not None else (200, {"merge_type": "fast-forward"})
        )
        return full_name

    def count(self, method, fragment):
        return sum(1 for m, url in self.calls if m == method and fragment in url)

    @property
    def merged(self):
        return [
            url.split("/repos/")[1].rsplit("/", 1)[0]
            for method, url in self.calls
            if method == "POST"
        ]

    def _reply(self, outcome, url):
        outcome = _next(outcome)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, requests.Response):
            outcome.url = url
            return outcome
        if isinstance(outcome, int):
            return response(outcome, {"message": "failure"}, url=url)
        status, body, *headers = outcome
        return response(status, body, headers[0] if headers else None, url)

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url))
        path = unquote(url.removeprefix(BASE))

        if path == "/user":
            return response(200, {"login": "demo"}, url=url)
        if path == "/user/repos":
            page = kwargs["params"]["page"]
            if self.pages is not None:
                index = min(page - 1, len(self.pages) - 1)
                return self._reply(self.pages[index], url)
            return response(200, self.listing[(page - 1) * 100: page * 100], url=url)

        match = re.fullmatch(r"/repos/([^/]+/[^/]+)/compare/.+", path)
        if match:
            outcome = _next(self.compares[match[1]])
            if isinstance(outcome, tuple) and len(outcome) == 2 and isinstance(outcome[1], int):
                return response(200, {"ahead_by": outcome[0], "behind_by": outcome[1]}, url=url)
            return self._reply(outcome, url)

        match = re.fullmatch(r"/repos/([^/]+/[^/]+)/merge-upstream", path)
        if match:
            self.merge_bodies.append(kwargs.get("json"))
            return self._reply(self.merges[match[1]], url)

        match = re.fullmatch(r"/repos/([^/]+/[^/]+)", path)
        if match:
            detail = _next(self.details[match[1]])
            if isinstance(detail, dict):
                return response(200, detail, url=url)
            return self._reply(detail, url)

        raise AssertionError(f"Unexpected request: {method} {url}")
