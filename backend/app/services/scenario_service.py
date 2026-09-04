"""What-if scenarios: deterministic re-runs against a temporary copy.

The rule of the whole system is that AI proposes and the deterministic core
disposes. This service is where that rule pays: every figure in a scenario
result is computed by the same code that computes today's figures, so a
number under "if" is the same shape as the number under "is". The model's
part is the paragraph that reads the two sets of numbers to a person.

Nothing here writes. Rating changes are applied inside a savepoint that is
rolled back at the end of the call; the "not rolled" and "cap change"
scenarios do not touch the database at all, because both are computable from
what is already there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import sterling
from app.models import Deal, PolicyVersion
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.services.retest_service import RetestService
from app.services.state_service import StateService


@dataclass
class ScenarioDelta:
    """The structured before-and-after a scenario produces.

    `changes` is the list a person or the model would want as bullets:
    concrete lines about what moved. `narrative` is the model's paragraph.

    Every figure named in `changes` has to appear in `before` or `after` or
    both; the model is prompted to quote only from the fields below it and
    to refuse to invent one.
    """

    scenario: str
    inputs: dict[str, Any]
    before: dict[str, Any]
    after: dict[str, Any]
    changes: list[str] = field(default_factory=list)
    narrative: str = ""


class ScenarioService:
    def __init__(
        self,
        session: Session,
        tenant_id: str,
        as_of_date: str,
        policy: PolicyVersion,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date
        self.policy = policy

    # ------------------------------------------------------------------
    # Scenario 1. A rating changes.
    # ------------------------------------------------------------------

    def rating_change(
        self, counterparty_id: str, new_rating: str, new_status: str = "STABLE"
    ) -> ScenarioDelta:
        """Applies the rating action in a savepoint, snapshots either side."""
        counterparty = cp_repo.get(self.session, counterparty_id)
        if counterparty is None or counterparty.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_FOUND)

        before = self._book_snapshot(counterparty_id)

        # A savepoint. Everything that follows is rolled back at the end so
        # a scenario never appears in the database, and the check runs and
        # breaches the retest would write live only for the duration of
        # this call.
        savepoint = self.session.begin_nested()
        try:
            retest = RetestService(
                self.session, self.tenant_id, self.as_of_date, self.policy
            )

            # A rating action writes rows with FKs to the users table. The
            # savepoint rolls those back, but the insert still validates the
            # FK, so the actor needs a real user_id. Any user does — nothing
            # here survives.
            from app.models import AppUser
            from sqlalchemy import select

            real_user_id = self.session.scalars(select(AppUser.id)).first()

            class _Actor:
                def __init__(self, user_id: str | None) -> None:
                    self.user_id = user_id

                def __str__(self) -> str:
                    return "What-if scenario"

            result = retest.apply_rating_action(
                counterparty_id=counterparty_id,
                new_rating=new_rating,
                new_status=new_status,
                recorded_by=_Actor(real_user_id),
                source="What-if scenario",
            )
            after = self._book_snapshot(counterparty_id)
            after["breaches_raised_by_scenario"] = result.breaches_raised
            after["positions_tested"] = result.positions_tested
        finally:
            savepoint.rollback()

        changes = self._describe_rating_change(before, after, new_rating)
        return ScenarioDelta(
            scenario="RATING_CHANGE",
            inputs={
                "counterparty_id": counterparty_id,
                "counterparty_name": counterparty.name,
                "new_rating": new_rating,
                "previous_rating": before["counterparty"]["rating"],
            },
            before=before,
            after=after,
            changes=changes,
        )

    # ------------------------------------------------------------------
    # Scenario 2. A deal is not rolled at maturity.
    # ------------------------------------------------------------------

    def not_rolled(self, deal_id: str) -> ScenarioDelta:
        """No write. The answer follows from the current book.

        On maturity day the principal and the accrued interest land in the
        operating account and stop consuming the counterparty's headroom. The
        scenario contrasts today's picture with that.
        """
        deal = deal_repo.get(self.session, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
        if deal.status not in ("ACTIVE", "MATURED"):
            raise TreasuryError(
                ErrorCode.DEAL_NOT_AMENDABLE,
                f"Only a live deal can be modelled. This one is {deal.status.lower()}.",
            )

        state = StateService(
            self.session,
            self.tenant_id,
            self.as_of_date,
            self.policy,
            tenant_name="",  # not read; scenarios never render the header
        )
        book = {row.counterparty_id: row for row in state.book()}
        row = book.get(deal.counterparty_id)
        if row is None:
            raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_FOUND)

        # The stored accrual and today's principal are what would land.
        from app.services.accrual_service import AccrualService

        _, interest = AccrualService(
            self.session, self.tenant_id, self.as_of_date
        ).summary_for_deal(deal_id)
        cash_arrives = deal.principal_pence + interest

        before = {
            "counterparty_name": row.name,
            "counterparty_used_pence": row.used_pence,
            "counterparty_limit_pence": row.limit_pence,
            "counterparty_headroom_pence": row.headroom_pence,
            "group_name": row.group_name,
            "group_used_pence": row.group_used_pence,
            "group_limit_pence": row.group_limit_pence,
            "uninvested_cash_pence": (state.calculator.uninvested_cash_pence() or 0),
            "portfolio_total_pence": (state.calculator.portfolio_total_pence() or 0),
        }

        # What the used figures look like the day after maturity, if the
        # cash stays in the operating account.
        cp_reduction = deal.principal_pence
        after = dict(before)
        after["counterparty_used_pence"] = max(0, row.used_pence - cp_reduction)
        after["counterparty_headroom_pence"] = (
            row.headroom_pence + cp_reduction if row.headroom_pence is not None else None
        )
        after["group_used_pence"] = max(0, row.group_used_pence - cp_reduction)
        after["uninvested_cash_pence"] = before["uninvested_cash_pence"] + cash_arrives
        # Portfolio total: live deals held at measured, so the maturing
        # deal was contributing `principal + interest`. That comes out of
        # the deals side and lands as cash, so the total is unchanged
        # except for the interest that stopped accruing.
        after["portfolio_total_pence"] = before["portfolio_total_pence"]

        # The daily income that stops.
        rate = deal.rate_bp / 10000
        daily_income_pence = int(round(deal.principal_pence * rate / 365))

        changes: list[str] = [
            f"{sterling(cash_arrives)} lands in the operating account "
            f"({sterling(deal.principal_pence)} principal, "
            f"{sterling(interest)} accrued).",
            f"{row.name} used drops by {sterling(deal.principal_pence)}, "
            f"headroom rises by the same.",
        ]
        if daily_income_pence > 0:
            changes.append(
                f"Roughly {sterling(daily_income_pence)} a day of interest "
                f"stops accruing."
            )

        return ScenarioDelta(
            scenario="NOT_ROLLED",
            inputs={
                "deal_id": deal_id,
                "counterparty_name": row.name,
                "principal_pence": deal.principal_pence,
                "rate_bp": deal.rate_bp,
                "maturity_date": deal.maturity_date,
            },
            before=before,
            after=after,
            changes=changes,
        )

    # ------------------------------------------------------------------
    # Scenario 3. The concentration cap changes.
    # ------------------------------------------------------------------

    def cap_change(self, new_cap_bp: int) -> ScenarioDelta:
        """No write. Which groups become breaches, and which clear."""
        if new_cap_bp <= 0 or new_cap_bp > 10000:
            raise TreasuryError(
                ErrorCode.LIMIT_REASON_REQUIRED,
                "A concentration cap has to be between 1 and 10,000 basis points.",
                field="new_cap_bp",
            )

        state = StateService(
            self.session,
            self.tenant_id,
            self.as_of_date,
            self.policy,
            tenant_name="",  # not read; scenarios never render the header
        )
        book = list(state.book())
        portfolio = (state.calculator.portfolio_total_pence() or 0)

        def concentration_bp(group_used: int) -> int:
            if portfolio <= 0:
                return 0
            return int(round((group_used * 10000) / portfolio))

        # Group by credit group.
        by_group: dict[str, dict[str, Any]] = {}
        for row in book:
            g = by_group.setdefault(
                row.group_id or row.counterparty_id,
                {
                    "name": row.group_name or row.name,
                    "used_pence": row.group_used_pence,
                    "share_bp": concentration_bp(row.group_used_pence),
                },
            )
            # `group_used_pence` is already the group total, so setting
            # again is idempotent.
            g["used_pence"] = row.group_used_pence
            g["share_bp"] = concentration_bp(row.group_used_pence)

        old_cap = self.policy.concentration_cap_bp
        before = {
            "cap_bp": old_cap,
            "portfolio_total_pence": portfolio,
            "groups": [
                {
                    **g,
                    "over_by_pence": max(0, g["used_pence"] - int(round(portfolio * old_cap / 10000))),
                    "breach": g["share_bp"] > old_cap,
                }
                for g in by_group.values()
            ],
        }
        after = {
            "cap_bp": new_cap_bp,
            "portfolio_total_pence": portfolio,
            "groups": [
                {
                    **g,
                    "over_by_pence": max(0, g["used_pence"] - int(round(portfolio * new_cap_bp / 10000))),
                    "breach": g["share_bp"] > new_cap_bp,
                }
                for g in by_group.values()
            ],
        }

        changes: list[str] = []
        for was, is_ in zip(before["groups"], after["groups"]):
            if was["breach"] and not is_["breach"]:
                changes.append(f"{was['name']} clears the cap.")
            elif not was["breach"] and is_["breach"]:
                changes.append(
                    f"{was['name']} becomes a breach, "
                    f"{sterling(is_['over_by_pence'])} over."
                )
            elif is_["breach"]:
                changes.append(
                    f"{was['name']} is still over the cap, now by "
                    f"{sterling(is_['over_by_pence'])} "
                    f"(was {sterling(was['over_by_pence'])})."
                )
        if not changes:
            changes.append("No group changes side of the cap.")

        return ScenarioDelta(
            scenario="CAP_CHANGE",
            # Formatted for the narrator. A cap of 5000bp is 50%, and the
            # model quotes what it is given verbatim, so if the input reads
            # "5000bp" the paragraph reads "5000bp".
            inputs={
                "new_cap": f"{new_cap_bp / 100:.2f}%",
                "previous_cap": f"{old_cap / 100:.2f}%",
            },
            before=before,
            after=after,
            changes=changes,
        )

    # ------------------------------------------------------------------
    # Shared: a small snapshot the rating scenario compares against.
    # ------------------------------------------------------------------

    def _book_snapshot(self, focus_cp_id: str) -> dict[str, Any]:
        state = StateService(
            self.session,
            self.tenant_id,
            self.as_of_date,
            self.policy,
            tenant_name="",  # not read; scenarios never render the header
        )
        book = list(state.book())
        focus = next((r for r in book if r.counterparty_id == focus_cp_id), None)
        breaches = list(state.breaches())
        return {
            "counterparty": {
                "id": focus_cp_id,
                "name": focus.name if focus else "",
                "rating": focus.rating if focus else "",
                "status": focus.status if focus else "",
                "limit_pence": focus.limit_pence if focus else None,
                "used_pence": focus.used_pence if focus else 0,
                "headroom_pence": focus.headroom_pence if focus else 0,
                "max_tenor_months": focus.max_tenor_months if focus else None,
            }
            if focus
            else None,
            "open_breach_count": len([b for b in breaches if b.status == "OPEN"]),
            "portfolio_total_pence": (state.calculator.portfolio_total_pence() or 0),
        }

    # ------------------------------------------------------------------
    # Change-description helpers.
    # ------------------------------------------------------------------

    @staticmethod
    def _describe_rating_change(
        before: dict[str, Any], after: dict[str, Any], new_rating: str
    ) -> list[str]:
        changes: list[str] = []
        b = before.get("counterparty") or {}
        a = after.get("counterparty") or {}
        if b.get("rating") != a.get("rating"):
            changes.append(
                f"{b.get('name', 'the counterparty')} moves from "
                f"{b.get('rating')} to {a.get('rating')}."
            )
        if b.get("limit_pence") != a.get("limit_pence"):
            direction = "tightens" if (a.get("limit_pence") or 0) < (b.get("limit_pence") or 0) else "widens"
            changes.append(
                f"Its limit {direction} to {sterling(a.get('limit_pence') or 0)} "
                f"(was {sterling(b.get('limit_pence') or 0)})."
            )
        raised = after.get("breaches_raised_by_scenario", 0)
        if raised == 1:
            changes.append("One position becomes a breach.")
        elif raised > 1:
            changes.append(f"{raised} positions become breaches.")
        else:
            changes.append("No new breach is raised.")

        b_open = before.get("open_breach_count", 0)
        a_open = after.get("open_breach_count", 0)
        if a_open != b_open:
            changes.append(
                f"Open breaches on the book move from {b_open} to {a_open}."
            )
        return changes
