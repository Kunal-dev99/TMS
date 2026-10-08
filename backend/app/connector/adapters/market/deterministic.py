"""MarketDataPort backed by an in-house deterministic engine.

Today the FX flows run through ``app.services.quote_engine`` — this
adapter is the port-facing wrapper. When the Xignite adapter lands
(Stage 6), this one stays alive for tests + demos.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.connector.ports import Quote, Rate


class DeterministicMarket:
    name = "deterministic"

    def spot(self, pair: str) -> Quote:
        # Lazy import so the port module never pays the cost when only
        # a different adapter is bound.
        from app.services import fx_rate_service as fxr

        q = fxr.spot(pair)
        return Quote(pair=q.pair, rate=float(q.spot), as_of=q.as_of, source="deterministic")

    def forward(self, pair: str, tenor_months: int) -> Quote:
        from app.services import fx_rate_service as fxr

        q = fxr.forward(pair, tenor_months)
        return Quote(pair=q.pair, rate=float(q.forward), as_of=q.as_of, source="deterministic")

    def benchmark(self, code: str, as_of: date) -> Rate:
        # No benchmark engine exists yet in Phase 1. Return a stable
        # zero so a caller has a defined shape to work with. Stage 6
        # replaces this once the reference table lands.
        return Rate(name=code, value_bp=0, as_of=as_of.isoformat(), source="deterministic")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
