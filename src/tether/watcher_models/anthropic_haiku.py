"""Haiku-backed WatcherModel implementation.

Hardened for production use: retries transient API errors with exponential
backoff, enforces a per-call timeout, and retries once when the model
returns text instead of a tool call. Every call is logged for cost tracking.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

import anthropic

from tether.state.store import EventLog, estimate_cost_usd

_log = logging.getLogger(__name__)


_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.5


class HaikuWatcherModel:
    """WatcherModel backed by Claude Haiku 4.5.

    Uses tool-use for all calls to guarantee structured output.
    Logs every call to the EventLog for cost tracking.

    Parameters
    ----------
    api_key : API key (falls back to ANTHROPIC_API_KEY env var).
    event_log : optional EventLog for cost tracking.
    session_id : session ID for the EventLog.
    budget_usd : per-session cost cap. Raises BudgetExceededError when hit.
    max_tokens : max output tokens per call.
    timeout_seconds : per-request timeout.
    max_retries : transient error retry count (total attempts = max_retries + 1).
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
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            timeout=timeout_seconds,
        )
        self._event_log = event_log
        self._session_id = session_id
        self._budget_usd = budget_usd
        self._session_cost: float = 0.0
        self._max_tokens = max_tokens
        self._max_retries = max_retries

    @property
    def session_cost_usd(self) -> float:
        return self._session_cost

    def check(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
        *,
        max_tokens: int | None = None,
    ) -> dict:
        """Call Haiku with tool-use and return the tool_input dict.

        Retries transient API errors (rate limits, overload, 5xx, network) with
        exponential backoff. If the model returns text instead of a tool call,
        retries once with a stricter nudge.
        """
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

        tokens = max_tokens or self._max_tokens
        last_err: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self.MODEL,
                    max_tokens=tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[tool_def],
                    tool_choice={"type": "tool", "name": tool_name},
                )
            except _TRANSIENT_ERRORS as e:
                last_err = e
                if attempt >= self._max_retries:
                    raise WatcherModelError(
                        f"Transient API error after {attempt + 1} attempts: {e}"
                    ) from e
                delay = _compute_backoff(attempt)
                _log.warning(
                    "Transient error from Anthropic API (attempt %d/%d): %s. "
                    "Retrying in %.1fs.",
                    attempt + 1, self._max_retries + 1, e, delay,
                )
                time.sleep(delay)
                continue
            except anthropic.BadRequestError as e:
                # Non-retryable. Surface with context for debugging.
                raise WatcherModelError(
                    f"Anthropic API rejected the request: {e}"
                ) from e

            # Record cost regardless of whether we got a tool_use block
            self._record_usage(response, tool_name)

            # Extract the tool call
            tool_input = _extract_tool_input(response, tool_name)
            if tool_input is not None:
                return tool_input

            # Model returned text instead of a tool call — retry once with a nudge
            if attempt == 0:
                _log.warning(
                    "Model did not call tool '%s' on first attempt; retrying.",
                    tool_name,
                )
                user = user + (
                    "\n\nReminder: you MUST respond by calling the "
                    f"`{tool_name}` tool. Do not respond with plain text."
                )
                continue

            raise WatcherModelError(
                f"Model did not call the expected tool '{tool_name}' "
                f"after {attempt + 1} attempts. Response: {response.content!r}"
            )

        # Unreachable
        raise WatcherModelError(f"Exhausted retries: {last_err}")

    def _record_usage(self, response: Any, tool_name: str) -> None:
        """Record token usage and cost for a completed response."""
        try:
            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
        except AttributeError:
            return

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Retryable errors only. APIStatusError is NOT included because it's the
# parent of BadRequestError, AuthenticationError, etc. — retrying a 400
# will just fail the same way three more times and waste budget. We
# explicitly enumerate the transient subclasses.
_TRANSIENT_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
    anthropic.RateLimitError,
)


def _compute_backoff(attempt: int) -> float:
    """Exponential backoff with jitter. attempt is 0-indexed."""
    base = _BACKOFF_BASE_SECONDS * (2 ** attempt)
    jitter = random.uniform(0, base * 0.25)
    return min(base + jitter, 30.0)


def _extract_tool_input(response: Any, tool_name: str) -> dict | None:
    """Find the tool_use block matching tool_name. Returns None if not found."""
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return block.input  # type: ignore[no-any-return]
    return None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WatcherModelError(RuntimeError):
    """Raised when the watcher model returns an unexpected response."""


class BudgetExceededError(RuntimeError):
    """Raised when the session cost budget is exceeded."""
