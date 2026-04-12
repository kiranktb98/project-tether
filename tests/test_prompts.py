"""Tests for prompt template safety rails."""

from tether.prompts import templates


def test_bootstrap_prompt_discourages_test_fixture_features() -> None:
    text = templates.BOOTSTRAP_SYSTEM
    assert "Ignore tests, fixtures, sample projects, generated artifacts" in text
    assert "Avoid duplicate or near-duplicate features" in text


def test_test_generation_prompt_discourages_hallucinated_apis() -> None:
    text = templates.TEST_GEN_SYSTEM
    assert "Never invent classes, functions, methods, modules, or imports" in text
    assert "emit a minimal skipped pytest stub instead of guessing" in text
