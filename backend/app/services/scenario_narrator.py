"""Turns a ScenarioDelta into a paragraph a treasurer would read.

The rule is the same one that governs the ranker: the model may not state a
number that was not handed to it. Every figure in `before`, `after` and
`changes` is deterministic — the model's job is the prose that reads them.

A failure falls back to a plain sentence built from `changes`. A treasury
system does not stop working because somebody else's endpoint is slow, and
scenarios in particular are not blocking anything.
"""
from __future__ import annotations

import json
import os

from app.services.scenario_service import ScenarioDelta

MODEL_VAR = "TREASURY_MODEL_NAME"
KEY_VAR = "TREASURY_MODEL_API_KEY"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 10.0

SYSTEM_PROMPT = (
    "You write short, factual paragraphs for a corporate treasurer. Each "
    "paragraph reads a what-if scenario on the treasury book. The numbers "
    "are computed deterministically and given to you as a list of changes.\n\n"
    "Rules:\n"
    "1. Never state a figure that is not in the input. No rates, amounts, "
    "counts, percentages, or dates of your own.\n"
    "2. Say what would change and what it means for the treasurer. Be direct.\n"
    "3. Two or three sentences of plain English. No bullet lists. No "
    "greetings. No sign-off.\n"
    "4. If the scenario is unremarkable, say so plainly. Do not manufacture "
    "drama.\n"
    "5. Reply with the paragraph and nothing else."
)


def _fallback(delta: ScenarioDelta) -> str:
    if not delta.changes:
        return "No material change under this scenario."
    return " ".join(delta.changes)


def narrate(delta: ScenarioDelta) -> str:
    """Fills `delta.narrative` if the model is available; falls back otherwise.

    Returns the same string it writes to `delta.narrative`, so a caller can
    also use it directly.
    """
    key = os.environ.get(KEY_VAR, "").strip()
    if not key:
        text = _fallback(delta)
        delta.narrative = text
        return text

    try:
        from groq import Groq

        client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
        # The change list is deterministic and already reads correctly. The
        # model rewrites it into one paragraph. Passing the full before/after
        # dicts would just leave the model less headroom for output and
        # invite it to invent details we already have.
        prompt = (
            f"Scenario: {delta.scenario.replace('_', ' ').lower()}.\n"
            f"Inputs: {json.dumps(delta.inputs, default=str)}\n"
            f"Deterministic changes (rewrite as one paragraph, quoting each "
            f"figure verbatim, no numbers of your own):\n- "
            + "\n- ".join(delta.changes)
        )
        completion = client.chat.completions.create(
            model=os.environ.get(MODEL_VAR, DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=500,
        )
        raw = (completion.choices[0].message.content or "").strip()
        # The prompt asks for JSON, but a paragraph is what a paragraph is.
        # If the model wrapped it in {"narrative": "..."}, take the field;
        # otherwise take the raw string.
        if raw.startswith("{"):
            try:
                text = str(json.loads(raw).get("narrative", "")).strip()
            except json.JSONDecodeError:
                text = raw
        else:
            text = raw
        text = text or _fallback(delta)
    except Exception:
        # Any failure at all falls back. A slow endpoint is not a reason
        # to withhold the numbers.
        text = _fallback(delta)

    delta.narrative = text
    return text
