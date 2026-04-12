"""Tests for the OllamaWatcherModel."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tether.watcher_models.ollama import (
    OllamaConnectionError,
    OllamaToolCallError,
    OllamaWatcherModel,
    OllamaWatcherModelError,
)


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["aligned", "drifted"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


def _make_tool_response(tool_name: str, args: dict) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": tool_name,
                        "arguments": args,
                    }
                }
            ],
        },
        "done": True,
    }


def _make_json_response(content: dict) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": json.dumps(content),
        },
        "done": True,
    }


# ---------------------------------------------------------------------------
# Tool-calling path
# ---------------------------------------------------------------------------


def test_check_via_tool_call(monkeypatch):
    expected = {"verdict": "aligned", "reason": "looks good"}
    response_data = _make_tool_response("intent_verdict", expected)

    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        result = model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == expected


def test_tool_call_arguments_as_string(monkeypatch):
    """Ollama sometimes returns tool arguments as a JSON string."""
    args = {"verdict": "drifted", "reason": "broke tests"}
    response_data = _make_tool_response("intent_verdict", json.dumps(args))

    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        result = model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == args


def test_wrong_tool_name_raises_tool_call_error(monkeypatch):
    """If the model calls a different tool, raise OllamaToolCallError."""
    response_data = _make_tool_response("wrong_tool", {"x": 1})

    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        # Should fall through to JSON mode; mock a second call
        mock_client.post.side_effect = [
            mock_resp,  # first call: tool wrong name
        ]
        with pytest.raises((OllamaToolCallError, OllamaWatcherModelError)):
            model._check_with_tools("sys", "user", "intent_verdict", SIMPLE_SCHEMA)


# ---------------------------------------------------------------------------
# JSON-mode fallback
# ---------------------------------------------------------------------------


def test_json_mode_fallback(monkeypatch):
    """When tool calling returns no tool_calls, fall through to JSON mode."""
    expected = {"verdict": "aligned", "reason": "fine"}

    no_tool_resp = MagicMock()
    no_tool_resp.json.return_value = {"message": {"content": "", "tool_calls": []}}
    no_tool_resp.raise_for_status = MagicMock()

    json_resp = MagicMock()
    json_resp.json.return_value = _make_json_response(expected)
    json_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [no_tool_resp, json_resp]
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        result = model.check("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == expected


def test_json_mode_extracts_embedded_json(monkeypatch):
    """JSON mode should extract a JSON object even if the model adds prose."""
    expected = {"verdict": "drifted", "reason": "test broke"}
    prose_response = f"Here is my answer:\n{json.dumps(expected)}\nDone."

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": prose_response}}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        result = model._check_with_json_mode("sys", "user", "intent_verdict", SIMPLE_SCHEMA)

    assert result == expected


def test_json_mode_raises_on_unparseable(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "this is not json at all"}}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        with pytest.raises(OllamaWatcherModelError):
            model._check_with_json_mode("sys", "user", "intent_verdict", SIMPLE_SCHEMA)


# ---------------------------------------------------------------------------
# Connection error
# ---------------------------------------------------------------------------


def test_connection_error_raises_ollama_connection_error(monkeypatch):
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client_cls.return_value = mock_client

        model = OllamaWatcherModel()
        with pytest.raises(OllamaConnectionError, match="ollama serve"):
            model._post("/api/chat", {})


# ---------------------------------------------------------------------------
# Session cost is always 0
# ---------------------------------------------------------------------------


def test_session_cost_is_zero():
    model = OllamaWatcherModel()
    assert model.session_cost_usd == 0.0
