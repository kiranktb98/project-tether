"""Tests for the .env.example scaffold in tether init."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tether.config import _ensure_env_example


@pytest.fixture
def in_tmp_cwd(tmp_path: Path):
    """Run tests in a fresh temp cwd so we don't pollute the repo."""
    prev = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)


def test_creates_env_example_when_missing(in_tmp_cwd: Path) -> None:
    written = _ensure_env_example()
    assert written is not None
    assert written.name == ".env.example"
    content = written.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" in content
    assert "ollama" in content.lower()


def test_does_not_overwrite_existing(in_tmp_cwd: Path) -> None:
    existing = in_tmp_cwd / ".env.example"
    existing.write_text("CUSTOM=value\n", encoding="utf-8")

    result = _ensure_env_example()

    # Must return None to signal "left alone", not the path that it did
    # NOT touch.
    assert result is None
    assert existing.read_text(encoding="utf-8") == "CUSTOM=value\n"
