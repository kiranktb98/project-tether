"""Haiku-backed WatcherModel implementation."""

from __future__ import annotations

import os
from typing import Any

import anthropic

from tether.state.store import EventLog, estimate_cost_usd


class HaikuWatcherModel:
    """WatcherModel backed by Claude Haiku 4.5.

    Uses tool-use for all calls to guarantee structured output.
    Logs every call to the EventLog for cost tracking.
    """

    # The watcher model must never be changed to Sonnet/Opus.
    MODEL = "claude-haiku-4-5-20251001"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        event_log: EventLog | None = None,
        session_id: str = "",
        budget_usd: float | None = None,
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        self._event_log = event_log
        self._session_id = session_id
        self._budget_usd = budget_usd
        self._session_cost: float = 0.0

    @property
    def session_cost_usd(self) -> float:
        return self._session_cost

    def check(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Call Haiku with tool-use and return the tool_input dict."""
        if self._budget_usd is not None and self._session_cost >= self._budget_usd:
            raise BudgetExceededError(
                f"Session budget of ${self._budget_usd:.2f} exceeded "
                f"(used ${self._session_cost:.4f})"
            )

        tool_def = {
            "name": tool_name,
            "description": f"Return the {tool_name} result.",
            "input_schema": tool_schema,
        }

        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool_def],
            tool_choice={"type": "any"},
        )

        # Extract cost
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cost = estimate_cost_usd(self.MODEL, input_tokens, output_tokens)
        self._session_cost += cost

        if self._event_log is not None:
            self._event_log.log_model_call(
                prompt_name=tool_name,
                model=self.MODEL,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                session_id=self._session_id,
            )

        # Find the tool_use block
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input  # type: ignore[return-value]

        raise WatcherModelError(
            f"Model did not call the expected tool '{tool_name}'. "
            f"Response content: {response.content}"
        )


class WatcherModelError(RuntimeError):
    """Raised when the watcher model returns an unexpected response."""


class BudgetExceededError(RuntimeError):
    """Raised when the session cost budget is exceeded."""
