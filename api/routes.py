from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from requests.exceptions import HTTPError, RequestException

from fork_sync.github import GitHubClient, GitHubRateLimitError
from fork_sync.synchronizer import ForkSynchronizer, has_failures, summarize

router = APIRouter(prefix="/api", tags=["sync"])


class SyncRequest(BaseModel):
    dry_run: bool = True
    confirmation: str | None = None
    repositories: list[str] | None = None


class SyncResult(BaseModel):
    repository: str
    status: str
    message: str | None = None
    behind_by: int | None = None
    ahead_by: int | None = None
    merge_type: str | None = None


class SyncResponse(BaseModel):
    account: str
    total: int
    summary: dict[str, int]
    has_failures: bool
    results: list[SyncResult]


def _rate_limit_response(error):
    return HTTPException(
        status_code=429,
        detail=str(error),
        headers={"Retry-After": str(error.retry_after)},
    )


@router.post("/sync", response_model=SyncResponse)
def sync_repositories(
    request: SyncRequest,
    authorization: str | None = Header(default=None),
):
    """Preview fork status or sync only the explicitly confirmed, lagging forks."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Provide a GitHub token using the Bearer authorization scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Provide a GitHub token using the Bearer authorization scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not request.dry_run:
        if request.confirmation != "SYNC":
            raise HTTPException(
                status_code=400,
                detail='Live synchronization requires confirmation="SYNC".',
            )
        if not request.repositories:
            raise HTTPException(
                status_code=400,
                detail="Select at least one repository from the preview before syncing.",
            )
        if len(request.repositories) > 5000:
            raise HTTPException(status_code=400, detail="Too many repositories were selected.")
        if len(set(request.repositories)) != len(request.repositories):
            raise HTTPException(status_code=400, detail="Duplicate repositories were selected.")

    client = GitHubClient(token.strip())
    try:
        try:
            user = client.get_authenticated_user()
        except GitHubRateLimitError as error:
            raise _rate_limit_response(error) from error
        except HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            if status_code == 401:
                raise HTTPException(status_code=401, detail="The GitHub token is invalid.") from error
            if status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="The GitHub token does not have sufficient permissions.",
                ) from error
            raise HTTPException(status_code=502, detail="GitHub authentication failed.") from error
        except RequestException as error:
            raise HTTPException(status_code=502, detail="Could not reach GitHub.") from error

        account = user.get("login") if isinstance(user, dict) else None
        if not isinstance(account, str) or not account.strip():
            raise HTTPException(status_code=502, detail="GitHub returned an invalid account profile.")

        synchronizer = ForkSynchronizer(client)
        try:
            discovery = synchronizer.discover_forks()
        except GitHubRateLimitError as error:
            raise _rate_limit_response(error) from error
        except (RequestException, ValueError, TypeError) as error:
            raise HTTPException(status_code=502, detail="Could not load forks from GitHub.") from error

        current_forks = discovery.forks
        if request.dry_run:
            # This performs read-only comparisons; it never submits a merge request.
            results = discovery.skipped + synchronizer.preview_all(current_forks)
        else:
            if any(result["status"] == "rate-limited" for result in discovery.skipped):
                raise HTTPException(
                    status_code=429,
                    detail="GitHub rate limit reached while loading forks. Preview again later.",
                )

            available = {
                fork.get("full_name")
                for fork in current_forks
                if isinstance(fork, dict) and isinstance(fork.get("full_name"), str)
            }
            if any(repository not in available for repository in request.repositories):
                raise HTTPException(
                    status_code=400,
                    detail="A selected repository is no longer an available fork for this account. Preview again.",
                )

            forks_by_name = {fork["full_name"]: fork for fork in current_forks}

            # sync_fork compares each fork immediately before merging, so stale or
            # edited browser requests cannot merge a fork that is not behind.
            results = synchronizer.sync_all(
                forks=[forks_by_name[name] for name in request.repositories]
            )

        return SyncResponse(
            account=account,
            total=len(results),
            summary=summarize(results),
            has_failures=has_failures(results),
            results=results,
        )
    finally:
        client.session.close()
