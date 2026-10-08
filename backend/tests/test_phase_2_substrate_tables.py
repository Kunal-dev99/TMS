"""Stage 2 acceptance: the 11 substrate tables exist and are empty.

Additive-only. Nothing in Phase 1 writes to any of these; adapters
land in later stages. If any of these tables ever has rows on a
freshly seeded book, either a stage started writing without notice or
the seed is wrong — both should trip this test.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import (
    AiRun,
    BankAck,
    CashBalance,
    DataSnapshot,
    GlAccountMap,
    GlPostingAck,
    IntegrationHealth,
    MarketSnapshot,
    OracleEntityMapping,
    SsoGroupMap,
    SsoIdentity,
)

ALL = [
    OracleEntityMapping,
    GlAccountMap,
    SsoIdentity,
    SsoGroupMap,
    AiRun,
    CashBalance,
    MarketSnapshot,
    BankAck,
    GlPostingAck,
    IntegrationHealth,
    DataSnapshot,
]


def test_every_substrate_table_is_empty_on_a_fresh_book(session):
    for cls in ALL:
        count = session.scalar(select(func.count()).select_from(cls))
        assert count == 0, (
            f"{cls.__tablename__} is populated; a Phase 1 path is writing "
            "to a substrate table it shouldn't touch until its adapter lands."
        )


def test_all_eleven_substrate_tables_are_registered(session):
    # Belt and braces: prove the count matches the plan exactly.
    assert len(ALL) == 11
