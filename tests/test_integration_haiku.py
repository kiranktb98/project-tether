"""Live integration smoke test for HaikuWatcherModel.

Skipped by default. Run explicitly with:
    pytest -m integration tests/test_integration_haiku.py

This test exists because the unit tests for HaikuWatcherModel all mock
the Anthropic SDK. If Anthropic changes the response shape, tool-use
schema, or pricing, mocks keep passing while production breaks. The
smoke test catches that — at the cost of a few cents per run.

Requires ANTHROPIC_API_KEY in the environment. If the key isn't set the
test self-skips so the marker alone doesn't fail CI on contributors
without an account.
"""

from __future__ import annotations

import os

import pytest

from tether.watcher_models.anthropic_haiku import HaikuWatcherModel


pytestmark = pytest.mark.integration


_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "integer", "description": "2 + 2"},
    },
    "required": ["answer"],
}


@pytest.fixture
def haiku_model() -> HaikuWatcherModel:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — integration test skipped")
    return HaikuWatcherModel(max_retries=1, timeout_seconds=30.0)


def test_live_tool_use_returns_structured_output(haiku_model: HaikuWatcherModel) -> None:
    """Minimum viable product: Haiku must accept a tool schema and return
    matching structured output. This is the one thing every watcher check
    depends on."""
    result = haiku_model.check(
        system="You are a math assistant. Use the tool to answer.",
        user="What is 2 + 2? Use the answer_math tool.",
        tool_name="answer_math",
        tool_schema=_SCHEMA,
    )
    assert isinstance(result, dict)
    assert "answer" in result
    assert result["answer"] == 4


def test_live_call_records_cost(haiku_model: HaikuWatcherModel) -> None:
    """session_cost_usd must update after a successful call — we rely on
    this for the per-session budget cap."""
    assert haiku_model.session_cost_usd == 0.0
    haiku_model.check(
        system="Answer using the tool.",
        user="2+2?",
        tool_name="answer_math",
        tool_schema=_SCHEMA,
    )
    assert haiku_model.session_cost_usd > 0.0
