"""S2 — planner settings and rate curve survive a process restart,
and don't leak between tenants.

Before this change, both lived in module-level singletons that reset on
restart and were shared across all tenants. The DB-backed replacement
must keep each tenant's values isolated and reload them on a cold session.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import seed_data as s
from app.models import Base, Tenant
from app.services import planner_settings, system_policy
from seed.seed import load


# --------------------------------------------------------------------- fixtures


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'persist.db'}", future=True)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, future=True)
    db = factory()
    load(db)
    # Seed a second tenant so leak tests have somewhere to compare against.
    db.add(Tenant(id="ten_other", name="Second Tenant", created_at="2026-01-01T00:00:00Z"))
    db.commit()
    db.close()
    return eng, factory


# --------------------------------------------------------------------- planner settings


def test_planner_settings_survive_a_fresh_session(engine):
    _, factory = engine

    db1 = factory()
    planner_settings.update_settings(
        db1, s.TENANT_ID, {"max_tenor_months": 18, "min_rating": "A"}
    )
    db1.commit()
    db1.close()

    db2 = factory()
    try:
        reloaded = planner_settings.get_settings(db2, s.TENANT_ID)
    finally:
        db2.close()

    assert reloaded.max_tenor_months == 18
    assert reloaded.min_rating == "A"


def test_planner_settings_are_per_tenant(engine):
    _, factory = engine
    db = factory()
    try:
        planner_settings.update_settings(
            db, s.TENANT_ID, {"max_tenor_months": 24}
        )
        planner_settings.update_settings(
            db, "ten_other", {"max_tenor_months": 6}
        )
        db.commit()

        a = planner_settings.get_settings(db, s.TENANT_ID)
        b = planner_settings.get_settings(db, "ten_other")
    finally:
        db.close()

    assert a.max_tenor_months == 24
    assert b.max_tenor_months == 6


def test_planner_reset_restores_defaults(engine):
    _, factory = engine
    db = factory()
    try:
        planner_settings.update_settings(
            db, s.TENANT_ID, {"max_tenor_months": 24, "per_name_cap_pct": 50}
        )
        db.commit()

        planner_settings.reset_defaults(db, s.TENANT_ID)
        db.commit()

        reloaded = planner_settings.get_settings(db, s.TENANT_ID)
    finally:
        db.close()

    defaults = planner_settings.PlannerSettings()
    assert reloaded.max_tenor_months == defaults.max_tenor_months
    assert reloaded.per_name_cap_pct == defaults.per_name_cap_pct


def test_planner_get_without_prior_write_returns_defaults(engine):
    _, factory = engine
    db = factory()
    try:
        s_values = planner_settings.get_settings(db, s.TENANT_ID)
    finally:
        db.close()
    defaults = planner_settings.PlannerSettings()
    assert s_values.min_rating == defaults.min_rating
    assert s_values.buckets == defaults.buckets


# --------------------------------------------------------------------- rate curve


def test_rate_curve_survives_a_fresh_session(engine):
    _, factory = engine
    db1 = factory()
    system_policy.update_rate_curve(
        db1, s.TENANT_ID, {"AAA": {"3": 999}}
    )
    db1.commit()
    db1.close()

    db2 = factory()
    try:
        curve = system_policy.get_rate_curve(db2, s.TENANT_ID)
    finally:
        db2.close()
    assert curve["AAA"][3] == 999


def test_rate_curve_is_per_tenant(engine):
    _, factory = engine
    db = factory()
    try:
        system_policy.update_rate_curve(db, s.TENANT_ID, {"AAA": {"3": 777}})
        system_policy.update_rate_curve(db, "ten_other", {"AAA": {"3": 123}})
        db.commit()

        a = system_policy.get_rate_curve(db, s.TENANT_ID)
        b = system_policy.get_rate_curve(db, "ten_other")
    finally:
        db.close()
    assert a["AAA"][3] == 777
    assert b["AAA"][3] == 123


def test_rate_curve_reset_restores_defaults(engine):
    _, factory = engine
    db = factory()
    try:
        system_policy.update_rate_curve(db, s.TENANT_ID, {"AAA": {"3": 1}})
        db.commit()
        system_policy.reset_rate_curve(db, s.TENANT_ID)
        db.commit()
        curve = system_policy.get_rate_curve(db, s.TENANT_ID)
    finally:
        db.close()
    # Default seed for AAA / 3-month is 385 bp.
    assert curve["AAA"][3] == 385
