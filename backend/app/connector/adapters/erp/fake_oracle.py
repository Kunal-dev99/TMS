"""ERPPort implementation backed by the seed rows already in the DB.

Reads ``currency_exposure`` and returns it as ``ExposureSnapshot``.
Journal posting writes to an in-memory list and returns a synthetic
ack — the point in Stage 1 is that the port surface exists; real
persistence + Oracle Fusion Cloud land in Stage 7.

When Oracle Fusion adapter is bound, callers see the same
``ExposureSnapshot`` / ``JournalAck`` shapes. This adapter never
disappears — tests use it forever.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.connector.ports import (
    BankStatement,
    ExposureSnapshot,
    JournalAck,
    JournalEntry,
)


class FakeOracle:
    name = "fake_oracle"

    def __init__(self) -> None:
        # Journal entries we've "posted" — inspectable by tests.
        self.posted: list[JournalEntry] = []
        # external_reference -> ledger_journal_id. Idempotency store,
        # mirrors Oracle's own uniqueness on ExternalReference.
        self._acks: dict[str, str] = {}

    def pull_exposure(
        self,
        tenant_id: str,
        legal_entity_id: str,
        as_of: date,
        currency: str = "EUR",
    ) -> ExposureSnapshot:
        """Aggregate today's ``currency_exposure`` rows into one snapshot.

        The real Oracle adapter returns one snapshot per (LE, currency);
        this fake mirrors that shape by aggregating our per-obligation
        rows. Zero snapshot if nothing matches.
        """
        from sqlalchemy import func, select

        from app.db import SessionLocal
        from app.models import CurrencyExposure

        with SessionLocal() as session:
            stmt = (
                select(CurrencyExposure.direction, func.sum(CurrencyExposure.amount_minor))
                .where(
                    CurrencyExposure.tenant_id == tenant_id,
                    CurrencyExposure.currency == currency.upper(),
                    CurrencyExposure.legal_entity_id == legal_entity_id,
                )
                .group_by(CurrencyExposure.direction)
            )
            totals = dict(session.execute(stmt).all())

        return ExposureSnapshot(
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            currency=currency.upper(),
            gross_receivable_pence=int(totals.get("RECEIVABLE", 0) or 0),
            gross_payable_pence=int(totals.get("PAYABLE", 0) or 0),
            forecast_pence=0,  # No forecast source in Phase 1; Stage 7 adds EPM.
            as_of_date=as_of.isoformat(),
            source="fake_oracle",
        )

    def pull_bank_statement(
        self, account_id: str, as_of: date
    ) -> BankStatement | None:
        # No cash_balance table yet — Stage 5. Return None so a caller
        # that already handles 'no statement today' keeps working.
        return None

    def post_journal(self, entry: JournalEntry) -> JournalAck:
        # Idempotency by external_reference — matches Oracle's behaviour.
        ext = entry.external_reference
        if ext in self._acks:
            return JournalAck(
                external_reference=ext,
                ledger_journal_id=self._acks[ext],
                posted_at=_now_iso(),
            )
        self.posted.append(entry)
        journal_id = f"fake-{uuid.uuid4().hex[:12]}"
        self._acks[ext] = journal_id
        return JournalAck(
            external_reference=ext,
            ledger_journal_id=journal_id,
            posted_at=_now_iso(),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
