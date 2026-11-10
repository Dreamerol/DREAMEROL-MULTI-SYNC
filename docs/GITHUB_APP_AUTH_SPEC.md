# DREAMEROL-SYNC GitHub App Authentication Specification

## Status

**Architecture direction accepted — implementation approval pending.**

This document specifies the proposed GitHub App authentication architecture for the local DREAMEROL-SYNC CLI using a minimal Auth Broker. It does not authorize implementation or deployment. Implementation requires explicit approval after the outstanding verification and security criteria in this document are satisfied.

## 1. Goals

Provide a simple GitHub sign-in experience for the local DREAMEROL-SYNC CLI. The user runs one CLI command, which opens GitHub's authorization page in the system browser.

Requirements:

- Users enter GitHub credentials only on GitHub.
- DREAMEROL-SYNC never requests, receives, or stores a GitHub password.
- The GitHub App `client_secret` is never distributed with the CLI.
- No QR codes, Device Flow, or manually copied authorization codes.
- GitHub credentials are stored locally in the operating system's Keyring.
- Multiple GitHub profiles are supported.
- The existing synchronization engine and its safety behavior remain unchanged.
- The MVP uses a GitHub App configured for non-expiring user access tokens.
- If the configured GitHub App cannot issue the expected non-expiring token, login fails clearly. There is no automatic fallback to refresh tokens or another authentication mode.

## 2. Scope

### 2.1 Included in the MVP

- Local CLI browser-based GitHub login.
- GitHub App Authorization Code Flow through an Auth Broker.
- One fixed, registered HTTPS callback URL.
- PKCE S256 and OAuth `state` validation.
- Short-lived authentication transactions.
- HTTPS polling and acknowledgment (ACK).
- GitHub identity verification through `GET /user`.
- Local Keyring credential storage and multiple local profiles.
- Token validation and reauthentication when access is revoked or invalid.
- Integration with the existing `GitHubClient` and `ForkSynchronizer`.

### 2.2 Explicitly excluded from the MVP

- DREAMEROL user registration, passwords, or a user database.
- Cloud profile storage or persistent GitHub token storage on the Broker.
- Expiring-token and refresh-token support, including automatic mode changes.
- Public web interface or browser-based PAT submission.
- New synchronization features.
- Integration with, or removal of, the separate `backend/github_client.py`.
- Analytics, user session history, Device Flow, or other alternate authentication methods.
- GitHub App installation-token authentication unless a separate review establishes that it is required.

Existing `api/`, `backend/`, and `web/` files are not automatically deleted. Their future is subject to a separate review.

## 3. Architecture

The runtime architecture consists of three application components:

```text
                  GitHub
                     |
             OAuth authorization
                     |
                     v
                Auth Broker
                     |
                HTTPS polling
                     |
                     v
                 Local CLI
                   /   \\
                  /     \\
             Keyring   GitHubClient
                           |
                           v
                    ForkSynchronizer
```

The GitHub App is a registration and configuration in GitHub, not a separate runtime component. The Keyring is an operating-system service, not an application server.

### 3.1 CLI responsibilities

The CLI starts authentication, generates and retains a cryptographically random polling secret, opens the authorization URL in the system browser, polls the Broker over HTTPS, verifies the returned GitHub identity, stores the credential in Keyring, sends ACK after successful storage, manages local profiles, and supplies the selected credential to the existing GitHub client.

The CLI never contains the GitHub App `client_secret` or PKCE verifier.

### 3.2 Auth Broker responsibilities

The Broker creates and manages temporary OAuth transactions; generates and stores the PKCE verifier; generates and validates OAuth `state`; handles the registered GitHub callback; exchanges authorization codes for GitHub App user access tokens; temporarily holds token responses until ACK or transaction expiry; and handles polling, ACK, and cleanup.

The Broker does not maintain a DREAMEROL user database, permanently store GitHub tokens, discover repositories, execute synchronization, maintain user profiles, or refresh tokens in the MVP.

The Broker is a publicly reachable HTTPS service that temporarily handles authorization codes and tokens. It must be operated as a security-sensitive component.

### 3.3 GitHub App and Keyring

The GitHub App registration defines the Client ID, Client Secret, callback URL, repository permissions, user authorization configuration, and token expiration policy. The Client Secret is stored only in protected Broker configuration.

The operating system's Keyring is the only persistent store for GitHub credentials in the MVP. Each account's access token is stored separately. Refresh tokens are not used. Tokens must never be stored in ordinary configuration files, `.env` files, JSON metadata, logs, or plaintext temporary files.

## 4. OAuth and PKCE policy

The Broker is the OAuth client: it creates the authorization request, receives the callback, retains the PKCE verifier, exchanges the authorization code, and holds the GitHub App `client_secret`.

DREAMEROL-SYNC requires PKCE S256 for every login transaction, a cryptographically random transaction-bound OAuth `state`, single-use authorization codes, a fixed registered HTTPS callback URL, and transaction ownership/state/TTL validation. The polling secret is separate from PKCE and authenticates the CLI to the Broker.

The implementation must follow the current official GitHub App Authorization Code Flow documentation. Before implementation approval, record the exact authorization URL, token endpoint, request encoding and parameters, PKCE behavior, callback URL matching requirements, and `client_secret` requirements.

References:

- [PKCE support for OAuth and GitHub App authentication](https://github.blog/changelog/2025-07-14-pkce-support-for-oauth-and-github-app-authentication/)
- [Generating a user access token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)

## 5. Authentication flow

### 5.1 Start a transaction

1. The CLI generates a cryptographically random polling secret with at least 256 bits of entropy and retains it only in process memory.
2. The CLI computes its SHA-256 hash and sends it to `POST /auth/start` over HTTPS.
3. The Broker generates an unpredictable transaction ID, OAuth `state`, PKCE verifier, and corresponding S256 challenge.
4. The Broker stores the minimum transaction data with a short TTL and returns the transaction ID and GitHub authorization URL.

The polling secret is never included in the authorization URL. The PKCE verifier remains on the Broker and is never returned to the CLI.

### 5.2 Browser authorization and URL constraints

The CLI opens the authorization URL returned by the Broker using the operating system's default browser. The authorization URL is generated only by the Broker. Its host must be exactly `github.com`; the CLI must not accept a caller-supplied authorization host, callback, or redirect target.

The user authenticates with GitHub, reviews the requested permissions, and authorizes DREAMEROL-SYNC. The flow does not require QR codes, Device Flow, or manual code entry. GitHub may independently request additional verification, such as two-factor authentication.

The GitHub App uses one fixed HTTPS callback URL. Wildcard callback matching must be disabled. `redirect_uri` is sent in the authorization and token-exchange requests as required by the verified GitHub flow and must exactly match the registered callback. No dynamic callback URL or open redirect is permitted.

### 5.3 Callback, state, and OAuth errors

GitHub redirects the browser to the registered HTTPS callback. The Broker handles both success and error callbacks.

For a successful callback, the Broker validates the state, transaction TTL, and expected transaction status, then atomically claims the transaction for processing by changing it from `PENDING` to `PROCESSING`. Only one callback handler may acquire this transition. Concurrent or replayed callbacks must not initiate another token exchange.

For a valid state and an explicit denial such as `error=access_denied`, the Broker atomically marks the associated transaction `CANCELLED`. For a valid state with another OAuth error or a missing authorization code, it marks that transaction `FAILED`.

A missing or invalid state does not identify a transaction. The Broker rejects the callback and displays a generic safe error without changing any transaction. The affected transaction expires naturally unless the user cancels it through a separately authenticated mechanism.

Callback `code` and `state` query parameters are redacted from proxy and application logs. A callback is processed at most once.

### 5.4 Token exchange and response validation

The Broker sends an HTTPS POST request to:

`https://github.com/login/oauth/access_token`

The implementation must use the exact request encoding documented for the selected GitHub App flow. It must explicitly request JSON with `Accept: application/json` and include the documented parameters, including `client_id`, `client_secret`, `code`, `redirect_uri`, and `code_verifier` as required by the verified flow.

The Broker validates the HTTP status, response `Content-Type`, JSON syntax, and response schema. It rejects malformed JSON, unexpected field types, missing required values, and error responses. Secrets and response bodies must not be logged.

For the MVP non-expiring-token mode, the response must satisfy all of these checks:

- `access_token` is present and non-empty.
- `token_type` is `bearer` (case-insensitive comparison may be used if the documented response permits it).
- `expires_in` is absent.
- `refresh_token` is absent.
- `refresh_token_expires_in` is absent.
- The GitHub App has been explicitly configured with user-to-server token expiration set to **Opt-out**, and that setting has been verified in GitHub App configuration.

Absence of `expires_in` alone is not proof of non-expiring mode. If any response or configuration check fails, the transaction fails with a safe error. No token is stored or delivered, and no refresh flow is started.

The token response is held only in temporary transaction storage, never persistent storage or logs.

### 5.5 Poll for the result

The CLI sends `POST /auth/poll`. The request body contains only the transaction ID:

```json
{
  "transaction_id": "<random-transaction-id>"
}
```

The polling secret is supplied only in an HTTPS request header:

```http
Authorization: Bearer <polling-secret>
```

The Broker locates the transaction, checks its TTL, hashes the supplied secret, compares it with the stored hash using a constant-time comparison, and checks transaction state. The token response is returned only if the secret is valid and the result is ready.

An incorrect or missing polling secret must not reveal whether a transaction exists or whether its token response is ready. Repeated polling before ACK returns the same temporary result only to a client proving possession of the polling secret.

Polling secrets must not appear in URLs, query parameters, request bodies, redirects, or logs. Responses containing authentication state or tokens include:

```http
Cache-Control: no-store
Pragma: no-cache
```

### 5.6 Verify GitHub identity

After receiving the token response, the CLI calls `GET https://api.github.com/user` using:

```http
Authorization: Bearer <github-access-token>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2026-03-10
```

The API version is a single centralized client configuration, not a per-method value. Before adopting a newer API version, review its changelog and test the integration. The version shown here must be supported by GitHub at implementation time.

The CLI verifies that the response is successful and contains a numeric GitHub user ID and username. The numeric user ID is the canonical profile identifier; the username is display metadata and may change.

### 5.7 Store the credential

The CLI stores the access token in the system Keyring, keyed by numeric GitHub user ID. The Keyring write must succeed before ACK.

If Keyring is unavailable or the write fails, the CLI does not ACK. It may retry the Keyring write or poll again with the same transaction and polling secret. The token remains only in process memory and is never written to a plaintext file. If the CLI exits and loses the polling secret or token response, the user must start a new login transaction.

### 5.8 Acknowledge delivery

After the Keyring write succeeds, the CLI sends `POST /auth/ack`. Its body contains only the transaction ID; the polling secret uses the same HTTPS `Authorization` header as polling.

The CLI sends ACK only after its Keyring operation succeeds. ACK is a client assertion that local credential storage completed; the Broker cannot independently inspect or verify the local Keyring.

The Broker accepts ACK only after the transaction has entered `DELIVERY_AUTHORIZED` through an authorized poll that returns the token payload. It atomically marks the transaction acknowledged and deletes the token response, PKCE verifier, and OAuth state. ACK is idempotent. If its response is lost, the CLI can retry using the same transaction ID and polling secret.

After ACK, the Broker may retain a short-lived tombstone containing only the transaction ID, polling-secret hash, acknowledged status, completion time, and tombstone expiry time. It contains no token, authorization code, PKCE verifier, or OAuth state. Proposed tombstone retention is 600 seconds and is configurable.

## 6. Broker API contract

The MVP exposes four endpoints.

### `POST /auth/start`

Request:

```json
{
  "poll_secret_hash": "<sha256-hex>"
}
```

Response:

```json
{
  "transaction_id": "<random-id>",
  "authorization_url": "https://github.com/login/oauth/authorize?...",
  "expires_in": 600
}
```

The endpoint validates request format and applies configurable rate limits.

### `GET /auth/callback`

Receives GitHub callback parameters `code` and `state` on success, or OAuth error parameters such as `error=access_denied` on failure. It never accepts an access token directly from the browser. Callback query parameters are redacted from access, application, tracing, and error-reporting logs.

### `POST /auth/poll`

Request body:

```json
{
  "transaction_id": "<random-id>"
}
```

Authentication:

```http
Authorization: Bearer <polling-secret>
```

### `POST /auth/ack`

Request body:

```json
{
  "transaction_id": "<random-id>"
}
```

Authentication:

```http
Authorization: Bearer <polling-secret>
```

Successful response:

```json
{
  "status": "acknowledged"
}
```

The polling secret is never sent in a URL or request body. All CLI-to-Broker requests use HTTPS.

## 7. Transaction lifecycle and concurrency

Internal transaction states and public poll results are:

| Internal state | Poll result | Behavior |
|---|---|---|
| `PENDING` | `pending` | OAuth flow is not complete |
| `PROCESSING` | `pending` | A callback handler has atomically claimed the transaction |
| `TOKEN_READY` | `completed` | Token is ready for delivery |
| `DELIVERY_AUTHORIZED` | `completed` | An authorized poll has been allowed to receive the token; repeat polls before ACK return the same payload |
| `ACKNOWLEDGED` | `already_acknowledged` | Never return the token again |
| `EXPIRED` | `expired` | Require a new login |
| `FAILED` | `failed` | Return a safe error category and require resolution/new login |
| `CANCELLED` | `failed` | Authorization was denied or cancelled |

`completed` means that token delivery is available or remains retryable; it does not mean that ACK has been received. `DELIVERY_AUTHORIZED` does not prove that the client received or persisted the response.

State transitions, callback acquisition, poll delivery authorization, and ACK must be atomic. Concurrent callback requests must not cause multiple token exchanges. Concurrent poll requests must not corrupt state. Concurrent ACK requests and retries must be safe and idempotent. ACK cannot succeed before an authorized poll has made token delivery available. After ACK succeeds, no poll may return token material.

Proposed initial transaction TTL is 600 seconds. The TTL is configurable but must remain short. The MVP uses an in-memory transaction store and assumes one Broker instance with one transaction-owning worker.

On Broker restart, unfinished transactions and undelivered token responses are discarded; the CLI starts a new login. Tokens are never recovered from persistent storage. Multiple Broker instances or workers require shared transaction state and a separate security review.

## 8. Token policy

### 8.1 MVP: non-expiring user access token

The MVP requires the GitHub App to be configured with user-to-server token expiration set to **Opt-out**. The authorization request must not include `offline_access`.

Before implementation approval, verify the App setting and response behavior against current official GitHub documentation and through a real GitHub App integration test. The response validation requirements in Section 5.4 apply. The absence of `expires_in` alone is insufficient proof.

If GitHub returns an expiring response or the App cannot be configured to issue the expected non-expiring token, login fails with a clear, non-secret error. The token is not accepted or stored, and the application does not silently switch modes.

A non-expiring token is not irrevocable; GitHub or the user can revoke access. GitHub recommends expiring tokens for security. The MVP's non-expiring-token requirement is an explicit product trade-off to reduce repeated authentication.

The product and operations documentation must explain how a user can revoke the GitHub App authorization and how the project operator can rotate or revoke the App's client secret.

### 8.2 Explicitly excluded: refresh-token flow

The MVP does not request `offline_access`, store refresh tokens, refresh access tokens, expose a Broker refresh endpoint, or silently switch to an expiring-token mode. A refresh flow may be proposed separately and requires a new architecture and security review.

### 8.3 Revocation and invalidation

On HTTP 401 or other confirmation that a credential is invalid, the CLI stops repeated authenticated requests and offers a new login. HTTP 403 is not automatically treated as an invalid token; it may indicate insufficient permissions, missing App resource access, organization restrictions, or SAML SSO requirements.

## 9. GitHub App authorization, resource access, and permissions

### 9.1 User authorization and repository access model

The MVP uses GitHub App user authorization and user access tokens. It does not use installation access tokens unless a separate review establishes that they are necessary.

User authorization, GitHub App permissions, App installation/resource access, and the user's own repository access are distinct concepts. Successful user authorization alone must not be treated as proof that every repository visible to the user is available to the App or token. GitHub determines effective access according to the selected GitHub App user authorization model and the user's access.

Before implementation approval, document and test how the selected GitHub App configuration exposes public and private repositories to a user access token, whether installation or repository selection is relevant for that configuration, and how the CLI reports a repository that the user can access but the token cannot. Do not make App installation on all repositories an architectural prerequisite without evidence that the selected user authorization flow requires it. Do not introduce installation-token authentication into the MVP without a separate approved requirement.

The CLI must handle repository access changing after login. API permission or resource-access failures are reported distinctly from invalid authentication. The CLI may refresh its repository list on the next operation; it must not assume that access granted at login remains unchanged.

### 9.2 GitHub App permission requirements

The endpoint inventory below was checked against the current GitHub REST API endpoint documentation and the official GitHub App permissions reference. The inventory is based on the actual calls in `fork_sync/github.py` and the way `ForkSynchronizer` uses them.

| Operation | REST endpoint | Minimum GitHub App repository permission |
|---|---|---|
| Identify authenticated user | `GET /user` | No additional permissions |
| Discover accessible repositories | `GET /user/repos` | `Metadata: read` |
| Retrieve repository metadata and fork parent information | `GET /repos/{owner}/{repo}` | `Metadata: read` |
| Compare upstream and fork branches | `GET /repos/{owner}/{repo}/compare/{basehead}` | `Contents: read` |
| Synchronize fork with upstream | `POST /repos/{owner}/{repo}/merge-upstream` | `Contents: write` |

Official references:

- [Get the authenticated user](https://docs.github.com/en/rest/users/users#get-the-authenticated-user)
- [List repositories for the authenticated user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user)
- [Get a repository](https://docs.github.com/en/rest/repos/repos#get-a-repository)
- [Compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
- [Sync a fork branch with the upstream repository](https://docs.github.com/en/rest/branches/branches#sync-a-fork-branch-with-the-upstream-repository)
- [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)

**Documentation verification date:** 2026-11-10.

`Contents` is a single GitHub App repository permission with read-only or read-and-write access levels. The application requires `Contents: read` for comparison and `Contents: write` for upstream synchronization. Therefore, the configured permission must be `Contents: Read and write`. This does not mean every operation in the workflow requires write access.

The repository-detail fallback retrieves missing fork parent information and consumes repository metadata fields only. It requires `Metadata: read` for the currently used fields. The application does not request merge-related settings from this endpoint. If future code reads merge-related settings, review the endpoint's additional documented permission requirements before adding that behavior.

### 9.3 Inventory boundary

The checked sync-related endpoint inventory includes:

- `GET /user` through `GitHubClient.get_authenticated_user()`.
- `GET /user/repos` through `GitHubClient.list_repositories()`.
- `GET /repos/{owner}/{repo}` through `GitHubClient.get_repository()` when fork parent metadata is missing.
- `GET /repos/{owner}/{repo}/compare/{basehead}` through `GitHubClient.compare_upstream()`.
- `POST /repos/{owner}/{repo}/merge-upstream` through `GitHubClient.merge_upstream()`.

Before implementation approval, re-review all modules in `fork_sync/`, `main.py`, and any indirect GitHub API calls to confirm that no additional endpoints or permissions are required. No additional permissions, including administration or workflow permissions, may be requested without evidence from the code and endpoint documentation.

## 10. Broker operational security

The Broker is publicly reachable and temporarily processes authorization codes and GitHub tokens. It must be operated as a security-sensitive service, even though it has no persistent token database.

### 10.1 Transport and callback security

- HTTPS is mandatory, with valid, automatically renewed TLS certificates.
- TLS termination occurs at a trusted, securely configured ingress or reverse proxy.
- Proxy-to-Broker traffic uses a protected network or authenticated encrypted transport.
- Authentication secrets are never sent over plaintext HTTP.
- The callback URL is fixed, registered, HTTPS-only, and configured with wildcard matching disabled.
- The Broker generates authorization URLs only for the exact `github.com` host.
- No dynamic `redirect_uri` or open redirect is permitted.

### 10.2 Logging and redaction

Never log GitHub authorization codes, access tokens, polling secrets or their hashes, PKCE verifiers, OAuth `state`, or token response bodies.

Reverse proxy access logs redact callback query parameters, especially `code` and `state`. Request-body logging is disabled for authentication endpoints. Monitoring, tracing, exception reporting, and error aggregation apply the same redaction policy.

### 10.3 Client secret operations

The GitHub App `client_secret` must be stored in a secret manager or protected deployment configuration and must never be committed to source control, included in the CLI, or exposed in logs.

The operator must document a rotation procedure before deployment:

1. Generate or obtain the replacement secret through GitHub's supported controls.
2. Update the Broker's protected secret configuration without exposing the value.
3. Restart or reload the Broker in a controlled manner.
4. Verify a new authorization/token exchange using a test account.
5. Revoke the old secret when safe under GitHub's rotation process.

If compromise is suspected, promptly revoke/rotate the secret, invalidate active Broker transactions, review access and deployment logs for exposure (without logging secrets), and notify affected users if their credentials may be at risk. The exact procedure must follow the current GitHub App controls.

### 10.4 Temporary data and crash handling

- Token responses exist only in temporary transaction storage.
- Core dumps and diagnostic memory dumps are disabled or securely restricted.
- Debug logging does not expose transaction secrets.
- Expired and completed transaction material is promptly deleted.
- Deployment documents residual process-memory and swap risks.

### 10.5 Abuse protection and configurable rate limits

All rate limits and operational thresholds are configurable deployment settings, not GitHub requirements. Initial suggested defaults are:

| Control | Suggested initial value |
|---|---:|
| Transaction TTL | 600 seconds |
| Maximum active transactions per source IP | 5 |
| `/auth/start` per source IP | 5 requests per 10 minutes |
| CLI polling interval | 2 seconds initially, with backoff such as 2, 4, then 8 seconds |
| Maximum poll rate per transaction | 30 requests per minute |
| ACK tombstone retention | 600 seconds |

The implementation combines source-IP controls with transaction-level limits and abuse detection. IP limits must account for shared NATs and must not permanently block users solely because multiple legitimate users share an address. Return a retryable rate-limit response where appropriate, avoid disclosing transaction state, and permit configuration/tuning based on deployment tests.

The Broker also enforces request-size limits, active-transaction limits, malformed-request rejection, repeated-callback protection, and polling-secret brute-force protection.

### 10.6 Monitoring and restart behavior

Monitoring may record request counts, safe status categories, transaction completion/failure counts, expiration counts, availability, and latency. It must not include tokens, authorization codes, polling secrets, OAuth state, or unnecessary personal GitHub profile data.

The MVP uses an in-memory transaction store. A Broker restart destroys unfinished transactions and undelivered token responses. The CLI reports this clearly and offers a new login. No token recovery from persistent storage is permitted.

## 11. Local profiles and storage

Profile metadata and authentication credentials are separate data categories.

### 11.1 Credential storage

The Keyring stores the GitHub access token. The MVP does not store a refresh token.

Suggested Keyring service name: `dreamerol-sync`.

Suggested credential key: `github-user-<numeric-id>`.

### 11.2 Non-secret local metadata

A local metadata file may be stored in the operating system's application-data directory. It may contain the numeric GitHub user ID, username, Keyring credential reference, token mode, account creation/update timestamp, last successful verification timestamp, and last-used timestamp.

It must not contain access tokens, refresh tokens, polling secrets, authorization codes, PKCE verifiers, or OAuth state. Email addresses are not required and should not be collected for the MVP. Use appropriate operating-system file permissions.

### 11.3 Multi-account behavior, logout, and profile removal

Each profile is identified by numeric GitHub user ID. Supported operations include adding, listing, selecting, removing, and reauthenticating accounts, validating a stored credential, and logging out.

Before removing a profile or deleting its Keyring credential, the CLI must identify the target account clearly and require explicit confirmation (or implement an equally clear, documented confirmation policy). Logout behavior must state whether it only deselects the active profile or also deletes its local credential; credential deletion requires explicit user confirmation. Local deletion does not itself revoke authorization at GitHub.

When switching profiles, the active client must be rebuilt with the selected profile's credential. The previous profile's token must not be reused, retained in a shared mutable client, or sent for requests made under the newly selected profile.

Username is display metadata and may change.

### 11.4 Existing account migration

The existing account manager uses username-keyed Keyring entries. Migration is explicit and non-destructive:

1. Read an existing credential without exposing it.
2. Authenticate with GitHub and call `GET /user`.
3. Obtain and validate the numeric GitHub user ID and username.
4. Store the credential under the new numeric-ID-based Keyring key.
5. Read back the new entry and verify it.
6. Update non-secret local metadata.
7. Preserve the legacy entry until migration is confirmed and cleanup is separately approved.

A PAT is not silently converted into a GitHub App user access token. Existing PAT authentication remains available during the migration period. Removing legacy entries requires a separate migration-completion decision.

## 12. CLI and synchronization integration

Authentication remains independent of synchronization logic. The intended dependency direction is:

```text
Authentication
      |
      v
TokenManager
      |
      v
GitHubClient
      |
      v
ForkSynchronizer
```

The synchronization engine does not depend on whether a credential originated from the existing PAT path or the new GitHub App flow.

This authentication work does not change fork discovery or comparison behavior, preview/dry-run behavior, explicit `SYNC` confirmation, diverged-history or local-commit protections, repository filtering, or per-repository error handling.

PAT compatibility remains in place during migration. Removing PAT support is a separate decision.

## 13. Error handling

| Situation | Required behavior |
|---|---|
| User denies authorization (`access_denied`) with valid state | Atomically mark the associated transaction `CANCELLED`; show a safe completion page |
| Missing or invalid callback state | Reject callback without changing any transaction; show a generic safe error |
| Valid state but missing code or another OAuth error | Mark only the associated transaction `FAILED` |
| Replayed or concurrent callback | Do not perform another token exchange |
| Expired transaction | Require a new login |
| Invalid polling secret | Reject without revealing transaction readiness |
| GitHub token exchange failure or invalid JSON/schema | Mark transaction `FAILED` |
| Unexpected or invalid token response | Fail login; do not enable refresh |
| GitHub `/user` returns 401 or invalid identity | Reject credential; do not ACK |
| Keyring write failure | Do not ACK; retry in memory or require a new login |
| Polling network failure | Retry with bounded backoff until transaction expiry |
| ACK response is lost | Retry ACK; do not deliver tokens after acknowledgment |
| ACK before an authorized delivery poll | Reject ACK without acknowledging the transaction |
| Concurrent poll or ACK requests | Apply atomic state transitions; never deliver after ACK |
| Broker restart | Discard unfinished transaction and start a new login |
| Token revoked | Stop using it and offer reauthentication |
| HTTP 403 | Report permission, resource access, organization, or SSO issue; do not automatically reauthenticate |
| Configured rate limit reached | Return a safe, retryable response where appropriate; do not reveal transaction state |

Error messages must not expose secrets, authorization codes, token responses, or raw request headers.

## 14. Testing strategy

### 14.1 Unit tests

- Polling-secret generation, hashing, and constant-time validation.
- PKCE S256 generation and verifier retention on the Broker.
- OAuth state validation and single-use behavior.
- OAuth denial, missing-code, and callback-error handling.
- Invalid/missing state does not modify any transaction.
- Atomic callback acquisition and replay rejection.
- Transaction TTL and atomic state transitions.
- `pending`, `completed`, and `already_acknowledged` poll responses.
- Repeated polling before ACK and no token delivery after ACK.
- Concurrent polling and ACK requests, including ACK-before-delivery rejection.
- Idempotent ACK and tombstone expiration.
- Token endpoint JSON request/response, HTTP status, Content-Type, and schema validation.
- Non-expiring MVP token validation and rejection of unexpected expiring responses.
- Keyring storage and retry behavior.
- Multi-account selection, logout, and confirmed removal.
- Profile switching does not reuse the previous profile's token.
- Non-secret metadata storage and legacy account migration.
- Rate-limit behavior under shared-IP/NAT scenarios.
- Callback URL and authorization-host restrictions; wildcard callback setting is disabled.
- Client-secret/log redaction.

### 14.2 Broker integration tests

Test `/auth/start`, `/auth/callback`, `/auth/poll`, and `/auth/ack`; invalid, expired, denied, and replayed callbacks; invalid polling secrets; repeated polling and ACK; token-exchange failure; Broker restart; Keyring failure before ACK; concurrent requests; configurable rate limits; and callback/query/secret log redaction.

### 14.3 Real GitHub integration tests

Use a separate test GitHub App and designated test fork to verify real browser authorization, callback, PKCE token exchange, JSON token response, `GET /user`, Keyring storage/retrieval, CLI restart, the selected user authorization/resource access model, repository permissions, `merge-upstream`, and configured non-expiring-token behavior.

Real write tests must not run automatically in ordinary unit-test CI and must not target a production repository without explicit authorization.

## 15. Acceptance criteria

The specification may be approved for implementation when:

- [ ] GitHub App registration settings and the selected user authorization/resource access model are finalized.
- [ ] Authorization Code Flow, exact token endpoint request encoding, and parameters are verified.
- [ ] Token exchange explicitly requests JSON and validates HTTP status, Content-Type, JSON syntax, and schema.
- [ ] PKCE S256 behavior is verified.
- [ ] The `client_secret` remains exclusively on the Broker and a rotation/compromise procedure is documented.
- [ ] One fixed HTTPS callback URL is finalized and wildcard matching is disabled.
- [ ] Authorization host is restricted to `github.com`; no open redirect or dynamic callback is permitted.
- [ ] Polling and ACK header contracts are finalized.
- [ ] Transaction TTL, atomic transitions, callback acquisition, poll/ACK races, and tombstone behavior are defined.
- [ ] Missing/invalid OAuth state never modifies a transaction; denial and callback errors are handled.
- [ ] ACK is accepted only after delivery has been authorized, and the CLI sends it only after successful Keyring storage.
- [ ] The non-expiring token configuration and response validation are verified with official documentation and a real GitHub App test.
- [ ] The MVP rejects unexpected expiring tokens and does not request `offline_access`.
- [ ] Every required API endpoint has an official, endpoint-specific permission reference.
- [ ] App permissions, user authorization, any applicable App resource/installation access, and user access to a repository are treated as distinct checks.
- [ ] The endpoint inventory has been rechecked against all current and indirect API calls in the repository.
- [ ] The centralized GitHub REST API version is supported and tested at implementation time.
- [ ] Keyring, non-secret metadata, logout, profile removal, and profile switching behavior are defined.
- [ ] Legacy PAT migration behavior is documented.
- [ ] Broker operational security, configurable rate limits, and log redaction have been reviewed and tested.
- [ ] Unit, Broker integration, and controlled GitHub integration test plans are approved.
- [ ] Existing synchronization behavior remains outside the scope of the authentication implementation.

## 16. Explicitly deferred decisions

The following require separate approval:

- Removing PAT authentication.
- Deleting the existing web/API prototype.
- Removing `backend/github_client.py`.
- Changing the synchronization algorithm.
- Introducing persistent Broker storage.
- Supporting multiple Broker instances or workers.
- Supporting GitHub Enterprise Server.
- Adding expiring-token or refresh-token support.
- Introducing installation access tokens.
- Changing the existing account model beyond the approved migration.

## 17. Official references

### GitHub App authentication and tokens

- [GitHub App authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app)
- [Generating a user access token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [Refreshing user access tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)

### OAuth and PKCE

- [PKCE support for OAuth and GitHub App authentication](https://github.blog/changelog/2025-07-14-pkce-support-for-oauth-and-github-app-authentication/)
- [Creating an OAuth app and callback URL configuration](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)

### GitHub App permissions and REST API endpoints

- [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)
- [Get the authenticated user](https://docs.github.com/en/rest/users/users#get-the-authenticated-user)
- [List repositories for the authenticated user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user)
- [Get a repository](https://docs.github.com/en/rest/repos/repos#get-a-repository)
- [Compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
- [Sync a fork branch with the upstream repository](https://docs.github.com/en/rest/branches/branches#sync-a-fork-branch-with-the-upstream-repository)

### GitHub REST API versioning and security

- [REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
- [REST API version 2026-03-10 changelog](https://github.blog/changelog/2026-03-12-rest-api-version-2026-03-10-is-now-available/)
- [GitHub App security best practices](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app)

## Final status

**ARCHITECTURE DIRECTION ACCEPTED — IMPLEMENTATION APPROVAL PENDING.**

This document defines the proposed authentication architecture and security requirements. It does not authorize code implementation or deployment. Any repository changes beyond this specification require separate approval.

Implementation requires explicit approval of this document and completion of the acceptance criteria.
