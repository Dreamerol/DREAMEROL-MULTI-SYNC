# ADR 0001: Keep `backend/github_client.py` for now

**Status:** Accepted, to be revisited when organization fork requirements are settled.

## Context

The project has two GitHub clients:

- `fork_sync/github.py` is the production client used by the CLI and web API. It discovers forks owned by the authenticated account.
- `backend/github_client.py` is not imported by any production code. It lists forks for a named user or organization, using `Link` header pagination, and is covered by `tests/test_github_client.py`.

The second client is the only code with organization support, but it cannot drive a sync on its own: its list responses have no `parent` data, so it has no upstream branch to compare against.

## Decision

Keep `backend/github_client.py` unchanged and out of the production path until it is decided whether organization-owned forks are in scope.

## Consequences

- Organization-owned forks are not synchronized. The production client requests `type=owner`.
- Fixes made to the production client, such as rate-limit handling and retries, do not apply to this module.
- `tests/test_github_client.py` also tests the production client, so removing this module later means removing only its specific tests.

If organization support is approved, move the owner-based listing into `fork_sync/github.py` and run its results through `ForkSynchronizer.discover_forks`. If it is rejected, delete the module and its tests.
