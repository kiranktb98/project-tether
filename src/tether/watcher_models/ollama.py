"""Ollama-backed WatcherModel implementation.

Calls a locally-running Ollama server for zero-cost, offline analysis.
Uses tool-calling when the model supports it; falls back to JSON-mode
with schema-embedded prompting for simpler models.

Recommended models (best results first):
  qwen2.5:7b         — fast, good tool-calling support
  llama3.2:3b        — lightweight, acceptable quality
  mistral:7b         — solid structured output support

Usage example in config.yaml:
  watcher:
    provider: ollama
    model: qwen2.5:7b
    ollama_base_url: http://localhost:11434
"""

from __future__ import annotations

import json
import re
from typing import Any

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "qwen2.5:7b"
_REQUEST_TIMEOUT = 120.0  # seconds — local models can be slow on first token


class OllamaWatcherModel:
    """WatcherModel backed by a local Ollama server.

    Tries tool-calling first (Ollama /api/chat with tools field).
    Falls back to JSON-mode response with schema injected into the prompt
    for models that don't support tool-calling.

    No cost tracking — local models are free.
    """

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout: float = _REQUEST_TIMEOUT,
        event_log=None,
        session_id: str = "",
        budget_usd: float | None = None,  # accepted but ignored (local models are free)
    ) -> None:
        if not _HTTPX_AVAILABLE:
            raise ImportError(
                "httpx is required for the Ollama backend. "
                "Install it with: pip install httpx"
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._event_log = event_log
        self._session_id = session_id
        # Session cost is always 0 for local models, but we expose the
        # attribute so callers that check session_cost_usd don't break.
        self.session_cost_usd: float = 0.0

    def check(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Run a watcher check against the local Ollama model.

        Tries tool-calling first; falls back to JSON-mode on failure.

        Returns the structured dict matching tool_schema.
        """
        try:
            return self._check_with_tools(system, user, tool_name, tool_schema)
        except OllamaToolCallError:
            return self._check_with_json_mode(system, user, tool_name, tool_schema)

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        """POST to the Ollama API and return the parsed JSON response."""
        url = f"{self._base_url}{path}"
        with httpx.Client(timeout=self._timeout) as client:
            try:
                resp = client.post(url, json=body)
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as exc:
                raise OllamaConnectionError(
                    f"Cannot reach Ollama at {self._base_url}. "
                    "Is the server running? Start it with: ollama serve"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise OllamaWatcherModelError(
                    f"Ollama API error {exc.response.status_code}: {exc.response.text}"
                ) from exc

    def _check_with_tools(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Attempt structured output via Ollama tool-calling API."""
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"Return the {tool_name} result.",
                        "parameters": tool_schema,
                    },
                }
            ],
            "stream": False,
        }

        data = self._post("/api/chat", body)

        msg = data.get("message", {})
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            raise OllamaToolCallError(
                f"Model did not emit a tool call for '{tool_name}'. "
                "Falling back to JSON mode."
            )

        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == tool_name:
                args = fn.get("arguments", {})
                # Ollama may return arguments as a string or dict
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as exc:
                        raise OllamaToolCallError(
                            f"Tool arguments were not valid JSON: {args}"
                        ) from exc
                return args

        raise OllamaToolCallError(
            f"Model called tools but none matched '{tool_name}'. "
            f"Got: {[tc.get('function', {}).get('name') for tc in tool_calls]}"
        )

    def _check_with_json_mode(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Fallback: ask for a JSON response matching the schema."""
        schema_str = json.dumps(tool_schema, indent=2)
        json_system = (
            f"{system}\n\n"
            f"You MUST respond with a single JSON object matching this schema:\n"
            f"```json\n{schema_str}\n```\n"
            f"Do not include any explanation — only output the JSON object."
        )

        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": json_system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "stream": False,
        }

        data = self._post("/api/chat", body)
        content = data.get("message", {}).get("content", "")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from the response if there's surrounding text
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError as exc:
                    raise OllamaWatcherModelError(
                        f"Could not parse JSON from model response: {content[:200]}"
                    ) from exc
            else:
                raise OllamaWatcherModelError(
                    f"Model response contained no JSON object: {content[:200]}"
                )

        if not isinstance(parsed, dict):
            raise OllamaWatcherModelError(
                f"Expected a JSON object, got {type(parsed).__name__}: {content[:200]}"
            )

        return parsed


class OllamaConnectionError(RuntimeError):
    """Raised when the Ollama server cannot be reached."""


class OllamaToolCallError(RuntimeError):
    """Raised when tool-calling fails (triggers JSON mode fallback)."""


class OllamaWatcherModelError(RuntimeError):
    """Raised when the Ollama model returns an unexpected response."""
