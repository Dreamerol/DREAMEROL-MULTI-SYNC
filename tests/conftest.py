import pytest


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record retry delays instead of waiting for them."""
    recorded = []
    monkeypatch.setattr("fork_sync.github.time.sleep", recorded.append)
    return recorded
