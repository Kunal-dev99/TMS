"""Stage 1 acceptance: every adapter honours its port.

Runs each fake adapter through a small contract that its real
sibling must also honour. When the real Oracle / Xignite / Entra
adapters land, they run through the SAME test class and prove
interchangeability.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.connector import ports, registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset()
    yield
    registry.reset()


# --- Secrets ---------------------------------------------------------------


def test_env_var_secrets_reads_process_env(monkeypatch):
    monkeypatch.setenv("TREASURY_CONNECTOR_TEST_KEY", "hello")
    s = registry.get(ports.SecretsPort)
    assert isinstance(s, ports.SecretsPort)
    assert s.get("TREASURY_CONNECTOR_TEST_KEY") == "hello"
    assert s.get("does_not_exist", "fallback") == "fallback"


def test_local_file_secrets_reads_env_file(tmp_path, monkeypatch):
    envfile = tmp_path / ".env.local"
    envfile.write_text('FOO="bar baz"\nQUOTED=hi\n', encoding="utf-8")
    monkeypatch.setenv("SECRETS_PROVIDER", "local_file")
    # We need to override the path — local file adapter defaults to CWD.
    from app.connector.adapters.secrets.local_file import LocalFileSecrets

    s = LocalFileSecrets(path=envfile)
    assert s.get("FOO") == "bar baz"
    assert s.get("QUOTED") == "hi"
    assert s.get("missing", "nope") == "nope"


# --- Mail ------------------------------------------------------------------


def test_console_mail_prints_expected_line(capsys):
    m = registry.get(ports.MailPort)
    assert isinstance(m, ports.MailPort)
    m.send("a@example.com", "Hello", "Body text")
    out = capsys.readouterr().out
    assert "a@example.com" in out
    assert "Hello" in out


# --- LLM -------------------------------------------------------------------


def test_deterministic_llm_returns_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    llm = registry.get(ports.LLMPort)
    assert isinstance(llm, ports.LLMPort)
    r = llm.chat(system="s", user="u")
    assert r.fallback is True
    assert r.model == "deterministic"


def test_groq_llm_returns_fallback_without_key(monkeypatch):
    monkeypatch.delenv("TREASURY_MODEL_API_KEY", raising=False)
    # Default provider is groq; no key -> fallback.
    llm = registry.get(ports.LLMPort)
    r = llm.chat(system="s", user="u")
    assert r.fallback is True


# --- Market ---------------------------------------------------------------


def test_deterministic_market_returns_quote():
    mkt = registry.get(ports.MarketDataPort)
    assert isinstance(mkt, ports.MarketDataPort)
    q = mkt.spot("EUR_GBP")
    assert q.pair == "EUR_GBP"
    assert q.rate > 0
    assert q.source == "deterministic"


def test_deterministic_market_forward_bp_scales_with_tenor():
    mkt = registry.get(ports.MarketDataPort)
    q3 = mkt.forward("EUR_GBP", 3)
    q12 = mkt.forward("EUR_GBP", 12)
    # Forwards move away from spot with tenor — same sign guaranteed by
    # the deterministic engine's linear scale.
    assert q3.rate != q12.rate


# --- ERP -------------------------------------------------------------------


def test_fake_oracle_journal_is_idempotent_on_external_reference():
    from app.connector.ports import JournalEntry, JournalLine

    erp = registry.get(ports.ERPPort)
    assert isinstance(erp, ports.ERPPort)
    entry = JournalEntry(
        external_reference="TR:test:once",
        ledger_name="Northgate UK",
        accounting_date="2026-09-23",
        description="test",
        lines=[
            JournalLine(account_combination="01-100-4550", currency="GBP", credit_pence=1000),
            JournalLine(account_combination="01-100-2500", currency="GBP", debit_pence=1000),
        ],
    )
    a = erp.post_journal(entry)
    b = erp.post_journal(entry)
    # Same external_reference => same ledger_journal_id, no duplicate row.
    assert a.ledger_journal_id == b.ledger_journal_id
    assert len(erp.posted) == 1  # type: ignore[attr-defined]


def test_fake_oracle_pull_exposure_aggregates_by_currency(session):
    # Uses the `session` fixture from conftest — seeded book present.
    from app import seed_data as s

    registry.reset()
    erp = registry.get(ports.ERPPort)
    snap = erp.pull_exposure(
        tenant_id=s.TENANT_ID,
        legal_entity_id=s.DEFAULT_LEGAL_ENTITY,
        as_of=date.fromisoformat(s.CLOCK_DATE),
        currency="EUR",
    )
    assert snap.currency == "EUR"
    # Seed carries EUR exposures for the UK entity; totals >= 0 always.
    assert snap.gross_receivable_pence >= 0
    assert snap.gross_payable_pence >= 0


# --- Bank ------------------------------------------------------------------


def test_file_bank_writes_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("BANK_OUTBOX", str(tmp_path / "outbox"))
    monkeypatch.setenv("BANK_INBOX", str(tmp_path / "inbox"))
    # Reset so the adapter reads the new paths.
    from app.connector.adapters.bank import file_bank as fb
    import importlib

    importlib.reload(fb)
    registry.reset()

    from app.connector.ports import Payment

    bank = registry.get(ports.BankPort)
    assert isinstance(bank, ports.BankPort)
    ack = bank.submit_payment(
        Payment(
            uetr="test-uetr-001",
            debtor_account="GB00BARC00000000000000",
            creditor_account="DE00DEUT0000000000",
            amount_pence=100_000,
            currency="GBP",
            value_date="2026-09-24",
            reference="TEST-1",
        ),
        signature=b"\x00" * 32,
    )
    assert ack.status == "ACCEPTED"
    assert (tmp_path / "outbox").exists()
    files = list((tmp_path / "outbox").iterdir())
    assert len(files) == 1
    assert b"test-uetr-001" in files[0].read_bytes()


# --- Signing ---------------------------------------------------------------


def test_software_signing_produces_deterministic_output_across_calls():
    sign = registry.get(ports.SigningPort)
    assert isinstance(sign, ports.SigningPort)
    sig_a = sign.sign(b"hello world", "test-key")
    sig_b = sign.sign(b"hello world", "test-key")
    # RSA signatures on the same input with the same key are equal
    # under PKCS1v15; the fallback hash mode is also deterministic.
    assert sig_a == sig_b
    assert sig_a != sign.sign(b"different", "test-key")


# --- Identity --------------------------------------------------------------


def test_local_password_identity_verifies_a_valid_bearer(client):
    # `client` fixture signs in as Whitfield and sets the bearer header;
    # extract and verify via the port.
    token = client.headers["Authorization"].split()[1]
    idp = registry.get(ports.IdentityPort)
    assert isinstance(idp, ports.IdentityPort)
    assertion = idp.verify_bearer(token)
    assert assertion is not None
    assert assertion.subject  # non-empty user id


def test_local_password_identity_rejects_garbage_bearer():
    idp = registry.get(ports.IdentityPort)
    assert idp.verify_bearer("not-a-real-token") is None


# --- Registry mechanics ----------------------------------------------------


def test_registry_override_wins_over_env(monkeypatch):
    class Stub:
        name = "stub"

        def get(self, key, default=None):
            return "from-stub"

        def rotate(self, key):
            pass

    registry.override(ports.SecretsPort, Stub())
    s = registry.get(ports.SecretsPort)
    assert s.name == "stub"
    assert s.get("anything") == "from-stub"


def test_registry_reset_clears_bindings(monkeypatch):
    first = registry.get(ports.SecretsPort)
    registry.reset()
    monkeypatch.setenv("SECRETS_PROVIDER", "env_var")
    second = registry.get(ports.SecretsPort)
    assert first is not second
