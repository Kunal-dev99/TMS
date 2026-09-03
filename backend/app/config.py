"""Configuration that does not belong in the database.

Two things live here and only two: secrets, and the address of something
outside the system. Everything a customer owns is versioned policy data in a
table, because a threshold in a config file is a threshold nobody can change
without a deployment.

`.env` is read if it is present, and it never overrides a variable that is
already set, so a real deployment sets environment variables and this file is
simply absent. It is in `.gitignore`, and it is the only place a key should
ever be written.
"""

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_ROOT / ".env"

#: Every variable the system reads, with what it is for. Named here so
#: `python -m app.config` can say what is set and what is missing without
#: printing any of the values.
KNOWN = {
    "TREASURY_DATABASE_URL": "Where the database is. Defaults to backend/treasury.db.",
    "TREASURY_TOKEN_SECRET": "Signs bearer tokens. Set this anywhere real.",
    "TREASURY_MODEL_API_KEY": "The advisory layer's model. Absent means the stub runs.",
    "TREASURY_MODEL_NAME": "Which model. Defaults to openai/gpt-oss-120b on Groq.",
    "TREASURY_API_ORIGIN": "Read by the frontend, not by this process.",
}

SECRETS = {"TREASURY_TOKEN_SECRET", "TREASURY_MODEL_API_KEY"}


def load_env_file(path: Path = ENV_FILE) -> int:
    """Read KEY=value lines. Deliberately small.

    No interpolation, no export keyword, no multi-line values. A file that
    needs any of those is a file that should be a real secret store.
    """
    if not path.exists():
        return 0

    loaded = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Never overrides. An environment variable set by whatever started
        # the process is more authoritative than a file on disk.
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


load_env_file()


def describe() -> str:
    """What is set, without printing anything that is a secret."""
    lines = ["Configuration:"]
    for name, purpose in KNOWN.items():
        value = os.environ.get(name)
        if value is None:
            state = "not set"
        elif name in SECRETS:
            state = f"set, {len(value)} characters"
        else:
            state = value
        lines.append(f"  {name:26} {state}")
        lines.append(f"  {'':26} {purpose}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
