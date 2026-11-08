from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from requests.exceptions import HTTPError, RequestException

from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer

router = APIRouter(prefix="/api", tags=["sync"])


class SyncRequest(BaseModel):
    dry_run: bool = True
    confirmation: str | None = None
    repositories: list[str] | None = None


class SyncResult(BaseModel):
    repository: str
    status: str
    message: str | None = None


class SyncResponse(BaseModel):
    account: str
    total: int
    results: list[SyncResult]


@router.post("/sync", response_model=SyncResponse)
def sync_repositories(
    request: SyncRequest,
    authorization: str | None = Header(default=None),
):
    """Preview forks or synchronize only the explicitly previewed forks."""
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
        if request.dry_run:
            results = synchronizer.sync_all(dry_run=True)
        else:
            try:
                current_forks = synchronizer.get_forks()
            except RequestException as error:
                raise HTTPException(status_code=502, detail="Could not load forks from GitHub.") from error
            available = {
                fork.get("full_name")
                for fork in current_forks
                if isinstance(fork.get("full_name"), str)
            }
            if any(repository not in available for repository in request.repositories):
                raise HTTPException(
                    status_code=400,
                    detail="A selected repository is no longer an available fork for this account. Preview again.",
                )
            selected = set(request.repositories)
            selected_forks = [
                fork for fork in current_forks if fork.get("full_name") in selected
            ]
            results = synchronizer.sync_all(forks=selected_forks)

        return SyncResponse(account=account, total=len(results), results=results)
    finally:
        client.session.close()
