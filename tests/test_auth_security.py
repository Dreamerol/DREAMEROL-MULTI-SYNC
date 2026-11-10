"""Tests for authentication secret helpers."""

import base64
import hashlib

from auth_broker.security import (
    generate_callback_state,
    generate_pkce_verifier,
    generate_polling_secret,
    hash_secret,
    pkce_s256_challenge,
    verify_secret,
)


def test_polling_secret_has_256_bits_of_entropy():
    secret = generate_polling_secret()
    decoded = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))

    assert len(decoded) == 32
    assert len(secret) >= 43


def test_polling_secret_generation_is_unique():
    assert generate_polling_secret() != generate_polling_secret()


def test_secret_hash_and_constant_time_verification_contract():
    secret = generate_polling_secret()
    digest = hash_secret(secret)

    assert len(digest) == 64
    assert verify_secret(secret, digest)
    assert not verify_secret("different-secret", digest)
    assert not verify_secret(secret, "invalid-digest")
    assert not verify_secret("", digest)


def test_pkce_verifier_and_s256_challenge():
    verifier = generate_pkce_verifier()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    assert 43 <= len(verifier) <= 128
    assert pkce_s256_challenge(verifier) == expected
    assert "=" not in expected


def test_callback_state_is_unpredictable_and_distinct():
    first = generate_callback_state()
    second = generate_callback_state()

    assert len(first) >= 43
    assert first != second
