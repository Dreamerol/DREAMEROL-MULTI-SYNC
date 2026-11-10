"""Tests for the in-memory authentication transaction state machine."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from auth_broker.security import generate_callback_state, generate_polling_secret, hash_secret
from auth_broker.transactions import (
    InvalidCallbackState,
    InvalidTransaction,
    InvalidTransition,
    TransactionExpired,
    TransactionState,
    TransactionStore,
)


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture
def store_and_secrets():
    clock = Clock()
    store = TransactionStore(ttl_seconds=10, clock=clock)
    polling_secret = generate_polling_secret()
    callback_state = generate_callback_state()
    transaction_id = store.create(hash_secret(polling_secret), callback_state)
    return store, clock, transaction_id, polling_secret, callback_state


def test_transaction_follows_valid_state_machine(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets

    assert store.poll(transaction_id, polling_secret).state is TransactionState.PENDING
    assert store.claim_callback(callback_state) == transaction_id
    store.make_token_ready(transaction_id, "credential-value")

    result = store.poll(transaction_id, polling_secret)
    assert result.state is TransactionState.DELIVERY_AUTHORIZED
    assert result.credential == "credential-value"
    assert store.acknowledge(transaction_id, polling_secret) is TransactionState.ACKNOWLEDGED
    assert store.poll(transaction_id, polling_secret) == type(result)(TransactionState.ACKNOWLEDGED)


def test_invalid_callback_state_does_not_change_transaction(store_and_secrets):
    store, _, transaction_id, polling_secret, _ = store_and_secrets

    with pytest.raises(InvalidCallbackState):
        store.claim_callback("attacker-controlled-state")

    assert store.poll(transaction_id, polling_secret).state is TransactionState.PENDING


def test_callback_can_be_claimed_only_once(store_and_secrets):
    store, _, transaction_id, _, callback_state = store_and_secrets

    assert store.claim_callback(callback_state) == transaction_id
    with pytest.raises(InvalidCallbackState):
        store.claim_callback(callback_state)


def test_concurrent_callback_claim_has_exactly_one_winner(store_and_secrets):
    store, _, transaction_id, _, callback_state = store_and_secrets
    barrier = Barrier(8)

    def claim():
        barrier.wait()
        try:
            return store.claim_callback(callback_state)
        except (InvalidCallbackState, InvalidTransition):
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: claim(), range(8)))

    assert outcomes.count(transaction_id) == 1
    assert outcomes.count(None) == 7


def test_callback_failure_and_denial_terminate_only_matching_transaction():
    store = TransactionStore()
    secret_a, state_a = generate_polling_secret(), generate_callback_state()
    secret_b, state_b = generate_polling_secret(), generate_callback_state()
    tx_a = store.create(hash_secret(secret_a), state_a)
    tx_b = store.create(hash_secret(secret_b), state_b)

    assert store.fail_callback(state_a) == tx_a
    assert store.fail_callback(state_b, cancelled=True) == tx_b
    assert store.poll(tx_a, secret_a).state is TransactionState.FAILED
    assert store.poll(tx_b, secret_b).state is TransactionState.CANCELLED


def test_processing_failure_transitions_to_failed_and_clears_credential(
    store_and_secrets,
):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)

    assert store.fail_processing(transaction_id) is TransactionState.FAILED
    assert store.poll(transaction_id, polling_secret).state is TransactionState.FAILED
    assert store._transactions[transaction_id].credential is None


def test_repeated_processing_failure_is_rejected(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)

    assert store.fail_processing(transaction_id) is TransactionState.FAILED
    with pytest.raises(InvalidTransition):
        store.fail_processing(transaction_id)

    assert store.poll(transaction_id, polling_secret).state is TransactionState.FAILED


def test_ack_is_rejected_before_delivery_and_preserves_credential(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")

    with pytest.raises(InvalidTransition):
        store.acknowledge(transaction_id, polling_secret)

    assert store.poll(transaction_id, polling_secret).credential == "credential-value"


def test_repeated_poll_returns_same_credential_until_ack(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")

    first = store.poll(transaction_id, polling_secret)
    second = store.poll(transaction_id, polling_secret)
    assert first.state is TransactionState.DELIVERY_AUTHORIZED
    assert second == first


def test_poll_completes_before_ack_returns_authorized_credential(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")

    poll_result = store.poll(transaction_id, polling_secret)

    assert poll_result.state is TransactionState.DELIVERY_AUTHORIZED
    assert poll_result.credential == "credential-value"
    assert store.acknowledge(transaction_id, polling_secret) is TransactionState.ACKNOWLEDGED


def test_ack_completes_before_subsequent_poll_returns_no_credential(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")
    assert store.poll(transaction_id, polling_secret).credential == "credential-value"

    assert store.acknowledge(transaction_id, polling_secret) is TransactionState.ACKNOWLEDGED

    poll_result = store.poll(transaction_id, polling_secret)
    assert poll_result.state is TransactionState.ACKNOWLEDGED
    assert poll_result.credential is None


def test_ack_is_idempotent_and_removes_credential(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")
    store.poll(transaction_id, polling_secret)

    assert store.acknowledge(transaction_id, polling_secret) is TransactionState.ACKNOWLEDGED
    assert store.acknowledge(transaction_id, polling_secret) is TransactionState.ACKNOWLEDGED
    after_ack = store.poll(transaction_id, polling_secret)
    assert after_ack.state is TransactionState.ACKNOWLEDGED
    assert after_ack.credential is None
    assert store._transactions[transaction_id].credential is None


def test_poll_and_ack_are_atomic_under_concurrent_retries(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")
    barrier = Barrier(12)

    def poll():
        barrier.wait()
        return store.poll(transaction_id, polling_secret)

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _: poll(), range(12)))

    assert all(result.state is TransactionState.DELIVERY_AUTHORIZED for result in results)
    assert {result.credential for result in results} == {"credential-value"}

    ack_barrier = Barrier(12)

    def ack():
        ack_barrier.wait()
        return store.acknowledge(transaction_id, polling_secret)

    with ThreadPoolExecutor(max_workers=12) as executor:
        ack_results = list(executor.map(lambda _: ack(), range(12)))

    assert set(ack_results) == {TransactionState.ACKNOWLEDGED}
    assert store.poll(transaction_id, polling_secret).credential is None


def test_poll_ack_race_is_linearizable(store_and_secrets):
    store, _, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")

    # Authorize delivery first so ACK is valid; then race a retrying poll
    # against ACK on the same transaction.
    assert (
        store.poll(transaction_id, polling_secret).state
        is TransactionState.DELIVERY_AUTHORIZED
    )
    barrier = Barrier(2)

    def poll():
        barrier.wait()
        return store.poll(transaction_id, polling_secret)

    def ack():
        barrier.wait()
        return store.acknowledge(transaction_id, polling_secret)

    with ThreadPoolExecutor(max_workers=2) as executor:
        poll_future = executor.submit(poll)
        ack_future = executor.submit(ack)
        poll_result = poll_future.result()
        ack_result = ack_future.result()

    assert ack_result is TransactionState.ACKNOWLEDGED
    if poll_result.state is TransactionState.DELIVERY_AUTHORIZED:
        # Poll linearized before ACK.
        assert poll_result.credential == "credential-value"
    else:
        # ACK linearized first; the racing poll must not get the credential.
        assert poll_result.state is TransactionState.ACKNOWLEDGED
        assert poll_result.credential is None

    after_ack = store.poll(transaction_id, polling_secret)
    assert after_ack.state is TransactionState.ACKNOWLEDGED
    assert after_ack.credential is None


def test_wrong_secret_never_reveals_transaction_state(store_and_secrets):
    store, _, transaction_id, _, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")

    with pytest.raises(InvalidTransaction):
        store.poll(transaction_id, "wrong-secret")
    with pytest.raises(InvalidTransaction):
        store.acknowledge("unknown-id", "wrong-secret")


def test_expiration_clears_credential_and_cleanup_removes_transaction(store_and_secrets):
    store, clock, transaction_id, polling_secret, callback_state = store_and_secrets
    store.claim_callback(callback_state)
    store.make_token_ready(transaction_id, "credential-value")
    store.poll(transaction_id, polling_secret)
    clock.advance(10)

    result = store.poll(transaction_id, polling_secret)
    assert result.state is TransactionState.EXPIRED
    assert result.credential is None
    assert store._transactions[transaction_id].credential is None
    assert store.cleanup_expired() == 1
    with pytest.raises(InvalidTransaction):
        store.poll(transaction_id, polling_secret)


def test_expired_callback_cannot_be_claimed(store_and_secrets):
    store, clock, _, _, callback_state = store_and_secrets
    clock.advance(10)

    with pytest.raises(TransactionExpired):
        store.claim_callback(callback_state)


def test_create_rejects_malformed_hash_and_empty_credential(store_and_secrets):
    store, _, _, _, _ = store_and_secrets
    with pytest.raises(ValueError):
        store.create("not-a-hash", generate_callback_state())
    with pytest.raises(ValueError):
        store.make_token_ready("missing", "")


@pytest.mark.parametrize(
    "ttl_seconds",
    [0, -1, float("nan"), float("inf"), float("-inf")],
)
def test_ttl_must_be_positive_and_finite(ttl_seconds):
    with pytest.raises(ValueError):
        TransactionStore(ttl_seconds=ttl_seconds)
