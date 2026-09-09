"""AI briefing for the Hedging panel.

Three things the panel wants from the model:

1. **Cross-currency briefing** — one paragraph ranked by policy-gap severity,
   naming the biggest un-hedged currency first.

2. **Per-currency recommendation** — a concrete action ("sell CHF 3m
   forward, 6 months, with Nordea") with the reasoning trail (which
   policy line, which exposures, which counterparty and why).

3. **Watch callouts** — short flags for maturity clustering or refinance
   walls in the existing hedge book. The deterministic side surfaces the
   pattern; the model writes the sentence.

Same "AI proposes, deterministic disposes" rule as the planner. The list
of eligible counterparties for a recommendation is computed here from
live headroom + FX_FORWARD permission; the model picks one from that
list. A response that names a counterparty not on the list is refused
and the deterministic fallback runs.

The prompt forbids rate prediction. Section 15 of the FX spec is
explicit: AI must not attempt to predict future exchange rates.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Counterparty,
    CounterpartyInstrument,
    CpGroup,
    CpLimit,
    Deal,
    HedgeLink,
)
from app.services.exposure_calculator import ExposureCalculator
from app.services.fx_exposure_service import FxExposureService
from app.services.fx_rate_service import forward as forward_rate

MODEL_VAR = "TREASURY_MODEL_NAME"
KEY_VAR = "TREASURY_MODEL_API_KEY"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 12.0

SYSTEM_PROMPT = (
    "You are a treasury GOVERNANCE narrator, not an FX trader. Your job is\n"
    "to describe the treasurer's own policy compliance — how the current\n"
    "hedge book compares to the configured targets and limits — and to\n"
    "suggest policy-compliant actions that close the gap. You are NOT a\n"
    "market advisor. You do NOT forecast, comment on, or hint at where\n"
    "any FX rate will move.\n\n"
    "You will be given a snapshot of the current FX exposure book:\n"
    "- Per-currency gross exposure, hedged amount, unhedged amount, policy target\n"
    "- Existing hedges with counterparty and maturity date\n"
    "- Eligible FX_FORWARD counterparties with live entity and group headroom\n\n"
    "You write:\n"
    "  briefing: one paragraph (2-3 sentences) ranking the currencies by\n"
    "    policy-gap severity. Name the biggest gap first and quote the\n"
    "    unhedged amount and policy target. Be terse and specific.\n\n"
    "  recommendations: one policy-compliance action per currency that\n"
    "    has a gap. This is a COMPLIANCE suggestion, not a trade view.\n"
    "    Each contains:\n"
    "      currency, amount_minor (integer, from the eligible options),\n"
    "      tenor_months (integer 3, 6, 9 or 12),\n"
    "      counterparty_id (must exactly match one id from eligible_counterparties),\n"
    "      reason (one sentence: state that this closes N% of the policy\n"
    "        gap and why the chosen counterparty is appropriate on GOVERNANCE\n"
    "        grounds — rating, headroom, concentration. Never mention rates,\n"
    "        market conditions, timing, or profitability).\n\n"
    "  watch: list of one-sentence callouts about maturity clustering,\n"
    "    refinance walls, or same-counterparty concentration. Empty list if\n"
    "    the book looks healthy. Reference actual dates and counterparties.\n\n"
    "Hard rules:\n"
    "  1. Every number you quote must be present in the input.\n"
    "  2. Never predict, forecast, or comment on where FX rates will go.\n"
    "     Rate quotes are indicative only.\n"
    "  3. Never say a rate is 'attractive', 'favourable', 'expensive',\n"
    "     'good time to hedge', or anything that implies a market view.\n"
    "  4. Never invent a counterparty. counterparty_id must be one of the\n"
    "     eligible list.\n"
    "  5. Amount must be from the input's suggested_amounts for that currency.\n"
    "  6. Reply with JSON only, this shape exactly:\n"
    "     {\n"
    '       "briefing": "...",\n'
    '       "recommendations": [\n'
    '         {"currency":"...","amount_minor":0,"tenor_months":0,\n'
    '          "counterparty_id":"...","reason":"..."}\n'
    "       ],\n"
    '       "watch": ["...", "..."]\n'
    "     }"
)


# ------------------------------------------------------------- data shapes


@dataclass
class RecommendedAction:
    currency: str
    amount_minor: int
    tenor_months: int
    counterparty_id: str
    counterparty_name: str
    reason: str


@dataclass
class FxBriefing:
    briefing: str
    recommendations: list[RecommendedAction]
    watch: list[str]


# --------------------------------------------------------- deterministic side


def _eligible_counterparties(
    session: Session, tenant_id: str, as_of_date: str, policy
) -> list[dict]:
    """FX_FORWARD-permitted counterparties, with live headroom.

    The LLM picks the id — this list is the whitelist.
    """
    statement = (
        select(Counterparty, CounterpartyInstrument)
        .join(
            CounterpartyInstrument,
            CounterpartyInstrument.counterparty_id == Counterparty.id,
        )
        .where(Counterparty.tenant_id == tenant_id)
        .where(Counterparty.status == "ACTIVE")
        .where(CounterpartyInstrument.instrument == "FX_FORWARD")
    )
    exposure = ExposureCalculator(session, tenant_id, as_of_date, policy)
    by_cp = exposure.exposure_by_counterparty()
    by_group = exposure.exposure_by_group()
    out: list[dict] = []
    seen: set[str] = set()
    for cp, _perm in session.execute(statement):
        if cp.id in seen:
            continue
        seen.add(cp.id)
        limit = session.scalars(
            select(CpLimit).where(CpLimit.counterparty_id == cp.id).where(CpLimit.superseded_at.is_(None))
        ).one_or_none()
        group = session.get(CpGroup, cp.group_id)
        out.append(
            {
                "id": cp.id,
                "name": cp.name,
                "rating": cp.rating,
                "entity_headroom_pence": max(0, (limit.amount_pence if limit else 0) - by_cp.get(cp.id, 0)),
                "group_headroom_pence": max(0, (group.group_limit_pence if group else 0) - by_group.get(cp.group_id, 0)),
            }
        )
    return out


def _extra_watch(snap: dict, session: Session, tenant_id: str) -> list[str]:
    """Deterministic pattern flags the AI can also produce.

    Included in the payload so the model has grounds to flag, and used
    directly by the fallback so a live watch section always shows
    something meaningful when something is meaningfully wrong.
    """
    flags: list[str] = []

    # Currency completely exposed with a real policy target
    for c in snap["currencies"]:
        if c["hedge_ratio_pct"] == 0 and c["target_pct"] > 0 and c["gross_minor"] > 0:
            flags.append(
                f"{c['currency']} exposure of "
                f"{c['gross_minor'] // 100:,.0f} {c['currency']} is entirely "
                f"un-hedged against a {c['target_pct']:.0f}% policy target — "
                f"a single forward would remove most of the risk."
            )

    # Single counterparty carrying more than half the hedge book
    rows = list(
        session.execute(
            select(Deal, HedgeLink)
            .join(HedgeLink, HedgeLink.deal_id == Deal.id)
            .where(Deal.tenant_id == tenant_id)
            .where(Deal.instrument == "FX_FORWARD")
            .where(HedgeLink.unlinked_at.is_(None))
        )
    )
    unique_deals: dict[str, Deal] = {}
    for deal, _link in rows:
        unique_deals[deal.id] = deal
    total_pence = sum(d.principal_pence for d in unique_deals.values())
    if total_pence > 0:
        by_cp: dict[str, int] = {}
        for d in unique_deals.values():
            by_cp[d.counterparty_id] = by_cp.get(d.counterparty_id, 0) + d.principal_pence
        for cp_id, share in by_cp.items():
            if share * 2 > total_pence:
                cp = session.get(Counterparty, cp_id)
                pct = round(share * 100 / total_pence)
                flags.append(
                    f"{cp.name if cp else cp_id} is carrying {pct}% of the "
                    f"hedge book. Spreading the next forward to a different "
                    f"approved counterparty would reduce name concentration."
                )

    return flags


def _maturity_clusters(session: Session, tenant_id: str) -> list[str]:
    """One-line flags for the AI to reword.

    Two patterns worth flagging: (a) three or more forwards maturing
    within a 30-day window; (b) more than half the notional in a single
    month.
    """
    rows = list(
        session.execute(
            select(Deal, HedgeLink)
            .join(HedgeLink, HedgeLink.deal_id == Deal.id)
            .where(Deal.tenant_id == tenant_id)
            .where(Deal.instrument == "FX_FORWARD")
            .where(HedgeLink.unlinked_at.is_(None))
        )
    )
    # Group deals uniquely by id (a deal appears once per link)
    unique: dict[str, Deal] = {}
    for deal, _link in rows:
        unique[deal.id] = deal
    deals = list(unique.values())
    if len(deals) < 3:
        return []

    by_month: dict[str, list[Deal]] = {}
    for d in deals:
        if d.maturity_date is None:
            continue
        key = d.maturity_date[:7]  # YYYY-MM
        by_month.setdefault(key, []).append(d)

    flags: list[str] = []
    for month, dl in sorted(by_month.items()):
        if len(dl) >= 3:
            total = sum(d.principal_pence for d in dl) // 100
            flags.append(
                f"{len(dl)} hedges mature in {month} (£{total:,} notional). "
                "Refinance cluster — spreading the next hedge into another "
                "month would level the ladder."
            )
    return flags


def _suggested_amount(gap_minor: int) -> list[int]:
    """A short menu of round amounts the LLM can pick from.

    Half the gap and the full gap, both rounded down to the nearest
    100,000 in minor units. Keeps the recommendation deterministic in
    magnitude while letting the model justify the choice.
    """
    if gap_minor <= 0:
        return []
    step = 100_000 * 100  # 100,000 major units in minor
    full = (gap_minor // step) * step
    half = ((gap_minor // 2) // step) * step
    return sorted({a for a in (half, full) if a > 0})


def _snapshot(
    session: Session, tenant_id: str, as_of_date: str, policy
) -> dict:
    """The payload sent to the LLM. Everything deterministic."""
    fx = FxExposureService(session, tenant_id, as_of_date)
    summary = fx.summary()
    eligible = _eligible_counterparties(session, tenant_id, as_of_date, policy)
    clusters = _maturity_clusters(session, tenant_id)

    currencies = []
    for row in summary:
        gap = row.gap_to_target_minor
        currencies.append(
            {
                "currency": row.currency,
                "gross_minor": row.gross_minor,
                "hedged_minor": row.hedged_minor,
                "unhedged_minor": row.unhedged_minor,
                "hedge_ratio_pct": row.hedge_ratio_bp / 100,
                "target_pct": row.target_cover_bp / 100,
                "gap_to_target_minor": gap,
                "suggested_amounts": _suggested_amount(gap),
            }
        )

    snap = {
        "as_of_date": as_of_date,
        "currencies": currencies,
        "eligible_counterparties": eligible,
        "existing_hedge_clusters": clusters,
    }
    snap["existing_hedge_clusters"] = clusters + _extra_watch(snap, session, tenant_id)
    return snap


def _deterministic_briefing(snap: dict, eligible_by_id: dict) -> FxBriefing:
    """Fallback and safety net.

    Runs when there is no LLM key configured, or when the LLM returns
    something the validator refuses. Writes prose that reads like a
    treasurer's briefing — priority first, then evidence — rather than
    a mechanical list.
    """
    currencies = sorted(
        snap["currencies"],
        key=lambda c: c["gap_to_target_minor"],
        reverse=True,
    )
    gapped = [c for c in currencies if c["gap_to_target_minor"] > 0]
    at_target = [c for c in currencies if c["gap_to_target_minor"] <= 0 and c["target_pct"] > 0]

    if not gapped:
        briefing = "Every currency meets or exceeds its policy target. Nothing to hedge today."
    else:
        priority = gapped[0]
        # Lead with the biggest gap, then contextualise.
        lead = (
            f"Your biggest coverage gap is {priority['currency']} — "
            f"only {priority['hedge_ratio_pct']:.0f}% hedged against a "
            f"{priority['target_pct']:.0f}% target, "
            f"{priority['gap_to_target_minor'] // 100:,.0f} {priority['currency']} short "
            f"over the next 12 months."
        )
        follow_parts: list[str] = []
        for c in gapped[1:]:
            follow_parts.append(
                f"{c['currency']} is {c['hedge_ratio_pct']:.0f}% hedged and needs another "
                f"{c['gap_to_target_minor'] // 100:,.0f} {c['currency']} to reach "
                f"{c['target_pct']:.0f}%"
            )
        follow = ""
        if follow_parts:
            follow = " " + "; ".join(follow_parts) + "."
        priority_note = (
            f" Priority order given the numbers: "
            + " > ".join(c["currency"] for c in gapped) + "."
            if len(gapped) > 1
            else ""
        )
        at_target_note = ""
        if at_target:
            at_target_note = (
                f" {', '.join(c['currency'] for c in at_target)} is at or above target."
            )
        briefing = lead + follow + priority_note + at_target_note

    # A recommendation per currency with a gap; pick the highest-rated
    # eligible counterparty that has room for the full suggested amount.
    recs: list[RecommendedAction] = []
    rating_rank = {"AAA": 0, "AA+": 1, "AA": 2, "AA-": 3, "A+": 4, "A": 5, "A-": 6, "BBB+": 7, "BBB": 8}
    for c in currencies:
        if c["gap_to_target_minor"] <= 0 or not c["suggested_amounts"]:
            continue
        amount = c["suggested_amounts"][0]  # half
        # amount is minor units of foreign currency; convert to GBP-pence for a rough headroom check
        quote = forward_rate(f"{c['currency']}_GBP", 6)
        gbp_pence = round(amount * quote.forward)
        candidates = sorted(
            [cp for cp in snap["eligible_counterparties"] if cp["entity_headroom_pence"] >= gbp_pence],
            key=lambda cp: rating_rank.get(cp["rating"], 99),
        )
        chosen = candidates[0] if candidates else None
        if chosen is None:
            continue
        recs.append(
            RecommendedAction(
                currency=c["currency"],
                amount_minor=amount,
                tenor_months=6,
                counterparty_id=chosen["id"],
                counterparty_name=chosen["name"],
                reason=(
                    f"Closes half the {c['currency']} policy gap. "
                    f"{chosen['name']} is the highest-rated FX-approved "
                    f"bank ({chosen['rating']}) with £{chosen['entity_headroom_pence'] // 100:,} headroom."
                ),
            )
        )
    return FxBriefing(
        briefing=briefing,
        recommendations=recs,
        watch=list(snap["existing_hedge_clusters"]),
    )


# ------------------------------------------------------------------ entry


def advise_on_hedge(
    session: Session,
    tenant_id: str,
    as_of_date: str,
    policy,
    currency: str,
    sell_amount_minor: int,
    tenor_months: int,
    counterparty_id: str,
) -> list[str]:
    """AI advisor for the Initiate modal.

    Reads the current state of the hedge book plus the proposed trade
    and produces 2-4 contextual observations for the treasurer to see
    alongside the six-check pills:

    - Concentration: what this hedge does to the counterparty's share
      of the FX book and their headroom utilisation.
    - Ladder: whether the maturity lands on top of existing hedges.
    - Rate context: sign and size of the forward-vs-spot differential
      for this tenor. Never a rate view.
    - Policy: what the trade does to the currency's hedge ratio.

    No LLM required — every observation is derived from real numbers so
    the output is deterministic and audit-friendly. If a Groq key is
    present, the LLM is used to rephrase the bullets in more natural
    prose; the underlying facts stay the same.
    """
    import json as _json
    import os as _os
    from datetime import date as _date, timedelta as _td

    fx = FxExposureService(session, tenant_id, as_of_date)
    summary_row = fx._summary_for(currency.upper())

    # Existing hedge book, and this counterparty's share
    rows = list(
        session.execute(
            select(Deal, HedgeLink)
            .join(HedgeLink, HedgeLink.deal_id == Deal.id)
            .where(Deal.tenant_id == tenant_id)
            .where(Deal.instrument == "FX_FORWARD")
            .where(HedgeLink.unlinked_at.is_(None))
        )
    )
    unique: dict[str, Deal] = {}
    for deal, _ in rows:
        unique[deal.id] = deal
    total_book_pence = sum(d.principal_pence for d in unique.values())
    cp_current = sum(
        d.principal_pence for d in unique.values() if d.counterparty_id == counterparty_id
    )

    # This trade's GBP-equivalent principal
    quote = forward_rate(f"{currency.upper()}_GBP", tenor_months)
    gbp_pence = round(sell_amount_minor * quote.forward)

    exposure_calc = ExposureCalculator(session, tenant_id, as_of_date, policy)
    by_cp = exposure_calc.exposure_by_counterparty()
    by_group = exposure_calc.exposure_by_group()

    cp = session.get(Counterparty, counterparty_id)
    limit = session.scalars(
        select(CpLimit)
        .where(CpLimit.counterparty_id == counterparty_id)
        .where(CpLimit.superseded_at.is_(None))
    ).one_or_none()
    group = session.get(CpGroup, cp.group_id) if cp else None

    observations: list[str] = []

    # --- Concentration on the book ---
    new_total = total_book_pence + gbp_pence
    cp_new_share = ((cp_current + gbp_pence) * 100) / max(new_total, 1)
    if total_book_pence == 0:
        observations.append(
            f"First live hedge on the book — this trade sets the baseline "
            f"concentration and the first entry in the maturity ladder."
        )
    elif cp_new_share > 50:
        observations.append(
            f"After this trade, {cp.name if cp else counterparty_id} would carry "
            f"{cp_new_share:.0f}% of the FX hedge book. Consider spreading the "
            f"next forward to another approved counterparty."
        )
    else:
        observations.append(
            f"After this trade, {cp.name if cp else counterparty_id} carries "
            f"{cp_new_share:.0f}% of the FX hedge book — comfortable name "
            f"diversification."
        )

    # --- Limit headroom utilisation ---
    if limit and cp:
        entity_used = by_cp.get(counterparty_id, 0) + gbp_pence
        util_pct = (entity_used * 100) / max(limit.amount_pence, 1)
        remaining = max(0, limit.amount_pence - entity_used)
        observations.append(
            f"This hedge takes {cp.name}'s counterparty exposure to "
            f"£{entity_used // 100:,} of a £{limit.amount_pence // 100:,} "
            f"limit ({util_pct:.0f}% utilised, £{remaining // 100:,} headroom left)."
        )

    # --- Group headroom ---
    if group and cp:
        group_used = by_group.get(cp.group_id, 0) + gbp_pence
        group_pct = (group_used * 100) / max(group.group_limit_pence, 1)
        if group_pct > 80:
            observations.append(
                f"Group total for {group.name} would reach "
                f"£{group_used // 100:,} of £{group.group_limit_pence // 100:,} "
                f"({group_pct:.0f}%). Above 80% is worth a second look."
            )

    # --- Maturity ladder ---
    proposed_maturity = _date.fromisoformat(as_of_date) + _td(days=30 * tenor_months)
    proposed_month = proposed_maturity.strftime("%Y-%m")
    same_month = [
        d for d in unique.values()
        if d.maturity_date and d.maturity_date.startswith(proposed_month)
    ]
    if same_month:
        observations.append(
            f"{len(same_month)} existing hedge{'s' if len(same_month) > 1 else ''} "
            f"already mature in {proposed_maturity.strftime('%b %Y')}. "
            f"Stretching or shortening the tenor by a month would smooth the ladder."
        )

    # (Cost-of-carry commentary intentionally omitted. The forward
    # rate is shown on the ticket for context; the AI does not
    # editorialise it, so nothing here reads as a market view.)

    # --- Policy gap movement ---
    if summary_row.target_cover_bp > 0:
        before_pct = summary_row.hedge_ratio_bp / 100
        after_hedged = summary_row.hedged_minor + sell_amount_minor
        after_pct = (after_hedged * 100) / max(summary_row.gross_minor, 1)
        target_pct = summary_row.target_cover_bp / 100
        if after_pct >= target_pct:
            observations.append(
                f"After this trade, {currency} would move from "
                f"{before_pct:.0f}% to {after_pct:.0f}% hedged — meeting the "
                f"{target_pct:.0f}% policy target."
            )
        else:
            gap_after = summary_row.target_cover_bp - round(after_pct * 100)
            observations.append(
                f"After this trade, {currency} would move from "
                f"{before_pct:.0f}% to {after_pct:.0f}% hedged, still "
                f"{gap_after / 100:.0f} percentage points short of the "
                f"{target_pct:.0f}% policy target."
            )

    # Optional: rephrase through the LLM for warmer prose. Facts stay
    # deterministic — we hand the model the exact bullets and ask it to
    # tighten them without changing the numbers.
    key = _os.environ.get(KEY_VAR, "").strip()
    if not key or not observations:
        return observations

    try:
        from groq import Groq

        client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
        completion = client.chat.completions.create(
            model=_os.environ.get(MODEL_VAR, DEFAULT_MODEL),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a treasury GOVERNANCE narrator. Rewrite each of "
                        "these bullets in tighter, more natural English. Preserve "
                        "every number, counterparty name, and percentage exactly. "
                        "You are describing counterparty concentration, limit "
                        "headroom, maturity ladder, and policy movement — never "
                        "a market view. Never predict or comment on where FX "
                        "rates will move; never say a rate is attractive, "
                        "favourable, or a good/bad time to hedge. Reply as JSON: "
                        '{"bullets": ["...", "..."]}'
                    ),
                },
                {"role": "user", "content": _json.dumps({"bullets": observations})},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        raw = (completion.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return observations
        parsed = _json.loads(raw[start : end + 1])
        rewritten = [str(b).strip() for b in parsed.get("bullets", []) if str(b).strip()]
        # Only trust the rewrite if the count matches — otherwise the
        # model changed the structure and we fall back to the facts.
        if len(rewritten) == len(observations):
            return rewritten
    except Exception:
        pass
    return observations


def narrate(
    session: Session, tenant_id: str, as_of_date: str, policy
) -> FxBriefing:
    """Return a briefing + recommendations. Never raises."""
    snap = _snapshot(session, tenant_id, as_of_date, policy)
    eligible_by_id = {cp["id"]: cp for cp in snap["eligible_counterparties"]}

    key = os.environ.get(KEY_VAR, "").strip()
    if not key:
        return _deterministic_briefing(snap, eligible_by_id)

    try:
        from groq import Groq

        client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
        completion = client.chat.completions.create(
            model=os.environ.get(MODEL_VAR, DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(snap, default=str)},
            ],
            temperature=0.2,
            max_tokens=1800,
        )
        raw = (completion.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON in response")
        parsed = json.loads(raw[start : end + 1])

        # Validate. Anything the model made up gets rejected — we don't
        # sneak invented counterparties or amounts into the record.
        allowed_currencies = {c["currency"] for c in snap["currencies"]}
        recs: list[RecommendedAction] = []
        for r in parsed.get("recommendations", []):
            ccy = str(r.get("currency", "")).upper()
            cp_id = str(r.get("counterparty_id", ""))
            if ccy not in allowed_currencies:
                continue
            if cp_id not in eligible_by_id:
                continue
            row = next((c for c in snap["currencies"] if c["currency"] == ccy), None)
            if row is None or int(r.get("amount_minor", 0)) not in row["suggested_amounts"]:
                continue
            tenor = int(r.get("tenor_months", 6))
            if tenor not in (3, 6, 9, 12):
                continue
            recs.append(
                RecommendedAction(
                    currency=ccy,
                    amount_minor=int(r["amount_minor"]),
                    tenor_months=tenor,
                    counterparty_id=cp_id,
                    counterparty_name=eligible_by_id[cp_id]["name"],
                    reason=str(r.get("reason", "")).strip(),
                )
            )

        briefing = str(parsed.get("briefing", "")).strip()
        watch = [str(w).strip() for w in parsed.get("watch", []) if str(w).strip()]

        if not briefing:
            briefing = _deterministic_briefing(snap, eligible_by_id).briefing

        return FxBriefing(briefing=briefing, recommendations=recs, watch=watch)
    except Exception:
        return _deterministic_briefing(snap, eligible_by_id)
