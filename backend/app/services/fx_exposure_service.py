"""FX exposure aggregation for the Hedging panel.

This is the read side: takes the CurrencyExposure rows and the live
HedgeLinks and produces the shapes the dashboard needs — a summary line
per currency and a bucketed drilldown for one currency.

Writes go through HedgeService, which is the invariant-holder. Nothing
here mutates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CurrencyCoverTarget, CurrencyExposure, InvestmentPolicy
from app.services.fx_rate_service import gbp_equivalent_pence
from app.services.hedge_service import BUCKETS, HedgeService


@dataclass
class CurrencySummary:
    currency: str
    gross_minor: int
    hedged_minor: int
    unhedged_minor: int
    hedge_ratio_bp: int
    gross_gbp_pence: int
    unhedged_gbp_pence: int
    target_cover_bp: int
    gap_to_target_minor: int


@dataclass
class BucketRow:
    bucket: str
    label: str
    forecast_minor: int
    hedged_minor: int
    unhedged_minor: int
    forecast_gbp_pence: int
    unhedged_gbp_pence: int


@dataclass
class ExposureRow:
    id: str
    expected_date: str
    amount_minor: int
    direction: str
    source: str
    source_reference: str | None
    status: str
    hedged_minor: int


class FxExposureService:
    def __init__(self, session: Session, tenant_id: str, as_of_date: str) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date
        self.hedge_service = HedgeService(session, tenant_id, as_of_date)

    def supported_currencies(self) -> list[str]:
        rows = self.session.scalars(
            select(CurrencyExposure.currency)
            .where(CurrencyExposure.tenant_id == self.tenant_id)
            .distinct()
        )
        return sorted({r for r in rows})

    def summary(self) -> list[CurrencySummary]:
        return [self._summary_for(ccy) for ccy in self.supported_currencies()]

    def _summary_for(self, currency: str) -> CurrencySummary:
        exposures = [
            e
            for e in self.hedge_service.exposures(currency)
            if e.status != "SETTLED" and e.direction == "RECEIVABLE"
        ]
        gross = sum(e.amount_minor for e in exposures)
        hedged = sum(self.hedge_service.covered_minor(e.id) for e in exposures)
        unhedged = max(0, gross - hedged)
        ratio_bp = round(hedged * 10_000 / gross) if gross > 0 else 0
        target_bp = self._target_bp(currency)
        target_minor = gross * target_bp // 10_000 if target_bp > 0 else 0
        gap = max(0, target_minor - hedged)
        return CurrencySummary(
            currency=currency,
            gross_minor=gross,
            hedged_minor=hedged,
            unhedged_minor=unhedged,
            hedge_ratio_bp=ratio_bp,
            gross_gbp_pence=gbp_equivalent_pence(currency, gross),
            unhedged_gbp_pence=gbp_equivalent_pence(currency, unhedged),
            target_cover_bp=target_bp,
            gap_to_target_minor=gap,
        )

    def by_bucket(self, currency: str) -> list[BucketRow]:
        rows: dict[str, BucketRow] = {
            key: BucketRow(
                bucket=key,
                label=label,
                forecast_minor=0,
                hedged_minor=0,
                unhedged_minor=0,
                forecast_gbp_pence=0,
                unhedged_gbp_pence=0,
            )
            for key, label, _ in BUCKETS
        }
        for exposure in self.hedge_service.exposures(currency):
            if exposure.status == "SETTLED" or exposure.direction != "RECEIVABLE":
                continue
            bucket = self._bucket_of(exposure.expected_date)
            row = rows[bucket]
            row.forecast_minor += exposure.amount_minor
            row.hedged_minor += self.hedge_service.covered_minor(exposure.id)
        for row in rows.values():
            row.unhedged_minor = max(0, row.forecast_minor - row.hedged_minor)
            row.forecast_gbp_pence = gbp_equivalent_pence(currency, row.forecast_minor)
            row.unhedged_gbp_pence = gbp_equivalent_pence(currency, row.unhedged_minor)
        return list(rows.values())

    def exposures(self, currency: str) -> list[ExposureRow]:
        out: list[ExposureRow] = []
        for exposure in self.hedge_service.exposures(currency):
            if exposure.direction != "RECEIVABLE":
                continue
            out.append(
                ExposureRow(
                    id=exposure.id,
                    expected_date=exposure.expected_date,
                    amount_minor=exposure.amount_minor,
                    direction=exposure.direction,
                    source=exposure.source,
                    source_reference=exposure.source_reference,
                    status=exposure.status,
                    hedged_minor=self.hedge_service.covered_minor(exposure.id),
                )
            )
        return out

    def _bucket_of(self, expected_date: str) -> str:
        days = (
            date.fromisoformat(expected_date) - date.fromisoformat(self.as_of_date)
        ).days
        for key, _label, ceiling in BUCKETS:
            if ceiling is not None and days <= ceiling:
                return key
        return "OVER_12M"

    def _target_bp(self, currency: str) -> int:
        policy = self.session.scalars(
            select(InvestmentPolicy)
            .where(InvestmentPolicy.tenant_id == self.tenant_id)
            .where(InvestmentPolicy.superseded_at.is_(None))
        ).one_or_none()
        if policy is None:
            return 0
        target = self.session.get(CurrencyCoverTarget, (policy.id, currency.upper()))
        return target.target_cover_bp if target else 0
