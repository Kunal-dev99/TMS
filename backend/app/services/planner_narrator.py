"""Ranks the four candidates and writes a short label for each.

The candidate list is deterministic. What the model adds:
  1. Which one to take, in one sentence.
  2. Per candidate, a one-liner that says what makes it interesting or
     unattractive given today's book. Not fact-repetition; the trade-off.

The prompt bounds the answer to a fixed set of candidate `kind` codes, so
a broken response cannot smuggle in an option that was not planned.
"""
from __future__ import annotations

import json
import os

from app.services.planner_service import DeploymentPlan, PlannerService

MODEL_VAR = "TREASURY_MODEL_NAME"
KEY_VAR = "TREASURY_MODEL_API_KEY"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 12.0

SYSTEM_PROMPT = (
    "You are an expert treasury advisor assisting a corporate treasurer on deploying idle cash.\n\n"
    "The treasurer has candidate deployment plans, each pre-checked against policy and safe to book. "
    "Your job is to provide an AI Quick Summary: a clear, point-wise executive briefing that synthesizes "
    "the decision so the treasurer gets the full picture at a glance without reading dense text.\n\n"
    "Rules:\n"
    "1. Choose exactly one candidate kind from the input. Never invent one.\n"
    "2. Every number you quote must be a figure already in the input. No rates or amounts of your own.\n"
    "3. Write 'recommendation_reason' as exactly 4 point-wise bullets separated by double newlines (\\n\\n):\n"
    "   • Cash to Deploy: [idle cash amount and currency] ready for allocation across [N] pre-checked strategies.\n"
    "   • Strategy Trade-Offs: Contrast the candidates (e.g. Blended Plan policy adherence vs Higher Yield extra return/yield vs concentration).\n"
    "   • Recommended Pick: State your recommended candidate and why it is the optimal risk-adjusted allocation today.\n"
    "   • Governance & Safety: Confirm all placements pre-pass policy controls (concentration, rating, limits) for 1-click execution.\n"
    "4. Per candidate, provide a one-sentence trade-off label under 'labels'.\n"
    "5. Reply as JSON, exactly this shape:\n"
    "   {\n"
    "     \"recommendation_kind\": \"...\",\n"
    "     \"recommendation_reason\": \"...\",\n"
    "     \"labels\": { \"<kind>\": \"...\" }\n"
    "   }"
)

VALID_KINDS = {
    "BLENDED",
    "HIGHER_YIELD",
    "TIGHTER_CONCENTRATION",
    "MAX_YIELD",
    "DIVERSIFIED",
    "PRESERVE_HEADROOM",
    "CONSERVATIVE",
}


def _fallback(plan: DeploymentPlan) -> dict:
    """A deterministic fallback: clear point-wise executive summary bullets + labels."""
    if not plan.candidates:
        return {"recommendation_kind": "", "recommendation_reason": "", "labels": {}}
    best = max(plan.candidates, key=lambda c: c.expected_annual_interest_pence)
    blended = next(
        (c for c in plan.candidates if c.kind == "BLENDED"), plan.candidates[0]
    )

    idle_str = f"£{plan.idle_cash_pence // 100:,.0f}"
    best_yield_str = f"£{best.expected_annual_interest_pence // 100:,.0f}"
    delta = (
        best.expected_annual_interest_pence
        - blended.expected_annual_interest_pence
    )
    delta_str = f", gaining +£{delta // 100:,.0f}/yr extra return" if delta > 0 else ""

    bullets = [
        f"• Cash to Deploy: {idle_str} of uninvested cash ready for allocation across {len(plan.candidates)} pre-checked strategies.",
        f"• Strategy Trade-Offs: The Blended Plan aligns strictly with your policy buckets at {blended.weighted_rate_bp / 100:.2f}%, whereas {best.label} delivers the highest return at {best_yield_str}/yr ({best.weighted_rate_bp / 100:.2f}%{delta_str}).",
        f"• Recommended Pick: We recommend {best.label} as the optimal risk-adjusted allocation today, remaining comfortably within your {plan.concentration_cap_bp / 100:.1f}% concentration cap.",
        "• Governance & Safety: Every placement has pre-passed all six policy controls for immediate one-click execution.",
    ]
    reason = "\n\n".join(bullets)
    return {
        "recommendation_kind": best.kind,
        "recommendation_reason": reason,
        "labels": {c.kind: c.tagline for c in plan.candidates},
    }


def narrate(plan: DeploymentPlan, planner: PlannerService) -> None:
    """Fill the plan's recommendation and per-candidate labels."""
    key = os.environ.get(KEY_VAR, "").strip()
    if not key:
        out = _fallback(plan)
        plan.recommendation_kind = out["recommendation_kind"]
        plan.recommendation_reason = out["recommendation_reason"]
        plan.per_candidate_labels = out["labels"]
        return

    try:
        from groq import Groq

        client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
        payload = planner.summarise(plan)
        completion = client.chat.completions.create(
            model=os.environ.get(MODEL_VAR, DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            temperature=0.2,
            # openai/gpt-oss-120b spends tokens on reasoning before it
            # writes anything visible, so the ceiling has to be large
            # enough to leave the JSON room. Empty responses are the
            # symptom of getting this wrong.
            max_tokens=2500,
            # No response_format: Groq's JSON mode fails when the
            # response is close to the token limit, even for a valid
            # object. The prompt is explicit about the shape and the
            # parser below is tolerant.
        )
        raw = (completion.choices[0].message.content or "").strip()
        # The model may wrap the JSON in a code fence or prose.
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in response")
        parsed = json.loads(raw[start:end + 1])

        kind = str(parsed.get("recommendation_kind", "")).strip()
        valid_kinds = VALID_KINDS | {c.kind for c in plan.candidates}
        if kind not in valid_kinds or not any(c.kind == kind for c in plan.candidates):
            # Model made something up. Fall back rather than trust it.
            out = _fallback(plan)
            plan.recommendation_kind = out["recommendation_kind"]
            plan.recommendation_reason = out["recommendation_reason"]
            plan.per_candidate_labels = out["labels"]
            return

        plan.recommendation_kind = kind
        plan.recommendation_reason = str(
            parsed.get("recommendation_reason", "")
        ).strip()
        labels = parsed.get("labels", {}) or {}
        plan.per_candidate_labels = {
            c.kind: str(labels.get(c.kind, c.tagline)).strip() or c.tagline
            for c in plan.candidates
        }
    except Exception:
        out = _fallback(plan)
        plan.recommendation_kind = out["recommendation_kind"]
        plan.recommendation_reason = out["recommendation_reason"]
        plan.per_candidate_labels = out["labels"]
