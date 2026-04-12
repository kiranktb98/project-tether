"""Lightweight project-local environment loading."""

from __future__ import annotations

import os
from pathlib import Path


def load_project_env(env_path: str | Path = ".env") -> Path | None:
    """Load KEY=VALUE pairs from a local .env file if present."""
    path = Path(env_path)
    if not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)

    return path
