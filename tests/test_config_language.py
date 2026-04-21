"""Tests for ProjectConfig.language validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tether.config import ProjectConfig, SUPPORTED_LANGUAGES


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_accepts_supported_languages(lang: str) -> None:
    cfg = ProjectConfig(language=lang)
    assert cfg.language == lang


def test_rejects_unknown_language() -> None:
    with pytest.raises(ValidationError) as exc:
        ProjectConfig(language="rust")
    assert "Unsupported language" in str(exc.value)


def test_default_language_is_python() -> None:
    assert ProjectConfig().language == "python"
