# DREAMEROL-SYNC GitHub App Authentication Specification

## Status

**Architecture direction accepted — implementation approval pending.**

This document specifies the proposed GitHub App authentication architecture for the local DREAMEROL-SYNC CLI using a minimal Auth Broker.

Implementation is not authorized until the remaining security and implementation requirements have been reviewed and this specification has been explicitly approved.

## 1. Goals

Provide a simple GitHub sign-in experience for the local DREAMEROL-SYNC CLI.

The user runs one CLI command, which opens GitHub's authorization page in the system browser.

Requirements:

- Users enter GitHub credentials only on GitHub.
- DREAMEROL-SYNC never requests, receives, or stores a GitHub password.
- The GitHub App `client_secret` is never distributed with the CLI.
- The flow does not use QR codes, Device Flow, or manually copied authorization codes.
- GitHub credentials are stored locally in the operating system's Keyring.
- Multiple GitHub profiles are supported.
- The existing synchronization engine and its safety behavior remain unchanged.
- The MVP uses a GitHub App configured for non-expiring user access tokens.
- If the configured GitHub App cannot issue the expected non-expiring token, login fails clearly. The MVP does not fall back to refresh tokens.

## 2. Scope

### 2.1 Included in the MVP

- Local CLI browser-based GitHub login.
- GitHub App Authorization Code Flow through an Auth Broker.
- A registered HTTPS callback URL on the Broker.
- PKCE S256.
- OAuth `state` validation.
- Short-lived authentication transactions.
- HTTPS polling and acknowledgment (ACK).
- GitHub identity verification through `GET /user`.
- Local Keyring credential storage.
- Multiple local GitHub profiles.
- Token validation and reauthentication when access is revoked or invalid.
- Integration with the existing `GitHubClient` and `ForkSynchronizer`.

### 2.2 Explicitly excluded from the MVP

- DREAMEROL user registration, passwords, or a user database.
- Cloud profile storage.
- Persistent GitHub token storage on the Broker.
- Expiring-token and refresh-token support.
- Automatic transition to any alternate token mode.
- Public web interface or browser-based PAT submission.
- New synchronization features.
- Integration with, or removal of, the separate `backend/github_client.py`.
- Analytics or user session history.
- Device Flow or other alternate authentication methods.

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
                   /   \
                  /     \
             Keyring   GitHubClient
                           |
                           v
                    ForkSynchronizer
```

The GitHub App is a registration and configuration in GitHub, not a separate runtime component. The Keyring is an operating-system service, not an application server.

### 3.1 CLI responsibilities

The CLI:

- Starts an authentication transaction.
- Generates and retains a cryptographically random polling secret.
- Opens the Broker-provided authorization URL in the system browser.
- Polls the Broker over HTTPS.
- Validates the returned GitHub identity.
- Stores the GitHub credential in the system Keyring.
- Sends ACK only after the Keyring write succeeds.
- Manages local GitHub profiles.
- Supplies the selected credential to the existing GitHub client.

The CLI never contains the GitHub App `client_secret` or PKCE verifier.

### 3.2 Auth Broker responsibilities

The Broker:

- Creates and manages temporary OAuth transactions.
- Generates and stores the PKCE verifier.
- Generates and validates OAuth `state`.
- Handles the registered GitHub callback.
- Exchanges authorization codes for GitHub App user access tokens.
- Temporarily holds token responses until delivery is acknowledged or the transaction expires.
- Delivers token responses to the CLI through polling authenticated by the polling secret.
- Handles ACK and transaction cleanup.

The Broker does not:

- Maintain a DREAMEROL user database.
- Permanently store GitHub user tokens.
- Discover repositories or execute synchronization.
- Maintain GitHub profile records.
- Act as a general-purpose application backend.
- Refresh tokens in the MVP.

The Broker is a publicly reachable HTTPS service that temporarily handles authorization codes and tokens. It must be operated as a security-sensitive component.

### 3.3 GitHub App responsibilities

The GitHub App registration defines:

- Client ID.
- Client secret.
- Registered callback URL.
- Repository permissions.
- User authorization configuration.
- User access token expiration policy.

The `client_secret` is stored only in protected Broker configuration.

### 3.4 Keyring responsibilities

The operating system's Keyring is the only persistent store for GitHub credentials in the MVP.

The Keyring stores each account's access token separately. Refresh tokens are not used in the MVP.

Tokens must never be stored in ordinary configuration files, `.env` files, JSON metadata, logs, or plaintext temporary files.

## 4. OAuth and PKCE policy

### 4.1 GitHub-supported behavior

The implementation must follow the official GitHub App Authorization Code Flow and current GitHub documentation.

The Broker is the OAuth client for this flow:

- It creates the authorization request.
- It receives the callback.
- It retains the PKCE verifier.
- It exchanges the authorization code.
- It holds the GitHub App `client_secret`.

When PKCE is used, the authorization request includes an S256 challenge, and the token exchange includes the corresponding `code_verifier`.

The GitHub App `client_secret` remains on the Broker and is not included in the CLI.

### 4.2 DREAMEROL-SYNC security policy

Regardless of GitHub's minimum requirements, DREAMEROL-SYNC requires:

- PKCE S256 for every login transaction.
- A cryptographically random, transaction-bound OAuth `state`.
- Single-use authorization codes.
- A fixed, registered HTTPS callback URL.
- Transaction ownership, state, and TTL validation.

The Broker generates and retains the PKCE verifier. The CLI never receives or stores it.

The polling secret is separate from PKCE. It authenticates the CLI to the Broker when polling for the token result.

### 4.3 Verification requirement

Before implementation approval, record the exact GitHub App documentation and request parameters for:

- The authorization URL.
- The token endpoint.
- `client_id` and `client_secret`.
- `code`, `redirect_uri`, and `code_verifier`.
- PKCE challenge parameters and the supported method.
- Callback URL matching requirements.

References:

- [PKCE support for OAuth and GitHub App authentication](https://github.blog/changelog/2025-07-14-pkce-support-for-oauth-and-github-app-authentication/)
- [Generating a user access token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)

## 5. Authentication flow

### 5.1 Start a transaction

1. The CLI generates a cryptographically random polling secret with at least 256 bits of entropy.
2. The CLI retains the secret only in process memory.
3. The CLI computes the SHA-256 hash of the polling secret.
4. The CLI sends `POST /auth/start` to the Broker with the hash.
5. The Broker generates:
   - An unpredictable transaction ID.
   - OAuth `state`.
   - A PKCE verifier.
   - The corresponding PKCE S256 challenge.
6. The Broker stores the temporary transaction data with a short TTL.
7. The Broker returns the transaction ID and GitHub authorization URL.

The polling secret is never included in the authorization URL.

The PKCE verifier remains on the Broker and is never returned to the CLI.

### 5.2 Open GitHub authorization

The CLI opens the returned authorization URL using the operating system's default browser.

The user authenticates with GitHub, reviews the requested permissions, and authorizes DREAMEROL-SYNC.

The flow does not require the user to scan a QR code, use Device Flow, or manually enter or copy an authorization code. GitHub may independently request additional account verification, such as two-factor authentication.

### 5.3 Handle the GitHub callback

GitHub redirects the browser to the registered HTTPS callback URL.

The Broker receives the authorization code and OAuth `state`. It then:

1. Locates the transaction associated with the state.
2. Checks that the transaction exists and has not expired.
3. Validates the state using a constant-time comparison.
4. Confirms that the transaction is in the expected state.
5. Performs one token exchange for the authorization code.

Invalid, expired, or reused state causes the callback to be rejected.

The callback's `code` and `state` query parameters must be redacted from proxy and application logs.

### 5.4 Exchange the authorization code

The Broker sends an HTTPS POST request to:

`https://github.com/login/oauth/access_token`

The request uses the documented GitHub App Authorization Code Flow parameters, including:

- `client_id`
- `client_secret`
- `code`
- `redirect_uri`
- `code_verifier`

The Broker validates the response structure and confirms that it matches the MVP's non-expiring-token policy before making it available for polling.

The token response is held only in temporary transaction storage. It is never written to persistent storage or logs.

If the response indicates an expiring token or otherwise does not match the configured MVP policy, the Broker fails the transaction. It does not initiate a refresh-token flow.

### 5.5 Poll for the result

The CLI sends `POST /auth/poll`.

The request body contains only the transaction ID:

```json
{
  "transaction_id": "<random-transaction-id>"
}
```

The polling secret is supplied only in an HTTPS request header:

```http
Authorization: Bearer <polling-secret>
```

The Broker:

1. Locates the transaction.
2. Checks its TTL.
3. Hashes the supplied polling secret.
4. Compares the hash with the stored hash using a constant-time comparison.
5. Checks the transaction state.
6. Returns the token response only if the polling secret is valid and the result is ready.

An incorrect or missing polling secret must not reveal whether a transaction exists or whether its token response is ready.

Repeated polling before ACK returns the same temporary token response only to a client that proves possession of the polling secret.

Polling secrets must not appear in URLs, query parameters, request bodies, redirects, or logs.

Responses containing authentication state or tokens must include:

```http
Cache-Control: no-store
Pragma: no-cache
```

### 5.6 Verify GitHub identity

After receiving the token response, the CLI calls:

`GET https://api.github.com/user`

The request uses:

```http
Authorization: Bearer <github-access-token>
Accept: application/vnd.github+json
```

The CLI verifies that:

- The response is successful.
- A numeric GitHub user ID is present.
- A username is present.

The numeric GitHub user ID is the canonical profile identifier. Username is display metadata and may change.

### 5.7 Store the credential

The CLI stores the access token in the system Keyring, keyed by the numeric GitHub user ID.

The Keyring write must succeed before the CLI sends ACK.

If the Keyring is unavailable or the write fails:

- The CLI does not send ACK.
- The token is retained only in process memory while the CLI process remains active.
- The CLI may retry the Keyring write or poll again with the same transaction and polling secret.
- The token is never written to a plaintext file.

If the CLI exits and loses the polling secret or token response held in memory, the user must start a new login transaction.

### 5.8 Acknowledge delivery

After the Keyring write succeeds, the CLI sends `POST /auth/ack`.

The request body contains only the transaction ID:

```json
{
  "transaction_id": "<random-transaction-id>"
}
```

The polling secret is supplied in the same HTTPS header used for polling:

```http
Authorization: Bearer <polling-secret>
```

The Broker validates the transaction and polling secret, marks the transaction as acknowledged, and deletes the token response, PKCE verifier, and OAuth state.

ACK is idempotent. If the response is lost, the CLI can retry ACK using the same transaction ID and polling secret.

After ACK, the Broker may retain a short-lived completion tombstone containing only:

- Transaction ID.
- Polling-secret hash.
- Acknowledged status.
- Completion time.
- Tombstone expiry time.

The tombstone contains no token, authorization code, PKCE verifier, or OAuth state.

The proposed tombstone retention period is 10 minutes.

## 6. Broker API contract

The MVP exposes four endpoints.

### 6.1 `POST /auth/start`

Creates an authentication transaction.

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

The endpoint validates request format and applies rate limits.

### 6.2 `GET /auth/callback`

Receives the GitHub browser callback.

Parameters:

- `code`
- `state`

This is the only endpoint that accepts the GitHub browser callback. It never accepts an access token directly from the browser.

Callback query parameters must be redacted from all access, application, tracing, and error-reporting logs.

### 6.3 `POST /auth/poll`

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

Public poll results:

| Internal transaction state | Poll result | Behavior |
|---|---|---|
| `PENDING` | `pending` | OAuth flow is not complete |
| `TOKEN_READY` | `completed` | Token is ready for delivery |
| `DELIVERED` | `completed` | Return the same temporary token payload to an authorized client |
| `ACKNOWLEDGED` | `already_acknowledged` | Never return the token again |
| `EXPIRED` | `expired` | Require a new login |
| `FAILED` | `failed` | Require a new login or report a safe error |

An invalid transaction ID or polling secret must not reveal whether a valid transaction or completed token exists. The public error response may use a generic unauthorized/invalid-transaction result.

`completed` means that the token is ready or remains available for delivery. It does **not** mean that the transaction has been acknowledged.

### 6.4 `POST /auth/ack`

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

ACK is idempotent. After ACK, polling returns `already_acknowledged` and never returns token material again.

All CLI-to-Broker requests use HTTPS. The polling secret is never sent in a URL or request body.

## 7. Transaction lifecycle

The state machine is:

```text
CREATED
   |
   v
PENDING
   |
   v
TOKEN_READY
   |
   v
DELIVERED
   |
   v
ACKNOWLEDGED
```

Additional terminal states:

- `EXPIRED`
- `FAILED`
- `CANCELLED`

The public poll results map to internal states as specified in Section 6.3.

Proposed initial transaction TTL: 10 minutes. The TTL is configurable but must remain short.

The MVP uses an in-memory transaction store and assumes one Broker instance with one transaction-owning worker.

On Broker restart:

- Unfinished transactions are lost.
- Undelivered token responses are discarded.
- The CLI starts a new login.
- Tokens are not recovered from persistent storage.

Supporting multiple Broker instances or workers requires shared transaction state and a separate security review.

## 8. Token policy

### 8.1 MVP mode: non-expiring user access token

The MVP requires the GitHub App to be configured for non-expiring user access tokens, using the applicable GitHub App expiration setting.

The authorization request must not include:

`offline_access`

Before the flow is approved, verify the App setting and response behavior using current official GitHub documentation and a real GitHub App integration test.

The Broker must validate that the token response matches the documented non-expiring response for the configured App. The absence of `expires_in` alone is not sufficient proof.

If GitHub returns an expiring-token response, or the App cannot be configured to issue the expected non-expiring token:

- The login transaction fails with a clear, non-secret error.
- The token is not stored as an accepted credential.
- No refresh token is accepted or stored.
- The application does not silently switch to another mode.

A non-expiring token is not irrevocable. GitHub or the user can revoke access at any time.

GitHub recommends expiring tokens for security. The MVP's non-expiring-token requirement is an explicit product trade-off to reduce repeated user authentication.

### 8.2 Explicitly excluded: refresh-token flow

The MVP does not:

- Request `offline_access`.
- Store refresh tokens.
- Refresh access tokens.
- Expose a Broker refresh endpoint.
- Silently switch to an expiring-token mode.

A refresh-token flow may be proposed as a separate future change. Any such design must define how refresh requests are authenticated, how the `client_secret` remains server-side, how rotated token pairs are delivered and stored, and how failures are handled.

### 8.3 Revocation and invalidation

When GitHub returns HTTP 401 or otherwise confirms that the credential is invalid:

- The credential is marked invalid.
- Repeated authenticated requests stop.
- The CLI offers a new GitHub login.

HTTP 403 is not automatically treated as an invalid token. It may indicate insufficient permissions or lack of access to a repository.

## 9. GitHub App permission requirements

The endpoint inventory below was reviewed against the current GitHub REST API documentation and the official GitHub App permissions reference.

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

**Verification date:** 2026-11-10.

### 9.1 Permission configuration note

`Contents` is a single GitHub App repository permission with read-only or read-and-write access levels. The application requires `Contents: read` for comparison and `Contents: write` for upstream synchronization. Therefore, the configured permission must be `Contents: Read and write`.

This does not mean that every operation in the workflow requires write access.

The GitHub App's permissions do not grant the authenticated user access to repositories the user is not otherwise authorized to access. GitHub evaluates the user's actual access to each target repository separately.

The repository-detail fallback used to retrieve missing fork parent information requires `Metadata: read` for the fields currently consumed by the sync code. The application does not request merge-related settings from this endpoint. If future code reads merge-related settings, the endpoint's additional documented permission requirements must be reviewed before that code is added.

### 9.2 Permission audit boundary

The endpoint inventory is based on the current code in:

- `fork_sync/github.py`
- `fork_sync/synchronizer.py`

Before implementation approval, review all modules in `fork_sync/`, `main.py`, and any indirect GitHub API calls to confirm that no additional endpoints or permissions are required.

No additional permissions, including administration or workflow permissions, may be requested without evidence from the code and endpoint documentation.

## 10. Broker operational security

The Broker is publicly reachable and temporarily processes authorization codes and GitHub tokens. It must be operated as a security-sensitive service, even though it has no persistent token database.

### 10.1 Transport security

- HTTPS is mandatory.
- TLS certificates must be valid and automatically renewed.
- TLS termination must occur at a trusted, securely configured ingress or reverse proxy.
- Traffic between the proxy and Broker must use a protected network or authenticated encrypted transport.
- Authentication secrets must never be sent over plaintext HTTP.

### 10.2 Logging and redaction

The following values must never be logged:

- GitHub authorization codes.
- GitHub access tokens.
- Polling secrets or their hashes.
- PKCE verifier.
- OAuth `state`.
- Token response bodies.

Reverse proxy access logs must redact callback query parameters, especially `code` and `state`.

Request-body logging must be disabled for authentication endpoints. Monitoring, tracing, exception reporting, and error aggregation must apply the same redaction policy.

### 10.3 Temporary data and crash handling

- Token responses exist only in temporary transaction storage.
- Core dumps and diagnostic memory dumps must be disabled or securely restricted.
- Debug logging must not expose transaction secrets.
- Expired and completed transaction material must be promptly deleted.
- Deployment must document the residual risk of process memory and swap.

### 10.4 Abuse protection

The Broker must implement:

- Rate limits for `/auth/start` and `/auth/poll`.
- Limits on active transactions.
- Request-size limits.
- Short transaction TTLs.
- Rejection of malformed requests.
- Protection against repeated callback processing.
- Protection against polling-secret brute force.

Rate limiting should consider source IP and transaction-level activity.

### 10.5 Monitoring

Operational monitoring may record request counts, safe status categories, transaction completion/failure counts, expiration counts, availability, and latency.

Monitoring must not include tokens, authorization codes, polling secrets, OAuth state, or unnecessary personal GitHub profile data.

### 10.6 Restart behavior

The MVP uses an in-memory transaction store. Broker restart destroys unfinished transactions and their undelivered token responses. The CLI must report this clearly and offer a new login.

No token recovery from persistent storage is permitted.

## 11. Local profiles and storage

Profile metadata and authentication credentials are separate data categories.

### 11.1 Credential storage

The Keyring stores:

- GitHub access token.

The MVP does not store a refresh token.

Suggested Keyring service name:

`dreamerol-sync`

Suggested credential key:

`github-user-<numeric-id>`

### 11.2 Non-secret local metadata

A local metadata file may be stored in the operating system's application-data directory. It may contain:

- Numeric GitHub user ID.
- GitHub username.
- Keyring credential reference.
- Token mode.
- Account creation/update timestamp.
- Last successful verification timestamp.
- Last-used timestamp.

The metadata file must not contain access tokens, refresh tokens, polling secrets, authorization codes, PKCE verifiers, or OAuth state.

Email addresses are not required and should not be collected for the MVP.

Use appropriate operating-system file permissions.

### 11.3 Multi-account behavior

Each GitHub profile is identified by its numeric GitHub user ID.

Supported operations:

- Add account.
- List accounts.
- Select an active account.
- Remove account.
- Reauthenticate an account.
- Validate a stored credential.

Username is display metadata and may change.

### 11.4 Existing account migration

The existing account manager uses username-keyed Keyring entries. Migration must be explicit and non-destructive:

1. Read an existing credential without exposing it.
2. Authenticate with GitHub and call `GET /user`.
3. Obtain and validate the numeric GitHub user ID and username.
4. Store the credential under the new numeric-ID-based Keyring key.
5. Read back the new entry and verify it.
6. Update non-secret local metadata.
7. Preserve the legacy entry until migration is confirmed and cleanup is separately approved.

A PAT must not be silently converted into a GitHub App user access token. Existing PAT authentication remains available during the migration period. Removing legacy entries requires a separate migration-completion decision.

## 12. CLI and synchronization integration

Authentication remains independent of synchronization logic.

Expected dependency direction:

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

The synchronization engine must not depend on whether a credential originated from the existing PAT path or the new GitHub App flow.

This authentication work must not change:

- Fork discovery or comparison behavior.
- Preview or dry-run behavior.
- Explicit `SYNC` confirmation.
- Diverged-history or local-commit protections.
- Repository filtering.
- Per-repository error handling.

PAT compatibility remains in place during the migration. Removing PAT support is a separate decision.

## 13. Error handling

| Situation | Required behavior |
|---|---|
| User denies GitHub authorization | Cancel login without storing credentials |
| Invalid or reused OAuth state | Reject callback |
| Expired transaction | Require a new login |
| Invalid polling secret | Reject without revealing transaction readiness |
| GitHub token exchange failure | Mark transaction `FAILED` |
| Unexpected expiring token response | Fail login; do not enable refresh |
| GitHub `/user` returns 401 or invalid identity | Reject credential |
| Keyring write failure | Do not ACK; retry in memory or require a new login |
| Polling network failure | Retry with bounded backoff until transaction expiry |
| ACK response is lost | Retry ACK; do not redeliver token after acknowledgment |
| Broker restart | Discard unfinished transaction and start a new login |
| Token revoked | Stop using it and offer reauthentication |
| HTTP 403 | Report permission or repository access issue |
| Missing repository permissions | Explain the missing permission; do not classify as invalid identity |

Error messages must not expose secrets, authorization codes, token responses, or raw request headers.

## 14. Testing strategy

### 14.1 Unit tests

- Polling-secret generation and hashing.
- Constant-time polling-secret validation.
- PKCE S256 generation and verifier retention on the Broker.
- OAuth state validation and single-use behavior.
- Transaction TTL and state transitions.
- `pending`, `completed`, and `already_acknowledged` poll responses.
- Repeated polling before ACK.
- Idempotent ACK and tombstone expiration.
- Token-response validation for the non-expiring MVP mode.
- Rejection of unexpected expiring responses.
- Keyring storage and retry behavior.
- Multi-account selection and removal.
- Non-secret metadata storage.
- Legacy account migration.
- Log and exception redaction.

### 14.2 Broker integration tests

- `/auth/start`.
- `/auth/callback`.
- `/auth/poll`.
- `/auth/ack`.
- Invalid, expired, and replayed callback state.
- Invalid polling secret.
- Expired transaction.
- Repeated polling before ACK.
- Repeated ACK.
- Token exchange failure.
- Broker restart.
- Keyring failure before ACK.
- Rate limiting and active-transaction limits.
- Callback query and request-secret log redaction.

### 14.3 Real GitHub integration tests

Use a separate test GitHub App and a test fork:

1. Complete a real browser authorization.
2. Receive the real GitHub callback.
3. Perform the real token exchange with PKCE.
4. Verify identity using `GET /user`.
5. Store and retrieve the credential using the real system Keyring.
6. Restart the CLI and confirm that the profile remains available.
7. Verify repository access and the required endpoint permissions.
8. Test `merge-upstream` only against an explicitly designated test fork.
9. Verify the configured non-expiring token behavior.

Real write tests must not run automatically in ordinary unit-test CI and must not target a production repository without explicit authorization.

## 15. Acceptance criteria

The specification may be approved for implementation when:

- [ ] GitHub App registration settings are finalized.
- [ ] Authorization Code Flow and exact token-exchange parameters are verified.
- [ ] PKCE S256 behavior is verified.
- [ ] The `client_secret` remains exclusively on the Broker.
- [ ] The registered HTTPS callback URL is finalized.
- [ ] Polling and ACK header contracts are finalized.
- [ ] Transaction TTL and tombstone behavior are defined.
- [ ] The non-expiring token configuration is verified with official documentation and a real GitHub App test.
- [ ] The MVP rejects unexpected expiring tokens and does not request `offline_access`.
- [ ] Every required GitHub API endpoint has an official, endpoint-specific permission reference.
- [ ] App permissions and user access to the target repository are treated as separate checks.
- [ ] Keyring and non-secret metadata storage are defined.
- [ ] Legacy PAT migration behavior is documented.
- [ ] Broker operational security has been reviewed.
- [ ] Logging, tracing, and proxy redaction have been tested.
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
- Changing the existing account model beyond the approved migration.

## 17. Official references

### GitHub App authentication and tokens

- [GitHub App authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app)
- [Generating a user access token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [Refreshing user access tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)

### OAuth and PKCE

- [PKCE support for OAuth and GitHub App authentication](https://github.blog/changelog/2025-07-14-pkce-support-for-oauth-and-github-app-authentication/)

### GitHub App permissions and REST API endpoints

- [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)
- [Get the authenticated user](https://docs.github.com/en/rest/users/users#get-the-authenticated-user)
- [List repositories for the authenticated user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user)
- [Get a repository](https://docs.github.com/en/rest/repos/repos#get-a-repository)
- [Compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
- [Sync a fork branch with the upstream repository](https://docs.github.com/en/rest/branches/branches#sync-a-fork-branch-with-the-upstream-repository)

### GitHub App security

- [GitHub App security best practices](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app)

## Final status

**ARCHITECTURE DIRECTION ACCEPTED — IMPLEMENTATION APPROVAL PENDING.**

This document defines the proposed authentication architecture and security requirements. It does not authorize repository changes, code implementation, or deployment.

Implementation requires explicit approval of this document and completion of the acceptance criteria.
