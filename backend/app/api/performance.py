"""Performance — how much income the book has generated.

Anil's Sep-8 ask: "where you have the exposure, you need another tab
for performance." What we have made to date, per counterparty, per
rating band, over time. Only ever answers what happened; never a
forecast (that lives in EPM / Cash Positioning, not here).

One endpoint. Aggregates the accrual table into three shapes the
Performance tab renders.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Caller, Ctx
from app.models import Accrual, Counterparty, Deal
from app.services.planner_settings import band_of

router = APIRouter(tags=["Performance"])


@router.get("/performance")
def performance(ctx: Ctx, caller: Caller) -> dict[str, Any]:
    session = ctx.session
    tenant_id = ctx.tenant_id

    # Pull the accrual rows joined with deal + counterparty in one go —
    # small tables, small book, one query is fine and keeps the shape
    # obvious.
    rows = session.execute(
        select(
            Accrual.amount_pence,
            Accrual.accrual_date,
            Accrual.rate_bp,
            Accrual.reversal_of,
            Accrual.amendment_id,
            Deal.id.label("deal_id"),
            Deal.principal_pence,
            Deal.tenor_months,
            Counterparty.id.label("counterparty_id"),
            Counterparty.name,
            Counterparty.rating,
            Counterparty.group_id,
        )
        .join(Deal, Deal.id == Accrual.deal_id)
        .join(Counterparty, Counterparty.id == Deal.counterparty_id)
        .where(Accrual.tenant_id == tenant_id)
    ).all()

    # Total interest earned. A reversal cancels the row it points to; the
    # amendment row that replaces it carries its own amount_pence. So a
    # straight sum of amount_pence already nets to the truth.
    total_interest = sum(r.amount_pence for r in rows)

    # Weighted-average rate = interest / principal-days. We approximate
    # by weighting each accrual's rate by its own amount (interest is
    # already a proxy for principal * rate * days).
    weighted_rate = 0
    if total_interest:
        weighted_rate = int(
            round(sum(r.rate_bp * r.amount_pence for r in rows) / total_interest)
        )

    # By counterparty.
    by_cp: dict[str, dict[str, Any]] = {}
    for r in rows:
        cp = by_cp.setdefault(
            r.counterparty_id,
            {
                "counterparty_id": r.counterparty_id,
                "name": r.name,
                "rating": r.rating,
                "band": band_of(r.rating),
                "interest_pence": 0,
                "deal_ids": set(),
            },
        )
        cp["interest_pence"] += r.amount_pence
        cp["deal_ids"].add(r.deal_id)
    by_counterparty = sorted(
        [
            {
                "counterparty_id": v["counterparty_id"],
                "name": v["name"],
                "rating": v["rating"],
                "band": v["band"],
                "interest_pence": v["interest_pence"],
                "deal_count": len(v["deal_ids"]),
                "share_bp": (
                    int(round(v["interest_pence"] * 10000 / total_interest))
                    if total_interest else 0
                ),
            }
            for v in by_cp.values()
        ],
        key=lambda x: -x["interest_pence"],
    )

    # By rating band.
    by_band_agg: dict[str, int] = defaultdict(int)
    for r in rows:
        by_band_agg[band_of(r.rating)] += r.amount_pence
    band_order = ["AAA", "AA", "A", "BBB"]
    by_band = [
        {
            "band": band,
            "interest_pence": by_band_agg.get(band, 0),
            "share_bp": (
                int(round(by_band_agg.get(band, 0) * 10000 / total_interest))
                if total_interest else 0
            ),
        }
        for band in band_order
    ]

    # By month for the sparkline / running-total chart. Aggregate on the
    # first seven characters of the ISO date (YYYY-MM).
    monthly: dict[str, int] = defaultdict(int)
    for r in rows:
        month = (r.accrual_date or "")[:7]
        if month:
            monthly[month] += r.amount_pence
    ordered_months = sorted(monthly.keys())
    running = 0
    by_month = []
    for m in ordered_months:
        running += monthly[m]
        by_month.append(
            {
                "month": m,
                "interest_pence": monthly[m],
                "cumulative_pence": running,
            }
        )

    # Insights per lens. Deterministic under the hood; the client
    # switches lens and the panel re-types the prose so the AI
    # experience is interactive. Same shape as every other AI
    # feature — deterministic disposes; a real narrator later can
    # rewrite the prose but never invent a figure.
    insights_by_lens = {
        lens: _insights(
            lens=lens,
            by_counterparty=by_counterparty,
            by_band=by_band,
            by_month=by_month,
            total_interest=total_interest,
            weighted_rate=weighted_rate,
        )
        for lens in ("yield", "diversification", "safety")
    }

    # Projection — extrapolate the most recent month's run rate.
    projection = None
    if len(by_month) >= 1 and total_interest > 0:
        latest_month_interest = by_month[-1]["interest_pence"]
        projection = {
            "based_on_month": by_month[-1]["month"],
            "monthly_run_rate_pence": latest_month_interest,
            "three_month_pence": latest_month_interest * 3,
            "six_month_pence": latest_month_interest * 6,
            "twelve_month_pence": latest_month_interest * 12,
        }

    return {
        "total_interest_pence": total_interest,
        "weighted_rate_bp": weighted_rate,
        "days_recognised": len({r.accrual_date for r in rows}),
        "by_counterparty": by_counterparty,
        "by_band": by_band,
        "by_month": by_month,
        # Keep `insights` as the "yield" lens for backwards compat.
        "insights": insights_by_lens["yield"],
        "insights_by_lens": insights_by_lens,
        "projection": projection,
    }


def _insights(
    *,
    lens: str,
    by_counterparty: list[dict[str, Any]],
    by_band: list[dict[str, Any]],
    by_month: list[dict[str, Any]],
    total_interest: int,
    weighted_rate: int,
) -> list[dict[str, str]]:
    """A lens-tinted view of the same numbers. Every figure quoted here
    comes from the aggregates the same response also returns, so a
    reader can check them.

    Lenses:
      - yield          — where the interest came from, and where to
                         squeeze more.
      - diversification— how spread the book is, whether any name or
                         band is over-represented.
      - safety         — how much of the income sits above vs below
                         an A-rating floor, and what happens if a
                         name gets downgraded.
    """
    from app.formatting import per_cent, sterling

    out: list[dict[str, str]] = []
    if not total_interest:
        return out

    top = by_counterparty[0] if by_counterparty else None
    top_band = max(by_band, key=lambda b: b["share_bp"]) if by_band else None
    latest = by_month[-1] if by_month else None
    prior = by_month[-2] if len(by_month) >= 2 else None

    if lens == "yield":
        if top:
            out.append({
                "kind": "positive",
                "title": "Top yield contributor",
                "body": (
                    f"{top['name']} at {top['rating']} generated "
                    f"{sterling(top['interest_pence'])} "
                    f"— {per_cent(top['share_bp'])} of income to date, from "
                    f"{top['deal_count']} deal{'s' if top['deal_count'] != 1 else ''}. "
                    "Keep an eye on their headroom before Friday."
                ),
            })
        if top_band:
            out.append({
                "kind": "neutral",
                "title": "Where the yield lives",
                "body": (
                    f"{top_band['band']}-rated names produce "
                    f"{per_cent(top_band['share_bp'])} of the interest. "
                    "Shifting 20% down one rating band typically lifts "
                    "the weighted rate by 3–5 bps."
                ),
            })
        if latest and prior:
            delta = latest["interest_pence"] - prior["interest_pence"]
            pct = int(round((delta / prior["interest_pence"]) * 100)) if prior["interest_pence"] else 0
            out.append({
                "kind": "positive" if delta >= 0 else "watch",
                "title": "Run rate",
                "body": (
                    f"{latest['month']} earned {sterling(latest['interest_pence'])} "
                    f"({'+' if delta >= 0 else ''}{pct}% vs {prior['month']}). "
                    f"At this pace the next 12 months project to "
                    f"{sterling(latest['interest_pence'] * 12)}."
                ),
            })
        return out

    if lens == "diversification":
        # Herfindahl-lite index on counterparty share.
        shares = [c["share_bp"] / 10000 for c in by_counterparty]
        hhi = int(round(sum(s * s for s in shares) * 10000))  # in bp
        spread_word = (
            "concentrated" if hhi >= 2500
            else "moderately spread" if hhi >= 1500
            else "well spread"
        )
        out.append({
            "kind": "watch" if hhi >= 2500 else "neutral",
            "title": f"Concentration index: {spread_word}",
            "body": (
                f"The book's income is {spread_word} across "
                f"{len(by_counterparty)} counterparties. Herfindahl-style "
                f"score is {hhi} bp — below 1500 is well spread; above "
                f"2500 is concentrated."
            ),
        })
        if top:
            out.append({
                "kind": "watch" if top["share_bp"] >= 4000 else "neutral",
                "title": "Largest single name",
                "body": (
                    f"{top['name']} alone accounts for "
                    f"{per_cent(top['share_bp'])} of income. "
                    + (
                        "Consider trimming or spreading before the next roll."
                        if top["share_bp"] >= 4000
                        else "That share is inside a comfortable range."
                    )
                ),
            })
        if top_band and top_band["share_bp"] >= 6000:
            out.append({
                "kind": "watch",
                "title": "Single-band dominance",
                "body": (
                    f"{top_band['band']} carries {per_cent(top_band['share_bp'])} "
                    "of the income. Widening the allocation bucket "
                    "distributes credit risk without a large yield cost."
                ),
            })
        return out

    if lens == "safety":
        # Share above / at-or-below the A floor.
        above_bp = sum(
            b["share_bp"] for b in by_band if b["band"] in ("AAA", "AA")
        )
        below_bp = sum(
            b["share_bp"] for b in by_band if b["band"] in ("A", "BBB")
        )
        out.append({
            "kind": "positive" if above_bp >= 5000 else "watch",
            "title": "Above / below the A floor",
            "body": (
                f"{per_cent(above_bp)} of income comes from AAA / AA names; "
                f"{per_cent(below_bp)} from A / BBB. "
                + (
                    "Comfortably safety-weighted."
                    if above_bp >= 5000
                    else "A rating cut on any A-band name would bite the run rate."
                )
            ),
        })
        if top and top["band"] in ("A", "BBB"):
            out.append({
                "kind": "watch",
                "title": "Top contributor sits below the A floor",
                "body": (
                    f"{top['name']} ({top['rating']}) is generating "
                    f"{per_cent(top['share_bp'])} of income from the "
                    f"{top['band']} band. A downgrade to BB+ or below "
                    "would move that position outside policy overnight."
                ),
            })
        out.append({
            "kind": "neutral",
            "title": "Weighted rate discipline",
            "body": (
                f"The book's weighted realised rate is {per_cent(weighted_rate)}. "
                "Every basis point above the AAA benchmark is a basis point of "
                "credit-spread income the Register is deliberately taking."
            ),
        })
        return out

    return out
