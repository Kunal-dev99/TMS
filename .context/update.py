"""Regenerate the auto-derivable parts of the project context matrix.

Two files are ground-truth-derived and must not be hand-edited:

  api.json         — the FastAPI OpenAPI surface (routes, methods, tags)
  data-model.json  — SQLAlchemy metadata (tables, columns, constraints)

Everything else in .context/ is hand-authored: project.json, architecture.json,
frontend.json, backend.json, ai.json, conventions.json, decisions/, changes/.

Run from the repo root:

    python .context/update.py

The MANIFEST.json is bumped with fresh mtimes and SHAs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CTX = REPO_ROOT / ".context"
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else ""


def _mtime(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- api.json


def dump_api() -> None:
    from app.main import app  # type: ignore

    spec = app.openapi()
    endpoints = []
    for path in sorted(spec.get("paths", {})):
        methods = spec["paths"][path]
        for method in sorted(methods):
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            meta = methods[method]
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "tag": (meta.get("tags") or ["_untagged"])[0],
                    "summary": (meta.get("summary") or "").strip(),
                    "operation_id": meta.get("operationId", ""),
                    "has_body": bool(meta.get("requestBody")),
                    "responses": sorted((meta.get("responses") or {}).keys()),
                }
            )
    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "fastapi.openapi()",
        "base_prefix": "/api/v1",
        "count": len(endpoints),
        "endpoints_by_tag": {},
    }
    for e in endpoints:
        out["endpoints_by_tag"].setdefault(e["tag"], []).append(
            {k: v for k, v in e.items() if k != "tag"}
        )
    _write(CTX / "api.json", out)
    print(f"  api.json         {len(endpoints)} endpoints")


# ------------------------------------------------------- data-model.json


def dump_data_model() -> None:
    from app import models  # type: ignore

    md = models.Base.metadata
    tables = {}
    for name in sorted(md.tables):
        t = md.tables[name]
        cols = []
        for c in t.columns:
            cols.append(
                {
                    "name": c.name,
                    "type": str(c.type),
                    "nullable": bool(c.nullable),
                    "pk": bool(c.primary_key),
                    "fk": sorted(str(fk.column) for fk in c.foreign_keys) or None,
                    "default": str(c.default.arg) if c.default is not None and hasattr(c.default, "arg") else None,
                }
            )
        constraints = []
        for cc in t.constraints:
            klass = type(cc).__name__
            if klass == "PrimaryKeyConstraint":
                continue
            sqltext_val = getattr(cc, "sqltext", None)
            sqltext_str = str(sqltext_val) if sqltext_val is not None else ""
            constraints.append({"kind": klass, "name": cc.name, "sqltext": sqltext_str})
        indices = [{"name": i.name, "columns": [c.name for c in i.columns], "unique": bool(i.unique)} for i in t.indexes]
        tables[name] = {
            "columns": cols,
            "constraints": [c for c in constraints if c["sqltext"] or c["kind"] != "CheckConstraint"],
            "indices": indices,
        }
    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "app.models.Base.metadata",
        "table_count": len(tables),
        "tables": tables,
    }
    _write(CTX / "data-model.json", out)
    print(f"  data-model.json  {len(tables)} tables")


# ---------------------------------------------------------- MANIFEST.json


def dump_manifest() -> None:
    files = {}
    for p in sorted(CTX.rglob("*.json")):
        if p.name == "MANIFEST.json":
            continue
        rel = p.relative_to(CTX).as_posix()
        files[rel] = {"sha": _sha(p), "mtime": _mtime(p), "bytes": p.stat().st_size}
    decisions_index = sorted(
        (p.stem for p in (CTX / "decisions").glob("*.json") if p.stem != "INDEX")
    )
    changes_index = sorted((p.stem for p in (CTX / "changes").glob("*.json")))
    manifest = {
        "schema_version": 1,
        "project": "treasury-register",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "read_order_for_new_chats": [
            "project.json",
            "architecture.json",
            "conventions.json",
            "backend.json",
            "frontend.json",
            "data-model.json",
            "api.json",
            "ai.json",
            "roadmap.json",
        ],
        "files": files,
        "decisions": decisions_index,
        "changes_recent": changes_index[-10:],
        "open_questions_file": "open-questions.json",
    }
    _write(CTX / "MANIFEST.json", manifest)
    print(f"  MANIFEST.json    {len(files)} files indexed, {len(decisions_index)} decisions")


def main() -> None:
    print(f"[context] regenerating .context/ from {REPO_ROOT}")
    dump_api()
    dump_data_model()
    dump_manifest()
    print("[context] done. Commit .context/ with your code change.")


if __name__ == "__main__":
    main()
