"""SecretsPort backed by ``.env.local`` beside the running process.

For dev only — a real deployment uses ``azure_key_vault`` or similar.
Reads the file once at construction; explicit ``reload()`` to refresh.
"""

from __future__ import annotations

import os
from pathlib import Path


class LocalFileSecrets:
    name = "local_file"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path.cwd() / ".env.local"
        self._cache: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._cache = {}
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            self._cache[k.strip()] = v.strip().strip('"').strip("'")

    def get(self, key: str, default: str | None = None) -> str | None:
        # Env still wins over the file; matches config.py's convention.
        if key in os.environ:
            return os.environ[key]
        return self._cache.get(key, default)

    def rotate(self, key: str) -> None:
        raise NotImplementedError("local_file adapter does not support rotation")
