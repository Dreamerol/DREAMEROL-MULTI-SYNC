"""Secret generation and comparison helpers for the authentication Broker."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import base64


POLLING_SECRET_BYTES = 32


def generate_polling_secret() -> str:
    """Return a URL-safe secret containing 256 bits of CSPRNG entropy."""
    random_bytes = secrets.token_bytes(POLLING_SECRET_BYTES)
    return base64.urlsafe_b64encode(random_bytes).rstrip(b"=").decode("ascii")


def generate_callback_state() -> str:
    """Return an unpredictable one-time callback state value."""
    return secrets.token_urlsafe(32)


def generate_pkce_verifier() -> str:
    """Return a PKCE verifier with sufficient entropy and valid URL-safe chars."""
    # 32 random bytes encode to 43 unpadded base64url characters, within PKCE's
    # allowed verifier length and character set.
    return secrets.token_urlsafe(32)


def pkce_s256_challenge(verifier: str) -> str:
    """Compute the base64url-encoded SHA-256 PKCE S256 challenge."""
    if not isinstance(verifier, str) or not verifier:
        raise ValueError("verifier must be a non-empty string")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_secret(secret: str) -> str:
    """Return a lowercase SHA-256 hex digest for a non-empty secret string."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, expected_hash: str) -> bool:
    """Compare a secret to a SHA-256 hex digest in constant time."""
    if not isinstance(secret, str) or not secret:
        return False
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        return False
    try:
        expected = bytes.fromhex(expected_hash)
    except ValueError:
        return False
    if len(expected) != hashlib.sha256().digest_size:
        return False
    actual = hashlib.sha256(secret.encode("utf-8")).digest()
    return hmac.compare_digest(actual, expected)
