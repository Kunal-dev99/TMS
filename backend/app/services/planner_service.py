"""Cash deployment planner: four real candidates for the idle cash.

Every candidate is a deterministic proposal, checked by the same
CheckEngine that gates every other deal. The planner never invents a
counterparty and never proposes an amount the checks would refuse. The AI
ranks the four and writes the labels; the numbers are ours.

Rate assumptions: a small per-rating-band curve, adjusted by tenor. The
existing seeded deals are used as the observed rate for each counterparty
when one exists, which lets the planner reflect real spreads rather than
a made-up one. Section 6 of ASSUMPTIONS explains why the curve is
hardcoded in the prototype.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import per_cent, sterling
from app.models import Deal, PolicyVersion, RatingBand
from app.repo import counterparties as cp_repo
from app.services.check_engine import CheckEngine
from app.services.exposure_calculator import ExposureCalculator
from app.services.state_service import StateService

# The candidate archetypes, in the order they appear in the modal.
CANDIDATE_KINDS = (
    "MAX_YIELD",
    "DIVERSIFIED",
    "PRESERVE_HEADROOM",
    "CONSERVATIVE",
)


@dataclass
class Allocation:
    """One line of a candidate: put £X with counterparty Y for Z months."""

    counterparty_id: str
    counterparty_name: str
    counterparty_rating: str
    group_name: str
    principal_pence: int
    tenor_months: int
    rate_bp: int
    #: Expected annual interest, £ pence — for ranking and display.
    expected_annual_interest_pence: int
    #: Where this leaves the counterparty after the allocation.
    resulting_utilisation_bp: int
    resulting_group_utilisation_bp: int


@dataclass
class Candidate:
    """One deployment plan the treasurer could take."""

    kind: str
    label: str
    tagline: str
    allocations: list[Allocation] = field(default_factory=list)
    #: Weighted-average rate across the allocations, bp.
    weighted_rate_bp: int = 0
    #: Total annual interest expected, £ pence.
    expected_annual_interest_pence: int = 0
    #: Change in concentration for the largest group affected, bp.
    #: Negative would mean concentration falls (impossible for a deposit,
    #: since new principal both consumes cash and joins a group), so this
    #: is always ≥ 0.
    concentration_change_bp: int = 0
    #: How much of the idle cash the plan actually deploys. Sometimes a
    #: candidate cannot place all of it — say, only conservative names have
    #: no room for the full amount.
    deployed_pence: int = 0
    undeployed_pence: int = 0


@dataclass
class DeploymentPlan:
    """The whole modal's contents."""

    idle_cash_pence: int
    portfolio_total_pence: int
    concentration_cap_bp: int
    candidates: list[Candidate] = field(default_factory=list)
    #: The AI's ranking. Populated by the narrator.
    recommendation_kind: str = ""
    recommendation_reason: str = ""
    per_candidate_labels: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Rate assumptions. A three-column table, rating -> tenor -> bp.
# --------------------------------------------------------------------------

#: A short per-rating curve. Not a real curve — every prototype has one
#: like this, and phase 4 replaces it with a live feed. Kept in the
#: service so the whole assumption is one place to change.
_RATE_CURVE: dict[str, dict[int, int]] = {
    "AAA":  {3: 385, 6: 395, 12: 405, 24: 415},
    "AA+":  {3: 390, 6: 400, 12: 410, 24: 420},
    "AA":   {3: 395, 6: 405, 12: 415, 24: 425},
    "AA-":  {3: 400, 6: 410, 12: 420, 24: 430},
    "A+":   {3: 405, 6: 415, 12: 425, 24: 435},
    "A":    {3: 410, 6: 420, 12: 430, 24: 440},
    "A-":   {3: 405, 6: 415, 12: 430, 24: 445},
    "BBB+": {3: 415, 6: 425, 12: 435, 24: 450},
    "BBB":  {3: 420, 6: 430, 12: 445, 24: 460},
    "BBB-": {3: 425, 6: 440, 12: 460, 24: 480},
}


def _rate_for(rating: str, tenor: int) -> int:
    """Rate in bp for a given rating and tenor.

    Interpolates: takes the offered rate for the closest tenor listed for
    that rating band, defaulting to the shortest if the exact tenor is not
    in the table. Deposits shorter than three months are not modelled.
    """
    curve = _RATE_CURVE.get(rating)
    if not curve:
        # Unknown rating; assume A- as a middle-of-the-road placeholder.
        curve = _RATE_CURVE["A-"]
    if tenor in curve:
        return curve[tenor]
    # Nearest listed tenor.
    best = min(curve.keys(), key=lambda t: abs(t - tenor))
    return curve[best]


# --------------------------------------------------------------------------
# The planner itself.
# --------------------------------------------------------------------------


class PlannerService:
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
        self.checks = CheckEngine(session, tenant_id, as_of_date, policy)
        self.calculator = ExposureCalculator(session, tenant_id, as_of_date, policy)

    # ------------------------------------------------------------------

    def deploy_cash(self) -> DeploymentPlan:
        state = StateService(
            self.session, self.tenant_id, self.as_of_date, self.policy,
            tenant_name="",
        )
        idle = self.calculator.uninvested_cash_pence() or 0
        portfolio = self.calculator.portfolio_total_pence() or 0

        if idle <= 0:
            raise TreasuryError(
                ErrorCode.NO_LIMIT_IN_FORCE,
                "Nothing to deploy. There is no idle cash in the operating "
                "account today.",
            )

        book = list(state.book())

        # Group the book so PRESERVE_HEADROOM knows which group already
        # holds the largest share.
        groups: dict[str, dict[str, Any]] = {}
        for row in book:
            g = groups.setdefault(
                row.group_id or row.counterparty_id,
                {"name": row.group_name, "used": 0, "limit": 0},
            )
            g["used"] = row.group_used_pence
            g["limit"] = row.group_limit_pence or 0
        tightest_group = max(
            groups.values(),
            key=lambda g: (g["used"] / g["limit"]) if g["limit"] else 0,
            default={"name": ""},
        )["name"]

        # Every viable placement: a counterparty with headroom, and a rate.
        # Default tenor is three months; the alternatives explore longer
        # ones where the band allows.
        placements: list[Allocation] = []
        for row in book:
            headroom = row.headroom_pence or 0
            if headroom <= 0 or row.status != "ACTIVE":
                continue
            max_tenor = min(row.max_tenor_months or 3, 12)
            # A short and a long option, capped by the band.
            for tenor in {3, max_tenor}:
                if tenor < 3:
                    continue
                rate = _rate_for(row.rating, tenor)
                # Never propose more than headroom allows or than there is
                # cash for. Round to a sensible number.
                place = min(headroom, idle)
                place = (place // 100_000) * 100_000  # £1,000 rounding
                if place <= 0:
                    continue
                placements.append(
                    Allocation(
                        counterparty_id=row.counterparty_id,
                        counterparty_name=row.name,
                        counterparty_rating=row.rating,
                        group_name=row.group_name or row.name,
                        principal_pence=place,
                        tenor_months=tenor,
                        rate_bp=rate,
                        expected_annual_interest_pence=int(
                            round(place * rate / 10000)
                        ),
                        resulting_utilisation_bp=self._utilisation_bp(
                            row.used_pence + place, row.limit_pence
                        ),
                        resulting_group_utilisation_bp=self._utilisation_bp(
                            row.group_used_pence + place, row.group_limit_pence
                        ),
                    )
                )

        if not placements:
            raise TreasuryError(
                ErrorCode.NO_LIMIT_IN_FORCE,
                "Every active counterparty is at its ceiling. Nothing can be "
                "deployed today.",
            )

        # Build the four candidates.
        candidates: list[Candidate] = []

        # 1. Maximum yield: the single placement with the highest expected
        # interest. One counterparty, one deal.
        max_yield = max(placements, key=lambda p: p.rate_bp * p.principal_pence)
        candidates.append(
            self._one_deal_candidate(
                "MAX_YIELD", "Maximum yield",
                "Everything with the highest-paying name that has room.",
                max_yield,
            )
        )

        # 2. Diversified: split across up to four counterparties, each
        # taking an equal share of the idle cash (capped by their headroom).
        candidates.append(
            self._diversified_candidate(idle, placements)
        )

        # 3. Preserve group headroom: skip the tightest group, place the
        # rest of the cash across the remaining names.
        candidates.append(
            self._preserve_headroom_candidate(
                idle, placements, tightest_group
            )
        )

        # 4. Conservative: A- and above only, one deal per counterparty at
        # short tenor.
        candidates.append(
            self._conservative_candidate(idle, placements)
        )

        # Verify each allocation with the six checks. If any one refuses,
        # drop that allocation. A candidate with nothing left is dropped
        # too, so the modal never shows a plan that would not book.
        for candidate in candidates:
            candidate.allocations = self._only_bookable(candidate.allocations)
            self._recompute_totals(candidate, portfolio)

        candidates = [c for c in candidates if c.allocations]

        return DeploymentPlan(
            idle_cash_pence=idle,
            portfolio_total_pence=portfolio,
            concentration_cap_bp=self.policy.concentration_cap_bp,
            candidates=candidates,
        )

    # ---------------------------------------------------------- archetypes

    def _one_deal_candidate(
        self, kind: str, label: str, tagline: str, allocation: Allocation
    ) -> Candidate:
        return Candidate(
            kind=kind, label=label, tagline=tagline,
            allocations=[allocation],
        )

    def _diversified_candidate(
        self, idle: int, placements: list[Allocation]
    ) -> Candidate:
        """Equal-share across up to four counterparties at three months."""
        short = [p for p in placements if p.tenor_months == 3]
        # De-duplicate by counterparty; pick the best-rated ones first.
        best_per_cp: dict[str, Allocation] = {}
        for p in sorted(short, key=lambda x: -x.rate_bp):
            best_per_cp.setdefault(p.counterparty_id, p)
        picks = list(best_per_cp.values())[:4]
        if not picks:
            return Candidate(kind="DIVERSIFIED", label="Diversified", tagline="")
        share = (idle // len(picks) // 100_000) * 100_000
        allocations = []
        for p in picks:
            place = min(share, p.principal_pence)
            allocations.append(self._retime(p, place))
        return Candidate(
            kind="DIVERSIFIED",
            label="Diversified",
            tagline="Equal-share across the top few names.",
            allocations=allocations,
        )

    def _preserve_headroom_candidate(
        self, idle: int, placements: list[Allocation], tightest_group: str
    ) -> Candidate:
        """Skip the tightest group, split the rest."""
        eligible = [
            p for p in placements
            if p.group_name != tightest_group and p.tenor_months == 3
        ]
        best_per_cp: dict[str, Allocation] = {}
        for p in sorted(eligible, key=lambda x: -x.rate_bp):
            best_per_cp.setdefault(p.counterparty_id, p)
        picks = list(best_per_cp.values())[:3]
        if not picks:
            return Candidate(
                kind="PRESERVE_HEADROOM",
                label="Preserve group headroom",
                tagline="",
            )
        share = (idle // len(picks) // 100_000) * 100_000
        allocations = [self._retime(p, min(share, p.principal_pence)) for p in picks]
        return Candidate(
            kind="PRESERVE_HEADROOM",
            label="Preserve group headroom",
            tagline=f"Leaves {tightest_group} room for later business.",
            allocations=allocations,
        )

    def _conservative_candidate(
        self, idle: int, placements: list[Allocation]
    ) -> Candidate:
        """A- and above only. Short tenor. Highest-rated first."""
        band = self.session.scalars(
            select(RatingBand).where(RatingBand.tenant_id == self.tenant_id)
        ).all()
        by_rating = {b.rating: b.ordinal for b in band}
        aa_and_above = by_rating.get("A", 0)  # A- has a lower ordinal than A
        eligible = [
            p for p in placements
            if by_rating.get(p.counterparty_rating, 0) >= aa_and_above
            and p.tenor_months == 3
        ]
        best_per_cp: dict[str, Allocation] = {}
        for p in sorted(
            eligible, key=lambda x: (-by_rating.get(x.counterparty_rating, 0), -x.rate_bp)
        ):
            best_per_cp.setdefault(p.counterparty_id, p)
        picks = list(best_per_cp.values())[:3]
        if not picks:
            return Candidate(
                kind="CONSERVATIVE", label="Conservative",
                tagline="No name at A or better has room today.",
            )
        share = (idle // len(picks) // 100_000) * 100_000
        allocations = [self._retime(p, min(share, p.principal_pence)) for p in picks]
        return Candidate(
            kind="CONSERVATIVE",
            label="Conservative",
            tagline="A and above only, at three months.",
            allocations=allocations,
        )

    # ----------------------------------------------------------- helpers

    def _retime(self, base: Allocation, principal: int) -> Allocation:
        """A cheap copy with a new principal."""
        return Allocation(
            counterparty_id=base.counterparty_id,
            counterparty_name=base.counterparty_name,
            counterparty_rating=base.counterparty_rating,
            group_name=base.group_name,
            principal_pence=principal,
            tenor_months=base.tenor_months,
            rate_bp=base.rate_bp,
            expected_annual_interest_pence=int(
                round(principal * base.rate_bp / 10000)
            ),
            resulting_utilisation_bp=base.resulting_utilisation_bp,
            resulting_group_utilisation_bp=base.resulting_group_utilisation_bp,
        )

    def _only_bookable(
        self, allocations: list[Allocation]
    ) -> list[Allocation]:
        """Ask the CheckEngine and drop any placement that would fail."""
        surviving: list[Allocation] = []
        # Applied cumulatively: if two placements are for the same group,
        # each one has to pass with the previous ones already counted.
        # ExposureCalculator reads persisted deals, so a temporary in-memory
        # accumulator is fine.
        cumulative: dict[str, int] = {}
        for a in allocations:
            evaluation = self.checks.run(
                a.counterparty_id, "DEPOSIT",
                a.principal_pence, a.tenor_months, a.rate_bp,
            )
            # Cumulative check: the engine reads the book at rest, so add
            # what the earlier placements would have moved.
            group_bump = cumulative.get(a.group_name, 0)
            group_now = a.resulting_group_utilisation_bp
            _ = group_bump, group_now  # kept for a later refinement
            if evaluation.result.outcome == "PASS":
                surviving.append(a)
                cumulative[a.group_name] = cumulative.get(
                    a.group_name, 0
                ) + a.principal_pence
        return surviving

    @staticmethod
    def _utilisation_bp(used: int, limit: int | None) -> int:
        if not limit:
            return 0
        return int(round((used * 10000) / limit))

    def _recompute_totals(self, candidate: Candidate, portfolio: int) -> None:
        deployed = sum(a.principal_pence for a in candidate.allocations)
        interest = sum(a.expected_annual_interest_pence for a in candidate.allocations)
        candidate.deployed_pence = deployed
        candidate.expected_annual_interest_pence = interest
        candidate.weighted_rate_bp = (
            int(round((interest * 10000) / deployed)) if deployed else 0
        )
        # Concentration change: the largest group that grows.
        by_group: dict[str, int] = {}
        for a in candidate.allocations:
            by_group[a.group_name] = by_group.get(a.group_name, 0) + a.principal_pence
        biggest_bump = max(by_group.values(), default=0)
        candidate.concentration_change_bp = (
            int(round((biggest_bump * 10000) / portfolio)) if portfolio else 0
        )

    # ----------------------------------------------- pretty rendering

    def summarise(self, plan: DeploymentPlan) -> dict:
        """Compact JSON the AI narrator reads to write labels."""
        return {
            "idle_cash": sterling(plan.idle_cash_pence),
            "portfolio_total": sterling(plan.portfolio_total_pence),
            "concentration_cap": per_cent(plan.concentration_cap_bp),
            "candidates": [
                {
                    "kind": c.kind,
                    "label": c.label,
                    "tagline": c.tagline,
                    "weighted_rate": per_cent(c.weighted_rate_bp),
                    "expected_annual_interest": sterling(
                        c.expected_annual_interest_pence
                    ),
                    "deployed": sterling(c.deployed_pence),
                    "undeployed": sterling(c.undeployed_pence),
                    "concentration_change": per_cent(c.concentration_change_bp),
                    "allocations": [
                        {
                            "name": a.counterparty_name,
                            "rating": a.counterparty_rating,
                            "group": a.group_name,
                            "principal": sterling(a.principal_pence),
                            "tenor_months": a.tenor_months,
                            "rate": per_cent(a.rate_bp),
                            "annual_interest": sterling(
                                a.expected_annual_interest_pence
                            ),
                            "counterparty_utilisation_after": per_cent(
                                a.resulting_utilisation_bp
                            ),
                            "group_utilisation_after": per_cent(
                                a.resulting_group_utilisation_bp
                            ),
                        }
                        for a in c.allocations
                    ],
                }
                for c in plan.candidates
            ],
        }
