"""BankPort skeleton — writes outbound payments to a local folder.

Dev-only. Every submitted payment lands in ``dev/outbox/`` as a
timestamped file matching the pain.001 shape a real bureau would
receive. Stage 5 replaces the placeholder file with a real serialiser.

Inbound polling reads ``dev/inbox/`` for MT / camt.053 samples. Same
files a real bureau would drop over SFTP.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.connector.ports import BankSubmissionAck, InboundMessage, Payment

OUTBOX = Path(os.environ.get("BANK_OUTBOX", "dev/outbox")).resolve()
INBOX = Path(os.environ.get("BANK_INBOX", "dev/inbox")).resolve()


class FileBank:
    name = "file_bank"

    def submit_payment(self, payment: Payment, signature: bytes) -> BankSubmissionAck:
        OUTBOX.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        fname = OUTBOX / f"payment-{stamp}-{payment.uetr}.xml"
        # Placeholder body — Stage 5 replaces with the real pain.001
        # serialiser. Shape is enough for tests to prove the flow.
        fname.write_bytes(
            b"<!-- pain.001 skeleton -->\n"
            + f"<UETR>{payment.uetr}</UETR>\n".encode()
            + f"<Amount ccy=\"{payment.currency}\">{payment.amount_pence}</Amount>\n".encode()
            + b"<Signature>" + signature.hex().encode() + b"</Signature>\n"
        )
        return BankSubmissionAck(
            uetr=payment.uetr,
            status="ACCEPTED",
            bank_reference=fname.name,
            reason_code=None,
            reason_text=None,
        )

    def poll_inbox(self) -> Iterable[InboundMessage]:
        if not INBOX.exists():
            return []
        out: list[InboundMessage] = []
        for path in sorted(INBOX.iterdir()):
            if not path.is_file():
                continue
            kind = _guess_kind(path.name)
            out.append(
                InboundMessage(
                    kind=kind,
                    body=path.read_bytes(),
                    received_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
            )
        return out


def _guess_kind(fname: str) -> str:
    lower = fname.lower()
    if "camt.053" in lower or "camt053" in lower:
        return "camt.053"
    if "mt940" in lower:
        return "MT940"
    if "mt300" in lower:
        return "MT300"
    if "mt320" in lower:
        return "MT320"
    return "unknown"
