"""LLMPort backed by Groq — today's provider.

Mirrors the pattern every service currently open-codes
(fx_narrator, planner_narrator, ranker, ...): read the key from
env, construct a Groq client on demand, fall back cleanly on
missing key or upstream error. When the key is absent this
adapter returns a fallback response — the service layer's own
deterministic path still runs downstream.

Later stages migrate every service to call ``registry.get(LLMPort)``
instead of re-implementing this dance. Stage 1 only introduces the
adapter; migration is a follow-up.
"""

from __future__ import annotations

import os

from app.connector.ports import LLMResponse

KEY_VAR = "TREASURY_MODEL_API_KEY"
MODEL_VAR = "TREASURY_MODEL_NAME"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 20


class GroqLLM:
    name = "groq"

    def chat(
        self, system: str, user: str, model_hint: str | None = None
    ) -> LLMResponse:
        key = os.environ.get(KEY_VAR, "").strip()
        model = model_hint or os.environ.get(MODEL_VAR, DEFAULT_MODEL)
        if not key:
            return LLMResponse(
                text="", model=model, tokens_prompt=0, tokens_completion=0, fallback=True
            )
        try:
            from groq import Groq

            client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            choice = resp.choices[0].message
            usage = getattr(resp, "usage", None)
            return LLMResponse(
                text=(choice.content or "").strip(),
                model=model,
                tokens_prompt=getattr(usage, "prompt_tokens", 0) or 0,
                tokens_completion=getattr(usage, "completion_tokens", 0) or 0,
                fallback=False,
            )
        except Exception:
            # Network / API / SDK failure: same shape as no-key. The
            # caller's own deterministic fallback still runs.
            return LLMResponse(
                text="", model=model, tokens_prompt=0, tokens_completion=0, fallback=True
            )
