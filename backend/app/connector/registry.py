"""Binds each port to an adapter at runtime.

Reads an env var per port to pick which adapter is bound; falls back
to the fake/default that reproduces today's behaviour. Every real
deployment sets the env vars explicitly (see PHASE_2_IMPLEMENTATION_PLAN
§7 for the table).

Tests use ``registry.override(port_cls, instance)`` to plug in a stub
without touching the environment. ``registry.reset()`` clears every
binding, restoring the env-driven defaults on the next ``get()``.

The registry is deliberately small — no dependency-injection framework,
no service locator ceremony. One global dict, one lookup function.
Simpler than the alternatives; nothing in this module is on a hot path.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, TypeVar

from app.connector import ports

T = TypeVar("T")


# Module-level singletons. A test that flips an env var must call
# ``reset()`` to force rebinding.
_bindings: dict[type, Any] = {}
_lock = threading.Lock()


# --- factories --------------------------------------------------------------


def _make_secrets() -> ports.SecretsPort:
    kind = os.environ.get("SECRETS_PROVIDER", "env_var").lower()
    if kind == "env_var":
        from app.connector.adapters.secrets.env_var import EnvVarSecrets

        return EnvVarSecrets()
    if kind == "local_file":
        from app.connector.adapters.secrets.local_file import LocalFileSecrets

        return LocalFileSecrets()
    if kind == "azure_key_vault":
        # Skeleton — Stage 8. Falls through to env_var if not implemented.
        try:
            from app.connector.adapters.secrets.azure_key_vault import (
                AzureKeyVaultSecrets,
            )

            return AzureKeyVaultSecrets()
        except NotImplementedError:
            from app.connector.adapters.secrets.env_var import EnvVarSecrets

            return EnvVarSecrets()
    raise ValueError(f"Unknown SECRETS_PROVIDER: {kind}")


def _make_mail() -> ports.MailPort:
    kind = os.environ.get("MAIL_PROVIDER", "console").lower()
    if kind == "console":
        from app.connector.adapters.mail.console import ConsoleMail

        return ConsoleMail()
    if kind == "smtp":
        from app.connector.adapters.mail.smtp import SmtpMail

        return SmtpMail()
    raise ValueError(f"Unknown MAIL_PROVIDER: {kind}")


def _make_llm() -> ports.LLMPort:
    kind = os.environ.get("LLM_PROVIDER", "groq").lower()
    if kind == "groq":
        from app.connector.adapters.llm.groq import GroqLLM

        return GroqLLM()
    if kind == "deterministic":
        from app.connector.adapters.llm.deterministic import DeterministicLLM

        return DeterministicLLM()
    raise ValueError(f"Unknown LLM_PROVIDER: {kind}")


def _make_market() -> ports.MarketDataPort:
    kind = os.environ.get("MARKET_DATA_PROVIDER", "deterministic").lower()
    if kind == "deterministic":
        from app.connector.adapters.market.deterministic import DeterministicMarket

        return DeterministicMarket()
    raise ValueError(f"Unknown MARKET_DATA_PROVIDER: {kind}")


def _make_identity() -> ports.IdentityPort:
    kind = os.environ.get("IDENTITY_PROVIDER", "local_password").lower()
    if kind == "local_password":
        from app.connector.adapters.identity.local_password import LocalPasswordIdentity

        return LocalPasswordIdentity()
    raise ValueError(f"Unknown IDENTITY_PROVIDER: {kind}")


def _make_erp() -> ports.ERPPort:
    kind = os.environ.get("ERP_PROVIDER", "fake_oracle").lower()
    if kind == "fake_oracle":
        from app.connector.adapters.erp.fake_oracle import FakeOracle

        return FakeOracle()
    raise ValueError(f"Unknown ERP_PROVIDER: {kind}")


def _make_bank() -> ports.BankPort:
    kind = os.environ.get("BANK_PROVIDER", "file_bank").lower()
    if kind == "file_bank":
        from app.connector.adapters.bank.file_bank import FileBank

        return FileBank()
    raise ValueError(f"Unknown BANK_PROVIDER: {kind}")


def _make_signing() -> ports.SigningPort:
    kind = os.environ.get("SIGNING_PROVIDER", "software").lower()
    if kind == "software":
        from app.connector.adapters.signing.software import SoftwareSigning

        return SoftwareSigning()
    raise ValueError(f"Unknown SIGNING_PROVIDER: {kind}")


def _make_rate_limit_store() -> ports.RateLimitStorePort:
    kind = os.environ.get("RATE_LIMIT_STORE", "memory").lower()
    if kind == "memory":
        from app.connector.adapters.rate_limit_store.memory import (
            MemoryRateLimitStore,
        )

        return MemoryRateLimitStore()
    if kind == "redis":
        from app.connector.adapters.rate_limit_store.redis import (
            RedisRateLimitStore,
            connect,
        )

        secrets = get(ports.SecretsPort)
        url = secrets.get("REDIS_URL")
        if not url:
            raise ValueError(
                "RATE_LIMIT_STORE=redis requires REDIS_URL in the secrets store."
            )
        return RedisRateLimitStore(connect(url))
    raise ValueError(f"Unknown RATE_LIMIT_STORE: {kind}")


_FACTORIES: dict[type, Callable[[], Any]] = {
    ports.SecretsPort: _make_secrets,
    ports.MailPort: _make_mail,
    ports.LLMPort: _make_llm,
    ports.MarketDataPort: _make_market,
    ports.IdentityPort: _make_identity,
    ports.ERPPort: _make_erp,
    ports.BankPort: _make_bank,
    ports.SigningPort: _make_signing,
    ports.RateLimitStorePort: _make_rate_limit_store,
}


# --- public surface ---------------------------------------------------------


def get(port_cls: type[T]) -> T:
    """Return the bound adapter for a port, creating it on first use."""
    with _lock:
        if port_cls in _bindings:
            return _bindings[port_cls]
        factory = _FACTORIES.get(port_cls)
        if factory is None:
            raise KeyError(f"No factory registered for {port_cls!r}")
        instance = factory()
        _bindings[port_cls] = instance
        return instance


def override(port_cls: type, instance: Any) -> None:
    """Force a specific adapter — tests use this to plug in stubs."""
    with _lock:
        _bindings[port_cls] = instance


def reset() -> None:
    """Clear every binding. Next ``get()`` re-reads env vars."""
    with _lock:
        _bindings.clear()
