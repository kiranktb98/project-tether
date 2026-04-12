"""Tests for project-local environment loading."""

from __future__ import annotations

import os
from pathlib import Path

from tether.env import load_project_env


def test_load_project_env_sets_missing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "ANTHROPIC_API_KEY=sk-test\n"
        "PLAIN=value\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PLAIN", raising=False)

    loaded = load_project_env(env_file)

    assert loaded == env_file
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"
    assert os.environ["PLAIN"] == "value"


def test_load_project_env_preserves_existing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('ANTHROPIC_API_KEY="from-file"\n', encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")

    load_project_env(env_file)

    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"
