"""FX rates for the hedging capability.

Two rates, not one: **spot** is what you would settle today, **forward** is
what the counterparty will settle on a future date. They differ by the
forward points, which come from the interest-rate differential between the
two currencies. A prototype that quoted spot as if it were a forward would
teach the user the wrong idea, and the correction later would cost more
than the discipline here.

The provider is stubbed. Real integration goes behind this same interface:
a Bloomberg BGN pull, a bank feed, whatever the customer already has. The
source label on every quote says so on the ticket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


#: The demo pairs. Each row: spot rate (units of quote per unit of base),
#: forward points per **year**, expressed in basis points of the spot.
#: A negative number means the forward trades at a discount to spot, which
#: is what happens when the base-currency interest rate is higher than the
#: quote currency's (EUR rates below GBP → EUR/GBP forward discount).
_PAIRS: dict[str, dict] = {
    # base_GBP: for a EUR receivable we sell EUR forward and buy GBP.
    #     Rate is GBP per 1 EUR.
    "EUR_GBP": {"spot": 0.8600, "annual_forward_bp": -150, "as_of": None},
    "USD_GBP": {"spot": 0.7800, "annual_forward_bp": -100, "as_of": None},
    "CHF_GBP": {"spot": 0.8850, "annual_forward_bp": 60, "as_of": None},
}


@dataclass
class FxQuote:
    pair: str
    spot: float
    forward: float
    forward_points_bp: int  # forward - spot, in bp of spot
    tenor_months: int
    source: str
    quality: str  # "indicative" (stubbed) or "executable" (real bank)
    as_of: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def spot(pair: str) -> FxQuote:
    """Today's mid, stubbed. Same shape as a Bloomberg BGN composite."""
    pair = pair.upper()
    row = _PAIRS.get(pair)
    if row is None:
        raise ValueError(f"Unknown pair {pair}")
    return FxQuote(
        pair=pair,
        spot=row["spot"],
        forward=row["spot"],
        forward_points_bp=0,
        tenor_months=0,
        source="Bloomberg BGN composite (stubbed)",
        quality="indicative",
        as_of=_now(),
    )


def forward(pair: str, tenor_months: int) -> FxQuote:
    """Forward mid, stubbed.

    A linear scale of the annual forward points is fine for a prototype —
    real curves are lumpy at the tenor boundaries but the shape and sign
    are what a treasurer wants to see, and the number is labelled
    indicative so nobody trades on it.
    """
    pair = pair.upper()
    row = _PAIRS.get(pair)
    if row is None:
        raise ValueError(f"Unknown pair {pair}")
    spot_rate = row["spot"]
    fwd_bp = round(row["annual_forward_bp"] * tenor_months / 12)
    fwd = round(spot_rate * (1 + fwd_bp / 10_000), 6)
    return FxQuote(
        pair=pair,
        spot=spot_rate,
        forward=fwd,
        forward_points_bp=fwd_bp,
        tenor_months=tenor_months,
        source="Bloomberg BGN composite (stubbed)",
        quality="indicative",
        as_of=_now(),
    )


def supported_pairs() -> list[str]:
    return list(_PAIRS.keys())


def gbp_equivalent_pence(currency: str, amount_minor: int) -> int:
    """Convert a foreign-currency minor-unit amount to GBP pence at spot."""
    currency = currency.upper()
    if currency == "GBP":
        return amount_minor
    quote = spot(f"{currency}_GBP")
    return round(amount_minor * quote.spot)
