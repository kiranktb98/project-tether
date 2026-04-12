"""WatcherModel protocol — the single interface all watcher models implement."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WatcherModel(Protocol):
    """A cheap model that answers structured checking questions.

    All tether analysis goes through this interface. The rule is:
    never use Sonnet/Opus here — only small, cheap models.
    """

    def check(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Run a single watcher check using tool-use for structured output.

        Args:
            system:      System prompt text.
            user:        User message text.
            tool_name:   Name of the tool the model must call.
            tool_schema: JSON Schema for the tool's input_schema.

        Returns:
            The tool_input dict from the model's tool_use response block.
        """
        ...
