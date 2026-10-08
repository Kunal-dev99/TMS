"""S1 — RateLimitStorePort contract + factory wiring.

The service-level sliding-window behaviour is covered by test_rate_limit.
These tests cover only the port + the Memory adapter in isolation + the
registry factory, so a Redis adapter added later can reuse the same
contract tests by swapping the fixture.
"""
from __future__ import annotations

import time

import pytest

from app.connector import ports, registry
from app.connector.adapters.rate_limit_store.memory import MemoryRateLimitStore


@pytest.fixture
def store():
    return MemoryRateLimitStore()


def test_memory_store_satisfies_the_port(store):
    assert isinstance(store, ports.RateLimitStorePort)
    assert store.name == "memory"


def test_hit_returns_allowed_until_cap(store):
    for _ in range(3):
        allowed, retry = store.hit("k", max_requests=3, window_seconds=5)
        assert allowed is True
        assert retry == 0.0


def test_hit_refuses_once_cap_is_reached(store):
    for _ in range(3):
        store.hit("k", 3, 5)
    allowed, retry = store.hit("k", 3, 5)
    assert allowed is False
    assert 0.0 <= retry <= 5.0


def test_keys_are_independent(store):
    for _ in range(3):
        store.hit("a", 3, 5)
    # 'b' still has full budget.
    allowed, _ = store.hit("b", 3, 5)
    assert allowed is True


def test_window_releases_tokens(store):
    store.hit("k", 1, 0.05)
    allowed, _ = store.hit("k", 1, 0.05)
    assert allowed is False
    time.sleep(0.08)
    allowed, _ = store.hit("k", 1, 0.05)
    assert allowed is True


def test_clear_wipes_state(store):
    store.hit("k", 1, 5)
    store.clear()
    allowed, _ = store.hit("k", 1, 5)
    assert allowed is True


def test_registry_returns_memory_store_by_default(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_STORE", raising=False)
    registry.reset()
    bound = registry.get(ports.RateLimitStorePort)
    assert bound.name == "memory"


def test_registry_refuses_unknown_backend(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STORE", "nope")
    registry.reset()
    with pytest.raises(ValueError, match="Unknown RATE_LIMIT_STORE"):
        registry.get(ports.RateLimitStorePort)
    registry.reset()


def test_redis_backend_requires_redis_url(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STORE", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    registry.reset()
    with pytest.raises(ValueError, match="REDIS_URL"):
        registry.get(ports.RateLimitStorePort)
    registry.reset()
