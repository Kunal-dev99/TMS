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

    return {
        "total_interest_pence": total_interest,
        "weighted_rate_bp": weighted_rate,
        "days_recognised": len({r.accrual_date for r in rows}),
        "by_counterparty": by_counterparty,
        "by_band": by_band,
        "by_month": by_month,
    }
