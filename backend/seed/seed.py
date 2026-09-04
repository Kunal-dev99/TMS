"""Load the seeded book.

Reads app.seed_data, which the mock server's fixtures also read, so the two
cannot disagree about a figure.

Run it directly:
    python -m seed.seed

The book it produces has to open with nothing in breach. The one thing that
makes that true is the manual limit on Northern Treasury Services Ltd, which
sits above its A- band ceiling. Remove it and an 18,119,836 position is
immediately outside its own limit.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app import seed_data as s
from app.db import SessionLocal
from app.ids import new_id
from app.models import (
    AppUser,
    Confirmation,
    Counterparty,
    CurrencyCoverTarget,
    ForecastLine,
    InvestmentPolicy,
    LadderTarget,
    CounterpartyInstrument,
    CpGroup,
    CpLimit,
    Deal,
    OracleBalance,
    NewsItem,
    PolicyVersion,
    RatingBand,
    SystemClock,
    Tenant,
)
from app.models import Membership, PHASE_ONE_TABLES
from app.security import hash_password

NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clear(session: Session) -> None:
    """Nothing is deleted in the running system. A reseed is not the system."""
    for model in reversed(PHASE_ONE_TABLES):
        session.query(model).delete()
    session.flush()


def load(session: Session) -> None:
    # Flushed one stage at a time. There are no ORM relationships on these
    # models, only foreign keys on the tables, so the unit of work has nothing
    # to order the inserts by and would otherwise write a child before its
    # parent.
    session.add(Tenant(id=s.TENANT_ID, name=s.TENANT_NAME, created_at=NOW))
    session.flush()

    session.add(
        SystemClock(tenant_id=s.TENANT_ID, today_date=s.CLOCK_DATE, updated_at=NOW)
    )

    # People before anything else, because every evidence record below names
    # one of them.
    for person in s.USERS:
        session.add(
            AppUser(
                id=person["id"],
                tenant_id=s.TENANT_ID,
                email=person["email"],
                display_name=person["display_name"],
                password_hash=hash_password(s.DEMO_PASSWORD),
                status="ACTIVE",
                created_at=NOW,
            )
        )
    session.flush()
    for person in s.USERS:
        for role in person["roles"]:
            session.add(
                Membership(
                    id=new_id("mem"),
                    tenant_id=s.TENANT_ID,
                    user_id=person["id"],
                    role=role,
                    granted_by="Seed",
                    granted_at=NOW,
                )
            )
    session.flush()
    session.add(PolicyVersion(**s.POLICY_VERSION))
    session.flush()

    for band_id, rating, ordinal, max_limit, max_tenor in s.RATING_BANDS:
        session.add(
            RatingBand(
                id=band_id,
                tenant_id=s.TENANT_ID,
                rating=rating,
                ordinal=ordinal,
                max_limit_pence=max_limit,
                max_tenor_months=max_tenor,
            )
        )

    session.flush()

    for group_id, name, group_limit in s.CP_GROUPS:
        session.add(
            CpGroup(
                id=group_id,
                tenant_id=s.TENANT_ID,
                name=name,
                group_limit_pence=group_limit,
            )
        )

    session.flush()

    for cp in s.COUNTERPARTIES:
        session.add(
            Counterparty(
                id=cp["id"],
                tenant_id=s.TENANT_ID,
                group_id=cp["group_id"],
                name=cp["name"],
                legal_entity_identifier=cp["lei"],
                group_parent_name=cp["group_parent"],
                country=cp["country"],
                rating=cp["rating"],
                rating_status=cp["rating_status"],
                status=cp["status"],
                created_by="A. Whitfield",
                created_by_user_id="usr_whitfield",
                created_at=NOW,
                verified_by="A. Whitfield",
                verified_at=NOW,
                approved_by="M. Doran",
                approved_at=NOW,
                activated_by_user_id="usr_doran",
                activated_at=NOW,
            )
        )
        for instrument in cp["instruments"]:
            session.add(
                CounterpartyInstrument(
                    id=f"cpi_{cp['id'][3:]}_{instrument.lower()}",
                    tenant_id=s.TENANT_ID,
                    counterparty_id=cp["id"],
                    instrument=instrument,
                    enabled=1,
                )
            )

    session.flush()

    for limit in s.CP_LIMITS:
        session.add(
            CpLimit(
                id=limit["id"],
                tenant_id=s.TENANT_ID,
                counterparty_id=limit["counterparty_id"],
                amount_pence=limit["amount_pence"],
                max_tenor_months=limit["max_tenor_months"],
                source=limit["source"],
                effective_from=limit["effective_from"],
                superseded_at=None,
                reason=limit["reason"],
                approved_by=limit["approved_by"],
                recorded_by_user_id="usr_whitfield",
                approved_at=limit["effective_from"],
            )
        )

    session.flush()

    for deal in s.DEALS:
        session.add(
            Deal(
                id=deal["id"],
                tenant_id=s.TENANT_ID,
                counterparty_id=deal["counterparty_id"],
                instrument=deal["instrument"],
                principal_pence=deal["principal_pence"],
                currency=deal["currency"],
                rate_bp=deal["rate_bp"],
                tenor_months=deal["tenor_months"],
                trade_date=deal["trade_date"],
                value_date=deal["value_date"],
                maturity_date=deal["maturity_date"],
                status=deal["status"],
                capture_source=deal["capture_source"],
                created_by=deal["created_by"],
                created_by_user_id="usr_whitfield",
                created_at=deal["trade_date"],
                required_approver=deal["required_approver"],
                approved_by=deal["approved_by"],
                approved_by_user_id="usr_doran",
                approved_role=deal["required_approver"],
                approved_at=deal["trade_date"],
                limit_id_at_booking=deal["limit_id_at_booking"],
                policy_version_id=s.POLICY_VERSION["id"],
                check_run_id=None,
            )
        )

    session.flush()

    # Phase 3. The confirmations that have already arrived. Both agree with
    # what was keyed, so both are matched and neither raises a queue item.
    deals_by_id = {deal["id"]: deal for deal in s.DEALS}
    for confirmation in s.CONFIRMATIONS:
        deal = deals_by_id[confirmation["deal_id"]]
        session.add(
            Confirmation(
                id=confirmation["id"],
                tenant_id=s.TENANT_ID,
                deal_id=deal["id"],
                counterparty_id=confirmation["counterparty_id"],
                message_type=confirmation["message_type"],
                reference=confirmation["reference"],
                instrument=deal["instrument"],
                principal_pence=deal["principal_pence"],
                rate_bp=deal["rate_bp"],
                value_date=deal["value_date"],
                maturity_date=deal["maturity_date"],
                received_at=NOW,
                match_status="MATCHED",
                matched_at=NOW,
                raw_payload=None,
            )
        )

    session.flush()

    # Phase 2. The policy the advisory layer measures a gap against, and the
    # forecast it reads.
    session.add(
        InvestmentPolicy(
            id=s.INVESTMENT_POLICY["id"],
            tenant_id=s.TENANT_ID,
            effective_from=s.POLICY_VERSION["effective_from"],
            superseded_at=None,
            liquidity_buffer_pence=s.INVESTMENT_POLICY["liquidity_buffer_pence"],
            buffer_horizon_days=s.INVESTMENT_POLICY["buffer_horizon_days"],
            priority_order=s.INVESTMENT_POLICY["priority_order"],
            model_enabled=s.INVESTMENT_POLICY["model_enabled"],
            approved_by=s.INVESTMENT_POLICY["approved_by"],
            recorded_by_user_id="usr_sethi",
        )
    )
    session.flush()

    for bucket, share_bp, minimum in s.LADDER_TARGETS:
        session.add(
            LadderTarget(
                policy_id=s.INVESTMENT_POLICY["id"],
                bucket=bucket,
                target_share_bp=share_bp,
                minimum_pence=minimum,
            )
        )
    for currency, cover_bp, horizon in s.CURRENCY_COVER_TARGETS:
        session.add(
            CurrencyCoverTarget(
                policy_id=s.INVESTMENT_POLICY["id"],
                currency=currency,
                target_cover_bp=cover_bp,
                horizon_days=horizon,
            )
        )

    for line in s.FORECAST_LINES:
        session.add(
            ForecastLine(
                id=line["id"],
                tenant_id=s.TENANT_ID,
                as_of=line["as_of"],
                forecast_date=line["forecast_date"],
                currency=line["currency"],
                amount_minor=line["amount_minor"],
                entity=line["entity"],
                received_at=NOW,
            )
        )

    session.flush()

    for balance in s.ORACLE_BALANCES:
        session.add(
            OracleBalance(
                id=balance["id"],
                tenant_id=s.TENANT_ID,
                account_name=balance["account_name"],
                balance_pence=balance["balance_pence"],
                as_of_date=balance["as_of_date"],
                received_at=NOW,
            )
        )


    # News items — one prototype substitute for a live newswire, so the
    # credit-signal scanner has something to read on open. Assumption 48
    # covers why this is seeded rather than fed live.
    for item in getattr(s, "NEWS_ITEMS", []):
        session.add(
            NewsItem(
                id=item["id"],
                tenant_id=s.TENANT_ID,
                counterparty_id=item["counterparty_id"],
                source=item["source"],
                headline=item["headline"],
                body=item["body"],
                published_at=item["published_at"],
                ingested_at=NOW,
            )
        )


def run() -> None:
    session = SessionLocal()
    try:
        clear(session)
        load(session)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    run()
    print(
        f"Seeded {len(s.COUNTERPARTIES)} counterparties, "
        f"{len(s.DEALS)} live deals, clock at {s.CLOCK_DATE}."
    )
