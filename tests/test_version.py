"""Tests for release metadata consistency."""

from pathlib import Path

from tether import __version__


def test_package_version_matches_pyproject() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
