#!/usr/bin/env bash
#
# First boot: run migrations, seed if the book is empty, start uvicorn.
# Every subsequent boot: run migrations (idempotent), skip the seed, start.
#
# The seed check looks for a specific seeded row rather than a table count,
# so a partially-migrated database triggers a seed too. `alembic upgrade
# head` is safe to re-run; it becomes a no-op when the DB is current.
#
# Railway sets PORT to whatever it wants; uvicorn binds to it. We default
# to 8000 so the script also works on a local machine.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[bootstrap] running alembic upgrade head"
python -m alembic upgrade head

echo "[bootstrap] checking whether the book is seeded"
export SEED_FX_DEMO=1
python - <<'PYEOF'
from app.db import SessionLocal
from app.models import Counterparty
from seed.seed import load

session = SessionLocal()
try:
    seeded = session.query(Counterparty).filter(
        Counterparty.id == "cp_meridian"
    ).count()
    if seeded == 0:
        print("[bootstrap] seeding the book")
        load(session)
        session.commit()
        print("[bootstrap] seeded")
    else:
        print("[bootstrap] book already present; skipping seed")
finally:
    session.close()
PYEOF

echo "[bootstrap] starting uvicorn on port ${PORT:-8000}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
