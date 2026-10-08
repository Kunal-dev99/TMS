"""Enforce PARKED_PLANS.json.

Every plan listed with ``status: "parked"`` is guaranteed to have
zero implementation on disk: no forbidden file exists, no forbidden
symbol appears in a source file. The moment someone starts building
without flipping ``status: "unparked"`` in PARKED_PLANS.json, this
test fails hard and CI refuses the change.

To start building a parked plan:
  1. Read the plan document.
  2. Change its ``status`` to ``unparked`` in ``PARKED_PLANS.json``.
  3. Commit that flip as its own commit — the diff is the audit
     record that the plan was consciously unparked.
  4. Then start writing code.

This is real enforcement. Not a comment, not a convention.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PARKED_PLANS = REPO_ROOT / "PARKED_PLANS.json"


def _load_plans() -> list[dict]:
    if not PARKED_PLANS.exists():
        pytest.skip(f"{PARKED_PLANS} not found — nothing to enforce")
    data = json.loads(PARKED_PLANS.read_text(encoding="utf-8"))
    return data.get("plans", [])


def _parked_plans() -> list[dict]:
    return [p for p in _load_plans() if p.get("status", "").lower() == "parked"]


def test_parked_plans_have_no_files_present():
    """No file listed under ``forbidden_while_parked.files`` may exist
    on disk while a plan is parked. A file starting to appear means
    someone is executing the plan without unparking it first."""
    failures: list[str] = []
    for plan in _parked_plans():
        forbidden = plan.get("forbidden_while_parked", {}).get("files", [])
        for rel in forbidden:
            path = REPO_ROOT / rel
            # A path may be a file OR a directory; both count.
            if path.exists():
                failures.append(
                    f"plan={plan['id']!r}: forbidden path exists: {rel}\n"
                    f"    -> either delete it, or flip {plan['id']} to 'unparked' "
                    f"in PARKED_PLANS.json (see plan.unpark_instructions)."
                )
    assert not failures, (
        "One or more parked plans appear to be under implementation:\n"
        + "\n".join(failures)
    )


def test_parked_plans_have_no_forbidden_symbols():
    """No forbidden symbol may appear in the named source file while a
    plan is parked. Symbols are matched by simple substring — if the
    plan document says ``MANAGE_INTEGRATIONS`` must not exist in
    ``permissions.py``, we grep for it."""
    failures: list[str] = []
    for plan in _parked_plans():
        symbols = plan.get("forbidden_while_parked", {}).get(
            "symbols_in_files", []
        )
        for entry in symbols:
            file_rel = entry["file"]
            symbol = entry["symbol"]
            path = REPO_ROOT / file_rel
            if not path.exists():
                # The file itself doesn't exist yet; if it's forbidden
                # anywhere else in this plan the file-check covers it.
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            if symbol in body:
                failures.append(
                    f"plan={plan['id']!r}: forbidden symbol {symbol!r} "
                    f"found in {file_rel}\n"
                    f"    -> flip {plan['id']} to 'unparked' in "
                    f"PARKED_PLANS.json first."
                )
    assert not failures, (
        "One or more parked plans have their forbidden symbols present:\n"
        + "\n".join(failures)
    )


def test_parked_plans_route_paths_not_registered_in_main_py():
    """FastAPI route prefixes reserved for a parked plan may not
    appear in ``backend/app/main.py``. Catches a router being
    registered before its plan is unparked."""
    main_py = REPO_ROOT / "backend" / "app" / "main.py"
    if not main_py.exists():
        pytest.skip("main.py not found; nothing to check")
    body = main_py.read_text(encoding="utf-8", errors="ignore")
    failures: list[str] = []
    for plan in _parked_plans():
        paths = plan.get("forbidden_while_parked", {}).get(
            "route_paths_in_main_py", []
        )
        for route in paths:
            if route in body:
                failures.append(
                    f"plan={plan['id']!r}: forbidden route {route!r} "
                    f"appears in main.py"
                )
    assert not failures, "\n".join(failures)


def test_parked_plans_no_forbidden_sql_in_migrations():
    """SQL patterns reserved for a parked plan (RLS, break-glass
    tables, etc.) may not appear in any Alembic migration while
    the plan is parked."""
    migrations_dir = REPO_ROOT / "backend" / "alembic" / "versions"
    if not migrations_dir.exists():
        pytest.skip("no alembic/versions directory")
    failures: list[str] = []
    for plan in _parked_plans():
        patterns = plan.get("forbidden_while_parked", {}).get(
            "sql_patterns_in_migrations", []
        )
        if not patterns:
            continue
        for mig in migrations_dir.glob("*.py"):
            body = mig.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                if pat in body:
                    failures.append(
                        f"plan={plan['id']!r}: forbidden SQL pattern "
                        f"{pat!r} appears in {mig.name}"
                    )
    assert not failures, "\n".join(failures)


def test_parked_plans_json_schema_stays_sane():
    """Every plan row has the fields the guards read; every 'status'
    is a known token. Catches a typo (e.g. 'unpark' instead of
    'unparked') that would silently disable the guard."""
    plans = _load_plans()
    assert plans, "PARKED_PLANS.json has no plans — did the file get corrupted?"
    for plan in plans:
        assert "id" in plan, plan
        assert "plan_document" in plan, plan
        assert plan.get("status") in ("parked", "unparked"), (
            f"plan {plan.get('id')!r} has unknown status {plan.get('status')!r} "
            f"— must be exactly 'parked' or 'unparked'."
        )
        if plan.get("status") == "parked":
            assert "forbidden_while_parked" in plan, (
                f"parked plan {plan['id']!r} missing forbidden_while_parked block"
            )
            assert "unpark_instructions" in plan, (
                f"parked plan {plan['id']!r} missing unpark_instructions"
            )
        # Every plan_document must exist on disk.
        assert (REPO_ROOT / plan["plan_document"]).exists(), (
            f"plan {plan['id']!r} references missing document {plan['plan_document']}"
        )
