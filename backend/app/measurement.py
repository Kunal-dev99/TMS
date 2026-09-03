"""How a deal is measured for counterparty exposure.

One implementation. ExposureCalculator in phase one calls this and so does
the mock server's fixture builder, which is what stops the mock and the real
API disagreeing about a figure.

A principal is not an exposure. A forward's notional is not an exposure
either. Every function here returns both the figure and the basis it was
measured on, because the interface shows the basis underneath the figure and
would otherwise have to reconstruct it.
"""

from dataclasses import dataclass
from datetime import date

DAYS_IN_YEAR = 365
BP = 10_000


@dataclass(frozen=True)
class Measure:
    """A measured exposure and the sentence that says how it was measured."""

    amount_pence: int
    basis: str


def _round_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounding halves away from zero.

    Python's round() is half to even and // truncates towards minus infinity.
    Neither is what a treasury expects to see next to a figure, and the
    difference shows up as a penny on screen.
    """
    if denominator == 0:
        return 0
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    n, d = abs(numerator), abs(denominator)
    return sign * ((2 * n + d) // (2 * d))


def days_between(start_iso: str, end_iso: str) -> int:
    return (date.fromisoformat(end_iso) - date.fromisoformat(start_iso)).days


def accrued_interest_pence(
    principal_pence: int, rate_bp: int, days: int
) -> int:
    """Simple interest, actual over 365, rounded half up to the penny."""
    if days <= 0:
        return 0
    return _round_half_up(principal_pence * rate_bp * days, BP * DAYS_IN_YEAR)


def measure_deal(
    *,
    instrument: str,
    principal_pence: int,
    rate_bp: int,
    value_date: str,
    as_of_date: str,
    fx_add_on_bp: int,
) -> Measure:
    """Measure one deal for counterparty exposure, as of a date.

    DEPOSIT     principal plus interest accrued to the as of date
    FX_FORWARD  the notional times the policy add on, never the notional
    MMF         the holding at principal, which is its current value here
    GILT        the holding at principal, clean, in this build
    """
    if instrument == "DEPOSIT":
        days = max(0, days_between(value_date, as_of_date))
        accrued = accrued_interest_pence(principal_pence, rate_bp, days)
        return Measure(
            amount_pence=principal_pence + accrued,
            basis=(
                f"principal plus {accrued / 100:,.0f} accrued over {days} days"
                if accrued
                else "principal, nothing accrued yet"
            ),
        )

    if instrument == "FX_FORWARD":
        add_on = _round_half_up(principal_pence * fx_add_on_bp, BP)
        return Measure(
            amount_pence=add_on,
            basis=f"{fx_add_on_bp / 100:g} per cent add on to notional",
        )

    if instrument == "MMF":
        return Measure(amount_pence=principal_pence, basis="holding at value")

    if instrument == "GILT":
        return Measure(amount_pence=principal_pence, basis="holding at clean price")

    raise ValueError(f"No exposure measure defined for instrument {instrument!r}")


def principal_for_measure(
    *, instrument: str, measure_pence: int, fx_add_on_bp: int
) -> int:
    """The largest principal whose measure fits inside `measure_pence`.

    The resize control sets the principal on the ticket, but headroom is
    expressed in measured exposure, and for a forward the two are not the
    same number. Offering the headroom as a principal would offer ten times
    what fits.

    Rounds down, so the resulting measure never exceeds the headroom. A deal
    proposed today has no accrued interest yet, which is why a deposit's
    principal and its measure are the same figure here and not in
    measure_deal.
    """
    if measure_pence <= 0:
        return 0
    if instrument == "FX_FORWARD":
        if fx_add_on_bp <= 0:
            return 0
        return (measure_pence * BP) // fx_add_on_bp
    if instrument in ("DEPOSIT", "MMF", "GILT"):
        return measure_pence
    raise ValueError(f"No exposure measure defined for instrument {instrument!r}")
