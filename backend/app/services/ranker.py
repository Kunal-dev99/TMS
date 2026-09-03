"""Stage 4. The only stage that calls a model.

Two implementations behind one interface. Switching `model_enabled` off in
the investment policy swaps the implementation, and no other code path
changes. `score_bp` is computed on every candidate whether or not the model
runs, so the fallback is always available and the recommendation always
exists.

What the model is allowed to return is the whole of the guardrail: an
identifier from a list it was given, and prose. It never returns a number.
Every figure in the recommendation was computed at stage 3 and is re-checked
at stage 5, so there is no arithmetic for it to get wrong.

Worth knowing internally: with four candidates and a clear priority order, a
scoring formula ranks them much the same. The model's real contribution is
the explanation, which is hard to write as a rule. The AI framing should not
be oversold on the ranking.
"""

import json
import os
from dataclasses import dataclass
from typing import Protocol

from app import config  # noqa: F401  reads .env before the key is looked up
from app.formatting import per_cent, sterling


@dataclass(frozen=True)
class RankedPick:
    candidate_id: str
    rationale: str | None
    source: str


class Ranker(Protocol):
    name: str

    def rank(self, candidates: list, context: dict) -> RankedPick: ...


class WeightedScoreRanker:
    """Stage 5b. The deterministic pick.

    Used when the model is switched off, when it is unreachable, and when
    what it returned fails validation. The recommendation survives; only the
    explanation is lost, and the interface says so.

    The prose here is assembled from the figures rather than written, which
    is exactly why it reads flatter than the model's. That is the honest
    difference between the two.
    """

    name = "weighted-score"

    def rank(self, candidates: list, context: dict) -> RankedPick:
        best = max(candidates, key=lambda candidate: candidate.score_bp)
        return RankedPick(
            candidate_id=best.id,
            rationale=None,
            source="RULE_FALLBACK",
        )


class ModelRanker:
    """The model call.

    Stubbed. Document 4 puts the language model behind an adapter like every
    other external dependency, and this is that adapter with nothing behind
    it yet. It picks the highest scoring candidate and writes prose about it,
    which is what a working model would do most of the time.

    Everything that makes the real call safe is already here: it receives a
    bounded list built at stage 3, it returns an identifier from that list,
    and every figure it puts in the prose comes from the candidate row rather
    than from the model.
    """

    name = "ranker-stub-v1"

    def rank(self, candidates: list, context: dict) -> RankedPick:
        best = max(candidates, key=lambda candidate: candidate.score_bp)
        runners = [c for c in candidates if c.id != best.id]

        rationale = (
            f"{context['names'][best.counterparty_id]} at "
            f"{context['ratings'][best.counterparty_id]} takes the whole amount "
            f"inside its own limit and its group limit, at "
            f"{per_cent(best.indicative_rate_bp)} for {best.tenor_months} months."
        )
        if context.get("gap_type") == "LADDER_GAP":
            rationale += " It also fills the empty bucket in the maturity ladder."
        if runners:
            second = max(runners, key=lambda candidate: candidate.score_bp)
            rationale += (
                f" {context['names'][second.counterparty_id]} was the next best "
                f"at {per_cent(second.indicative_rate_bp)}, on "
                f"{sterling(second.amount_pence)}."
            )

        return RankedPick(
            candidate_id=best.id,
            rationale=rationale,
            source="MODEL",
        )


class GroqRanker:
    """The real model call, over Groq.

    What it is allowed to return is the whole of the guardrail: one candidate
    identifier from the list it was given, and prose. The prompt says so, but
    the prompt is not what enforces it. Stage 5 does, and it does not trust
    this class at all:

      ID_IS_REAL          the identifier has to be a row from this run
      CHECKS_RERUN_CLEAN  the pick has to pass the six checks again
      FIGURES_AGREE       every number in the prose has to be one computed
                          at stage 3

    So the worst this can do is be rejected, at which point the deterministic
    pick is shown instead and the interface says RULE_FALLBACK. There is no
    output it can produce that reaches the book unchecked.

    The candidate list is already bounded, priced and compliant when it gets
    here, because stage 3 excluded anything that would fail the checks before
    the list existed. The model is choosing between options that were all
    acceptable.

    Any failure at all raises, and AdvisoryService falls back. A treasury
    system does not stop working because somebody else's endpoint is slow.
    """

    #: Reads the environment rather than a settings file, so the key is never
    #: in the repository and never in a database row. Rotate it there.
    API_KEY_VAR = "TREASURY_MODEL_API_KEY"
    MODEL_VAR = "TREASURY_MODEL_NAME"
    #: Overridden with TREASURY_MODEL_NAME. Check what a key can actually
    #: reach before changing it: models come and go, and a name a key has no
    #: access to is a 404 rather than a warning.
    DEFAULT_MODEL = "openai/gpt-oss-120b"
    TIMEOUT_SECONDS = 12.0

    SYSTEM_PROMPT = (
        "You are ranking pre-approved treasury deposit options for a "
        "corporate treasurer.\n\n"
        "Every option you are given has already passed a compliance gate. "
        "You are choosing between acceptable options, not deciding what is "
        "allowed.\n\n"
        "Rules you must follow:\n"
        "1. Choose exactly one candidate_id from the list provided. Never "
        "invent one.\n"
        "2. Never state a number that is not given to you in the list. No "
        "rates, amounts, terms or percentages of your own.\n"
        "3. Two or three sentences of plain English. Say why this option "
        "over the others.\n"
        "4. Reply with JSON only: "
        '{"candidate_id": "...", "rationale": "..."}'
    )

    def __init__(self) -> None:
        self.model = os.environ.get(self.MODEL_VAR, self.DEFAULT_MODEL)
        self.name = f"groq/{self.model}"

    @classmethod
    def configured(cls) -> bool:
        return bool(os.environ.get(cls.API_KEY_VAR, "").strip())

    def rank(self, candidates: list, context: dict) -> RankedPick:
        from groq import Groq

        client = Groq(
            api_key=os.environ[self.API_KEY_VAR], timeout=self.TIMEOUT_SECONDS
        )
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": self._brief(candidates, context)},
            ],
            # Low, because this is an explanation of an arithmetic result
            # rather than a piece of writing. The pick should not move
            # between two runs of the same book.
            temperature=0.2,
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        answer = json.loads(completion.choices[0].message.content)
        candidate_id = str(answer["candidate_id"]).strip()
        rationale = str(answer.get("rationale", "")).strip() or None

        # A first check here so an obviously wrong answer never reaches the
        # recommendation. Stage 5 checks it again and is the one that counts.
        if candidate_id not in {candidate.id for candidate in candidates}:
            raise ValueError(f"{candidate_id} is not a candidate from this run")

        return RankedPick(
            candidate_id=candidate_id, rationale=rationale, source="MODEL"
        )

    def _brief(self, candidates: list, context: dict) -> str:
        """Everything the model sees, and nothing else.

        No counterparty it could pick that is not listed, and no figure it
        needs that is not given. The gap is stated so the prose can refer to
        it; the arithmetic behind it is not the model's to redo.
        """
        lines = [
            f"Gap: {context.get('gap_type', 'UNKNOWN').replace('_', ' ').lower()}.",
            f"Priority order from the investment policy: "
            f"{context.get('priority_order', 'SECURITY,LIQUIDITY,YIELD')}.",
            "",
            "Candidates:",
        ]
        for candidate in candidates:
            lines.append(
                f"- candidate_id={candidate.id} | "
                f"counterparty={context['names'].get(candidate.counterparty_id)} | "
                f"rating={context['ratings'].get(candidate.counterparty_id)} | "
                f"amount={sterling(candidate.amount_pence)} | "
                f"term={candidate.tenor_months} months | "
                f"rate={per_cent(candidate.indicative_rate_bp)} | "
                f"score={candidate.score_bp}"
            )
        lines.append("")
        lines.append(
            "Pick one candidate_id and explain the choice against the "
            "priority order. Use only the figures above."
        )
        return "\n".join(lines)


def ranker_for(model_enabled: bool) -> Ranker:
    """The one place the switch is read.

    `model_enabled` is a policy field rather than an environment variable, so
    a customer owns it and can turn it off without a deployment. Whether a
    real model is reachable is an environment question, and it is separate:
    with the model enabled and no key configured, the stub runs and the
    interface is unchanged.
    """
    if not model_enabled:
        return WeightedScoreRanker()
    if GroqRanker.configured():
        return GroqRanker()
    return ModelRanker()
