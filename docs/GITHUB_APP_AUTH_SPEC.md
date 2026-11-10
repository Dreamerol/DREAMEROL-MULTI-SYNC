# DREAMEROL-SYNC — Authentication Implementation Brief

**Status:** Architecture direction accepted — implementation approval pending  
**Goal:** Implement a secure, minimal GitHub authentication flow without disrupting existing repository synchronization.

## 1. What we are building

A small HTTPS Auth Broker that lets the DREAMEROL-SYNC CLI authenticate with GitHub and securely receive the resulting credential.

**Two components:**
- **CLI:** Starts authentication, polls the Broker, writes the credential to the OS Keyring, then sends an ACK.
- **Auth Broker:** Coordinates the browser-based GitHub authorization flow and temporarily holds the resulting credential until the CLI retrieves it.

GitHub remains the identity and authorization provider. The Broker is not a replacement for GitHub authentication.

## 2. Authentication flow

1. CLI requests `/auth/start`.
2. Broker creates an authentication transaction and returns the browser authorization URL, transaction ID, and polling secret.
3. User completes GitHub authorization in the browser.
4. GitHub redirects to `/auth/callback`.
5. Broker validates the callback, exchanges the authorization code, and makes the resulting credential available to the CLI.
6. CLI polls `/auth/poll` using the transaction ID and polling secret.
7. CLI receives the credential and writes it to the OS Keyring.
8. **Only after the Keyring write succeeds**, CLI sends `/auth/ack`.
9. Broker marks the transaction acknowledged and removes its temporary credential material.

The CLI must never send ACK before a successful Keyring write.

## 3. API endpoints

| Endpoint | Responsibility |
|---|---|
| `POST /auth/start` | Create transaction and return authorization details |
| `GET /auth/callback` | Handle GitHub authorization callback |
| `POST /auth/poll` | Allow the CLI to retrieve the credential |
| `POST /auth/ack` | Acknowledge successful local storage |

Use the existing request/response contracts where already implemented. Do not add endpoints without a concrete requirement.

## 4. Transaction states

Keep the state machine simple:

`PENDING → READY → ACKNOWLEDGED`

- **PENDING:** Browser authorization is in progress.
- **READY:** Authorization succeeded and the credential is available for CLI delivery.
- **ACKNOWLEDGED:** CLI reports that it successfully stored the credential.

The Broker must reject ACK for transactions that have not reached READY.

**Important:** ACK is a client assertion. The Broker cannot inspect or independently verify the CLI's local OS Keyring. It can verify transaction state and accept ACK only after credential delivery has been made available.

Polling and ACK handling must be safe against retries and duplicate requests.

## 5. Security requirements

- Use HTTPS for all Broker communication.
- Use OAuth `state` validation to prevent callback CSRF.
- Use PKCE with S256 where supported by the selected GitHub authorization flow.
- Generate cryptographically secure transaction IDs and polling secrets.
- Keep polling secrets separate from transaction IDs.
- Never expose credentials in URLs, logs, error messages, or telemetry.
- Do not store credentials permanently in the Broker.
- Remove temporary credential material after ACK or transaction expiration.
- Apply transaction expiration and cleanup.
- Do not weaken validation to make retries easier.

## 6. GitHub access model

Do not assume that every repository requires a GitHub App installation.

The implementation must use the selected **user-to-server access-token model** and its actual GitHub permission semantics. Do not silently mix it with GitHub App installation-token behavior.

Before changing scopes or permissions, verify them against:
- The actual authorization flow being used.
- The GitHub API operations DREAMEROL-SYNC performs.
- The permissions required for the repositories the user intends to synchronize.

Do not request broader access than necessary. Do not introduce installation tokens or mandatory installation steps unless the product explicitly adopts that access model.

## 7. Existing synchronization code

Authentication changes must preserve the existing synchronization behavior.

The current code has been inspected:
- `fork_sync/github.py` contains the GitHub API client and uses the five identified GitHub endpoints.
- `main.py` delegates to `GitHubClient` and `ForkSynchronizer`.

Keep authentication responsibilities separate from repository synchronization. Do not rewrite working synchronization logic as part of this task.

Any change to the existing GitHub API calls must be justified by an actual implementation requirement.

## 8. Broker implementation constraints

For the initial version:
- One HTTPS Broker instance.
- In-memory transaction storage.
- No database.
- No Redis.
- No multi-instance coordination.
- No permanent token storage.

This is an intentional first-version constraint, not a claim that in-memory storage supports horizontal scaling. Multiple Broker instances would require shared transaction state and a separate design decision.

## 9. Rate limiting and abuse protection

Rate limits are **configurable deployment settings**, not universal constants.

Apply sensible controls at multiple levels:
- Per IP.
- Per transaction.
- Per endpoint.
- Abuse detection for repeated failed or suspicious requests.

Account for shared NAT addresses: multiple legitimate users may appear behind one public IP. Avoid treating IP-based limits as the only security control.

Document defaults in configuration and make them adjustable by deployment operators.

## 10. Token lifecycle

The initial version does not implement a refresh-token workflow.

Token expiration, revocation, and reauthorization behavior must reflect the actual GitHub token type issued by the selected flow. Do not promise that a token never expires unless that behavior is confirmed for the chosen token type.

When a credential becomes invalid, the CLI must report an actionable authentication error and allow the user to authenticate again.

## 11. CLI behavior

The CLI must:
- Start authentication and open or display the browser authorization URL.
- Poll without exposing secrets.
- Handle pending, successful, expired, and failed transactions.
- Write the credential to the OS Keyring.
- Send ACK only after the Keyring write succeeds.
- Report Keyring and authentication failures clearly.
- Never print the credential itself.

If the Keyring write fails, do not send ACK. Preserve enough transaction state to allow a safe retry until the transaction expires.

## 12. Acceptance criteria

Implementation is ready for review when all of the following are true:

1. A user can complete GitHub authorization from the CLI.
2. Callback `state` validation works.
3. The CLI can retrieve the authorized credential securely.
4. The credential is written to the OS Keyring.
5. ACK is sent only after a successful Keyring write.
6. The Broker rejects ACK before READY.
7. Repeated polling and ACK requests behave safely.
8. Expired and failed transactions are handled correctly.
9. Credentials do not appear in logs or URLs.
10. Existing repository synchronization still works.
11. GitHub permissions match the actual API operations and selected access model.
12. Rate limits are configurable and account for shared IP environments.

## 13. Out of scope for v1

- Database or Redis integration.
- Multiple Broker instances.
- Refresh-token workflow.
- Mandatory GitHub App installation for every repository.
- Rewriting repository synchronization.
- Unnecessary new authentication
