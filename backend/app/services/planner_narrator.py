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
    "You are advising a corporate treasurer on where to deploy idle cash.\n\n"
    "The treasurer has four candidate deployment plans, each already checked "
    "and safe to book. You choose the best one for today's book and write a "
    "short label for each candidate.\n\n"
    "Rules:\n"
    "1. Choose exactly one candidate kind from the list. Never invent one.\n"
    "2. Every number you quote must be a figure already in the input. No "
    "rates, amounts, percentages of your own.\n"
    "3. Per candidate, write a single sentence of trade-off: what it buys, "
    "what it costs. Not a repetition of the tagline.\n"
    "4. The recommendation is one sentence. Say why this one, not the others.\n"
    "5. Reply as JSON, exactly this shape:\n"
    "   {\n"
    "     \"recommendation_kind\": \"MAX_YIELD\" | \"DIVERSIFIED\" | "
    "\"PRESERVE_HEADROOM\" | \"CONSERVATIVE\",\n"
    "     \"recommendation_reason\": \"...\",\n"
    "     \"labels\": {\n"
    "       \"MAX_YIELD\": \"...\",\n"
    "       \"DIVERSIFIED\": \"...\",\n"
    "       \"PRESERVE_HEADROOM\": \"...\",\n"
    "       \"CONSERVATIVE\": \"...\"\n"
    "     }\n"
    "   }"
)

VALID_KINDS = {"MAX_YIELD", "DIVERSIFIED", "PRESERVE_HEADROOM", "CONSERVATIVE"}


def _fallback(plan: DeploymentPlan) -> dict:
    """A deterministic fallback: rank by yield, describe each in one line."""
    if not plan.candidates:
        return {"recommendation_kind": "", "recommendation_reason": "", "labels": {}}
    best = max(plan.candidates, key=lambda c: c.expected_annual_interest_pence)
    return {
        "recommendation_kind": best.kind,
        "recommendation_reason": (
            f"{best.label.lower()} earns the most: "
            f"{best.expected_annual_interest_pence // 100:,}p a year."
        ),
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
        if kind not in VALID_KINDS or not any(c.kind == kind for c in plan.candidates):
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
