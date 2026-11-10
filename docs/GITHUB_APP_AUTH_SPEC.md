# DREAMEROL-SYNC — Authentication Implementation Brief

**Status:** Architecture direction accepted — implementation approval pending  
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
7. Broker validates `state` and atomically moves the transaction from `PENDING` to `PROCESSING`.
8. Broker exchanges the authorization code and validates the token response.
9. Broker makes the credential available and moves the transaction to `READY`.
10. CLI polls `POST /auth/poll`, authenticating with the transaction ID and polling secret in an HTTPS header.
11. CLI receives the credential and writes it to the OS Keyring.
12. **Only after the Keyring write succeeds**, CLI sends `POST /auth/ack`, using the same transaction ID and polling secret.
13. Broker atomically marks the transaction `ACKNOWLEDGED` and removes the temporary credential material.

If the Keyring write fails, CLI must not send ACK.

## 3. API endpoints

| Endpoint | Responsibility |
|---|---|
| `POST /auth/start` | Create a transaction using the CLI-supplied polling-secret hash |
| `GET /auth/callback` | Validate the callback and complete authorization |
| `POST /auth/poll` | Authenticate the CLI and deliver the credential when READY |
| `POST /auth/ack` | Authenticate the CLI and acknowledge successful local storage |

The request/response contracts in the **approved specification are normative**. They must be implemented as approved. Any contract change requires review and explicit approval; do not silently reinterpret or extend the contracts.

## 4. Polling secret and transaction security

- CLI generates the polling secret using a cryptographically secure random generator.
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
- Callback URL must be a fixed HTTPS redirect URI.
- Wildcard callback matching must be disabled.
- A missing or invalid `state` must not modify or advance an arbitrary transaction.
- After successful `state` validation, the matching transaction must atomically transition from `PENDING` to `PROCESSING` **before** token exchange begins.
- Duplicate callbacks and concurrent callback requests must not cause multiple token exchanges or conflicting state transitions.

## 6. Token exchange and validation

- GitHub `client_secret` is stored and used only by the Broker.
- It must never be sent to the CLI or exposed in logs.
- Broker must validate the token response before making a credential available:
  - Successful HTTP status.
  - Expected `Content-Type`.
  - Valid JSON response.
  - Required fields and expected field types according to the selected GitHub token response schema.
  - Token type and expiration behavior consistent with the approved MVP policy.
- Invalid, incomplete, unexpected, or malformed responses must fail the transaction.
- Never log the token response or credential.

## 7. Token expiration policy — MVP

The approved MVP policy remains:

- The GitHub App is configured with expiration set to **Opt-out**.
- The authorization request does not request `offline_access`.
- An unexpectedly expiring token is rejected.
- No refresh-token fallback or refresh workflow is implemented.
- The CLI reports an actionable authentication failure rather than silently changing token behavior.

Changing this policy is a new product/architecture decision and requires explicit review. It must not happen implicitly during implementation.

## 8. Transaction state machine

Use the following states:

`PENDING → PROCESSING → READY → ACKNOWLEDGED`

- **PENDING:** Waiting for browser authorization.
- **PROCESSING:** Valid callback accepted; token exchange is in progress.
- **READY:** Token exchange succeeded and credential delivery is available.
- **ACKNOWLEDGED:** CLI reports successful Keyring storage.

Invalid transitions must be rejected.

**ACK semantics:** ACK is a client assertion. Broker cannot independently inspect or verify the CLI's local OS Keyring. It can verify the transaction state and polling-secret authorization, and accept ACK only after the transaction reaches READY.

## 9. Polling and ACK concurrency

Polling and ACK must use atomic state transitions and safe handling of retries.

- Poll must never return a credential for a transaction that is not READY.
- Concurrent poll requests must not cause inconsistent transaction state.
- ACK is accepted only for a READY transaction.
- ACK must atomically transition the transaction to ACKNOWLEDGED and remove the temporary credential.
- Once ACK succeeds, Broker must **never return that credential again**, including on subsequent or concurrent poll requests.
- Repeated ACK requests must be handled safely and must not restore or expose credential material.
- Retain sufficient transaction state to reject later requests until transaction expiration.

## 10. GitHub repository access and permissions

Do not assume every repository requires a GitHub App installation.

Use the approved user-to-server access-token model. Do not conflate user-to-server tokens with installation tokens or introduce mandatory installation steps unless the product explicitly adopts that model.

The **approved GitHub permission matrix for the five identified API operations remains normative**. Preserve its exact permissions and scope decisions from the approved specification. Do not broaden, replace, or leave the matrix open for interpretation during implementation.

Any proposed permission change must be justified against the actual API operation and reviewed before implementation.

## 11. Existing synchronization code

The existing code has been inspected:

- `fork_sync/github.py` contains the GitHub API client and uses the five identified GitHub endpoints.
- `main.py` delegates to `GitHubClient` and `ForkSynchronizer`.

Authentication changes must preserve existing synchronization behavior.

Do not rewrite working synchronization logic as part of this task. Keep authentication responsibilities separate from repository synchronization. Any change to existing GitHub API calls must be justified by a concrete requirement and checked against the approved permission matrix.

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

Account for shared NAT addresses. Multiple legitimate users may share one public IP, so IP-based limits must not be the only security control.

Document deployment defaults and make them configurable. Avoid treating a shared IP as proof that requests belong to one user.

## 14. CLI requirements

CLI must:

- Generate and retain the polling secret in memory.
- Start authentication and display or open the browser authorization URL.
- Poll using the transaction ID and polling secret.
- Handle pending, processing, ready, expired, and failed states.
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

Implementation is ready for review when:

1. CLI generates the polling secret and sends only its hash to `/auth/start`.
2. Transaction ID alone cannot retrieve a credential or authorize ACK.
3. PKCE S256 is enforced with no fallback.
4. Callback uses the fixed HTTPS redirect URI with wildcard matching disabled.
5. Missing or invalid `state` cannot modify an arbitrary transaction.
6. Valid callback atomically transitions the transaction to PROCESSING before token exchange.
7. Broker validates the token response before making the credential available.
8. The approved Opt-out expiration policy is enforced.
9. CLI can retrieve the credential using the polling secret.
10. Credential is successfully stored in the OS Keyring before ACK.
11. Broker rejects ACK before READY.
12. Successful ACK atomically removes the credential and prevents any subsequent token delivery.
13. Duplicate and concurrent poll, callback, and ACK requests are handled safely.
14. Credentials and secrets never appear in logs or URLs.
15. The approved GitHub permission matrix is preserved.
16. Existing repository synchronization continues to work.
17. Rate limits are configurable and account for shared NAT environments.

**Implementation priority:** Implement the approved flow as written, test the security-critical transitions and failure cases, and preserve working synchronization. Do not expand scope or change approved architecture decisions without review.
