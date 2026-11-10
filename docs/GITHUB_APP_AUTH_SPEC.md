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
