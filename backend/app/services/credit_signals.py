"""Credit-signal watching.

AI reads the news items on file for each counterparty, classifies each
one as material or immaterial, and writes a one-line "so what" grounded
in the counterparty's current position. The output is a set of signal
cards ready for the interface.

A treasurer cannot personally read the FT for forty counterparties every
morning. AI can. What AI cannot do is act — every card offers a
suggested action; the person clicks, and the ordinary control path
handles the rest.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formatting import per_cent, sterling
from app.models import Counterparty, NewsItem, PolicyVersion
from app.services.state_service import StateService

MODEL_VAR = "TREASURY_MODEL_NAME"
KEY_VAR = "TREASURY_MODEL_API_KEY"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 15.0


@dataclass
class NewsSummary:
    """One news item, with the AI's read of it."""

    id: str
    source: str
    headline: str
    published_at: str
    materiality: str = "IMMATERIAL"  # MATERIAL | WATCH | IMMATERIAL
    reasoning: str = ""


@dataclass
class CreditSignal:
    """One counterparty's news, distilled into a card."""

    counterparty_id: str
    counterparty_name: str
    rating: str
    #: Overall severity for the counterparty across its items. If any
    #: item is MATERIAL, the card is MATERIAL. This drives sorting.
    severity: str = "QUIET"  # MATERIAL | WATCH | QUIET
    #: Current exposure and headroom so the reader can weigh the news.
    used_pence: int = 0
    limit_pence: int = 0
    utilisation_bp: int = 0
    #: The AI's paragraph — one or two sentences on what this means for
    #: today's book.
    summary: str = ""
    #: One suggested action, drawn from a fixed set.
    suggested_action: str = "MONITOR"  # PUT_ON_WATCH | REDUCE | ROLL_OFF | MONITOR | IGNORE
    items: list[NewsSummary] = field(default_factory=list)


SEVERITY_ORDER = {"MATERIAL": 0, "WATCH": 1, "QUIET": 2}
MATERIAL_ORDER = {"MATERIAL": 0, "WATCH": 1, "IMMATERIAL": 2}


SYSTEM_PROMPT = (
    "You are a credit analyst reading news about a corporate treasury "
    "counterparty. You are given today's exposure to that counterparty, "
    "the counterparty's rating, and every news item on file for them.\n\n"
    "For every item, classify materiality:\n"
    "  MATERIAL     — a rating action, a downgrade watch, restructuring, "
    "significant loss, regulatory action, or contagion signal that would "
    "warrant reviewing the position today.\n"
    "  WATCH        — worth noting but not urgent (a management change at "
    "a senior level, an earnings miss, sector pressure without a direct "
    "hit).\n"
    "  IMMATERIAL   — routine news, dividends, business-as-usual mandates, "
    "junior appointments.\n\n"
    "Then write:\n"
    "  summary          — one or two sentences on what today's news means "
    "for today's position. Quote the exposure figures if they matter. Be "
    "direct, not alarmist.\n"
    "  suggested_action — one of PUT_ON_WATCH, REDUCE, ROLL_OFF, "
    "MONITOR, IGNORE.\n\n"
    "Rules:\n"
    "1. Only quote figures that are in the input.\n"
    "2. Say IGNORE only when nothing on file needs a treasurer's "
    "attention. Say MONITOR when there is nothing to act on but the story "
    "is worth remembering.\n"
    "3. Reply as JSON: {\n"
    "     \"summary\": \"...\",\n"
    "     \"suggested_action\": \"...\",\n"
    "     \"items\": [{\"id\": \"...\", \"materiality\": \"...\", "
    "\"reasoning\": \"...\"}]\n"
    "   }"
)


class CreditSignalService:
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

    def scan(self) -> list[CreditSignal]:
        state = StateService(
            self.session, self.tenant_id, self.as_of_date, self.policy,
            tenant_name="",
        )
        book = {row.counterparty_id: row for row in state.book()}
        counterparties = self.session.scalars(
            select(Counterparty).where(Counterparty.tenant_id == self.tenant_id)
        ).all()
        signals: list[CreditSignal] = []
        for cp in counterparties:
            items = self.session.scalars(
                select(NewsItem)
                .where(NewsItem.counterparty_id == cp.id)
                .order_by(NewsItem.published_at.desc())
            ).all()
            if not items:
                continue
            row = book.get(cp.id)
            signal = CreditSignal(
                counterparty_id=cp.id,
                counterparty_name=cp.name,
                rating=cp.rating or "",
                used_pence=row.used_pence if row else 0,
                limit_pence=row.limit_pence if row else 0,
                utilisation_bp=(
                    int(round(row.used_pence * 10000 / row.limit_pence))
                    if row and row.limit_pence
                    else 0
                ),
                items=[
                    NewsSummary(
                        id=item.id,
                        source=item.source,
                        headline=item.headline,
                        published_at=item.published_at,
                    )
                    for item in items
                ],
            )
            self._read(signal, items)
            signal.severity = min(
                (item.materiality for item in signal.items),
                key=lambda m: MATERIAL_ORDER.get(m, 3),
                default="QUIET",
            )
            # Rewrite MATERIAL/WATCH into severity keys; IMMATERIAL -> QUIET.
            if signal.severity == "IMMATERIAL":
                signal.severity = "QUIET"
            signals.append(signal)

        # Sort by severity so material signals surface first.
        signals.sort(
            key=lambda s: (
                SEVERITY_ORDER.get(s.severity, 3),
                -s.utilisation_bp,
                s.counterparty_name,
            )
        )
        return signals

    # ------------------------------------------------------------------

    def _read(
        self, signal: CreditSignal, items: list[NewsItem]
    ) -> None:
        key = os.environ.get(KEY_VAR, "").strip()
        if not key:
            self._fallback(signal, items)
            return
        try:
            from groq import Groq

            payload = {
                "counterparty": {
                    "name": signal.counterparty_name,
                    "rating": signal.rating,
                    "used": sterling(signal.used_pence),
                    "limit": sterling(signal.limit_pence),
                    "utilisation": per_cent(signal.utilisation_bp),
                },
                "items": [
                    {
                        "id": item.id,
                        "source": item.source,
                        "headline": item.headline,
                        "body": item.body,
                        "published_at": item.published_at,
                    }
                    for item in items
                ],
            }
            client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
            completion = client.chat.completions.create(
                model=os.environ.get(MODEL_VAR, DEFAULT_MODEL),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            raw = (completion.choices[0].message.content or "").strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("no JSON object")
            data: dict[str, Any] = json.loads(raw[start:end + 1])
        except Exception:
            self._fallback(signal, items)
            return

        signal.summary = str(data.get("summary", "")).strip() or self._flat_summary(
            signal, items
        )
        action = str(data.get("suggested_action", "MONITOR")).strip().upper()
        if action not in ("PUT_ON_WATCH", "REDUCE", "ROLL_OFF", "MONITOR", "IGNORE"):
            action = "MONITOR"
        signal.suggested_action = action

        classifications = {
            item.get("id"): item
            for item in data.get("items", [])
            if isinstance(item, dict)
        }
        for summary in signal.items:
            cls = classifications.get(summary.id) or {}
            m = str(cls.get("materiality", "IMMATERIAL")).strip().upper()
            if m not in ("MATERIAL", "WATCH", "IMMATERIAL"):
                m = "IMMATERIAL"
            summary.materiality = m
            summary.reasoning = str(cls.get("reasoning", "")).strip()

    @staticmethod
    def _fallback(signal: CreditSignal, items: list[NewsItem]) -> None:
        # Deterministic fallback: MATERIAL for anything mentioning "downgrade"
        # or "review", WATCH for "outlook" / "loss" / "restructuring", else
        # IMMATERIAL.
        MATERIAL = ("downgrade", "review", "restructuring", "default")
        WATCH_WORDS = ("outlook", "loss", "cut", "job", "risk", "stress", "provision")
        for summary, item in zip(signal.items, items):
            text = (item.headline + " " + item.body).lower()
            if any(w in text for w in MATERIAL):
                summary.materiality = "MATERIAL"
            elif any(w in text for w in WATCH_WORDS):
                summary.materiality = "WATCH"
            else:
                summary.materiality = "IMMATERIAL"
            summary.reasoning = ""
        signal.summary = CreditSignalService._flat_summary(signal, items)
        material = [
            s for s in signal.items if s.materiality in ("MATERIAL", "WATCH")
        ]
        signal.suggested_action = "PUT_ON_WATCH" if material else "MONITOR"

    @staticmethod
    def _flat_summary(signal: CreditSignal, items) -> str:
        parts = [f"{len(signal.items)} item(s) on file for {signal.counterparty_name}"]
        if signal.utilisation_bp:
            parts.append(
                f"currently at {per_cent(signal.utilisation_bp)} of its limit"
            )
        return ". ".join(parts) + "."
