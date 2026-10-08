"""MailPort that prints instead of sending. Today's behaviour.

Every existing invite/reset/breach email path currently prints to
stdout; this adapter formalises that. Tests can override with a
capturing adapter via ``registry.override(MailPort, ...)``.
"""

from __future__ import annotations


class ConsoleMail:
    name = "console"

    def send(
        self, to: str, subject: str, body_text: str, body_html: str | None = None
    ) -> None:
        # One line per email so log-aggregating tests can grep.
        print(f"[mail:console] to={to!r} subject={subject!r} body={body_text!r}")
