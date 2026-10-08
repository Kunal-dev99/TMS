"""SecretsPort backed by process environment. Today's behaviour."""

from __future__ import annotations

import os


class EnvVarSecrets:
    name = "env_var"

    def get(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

    def rotate(self, key: str) -> None:
        # Env vars can't rotate themselves. Real vaults implement this.
        raise NotImplementedError("env_var adapter does not support rotation")
