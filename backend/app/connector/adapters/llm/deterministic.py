"""LLMPort fallback that returns a fixed, deterministic response.

The existing service-layer fallbacks (fx_narrator, planner_narrator,
etc.) still handle the domain-specific 'no AI' text; this adapter is
what registry binds when ``LLM_PROVIDER=deterministic`` — used by
tests + demos with no API key.
"""

from __future__ import annotations

from app.connector.ports import LLMResponse


class DeterministicLLM:
    name = "deterministic"

    def chat(
        self, system: str, user: str, model_hint: str | None = None
    ) -> LLMResponse:
        # Non-empty so callers can tell the difference from "network
        # failed" -> None; short so nothing surprises a test snapshot.
        return LLMResponse(
            text="[deterministic-llm] no upstream model bound",
            model="deterministic",
            tokens_prompt=0,
            tokens_completion=0,
            fallback=True,
        )
