"""GitHub Fork discovery and upstream synchronization."""

from collections import Counter
from typing import NamedTuple

import requests

from fork_sync.github import GitHubRateLimitError


FAILURE_STATUSES = {"error", "conflict", "skipped", "unknown", "rate-limited"}
_EXPECTED_ERRORS = (requests.exceptions.RequestException, ValueError, KeyError, TypeError)


class ForkDiscovery(NamedTuple):
    """Usable forks plus results describing the ones that could not be used."""

    forks: list
    skipped: list


def has_failures(results):
    """Return whether any result should make the run report failure."""
    return any(result.get("status") in FAILURE_STATUSES for result in results)


def summarize(results):
    """Count results by status, in first-seen order."""
    return dict(Counter(result.get("status", "unknown") for result in results))


def describe_summary(results):
    """One-line summary shared in meaning with the web interface."""
    return ", ".join(f"{count} {status}" for status, count in summarize(results).items())


def _result(repository, status, message, behind_by=None, ahead_by=None):
    return {
        "repository": repository,
        "status": status,
        "message": message,
        "behind_by": behind_by,
        "ahead_by": ahead_by,
    }


def _rate_limited(repository, message):
    return _result(repository, "rate-limited", message)


def _skipped(repository, message):
    return {"repository": repository, "status": "skipped", "message": message}


def _name_of(repo):
    return repo.get("full_name", "unknown") if isinstance(repo, dict) else "unknown"


def _is_full_name(value):
    if not isinstance(value, str):
        return False
    owner, separator, name = value.strip().partition("/")
    return bool(owner and separator and name and "/" not in name)


def _fork_details_problem(repository):
    """Explain why single-repository data cannot be used, or return None."""
    if not isinstance(repository, dict):
        return "GitHub returned malformed repository details."
    if repository.get("fork") is not True:
        return "GitHub's repository details do not identify this as a fork."
    if not _is_full_name(repository.get("full_name")):
        return "GitHub's repository details have no valid name."
    branch = repository.get("default_branch")
    if not isinstance(branch, str) or not branch.strip():
        return "GitHub's repository details have no default branch."
    parent = repository.get("parent")
    if not isinstance(parent, dict):
        return "GitHub's repository details have no upstream parent."
    upstream_branch = parent.get("default_branch")
    if (
        not _is_full_name(parent.get("full_name"))
        or not isinstance(upstream_branch, str)
        or not upstream_branch.strip()
    ):
        return "GitHub's upstream details are incomplete."
    return None


class ForkSynchronizer:
    """Synchronize GitHub forks with their upstream repositories."""

    def __init__(self, github_client):
        self.github = github_client

    def discover_forks(self):
        """Find the account's forks and report every fork that could not be used.

        The repository list has no parent data, so each fork is fetched
        individually. Listing failures raise; a problem with one repository
        becomes a "skipped" result instead of disappearing.
        """
        repositories = self.github.list_repositories()
        if not isinstance(repositories, list):
            raise ValueError("Invalid repository list returned by GitHub.")

        forks = []
        skipped = []
        seen = set()
        rate_limit_message = None
        for item in repositories:
            if not isinstance(item, dict):
                skipped.append(_skipped("unknown", "GitHub returned a malformed repository entry."))
                continue
            if item.get("fork") is False:
                continue

            full_name = item.get("full_name")
            if not _is_full_name(full_name):
                skipped.append(_skipped("unknown", "GitHub returned a repository without a valid name."))
                continue
            full_name = full_name.strip()
            if item.get("fork") is not True:
                skipped.append(_skipped(full_name, "GitHub did not say whether this repository is a fork."))
                continue
            if full_name in seen:
                continue
            seen.add(full_name)

            if rate_limit_message:
                skipped.append(_rate_limited(full_name, f"Not checked: {rate_limit_message}"))
                continue

            try:
                repository = self.github.get_repository(full_name)
            except GitHubRateLimitError as error:
                rate_limit_message = str(error)
                skipped.append(_rate_limited(full_name, rate_limit_message))
                continue
            except _EXPECTED_ERRORS as error:
                skipped.append(_skipped(full_name, f"Could not load fork details: {error}"))
                continue

            problem = _fork_details_problem(repository)
            if problem:
                skipped.append(_skipped(full_name, problem))
                continue
            forks.append(repository)

        return ForkDiscovery(forks, skipped)

    @staticmethod
    def _fork_refs(repo):
        """Validate fork metadata and return its repository and branch names."""
        if not isinstance(repo, dict):
            raise ValueError("Invalid repository data.")

        full_name = repo.get("full_name")
        fork_branch = repo.get("default_branch")
        parent = repo.get("parent")
        upstream_full_name = parent.get("full_name") if isinstance(parent, dict) else None
        upstream_branch = parent.get("default_branch") if isinstance(parent, dict) else None

        if not isinstance(full_name, str) or not full_name.strip():
            raise ValueError("Missing or invalid repository full_name.")
        if not _is_full_name(full_name):
            raise ValueError("Invalid repository full_name.")
        if not isinstance(fork_branch, str) or not fork_branch.strip():
            raise ValueError("Missing or invalid default branch.")
        if (
            not _is_full_name(upstream_full_name)
            or not isinstance(upstream_branch, str)
            or not upstream_branch.strip()
        ):
            raise ValueError("Missing upstream branch information.")

        return (
            full_name.strip(),
            fork_branch.strip(),
            upstream_full_name.strip(),
            upstream_branch.strip(),
        )

    def _inspect(self, repo):
        """Read-only classification of a fork; the single source of sync decisions."""
        full_name, fork_branch, upstream_full_name, upstream_branch = self._fork_refs(repo)

        if repo.get("archived") or repo.get("disabled"):
            return _result(
                full_name, "unavailable", "Fork is archived or disabled; GitHub will not update it."
            )

        # GitHub does not document whether its merge endpoint uses a fork's parent
        # or its source, so a sync is only safe when they are the same repository.
        source = repo.get("source")
        source_full_name = source.get("full_name") if isinstance(source, dict) else None
        if not _is_full_name(source_full_name):
            return _result(
                full_name,
                "upstream-unverified",
                "GitHub did not report this fork's source repository. Refusing to "
                "sync because the upstream GitHub would merge cannot be verified.",
            )
        if source_full_name.strip() != upstream_full_name:
            return _result(
                full_name,
                "upstream-unverified",
                f"Fork parent '{upstream_full_name}' differs from its source "
                f"'{source_full_name.strip()}'. Refusing to sync because the "
                "upstream GitHub would merge cannot be verified.",
            )

        # GitHub's merge endpoint accepts only the fork's branch name, so with
        # different names there is no way to know which upstream branch it uses.
        if fork_branch != upstream_branch:
            return _result(
                full_name,
                "branch-mismatch",
                f"Fork default branch '{fork_branch}' differs from upstream default "
                f"branch '{upstream_branch}'. Refusing to sync because the branch "
                "GitHub would merge cannot be verified.",
            )

        comparison = self.github.compare_upstream(
            fork_full_name=full_name,
            upstream_full_name=upstream_full_name,
            upstream_branch=upstream_branch,
            fork_branch=fork_branch,
        )
        if not isinstance(comparison, dict):
            raise ValueError("Invalid comparison data returned by GitHub.")

        ahead_by = comparison.get("ahead_by")
        behind_by = comparison.get("behind_by")
        if (
            isinstance(ahead_by, bool)
            or not isinstance(ahead_by, int)
            or ahead_by < 0
            or isinstance(behind_by, bool)
            or not isinstance(behind_by, int)
            or behind_by < 0
        ):
            raise ValueError("Invalid comparison counts returned by GitHub.")

        if behind_by and ahead_by:
            status, message = "diverged", "Fork and upstream have diverged; no automatic sync."
        elif ahead_by:
            status, message = "ahead", "Fork has local commits and is not safe to merge."
        elif behind_by:
            status, message = "behind", f"{behind_by} upstream commit(s) available."
        else:
            status, message = "up-to-date", "No changes."
        return _result(full_name, status, message, behind_by=behind_by, ahead_by=ahead_by)

    @staticmethod
    def _error_result(repo, error):
        return _result(_name_of(repo), "error", str(error))

    def preview_fork(self, repo):
        """Read-only status check for one fork; no synchronization request is sent."""
        try:
            return self._inspect(repo)
        except GitHubRateLimitError as error:
            return _rate_limited(_name_of(repo), str(error))
        except _EXPECTED_ERRORS as error:
            return self._error_result(repo, error)

    def preview_all(self, forks):
        """Compare the given forks without changing any repository."""
        return self._process_each(forks, self.preview_fork)

    def _process_each(self, forks, process):
        """Isolate per-fork failures, but stop calling GitHub once rate limited."""
        results = []
        rate_limit_message = None
        for repository in forks:
            if rate_limit_message:
                results.append(
                    _rate_limited(_name_of(repository), f"Not attempted: {rate_limit_message}")
                )
                continue
            try:
                result = process(repository)
            except Exception as error:
                result = self._error_result(repository, error)
            results.append(result)
            if result["status"] == "rate-limited":
                rate_limit_message = result["message"]
        return results

    def sync_fork(self, repo):
        """Merge upstream only when a fresh comparison shows the fork is strictly behind."""
        try:
            state = self._inspect(repo)
        except GitHubRateLimitError as error:
            return _rate_limited(_name_of(repo), str(error))
        except _EXPECTED_ERRORS as error:
            return self._error_result(repo, error)
        if state["status"] != "behind":
            return state

        try:
            outcome = self.github.merge_upstream(
                state["repository"], repo["default_branch"].strip()
            )
        except GitHubRateLimitError as error:
            return {**state, "status": "rate-limited", "message": f"Merge refused: {error}"}
        except requests.exceptions.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            if status_code == 409:
                return {**state, "status": "conflict", "message": str(error)}
            if status_code is None or status_code >= 500:
                return self._check_unconfirmed_merge(repo, state, error)
            return {**state, "status": "error", "message": str(error)}
        except Exception as error:
            # Any other failure can follow a merge that GitHub applied, so the
            # outcome has to be checked, never assumed.
            return self._check_unconfirmed_merge(repo, state, error)

        return self._merge_result(state, outcome)

    @staticmethod
    def _merge_result(state, outcome):
        """Report what GitHub says it did, not what the earlier comparison predicted."""
        merge_type = outcome.get("merge_type") if isinstance(outcome, dict) else None
        behind_by = state["behind_by"]

        if merge_type == "fast-forward":
            status = "synced"
            message = f"Fast-forwarded to upstream; fork was {behind_by} commit(s) behind."
        elif merge_type == "merge":
            status = "merged"
            message = (
                "GitHub created a merge commit instead of fast-forwarding; the fork "
                "may have changed after it was compared. Review the fork's history."
            )
        elif merge_type == "none":
            status = "no-change"
            message = (
                f"GitHub merged nothing although the fork was {behind_by} commit(s) "
                "behind when compared; it may have been updated in the meantime."
            )
        else:
            return {
                **state,
                "status": "unknown",
                "message": "GitHub accepted the request but did not report what it merged. "
                "Check the fork before trying again.",
            }
        return {**state, "status": status, "message": message, "merge_type": merge_type}

    def _check_unconfirmed_merge(self, repo, state, error):
        """Establish what is observable after an unconfirmed merge; never retry it."""
        prefix = f"GitHub did not confirm the merge and it was not retried ({error})."
        try:
            current = self._inspect(repo)
        except Exception:
            return {
                **state,
                "status": "unknown",
                "message": f"{prefix} The fork's current state could not be checked.",
            }
        if current["status"] == "up-to-date":
            return {
                **current,
                "status": "synced",
                "message": f"{prefix} A new comparison shows the fork now matches upstream.",
            }
        return {
            **current,
            "status": "unknown",
            "message": f"{prefix} A new comparison reports '{current['status']}'; "
            "check the fork before trying again.",
        }

    def sync_all(self, forks):
        """Process each fork independently so one failure cannot stop others."""
        return self._process_each(forks, self.sync_fork)
