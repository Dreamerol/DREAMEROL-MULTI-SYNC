"""Thread-safe, in-memory authentication transaction state machine.

This module deliberately has no persistence or OAuth/network dependencies. A
Broker process can use it as its single-process transaction store; running
multiple Broker workers requires a separately designed shared-state backend.
"""

from __future__ import annotations

import hmac
import math
import re
import secrets
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .security import hash_secret


_HASH_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


class TransactionState(str, Enum):
    """States permitted by the approved authentication flow."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    TOKEN_READY = "TOKEN_READY"
    DELIVERY_AUTHORIZED = "DELIVERY_AUTHORIZED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TransactionError(Exception):
    """Base exception for transaction operations."""


class InvalidTransaction(TransactionError):
    """The transaction is unknown or the supplied polling secret is invalid."""


class InvalidCallbackState(TransactionError):
    """The callback state does not identify a valid transaction."""


class InvalidTransition(TransactionError):
    """The requested operation is not valid for the transaction's state."""


class TransactionExpired(TransactionError):
    """The transaction has expired."""


@dataclass(frozen=True)
class PollResult:
    """Safe poll result; credential is present only when delivery is allowed."""

    state: TransactionState
    credential: str | None = None


@dataclass
class _Transaction:
    transaction_id: str
    polling_secret_hash: str
    callback_state_hash: str
    created_at: float
    expires_at: float
    state: TransactionState = TransactionState.PENDING
    credential: str | None = None


class TransactionStore:
    """Atomic in-memory transaction store for one Broker process."""

    def __init__(
        self,
        ttl_seconds: float = 600,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be a positive finite number")
        try:
            ttl_seconds = float(ttl_seconds)
        except (OverflowError, TypeError, ValueError):
            raise ValueError("ttl_seconds must be a positive finite number") from None
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive finite number")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._transactions: dict[str, _Transaction] = {}
        self._callback_states: dict[str, str] = {}
        # Hash -> original transaction expiry. Never retain callback plaintext.
        self._used_callback_states: dict[str, float] = {}

    def create(self, polling_secret_hash: str, callback_state: str) -> str:
        """Create a PENDING transaction, storing only hashes of supplied secrets."""
        if not isinstance(polling_secret_hash, str) or not _HASH_PATTERN.fullmatch(
            polling_secret_hash
        ):
            raise ValueError("polling_secret_hash must be a lowercase SHA-256 hex digest")
        if not isinstance(callback_state, str) or not callback_state:
            raise ValueError("callback_state must be a non-empty string")

        callback_state_hash = hash_secret(callback_state)
        with self._lock:
            now = self._clock()
            self._cleanup_expired_locked(now)
            if (
                callback_state_hash in self._callback_states
                or callback_state_hash in self._used_callback_states
            ):
                raise ValueError("callback state has already been used")
            transaction_id = secrets.token_urlsafe(32)
            while transaction_id in self._transactions:
                transaction_id = secrets.token_urlsafe(32)
            transaction = _Transaction(
                transaction_id=transaction_id,
                polling_secret_hash=polling_secret_hash,
                callback_state_hash=callback_state_hash,
                created_at=now,
                expires_at=now + self._ttl_seconds,
            )
            self._transactions[transaction_id] = transaction
            self._callback_states[callback_state_hash] = transaction_id
            return transaction_id

    def claim_callback(self, callback_state: str) -> str:
        """Atomically claim a valid callback once, transitioning PENDING to PROCESSING."""
        if not isinstance(callback_state, str) or not callback_state:
            raise InvalidCallbackState("invalid callback state")
        supplied_hash = hash_secret(callback_state)
        with self._lock:
            transaction_id = self._callback_states.get(supplied_hash)
            if transaction_id is None:
                raise InvalidCallbackState("invalid callback state")
            transaction = self._transactions.get(transaction_id)
            if transaction is None or not hmac.compare_digest(
                supplied_hash, transaction.callback_state_hash
            ):
                raise InvalidCallbackState("invalid callback state")
            self._expire_if_needed(transaction)
            if transaction.state is TransactionState.EXPIRED:
                self._callback_states.pop(supplied_hash, None)
                raise TransactionExpired("transaction has expired")
            if transaction.state is not TransactionState.PENDING:
                raise InvalidTransition("callback has already been claimed or completed")
            transaction.state = TransactionState.PROCESSING
            # Retain this digest until the original transaction expiry so the
            # same callback state cannot be re-used for a new transaction.
            self._used_callback_states[supplied_hash] = transaction.expires_at
            self._callback_states.pop(supplied_hash, None)
            return transaction_id

    def fail_callback(self, callback_state: str, *, cancelled: bool = False) -> str:
        """Fail/cancel a callback only after authenticating its transaction state."""
        if not isinstance(callback_state, str) or not callback_state:
            raise InvalidCallbackState("invalid callback state")
        supplied_hash = hash_secret(callback_state)
        with self._lock:
            transaction_id = self._callback_states.get(supplied_hash)
            if transaction_id is None:
                raise InvalidCallbackState("invalid callback state")
            transaction = self._transactions.get(transaction_id)
            if transaction is None or not hmac.compare_digest(
                supplied_hash, transaction.callback_state_hash
            ):
                raise InvalidCallbackState("invalid callback state")
            self._expire_if_needed(transaction)
            if transaction.state is TransactionState.EXPIRED:
                self._callback_states.pop(supplied_hash, None)
                raise TransactionExpired("transaction has expired")
            if transaction.state is not TransactionState.PENDING:
                raise InvalidTransition("callback is not pending")
            transaction.state = (
                TransactionState.CANCELLED if cancelled else TransactionState.FAILED
            )
            self._used_callback_states[supplied_hash] = transaction.expires_at
            self._callback_states.pop(supplied_hash, None)
            return transaction_id

    def fail_processing(self, transaction_id: str) -> TransactionState:
        """Atomically fail a claimed callback after exchange/validation failure."""
        with self._lock:
            transaction = self._get_transaction(transaction_id)
            self._expire_if_needed(transaction)
            if transaction.state is TransactionState.EXPIRED:
                raise TransactionExpired("transaction has expired")
            if transaction.state is not TransactionState.PROCESSING:
                raise InvalidTransition("only PROCESSING transactions can fail")
            transaction.credential = None
            transaction.state = TransactionState.FAILED
            self._callback_states.pop(transaction.callback_state_hash, None)
            return transaction.state

    def make_token_ready(self, transaction_id: str, credential: str) -> None:
        """Store a validated credential after callback processing succeeds."""
        if not isinstance(credential, str) or not credential:
            raise ValueError("credential must be a non-empty string")
        with self._lock:
            transaction = self._get_transaction(transaction_id)
            self._expire_if_needed(transaction)
            if transaction.state is TransactionState.EXPIRED:
                raise TransactionExpired("transaction has expired")
            if transaction.state is not TransactionState.PROCESSING:
                raise InvalidTransition("only PROCESSING transactions can become TOKEN_READY")
            transaction.credential = credential
            transaction.state = TransactionState.TOKEN_READY

    def poll(self, transaction_id: str, polling_secret: str) -> PollResult:
        """Authenticate a poll and atomically authorize/repeat token delivery."""
        with self._lock:
            transaction = self._get_authenticated(transaction_id, polling_secret)
            self._expire_if_needed(transaction)
            if transaction.state is TransactionState.EXPIRED:
                return PollResult(TransactionState.EXPIRED)
            if transaction.state is TransactionState.TOKEN_READY:
                if transaction.credential is None:
                    raise InvalidTransition("TOKEN_READY transaction has no credential")
                transaction.state = TransactionState.DELIVERY_AUTHORIZED
                return PollResult(transaction.state, transaction.credential)
            if transaction.state is TransactionState.DELIVERY_AUTHORIZED:
                if transaction.credential is None:
                    raise InvalidTransition("DELIVERY_AUTHORIZED transaction has no credential")
                return PollResult(transaction.state, transaction.credential)
            return PollResult(transaction.state)

    def acknowledge(self, transaction_id: str, polling_secret: str) -> TransactionState:
        """Acknowledge delivery; only DELIVERY_AUTHORIZED transactions can ACK."""
        with self._lock:
            transaction = self._get_authenticated(transaction_id, polling_secret)
            self._expire_if_needed(transaction)
            if transaction.state is TransactionState.EXPIRED:
                raise TransactionExpired("transaction has expired")
            if transaction.state is TransactionState.ACKNOWLEDGED:
                return TransactionState.ACKNOWLEDGED
            if transaction.state is not TransactionState.DELIVERY_AUTHORIZED:
                raise InvalidTransition("ACK is allowed only after delivery is authorized")
            transaction.credential = None
            transaction.state = TransactionState.ACKNOWLEDGED
            return transaction.state

    def cleanup_expired(self) -> int:
        """Remove expired transactions and callback indexes; return removed count."""
        with self._lock:
            return self._cleanup_expired_locked(self._clock())

    def _cleanup_expired_locked(self, now: float) -> int:
        """Purge expired transactions and callback tombstones; caller holds lock."""
        expired_ids = [
            transaction_id
            for transaction_id, transaction in self._transactions.items()
            if now >= transaction.expires_at
        ]
        for transaction_id in expired_ids:
            transaction = self._transactions.pop(transaction_id)
            transaction.credential = None
            self._callback_states.pop(transaction.callback_state_hash, None)

        expired_state_hashes = [
            state_hash
            for state_hash, expires_at in self._used_callback_states.items()
            if now >= expires_at
        ]
        for state_hash in expired_state_hashes:
            self._used_callback_states.pop(state_hash, None)

        return len(expired_ids)

    def _get_authenticated(self, transaction_id: str, polling_secret: str) -> _Transaction:
        transaction = self._transactions.get(transaction_id)
        if transaction is None:
            raise InvalidTransaction("invalid transaction or polling secret")
        if not isinstance(polling_secret, str) or not polling_secret:
            raise InvalidTransaction("invalid transaction or polling secret")
        supplied_hash = hash_secret(polling_secret)
        if not hmac.compare_digest(supplied_hash, transaction.polling_secret_hash):
            raise InvalidTransaction("invalid transaction or polling secret")
        return transaction

    def _get_transaction(self, transaction_id: str) -> _Transaction:
        transaction = self._transactions.get(transaction_id)
        if transaction is None:
            raise InvalidTransaction("unknown transaction")
        return transaction

    def _expire_if_needed(self, transaction: _Transaction) -> None:
        if self._clock() >= transaction.expires_at:
            transaction.credential = None
            transaction.state = TransactionState.EXPIRED
            self._callback_states.pop(transaction.callback_state_hash, None)
