"""phase 2 substrate: 11 additive tables for the Treasury Register Connector

Revision ID: a91c4e2f0d05
Revises: d6a2e91b31c4
Create Date: 2026-09-23 09:30:00.000000

Every table is additive, mostly nullable, and populated only when the
corresponding adapter lands. See PHASE_2_IMPLEMENTATION_PLAN.md §3.

Portable across SQLite + Postgres: no dialect-specific DDL, no partial
indexes (nothing that far along), simple UNIQUE + CHECK + FK.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a91c4e2f0d05"
down_revision: Union[str, None] = "d6a2e91b31c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every table's tenant_id needs a FK to tenant + an index — the
    # models' _tenant() factory does that in ORM, so migrations must
    # match or the model/migration parity test fails.

    op.create_table(
        "oracle_entity_mapping",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("business_unit_name", sa.String(length=200), nullable=False),
        sa.Column("legal_entity_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"], ["legal_entity.id"], name="fk_oem_legal_entity"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["app_user.id"], name="fk_oem_created_by"
        ),
        sa.UniqueConstraint(
            "tenant_id", "business_unit_name", name="ux_oem_bu_per_tenant"
        ),
    )
    op.create_index(
        "ix_oracle_entity_mapping_tenant_id", "oracle_entity_mapping", ["tenant_id"]
    )

    op.create_table(
        "gl_account_map",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("event_kind", sa.String(length=40), nullable=False),
        sa.Column("legal_entity_id", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("account_combination_debit", sa.String(length=120), nullable=False),
        sa.Column("account_combination_credit", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"], ["legal_entity.id"], name="fk_gam_legal_entity"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["app_user.id"], name="fk_gam_created_by"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_kind",
            "legal_entity_id",
            "currency",
            name="ux_gam_lookup",
        ),
        sa.CheckConstraint(
            "event_kind in ("
            "'accrual','settlement_principal','settlement_interest',"
            "'reversal_accrual','fx_gain','fx_loss')",
            name="ck_gam_event_kind",
        ),
    )
    op.create_index(
        "ix_gl_account_map_tenant_id", "gl_account_map", ["tenant_id"]
    )

    op.create_table(
        "sso_identity",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("issuer", sa.String(length=400), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("first_seen_at", sa.String(length=30), nullable=False),
        sa.Column("last_seen_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_sso_identity_user"
        ),
        sa.UniqueConstraint(
            "provider", "issuer", "subject", name="ux_sso_identity_natural"
        ),
    )
    op.create_index("ix_sso_identity_user", "sso_identity", ["user_id"])
    op.create_index("ix_sso_identity_tenant_id", "sso_identity", ["tenant_id"])

    op.create_table(
        "sso_group_map",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("group_claim", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.UniqueConstraint(
            "tenant_id", "group_claim", "role", name="ux_sso_group_map"
        ),
    )
    op.create_index(
        "ix_sso_group_map_tenant_id", "sso_group_map", ["tenant_id"]
    )

    op.create_table(
        "ai_run",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.String(length=30), nullable=False),
        sa.Column("endpoint", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_completion", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "fallback_used", sa.String(length=5), nullable=False, server_default="false"
        ),
        sa.Column("subject_type", sa.String(length=32), nullable=True),
        sa.Column("subject_id", sa.String(length=60), nullable=True),
        sa.Column("human_decision_id", sa.String(length=60), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
    )
    op.create_index("ix_ai_run_occurred_at", "ai_run", ["occurred_at"])
    op.create_index("ix_ai_run_endpoint", "ai_run", ["endpoint", "occurred_at"])
    op.create_index("ix_ai_run_subject", "ai_run", ["subject_type", "subject_id"])
    op.create_index("ix_ai_run_tenant_id", "ai_run", ["tenant_id"])

    op.create_table(
        "cash_balance",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("legal_entity_id", sa.String(length=40), nullable=False),
        sa.Column("account_id", sa.String(length=60), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("as_of_date", sa.String(length=10), nullable=False),
        sa.Column("opening_balance_pence", sa.Integer(), nullable=False),
        sa.Column("closing_balance_pence", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("received_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["legal_entity_id"],
            ["legal_entity.id"],
            name="fk_cash_balance_legal_entity",
        ),
        sa.UniqueConstraint(
            "tenant_id", "account_id", "as_of_date", name="ux_cash_balance_daily"
        ),
    )
    op.create_index(
        "ix_cash_balance_le_date", "cash_balance", ["legal_entity_id", "as_of_date"]
    )
    op.create_index(
        "ix_cash_balance_tenant_id", "cash_balance", ["tenant_id"]
    )

    op.create_table(
        "market_snapshot",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("pair", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("tenor_months", sa.Integer(), nullable=True),
        sa.Column("rate_micro", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("as_of", sa.String(length=30), nullable=False),
        sa.Column("used_in_subject_type", sa.String(length=32), nullable=False),
        sa.Column("used_in_subject_id", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.CheckConstraint(
            "kind in ('SPOT','FORWARD','BENCHMARK')", name="ck_market_snapshot_kind"
        ),
    )
    op.create_index(
        "ix_market_snapshot_subject",
        "market_snapshot",
        ["used_in_subject_type", "used_in_subject_id"],
    )
    op.create_index(
        "ix_market_snapshot_tenant_id", "market_snapshot", ["tenant_id"]
    )

    op.create_table(
        "bank_ack",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("uetr", sa.String(length=40), nullable=False),
        sa.Column("deal_instruction_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("bank_reference", sa.String(length=120), nullable=True),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["deal_instruction_id"],
            ["oracle_instruction.id"],
            name="fk_bank_ack_instruction",
        ),
        sa.UniqueConstraint("tenant_id", "uetr", name="ux_bank_ack_uetr"),
        sa.CheckConstraint(
            "status in ('ACCEPTED','REJECTED','PENDING')",
            name="ck_bank_ack_status",
        ),
    )
    op.create_index("ix_bank_ack_tenant_id", "bank_ack", ["tenant_id"])

    op.create_table(
        "gl_posting_ack",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("external_reference", sa.String(length=120), nullable=False),
        sa.Column("accrual_id", sa.String(length=40), nullable=True),
        sa.Column("settlement_id", sa.String(length=40), nullable=True),
        sa.Column("ledger_journal_id", sa.String(length=60), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("posted_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["accrual_id"], ["accrual.id"], name="fk_gl_ack_accrual"
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"], ["settlement.id"], name="fk_gl_ack_settlement"
        ),
        sa.UniqueConstraint(
            "tenant_id", "external_reference", name="ux_gl_ack_external_ref"
        ),
    )
    op.create_index(
        "ix_gl_posting_ack_tenant_id", "gl_posting_ack", ["tenant_id"]
    )

    op.create_table(
        "integration_health",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=True),
        sa.Column("port", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("last_success_at", sa.String(length=30), nullable=True),
        sa.Column("last_error_at", sa.String(length=30), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("updated_at", sa.String(length=30), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "port", "provider", name="ux_integration_health_key"
        ),
    )

    op.create_table(
        "data_snapshot",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=60), nullable=False),
        sa.Column("as_of", sa.String(length=30), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
    )
    op.create_index(
        "ix_data_snapshot_entity",
        "data_snapshot",
        ["entity_type", "entity_id", "as_of"],
    )
    op.create_index(
        "ix_data_snapshot_tenant_id", "data_snapshot", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_data_snapshot_tenant_id", table_name="data_snapshot")
    op.drop_index("ix_data_snapshot_entity", table_name="data_snapshot")
    op.drop_table("data_snapshot")
    op.drop_table("integration_health")
    op.drop_index("ix_gl_posting_ack_tenant_id", table_name="gl_posting_ack")
    op.drop_table("gl_posting_ack")
    op.drop_index("ix_bank_ack_tenant_id", table_name="bank_ack")
    op.drop_table("bank_ack")
    op.drop_index("ix_market_snapshot_tenant_id", table_name="market_snapshot")
    op.drop_index("ix_market_snapshot_subject", table_name="market_snapshot")
    op.drop_table("market_snapshot")
    op.drop_index("ix_cash_balance_tenant_id", table_name="cash_balance")
    op.drop_index("ix_cash_balance_le_date", table_name="cash_balance")
    op.drop_table("cash_balance")
    op.drop_index("ix_ai_run_tenant_id", table_name="ai_run")
    op.drop_index("ix_ai_run_subject", table_name="ai_run")
    op.drop_index("ix_ai_run_endpoint", table_name="ai_run")
    op.drop_index("ix_ai_run_occurred_at", table_name="ai_run")
    op.drop_table("ai_run")
    op.drop_index("ix_sso_group_map_tenant_id", table_name="sso_group_map")
    op.drop_table("sso_group_map")
    op.drop_index("ix_sso_identity_tenant_id", table_name="sso_identity")
    op.drop_index("ix_sso_identity_user", table_name="sso_identity")
    op.drop_table("sso_identity")
    op.drop_index("ix_gl_account_map_tenant_id", table_name="gl_account_map")
    op.drop_table("gl_account_map")
    op.drop_index(
        "ix_oracle_entity_mapping_tenant_id", table_name="oracle_entity_mapping"
    )
    op.drop_table("oracle_entity_mapping")
