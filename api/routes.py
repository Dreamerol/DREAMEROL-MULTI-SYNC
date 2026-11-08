
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from requests.exceptions import RequestException

from fork_sync.accounts import AccountManager
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer

router = APIRouter(prefix="/api", tags=["sync"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SyncResponse(BaseModel):
    account: str
    total: int
    results: list[dict]


@router.post("/sync", response_model=SyncResponse)
def sync_repositories(credentials: LoginRequest):
    """
    Authenticate and synchronize only forks with upstream changes.

    IMPORTANT:
    Email/password authentication must be implemented separately.
    Never treat a GitHub password as a GitHub API token.
    """
    raise HTTPException(
        status_code=501,
        detail="Authentication provider is not configured yet."
    )

