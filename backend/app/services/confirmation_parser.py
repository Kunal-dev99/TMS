"""AI parser for confirmation messages arriving as free text.

Every counterparty writes confirmations in their own format — SWIFT MT
messages, email bodies, PDF-pasted text, broker note screenshots. The
existing ingest endpoint expects a clean JSON object; this service closes
the gap between the interface and reality.

Rule: the parser reads, the matcher decides. Every field is extracted by
the model and every field is presented to the person for review; only
after they hit "Ingest" does the deterministic MatchService run. If the
parser is wrong, the fields the person edits are what get ingested. If
the parser is unavailable, the whole modal falls back to a manual entry
form.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formatting import sterling
from app.models import Counterparty

MODEL_VAR = "TREASURY_MODEL_NAME"
KEY_VAR = "TREASURY_MODEL_API_KEY"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 15.0


@dataclass
class ParsedConfirmation:
    """What the AI extracted, and how sure it is.

    Every field is optional because a real message may be missing any of
    them; the modal renders what came back and asks the person for the
    rest. The `warnings` list surfaces things the parser thinks are worth
    a second look — a rate that seems too high, a maturity before the
    value date, and so on.
    """

    message_type: str | None = None
    reference: str | None = None
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    instrument: str | None = None
    principal_pence: int | None = None
    rate_bp: int | None = None
    value_date: str | None = None
    maturity_date: str | None = None
    raw_payload: str = ""
    warnings: list[str] = field(default_factory=list)
    #: For the UI: what the model was and wasn't confident about.
    fields_extracted: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)


SYSTEM_PROMPT = (
    "You extract structured confirmation fields from a raw treasury "
    "message. The message may be a SWIFT MT300 or MT320, an email, a "
    "broker note, or text pasted from a PDF.\n\n"
    "Rules:\n"
    "1. Return every field you can identify with confidence. Leave a "
    "field null if the message does not clearly state it. Never invent "
    "figures.\n"
    "2. counterparty_name must match one of the names in the "
    "counterparties list exactly, or be null. Do not translate, "
    "abbreviate or shorten a name.\n"
    "3. instrument is one of: DEPOSIT, FX_FORWARD, MMF, GILT. Read from "
    "the message: a currency pair or 'we buy/sell' pattern is FX_FORWARD; "
    "a placed/matured amount at a rate for a term is DEPOSIT.\n"
    "4. principal_pence is the deposit amount in pence — GBP 3,000,000 "
    "is 300000000. For a forward, the amount sold in the base currency.\n"
    "5. rate_bp is basis points: a deposit at 4.20 per cent is 420, an "
    "FX forward rate of 1.1740 is 11740.\n"
    "6. value_date and maturity_date are ISO dates (YYYY-MM-DD).\n"
    "7. Reply as JSON:\n"
    "   {\n"
    "     \"message_type\": \"MT300\"|\"MT320\"|\"MT535\"|\"MT536\"|"
    "\"BROKER_NOTE\"|\"DOCUMENT\"|null,\n"
    "     \"reference\": \"...\"|null,\n"
    "     \"counterparty_name\": \"exact match\"|null,\n"
    "     \"instrument\": \"DEPOSIT\"|\"FX_FORWARD\"|\"MMF\"|\"GILT\"|null,\n"
    "     \"principal_pence\": integer|null,\n"
    "     \"rate_bp\": integer|null,\n"
    "     \"value_date\": \"YYYY-MM-DD\"|null,\n"
    "     \"maturity_date\": \"YYYY-MM-DD\"|null,\n"
    "     \"warnings\": [\"...\"] (empty if nothing worth flagging)\n"
    "   }"
)

REQUIRED_FIELDS = (
    "counterparty_name",
    "instrument",
    "principal_pence",
    "rate_bp",
    "value_date",
)


def parse(
    session: Session,
    tenant_id: str,
    raw_text: str,
) -> ParsedConfirmation:
    """Extract structured fields from a raw confirmation message."""
    text = (raw_text or "").strip()
    if not text:
        return ParsedConfirmation(
            raw_payload="",
            warnings=["The message is empty."],
            fields_missing=list(REQUIRED_FIELDS),
        )

    counterparties = session.scalars(
        select(Counterparty).where(Counterparty.tenant_id == tenant_id)
    ).all()
    # Two indexes: the canonical name for exact match and a lowercased
    # version to catch SWIFT messages that arrive in ALL CAPS.
    name_lookup = {cp.name: cp.id for cp in counterparties}
    name_lookup_ci = {cp.name.lower(): (cp.id, cp.name) for cp in counterparties}
    name_list = "\n".join(f"- {cp.name}" for cp in counterparties)

    parsed = ParsedConfirmation(raw_payload=text)

    key = os.environ.get(KEY_VAR, "").strip()
    if not key:
        parsed.warnings.append(
            "The parser is unavailable (no model key). Key the fields by hand."
        )
        parsed.fields_missing = list(REQUIRED_FIELDS)
        return parsed

    try:
        from groq import Groq

        client = Groq(api_key=key, timeout=TIMEOUT_SECONDS)
        completion = client.chat.completions.create(
            model=os.environ.get(MODEL_VAR, DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Counterparties on the book:\n{name_list}\n\n"
                        f"Raw confirmation message:\n<<<\n{text}\n>>>"
                    ),
                },
            ],
            temperature=0,
            max_tokens=1200,
        )
        raw = (completion.choices[0].message.content or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in response")
        data: dict[str, Any] = json.loads(raw[start:end + 1])
    except Exception as cause:
        parsed.warnings.append(
            f"The parser could not read this. Key the fields by hand. "
            f"({type(cause).__name__})"
        )
        parsed.fields_missing = list(REQUIRED_FIELDS)
        return parsed

    parsed.message_type = _as_string(data.get("message_type"))
    parsed.reference = _as_string(data.get("reference"))
    name = _as_string(data.get("counterparty_name"))
    if name and name in name_lookup:
        parsed.counterparty_name = name
        parsed.counterparty_id = name_lookup[name]
    elif name and name.lower() in name_lookup_ci:
        # SWIFT messages arrive in ALL CAPS; email footers wrap in extra
        # whitespace. Resolve to the canonical name rather than let the
        # matcher refuse a real message on a formatting difference.
        canonical_id, canonical_name = name_lookup_ci[name.lower()]
        parsed.counterparty_name = canonical_name
        parsed.counterparty_id = canonical_id
    elif name:
        parsed.warnings.append(
            f'The counterparty "{name}" is not on the book. Choose one.'
        )
    parsed.instrument = _as_string(data.get("instrument"))
    parsed.principal_pence = _as_int(data.get("principal_pence"))
    parsed.rate_bp = _as_int(data.get("rate_bp"))
    parsed.value_date = _as_string(data.get("value_date"))
    parsed.maturity_date = _as_string(data.get("maturity_date"))

    warnings = data.get("warnings") or []
    if isinstance(warnings, list):
        parsed.warnings.extend(str(w) for w in warnings)

    # Sanity checks. Deterministic; not model-authored.
    if (
        parsed.rate_bp is not None
        and parsed.instrument == "DEPOSIT"
        and parsed.rate_bp > 2500
    ):
        parsed.warnings.append(
            "The rate reads over 25 per cent for a deposit — check the units."
        )
    if (
        parsed.value_date
        and parsed.maturity_date
        and parsed.maturity_date < parsed.value_date
    ):
        parsed.warnings.append(
            "Maturity is before value date — one of them is wrong."
        )
    if parsed.principal_pence is not None and parsed.principal_pence <= 0:
        parsed.warnings.append("Principal cannot be zero or negative.")

    # Build the extracted/missing lists so the modal can show them.
    field_values = {
        "message_type": parsed.message_type,
        "reference": parsed.reference,
        "counterparty_name": parsed.counterparty_name,
        "instrument": parsed.instrument,
        "principal_pence": parsed.principal_pence,
        "rate_bp": parsed.rate_bp,
        "value_date": parsed.value_date,
        "maturity_date": parsed.maturity_date,
    }
    for name_, value in field_values.items():
        if value is None or value == "":
            if name_ in REQUIRED_FIELDS:
                parsed.fields_missing.append(name_)
        else:
            parsed.fields_extracted.append(name_)

    return parsed


def _as_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None
