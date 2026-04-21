"""Lightweight project-local environment loading."""

from __future__ import annotations

import os
from pathlib import Path


def check_provider_ready(provider: str) -> str | None:
    """Return a human-readable error message if the watcher provider isn't
    usable, or None if the environment is ready.

    Centralized so every command (plan, watch, verify, ask, bootstrap) gives
    the same helpful hint instead of a one-liner.
    """
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        return (
            "ANTHROPIC_API_KEY is not set.\n"
            "  • Get a key at https://console.anthropic.com/\n"
            "  • Export it: export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  • Or put it in a .env file at the project root\n"
            "  • Or use local Ollama: set watcher.provider: ollama in .tether/config.yaml"
        )
    return None


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
