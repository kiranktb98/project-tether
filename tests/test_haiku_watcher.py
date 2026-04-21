"""Tests for HaikuWatcherModel retry / timeout / fallback behavior.

These tests mock the Anthropic SDK. The goal is to prove that:
- Transient errors are retried with backoff and eventually succeed.
- Non-retryable errors (BadRequest) surface immediately as WatcherModelError.
- A response that contains text instead of a tool_use block triggers one
  nudge-retry, then fails with a clear error.
- The budget cap is enforced before making any API call.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from tether.watcher_models.anthropic_haiku import (
    BudgetExceededError,
    HaikuWatcherModel,
    WatcherModelError,
    _compute_backoff,
    _extract_tool_input,
)


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}},
    "required": ["verdict"],
}


def _fake_tool_response(tool_name: str, payload: dict, *, input_tokens: int = 10, output_tokens: int = 5):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=payload)
    return SimpleNamespace(
        content=[block],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _fake_text_response(text: str, *, input_tokens: int = 10, output_tokens: int = 5):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(
        content=[block],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_successful_call_returns_tool_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    response = _fake_tool_response("intent_verdict", {"verdict": "aligned"})

    with patch("anthropic.Anthropic") as mock_client_cls:
        client = MagicMock()
        client.messages.create.return_value = response
        mock_client_cls.return_value = client

        model = HaikuWatcherModel(max_retries=0)
        result = model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == {"verdict": "aligned"}
    assert model.session_cost_usd > 0


def test_transient_error_is_retried(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # Skip actual sleeps during backoff to keep tests fast.
    monkeypatch.setattr(
        "tether.watcher_models.anthropic_haiku.time.sleep",
        lambda *_a, **_kw: None,
    )

    success = _fake_tool_response("intent_verdict", {"verdict": "aligned"})

    with patch("anthropic.Anthropic") as mock_client_cls:
        client = MagicMock()
        # Fail twice with a transient error, then succeed.
        client.messages.create.side_effect = [
            anthropic.APIConnectionError(request=MagicMock()),
            anthropic.APIConnectionError(request=MagicMock()),
            success,
        ]
        mock_client_cls.return_value = client

        model = HaikuWatcherModel(max_retries=3)
        result = model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == {"verdict": "aligned"}
    assert client.messages.create.call_count == 3


def test_exhausted_retries_raises_watcher_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "tether.watcher_models.anthropic_haiku.time.sleep",
        lambda *_a, **_kw: None,
    )

    with patch("anthropic.Anthropic") as mock_client_cls:
        client = MagicMock()
        client.messages.create.side_effect = anthropic.APIConnectionError(request=MagicMock())
        mock_client_cls.return_value = client

        model = HaikuWatcherModel(max_retries=2)
        with pytest.raises(WatcherModelError, match="Transient API error"):
            model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)


def test_bad_request_surfaces_immediately(monkeypatch):
    """A 400 should not be retried — retrying a malformed request is pointless."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    bad_resp = MagicMock()
    bad_resp.status_code = 400

    with patch("anthropic.Anthropic") as mock_client_cls:
        client = MagicMock()
        client.messages.create.side_effect = anthropic.BadRequestError(
            "bad schema", response=bad_resp, body=None
        )
        mock_client_cls.return_value = client

        model = HaikuWatcherModel(max_retries=3)
        with pytest.raises(WatcherModelError, match="rejected"):
            model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert client.messages.create.call_count == 1


def test_text_response_triggers_nudge_retry(monkeypatch):
    """If the model returns text instead of a tool call on attempt 0,
    the nudge reminder is appended and one more attempt is made."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    text_resp = _fake_text_response("I think it's aligned.")
    tool_resp = _fake_tool_response("intent_verdict", {"verdict": "aligned"})

    with patch("anthropic.Anthropic") as mock_client_cls:
        client = MagicMock()
        client.messages.create.side_effect = [text_resp, tool_resp]
        mock_client_cls.return_value = client

        model = HaikuWatcherModel(max_retries=2)
        result = model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == {"verdict": "aligned"}
    # Second call's user message should carry the nudge reminder.
    second_call = client.messages.create.call_args_list[1]
    second_user = second_call.kwargs["messages"][0]["content"]
    assert "intent_verdict" in second_user
    assert "MUST" in second_user


def test_budget_cap_blocks_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client_cls.return_value = MagicMock()

        model = HaikuWatcherModel(budget_usd=0.001)
        # Push the session past budget without making a real API call.
        model._session_cost = 1.0
        with pytest.raises(BudgetExceededError):
            model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)


def test_backoff_is_bounded():
    # Even at a very high attempt number, backoff is capped at 30s.
    assert _compute_backoff(0) < 5.0
    assert _compute_backoff(100) <= 30.0


def test_extract_tool_input_ignores_text_blocks():
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="noise"),
            SimpleNamespace(type="tool_use", name="right_tool", input={"ok": True}),
        ]
    )
    assert _extract_tool_input(response, "right_tool") == {"ok": True}
    assert _extract_tool_input(response, "other_tool") is None
