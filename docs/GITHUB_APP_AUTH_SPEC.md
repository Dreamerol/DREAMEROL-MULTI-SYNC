# DREAMEROL-SYNC — Authentication Implementation Brief

**Status:** Approved architecture — implementation approval pending  
**Purpose:** Implement the approved GitHub authentication architecture with minimal scope and no disruption to existing synchronization.

## 1. Scope and components

The implementation consists of two components:

- **CLI:** Initiates authentication, generates and retains the polling secret in memory, receives the credential, stores it in the OS Keyring, and sends ACK.
- **Auth Broker:** Coordinates GitHub authorization, validates the callback, exchanges the authorization code, and temporarily makes the credential available to the CLI.

GitHub remains the identity and authorization provider.

The Broker is a single HTTPS service for v1.

## 2. Authentication flow

1. CLI generates a cryptographically secure polling secret and computes its hash.
2. CLI sends `POST /auth/start`, including the hash but never the plaintext secret.
3. Broker creates a transaction and returns its transaction ID and browser authorization URL.
4. CLI retains the plaintext polling secret in memory for subsequent requests.
5. User completes GitHub authorization in the browser.
6. GitHub redirects to the Broker's fixed HTTPS callback.
7. Broker validates `state` and atomically moves the transaction from `PENDING` to `PROCESSING` before token exchange.
8. Broker exchanges the authorization code and validates the token response.
9. Broker makes the credential available and moves the transaction to `TOKEN_READY`.
10. CLI polls `POST /auth/poll`. The transaction ID is in the JSON request body; the polling secret is in a dedicated HTTPS authentication header.
11. On the first authorized poll in `TOKEN_READY`, Broker atomically snapshots the response payload for that request and moves the transaction to `DELIVERY_AUTHORIZED`. The response contains the credential. Repeated authorized polls before ACK return the same credential payload.
12. CLI writes the credential to the OS Keyring.
13. **Only after the Keyring write succeeds**, CLI sends `POST /auth/ack`, using the transaction ID in the JSON body and polling secret in the same HTTPS authentication header.
14. Broker atomically marks the transaction `ACKNOWLEDGED` and removes the temporary credential material.

If the Keyring write fails, CLI must not send ACK. It may retry the Keyring write or poll again while the transaction remains valid.

## 3. API endpoints

| Endpoint | Responsibility |
|---|---|
| `POST /auth/start` | Create a transaction using the CLI-supplied polling-secret hash |
| `GET /auth/callback` | Validate the callback and complete or safely fail authorization |
| `POST /auth/poll` | Authenticate the CLI and deliver the credential when available |
| `POST /auth/ack` | Authenticate the CLI and acknowledge successful local storage |

The request/response contracts in the approved specification are normative. They must be implemented as approved. Any contract change requires review and explicit approval; do not silently reinterpret or extend the contracts.

For `/auth/poll` and `/auth/ack`, the transaction ID is sent in the JSON body and the polling secret only in the dedicated HTTPS authentication header. Neither secret nor credential may appear in a URL.

## 4. Polling secret and transaction security

- CLI generates the polling secret using a cryptographically secure random generator with at least 256 bits of entropy.
- CLI retains the plaintext secret in memory only.
- `/auth/start` receives only the secret's cryptographic hash.
- Broker stores the hash, not the plaintext secret.
- `/auth/poll` and `/auth/ack` require the plaintext secret in a dedicated HTTPS header.
- Transaction ID alone must never authorize token retrieval or ACK.
- Compare secret hashes safely; do not expose secrets in logs, URLs, or error messages.
- Apply transaction expiration and cleanup.
- Do not persist the polling secret or credential permanently.

## 5. OAuth and callback requirements

- PKCE with **S256 is mandatory**.
- If the selected GitHub authorization flow cannot satisfy the PKCE S256 requirement, authentication must fail. Do not fall back to a flow without PKCE.
- OAuth `state` validation is mandatory.
- Callback URL must be a fixed HTTPS redirect URI, with wildcard callback matching disabled.
- Authorization URLs are generated only by the Broker for the exact `github.com` host. Do not accept caller-supplied callback URLs or implement open redirects.
- A missing or invalid `state` must not modify or advance any transaction. Reject the callback and return a generic safe browser error.
- After successful `state` validation, the matching transaction must atomically transition from `PENDING` to `PROCESSING` **before** token exchange begins.
- For a valid `state` with `error=access_denied`, mark the matching transaction `CANCELLED`.
- For a valid `state` with another OAuth error or a missing authorization code, mark only the matching transaction `FAILED`.
- Duplicate callbacks and concurrent callback requests must not cause multiple token exchanges or conflicting state transitions.

## 6. Token exchange and validation

- GitHub `client_secret` is stored and used only by the Broker.
- It must never be sent to the CLI or exposed in logs.
- Broker sends an HTTPS POST to the documented GitHub token endpoint using the verified request encoding and required parameters for the selected flow, including `client_id`, `client_secret`, `code`, `redirect_uri`, and `code_verifier` as required by the verified contract.
- Broker explicitly requests JSON using `Accept: application/json`.
- Broker validates the token response before making a credential available:
  - Successful HTTP status.
  - Expected response `Content-Type`.
  - Valid JSON response.
  - Required fields and expected field types according to the selected GitHub token response schema.
  - Token type and expiration behavior consistent with the approved MVP policy.
- Invalid, incomplete, unexpected, or malformed responses must fail the transaction.
- Never log the token response or credential.

## 7. Token expiration policy — MVP

The approved MVP policy remains:

- The GitHub App is configured with user-to-server token expiration set to **Opt-out**.
- The authorization request does not request `offline_access`.
- The token response must contain a non-empty `access_token` and `token_type` of `bearer`.
- `expires_in`, `refresh_token`, and `refresh_token_expires_in` must be absent.
- The App's Opt-out configuration must be verified; absence of `expires_in` alone is not proof of the intended mode.
- An unexpectedly expiring or otherwise nonconforming token is rejected.
- No refresh-token fallback or refresh workflow is implemented.
- The CLI reports an actionable authentication failure rather than silently changing token behavior.

Changing this policy is a new product/architecture decision and requires explicit review. It must not happen implicitly during implementation.

## 8. Transaction state machine

Use the following states:

`PENDING → PROCESSING → TOKEN_READY → DELIVERY_AUTHORIZED → ACKNOWLEDGED`

Terminal failure states are `FAILED`, `CANCELLED`, and `EXPIRED`.

- **PENDING:** Waiting for browser authorization.
- **PROCESSING:** A callback with valid `state` has atomically claimed the transaction; token exchange is in progress. Only one callback handler may acquire this transition.
- **TOKEN_READY:** Token exchange and token-response validation succeeded. The credential is available for an authorized poll, but no poll has yet been authorized to receive it.
- **DELIVERY_AUTHORIZED:** An authenticated poll with the correct transaction ID and polling secret has atomically been authorized to receive the token payload. This state does not prove that the client received or persisted the response.
- **ACKNOWLEDGED:** The CLI reports successful Keyring storage. This is a client assertion; the Broker cannot independently inspect or verify the local Keyring.
- **FAILED:** A valid transaction encountered a non-recoverable OAuth or token-exchange error.
- **CANCELLED:** The user denied authorization or cancelled through a valid callback.
- **EXPIRED:** The transaction TTL elapsed before completion.

Invalid transitions must be rejected. A callback with missing or invalid `state` must not change any transaction.

## 9. Polling and ACK concurrency

Polling and ACK must use atomic state transitions and safe retry handling.

- Poll must never return a credential for a transaction that is not `TOKEN_READY` or `DELIVERY_AUTHORIZED`.
- The first authorized poll atomically transitions `TOKEN_READY` to `DELIVERY_AUTHORIZED` and snapshots the response payload for that request.
- Repeated authorized polls in `DELIVERY_AUTHORIZED` return the same credential payload until ACK or transaction expiration.
- If ACK has already atomically completed, subsequent polls must never return credential material.
- ACK is accepted only for a `DELIVERY_AUTHORIZED` transaction and must atomically transition it to `ACKNOWLEDGED` while deleting the temporary credential.
- ACK received before an authorized delivery poll is rejected and does not change the transaction state.
- Concurrent polls must not corrupt state. Concurrent ACK requests and retries must be idempotent and must not restore or expose credential material.
- Poll and ACK operations must be serialized or otherwise coordinated so no poll that begins after ACK commits can receive the credential. An already authorized response may be in flight when ACK is received; ACK is sent by the CLI only after it has received and stored the credential.
- Retain only the minimum non-secret transaction/tombstone state needed to reject later requests until its configured expiry.

## 10. GitHub repository access and permissions

Do not assume every repository requires a GitHub App installation.

Use the approved user-to-server access-token model. Do not conflate user-to-server tokens with installation tokens or introduce mandatory installation steps unless the product explicitly adopts that model.

The approved GitHub permission matrix for the five identified API operations remains normative:

| Operation | REST endpoint | Minimum GitHub App repository permission |
|---|---|---|
| Identify authenticated user | `GET /user` | No additional permissions |
| Discover accessible repositories | `GET /user/repos` | `Metadata: read` |
| Retrieve repository metadata and fork parent information | `GET /repos/{owner}/{repo}` | `Metadata: read` |
| Compare upstream and fork branches | `GET /repos/{owner}/{repo}/compare/{basehead}` | `Contents: read` |
| Synchronize fork with upstream | `POST /repos/{owner}/{repo}/merge-upstream` | `Contents: write` |

The configured App permission is `Metadata: Read-only` and `Contents: Read and write`. This does not mean every operation requires write access. App permissions and the user's actual access to a repository are distinct. Preserve these permission and scope decisions. Do not broaden them or leave the matrix open to interpretation during implementation.

Any proposed permission change must be justified against the actual API operation and reviewed before implementation. Do not introduce installation access tokens or mandatory installation steps without an approved product decision.

## 11. Existing synchronization code

The existing code has been inspected:

- `fork_sync/github.py` contains the GitHub API client and uses the five identified GitHub endpoints.
- `main.py` delegates to `GitHubClient` and `ForkSynchronizer`.

Authentication changes must preserve existing synchronization behavior. Do not rewrite working synchronization logic as part of this task. Keep authentication responsibilities separate from repository synchronization. Any change to existing GitHub API calls must be justified by a concrete requirement and checked against the approved permission matrix.

## 12. Broker implementation constraints — v1

- One HTTPS Broker instance.
- In-memory transaction storage.
- No database.
- No Redis.
- No multi-instance coordination.
- No permanent credential storage.

These are deliberate v1 constraints. In-memory transaction storage does not support horizontal scaling across independent Broker instances. Multi-instance deployment requires a separately reviewed shared-state design.

## 13. Rate limiting and abuse protection

Rate limits are configurable deployment settings, not universal constants.

Apply controls at multiple levels:

- Per IP.
- Per transaction.
- Per endpoint.
- Repeated authentication failures and suspicious activity.

Account for shared NAT addresses. Multiple legitimate users may share one public IP, so IP-based limits must not be the only security control. Document deployment defaults and make them configurable. Avoid treating a shared IP as proof that requests belong to one user.

## 14. CLI requirements

CLI must:

- Generate and retain the polling secret in memory.
- Start authentication and display or open the Broker-generated browser authorization URL.
- Poll using the transaction ID in the request body and polling secret in the dedicated HTTPS header.
- Handle pending, processing, token-ready, delivery-authorized, expired, failed, and cancelled outcomes.
- Write the credential to the OS Keyring.
- Send ACK only after successful Keyring storage.
- Never print or log the credential or polling secret.
- Report Keyring and authentication failures clearly.

If Keyring storage fails, do not send ACK. Allow a safe retry while the transaction remains valid.

## 15. Out of scope for v1

- Database or Redis integration.
- Multiple Broker instances.
- Refresh-token workflow.
- Mandatory GitHub App installation for every repository.
- Permanent Broker-side credential storage.
- Rewriting existing repository synchronization.
- Unnecessary authentication abstractions.
- Any fallback that bypasses PKCE S256.

## 16. Acceptance criteria

Implementation is ready for review when all of the following are true:

1. CLI generates the polling secret and sends only its hash to `/auth/start`.
2. Transaction ID alone cannot retrieve a credential or authorize ACK.
3. PKCE S256 is enforced with no fallback.
4. Callback uses a fixed HTTPS redirect URI with wildcard matching disabled.
5. Missing or invalid `state` cannot modify an arbitrary transaction.
6. Valid callback atomically transitions the transaction to `PROCESSING` before token exchange.
7. OAuth denial and other callback errors terminate the associated transaction safely and do not leave it pending indefinitely.
8. Broker validates token endpoint HTTP status, `Content-Type`, JSON syntax, schema, and token fields before making the credential available.
9. The approved Opt-out expiration policy is enforced; unexpected expiring responses are rejected and no refresh fallback occurs.
10. CLI can retrieve the credential using the polling secret.
11. Credential is successfully stored in the OS Keyring before ACK.
12. Broker rejects ACK before `DELIVERY_AUTHORIZED`; ACK is a client assertion, not independent Keyring verification.
13. Successful ACK atomically removes the credential and prevents any poll begun after ACK from receiving it.
14. Duplicate and concurrent poll, callback, and ACK requests are handled safely.
15. Credentials and secrets never appear in logs or URLs.
16. The approved GitHub permission matrix is preserved.
17. Existing repository synchronization continues to work without changes to its safety behavior.
18. Rate limits are configurable and account for shared NAT environments.

**Implementation priority:** Implement the approved flow as written, test the security-critical transitions and failure cases, and preserve working synchronization. Do not expand scope or change approved architecture decisions without review.
