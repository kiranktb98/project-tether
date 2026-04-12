"""WatcherModel implementations and factory."""

from tether.watcher_models.base import WatcherModel
from tether.watcher_models.anthropic_haiku import HaikuWatcherModel, BudgetExceededError, WatcherModelError


def create_watcher_model(cfg, *, event_log=None, session_id: str = "") -> WatcherModel:
    """Instantiate the correct WatcherModel from config.

    Reads cfg.watcher.provider:
      - "anthropic" (default) → HaikuWatcherModel
      - "ollama"              → OllamaWatcherModel
    """
    import os

    provider = getattr(cfg.watcher, "provider", "anthropic").lower()

    if provider == "ollama":
        from tether.watcher_models.ollama import OllamaWatcherModel
        base_url = getattr(cfg.watcher, "ollama_base_url", "http://localhost:11434")
        return OllamaWatcherModel(
            base_url=base_url,
            model=cfg.watcher.model,
            event_log=event_log,
            session_id=session_id,
            budget_usd=cfg.watcher.budget_usd_per_session,
        )

    # Default: Anthropic Haiku
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return HaikuWatcherModel(
        api_key=api_key,
        event_log=event_log,
        session_id=session_id,
        budget_usd=cfg.watcher.budget_usd_per_session,
    )


__all__ = [
    "WatcherModel",
    "HaikuWatcherModel",
    "BudgetExceededError",
    "WatcherModelError",
    "create_watcher_model",
]
