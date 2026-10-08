"""One AI call, one ai_run row. Closes Q-004.

Every LLM invocation in the app SHOULD flow through ``chat()`` here.
The wrapper:

  1. Calls the bound ``LLMPort`` adapter.
  2. Times it.
  3. Records prompt + response + timing + fallback flag in ``ai_run``.
  4. Returns the response so callers use it exactly like a direct call.

The recording is best-effort — a failure to write ``ai_run`` never
blocks a decision. The AI is not on the critical path (ADR-0005 —
'AI proposes, deterministic disposes'), and neither is its audit
row. If we can't log, the deterministic fallback still runs and the
caller still gets a response.

Rationale for storing full prompt+response text (per Q-004
recommendation): the compliance officer needs to reconstruct what
the model saw + what it said. A hash alone can't answer 'why did
we act on this recommendation?'.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connector import ports, registry
from app.models import AiRun


@dataclass(frozen=True)
class ChatResult:
    """What callers get back. Superset of ``LLMResponse`` plus the id
    of the ``ai_run`` row so a caller can later record the human
    decision that responded to this AI output."""

    text: str
    model: str
    fallback_used: bool
    tokens_prompt: int
    tokens_completion: int
    ai_run_id: str | None  # None if the write failed; response still valid.


def chat(
    *,
    session: Session,
    tenant_id: str,
    endpoint: str,
    system: str,
    user: str,
    model_hint: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
) -> ChatResult:
    """Fire one chat call, log it, return the response."""
    started = time.perf_counter()
    llm = registry.get(ports.LLMPort)
    response = llm.chat(system=system, user=user, model_hint=model_hint)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    ai_run_id: str | None = None
    try:
        row_id = "run_" + uuid.uuid4().hex[:16]
        session.add(
            AiRun(
                id=row_id,
                tenant_id=tenant_id,
                occurred_at=_now_iso(),
                endpoint=endpoint,
                model=response.model,
                prompt_hash=_prompt_hash(system, user),
                prompt_text=_truncate(system + "\n---USER---\n" + user, 60000),
                response_text=_truncate(response.text, 60000),
                response_ms=elapsed_ms,
                tokens_prompt=int(response.tokens_prompt or 0),
                tokens_completion=int(response.tokens_completion or 0),
                fallback_used="true" if response.fallback else "false",
                subject_type=subject_type,
                subject_id=subject_id,
                human_decision_id=None,
                outcome=None,
            )
        )
        session.flush()  # id becomes durable; caller may reference it.
        ai_run_id = row_id
    except Exception:
        # Never let logging break the caller. AI is not on the six-check
        # gate path — losing an ai_run row is a compliance visibility
        # loss, never a decision loss.
        pass

    return ChatResult(
        text=response.text,
        model=response.model,
        fallback_used=response.fallback,
        tokens_prompt=int(response.tokens_prompt or 0),
        tokens_completion=int(response.tokens_completion or 0),
        ai_run_id=ai_run_id,
    )


def record_decision(session: Session, ai_run_id: str, outcome: str) -> None:
    """Link a human decision back to the AI row that informed it.

    Called from the deal / hedge / advisory flows when a user
    accepts or rejects an AI recommendation. Outcome is a short code
    ('accepted' / 'rejected' / 'ignored'). Silently no-ops if the id
    is unknown — the shape is a courtesy, not a contract.
    """
    if not ai_run_id:
        return
    try:
        row = session.get(AiRun, ai_run_id)
        if row is None:
            return
        row.outcome = outcome
        session.flush()
    except Exception:
        pass


# --- helpers ---------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256(("SYS:" + system + "|USR:" + user).encode()).hexdigest()


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "…[truncated]"
