"""tether ask — natural-language interface to the feature ledger.

Ask any question about your project's features and get an answer
grounded in the actual ledger content.

Examples
--------
    tether ask "what features use auth.py?"
    tether ask "which features would break if I changed the rate limiter?"
    tether ask "what are the must-handle edge cases for feature f2?"
    tether ask "what does the middleware feature do and what could go wrong?"
"""

from __future__ import annotations

import os

import yaml
from rich.console import Console
from rich.markdown import Markdown

from tether.config import load_config
from tether.ledger.store import load_ledger
from tether.state.store import EventLog, ensure_tether_dir
from tether.state.manifest import SessionManifest
from tether.watcher_models import create_watcher_model

console = Console(legacy_windows=False)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_ASK_SYSTEM = """You are an expert software architect answering questions about
a specific project's feature set. You have been given the full feature ledger
for this project — a structured description of every feature, what it does,
which files it lives in, and what edge cases it must handle.

Answer the user's question using only information that can be derived from the
ledger. Be specific and reference feature IDs (e.g. f1, f2) when relevant.
If the question asks about risk or impact, reason through which features share
files or state with the relevant code and explain the risk clearly.

Format your answer in clean markdown with headers where useful. Be concise but
thorough — a developer making an architectural decision is reading this."""

_ASK_TOOL_NAME = "answer_question"
_ASK_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "Markdown-formatted answer to the question.",
        },
        "referenced_feature_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of features referenced in the answer.",
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "How confidently the ledger answers this question.",
        },
    },
    "required": ["answer", "confidence"],
}


def run_ask(
    question: str,
    config_path: str | None = None,
    verbose: bool = False,
) -> None:
    """Answer a natural-language question about the project's feature ledger."""
    cfg = load_config(config_path)
    tether_dir = ensure_tether_dir(".tether")

    if cfg.watcher.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is not set.")
        return

    ledger = load_ledger(cfg.ledger.path)
    if not ledger.features:
        console.print(
            "[yellow]Ledger is empty.[/yellow] "
            "Run [cyan]tether bootstrap[/cyan] first."
        )
        return

    event_log = EventLog(tether_dir)
    manifest = SessionManifest.load(tether_dir) or SessionManifest(tether_dir)
    model = create_watcher_model(cfg, event_log=event_log, session_id=manifest.session_id)

    # Build a compact ledger summary for the prompt
    ledger_yaml = _ledger_to_prompt_yaml(ledger)

    user_msg = f"""Project: {cfg.project.name}

Feature ledger:
{ledger_yaml}

Question: {question}"""

    console.print(f"\n[dim]Consulting ledger ({len(ledger.features)} features)...[/dim]\n")

    raw = model.check(
        system=_ASK_SYSTEM,
        user=user_msg,
        tool_name=_ASK_TOOL_NAME,
        tool_schema=_ASK_TOOL_SCHEMA,
    )

    answer = raw.get("answer", "")
    confidence = raw.get("confidence", "medium")
    referenced = raw.get("referenced_feature_ids", [])

    console.print(Markdown(answer))

    footer_parts = [f"confidence: {confidence}"]
    if referenced:
        footer_parts.append(f"features: {', '.join(referenced)}")
    footer_parts.append(f"cost: ${model.session_cost_usd:.4f}")
    console.print(f"\n[dim]{' · '.join(footer_parts)}[/dim]\n")


def _ledger_to_prompt_yaml(ledger) -> str:
    """Render the ledger as a compact YAML for inclusion in the prompt."""
    features = []
    for f in ledger.features:
        must_handle = [
            ec.description for ec in f.edge_cases if ec.must_handle
        ]
        features.append({
            "id": f.id,
            "name": f.name,
            "description": f.description,
            "status": f.status.value,
            "files": f.files,
            "must_handle_edge_cases": must_handle,
        })
    return yaml.dump(features, default_flow_style=False, allow_unicode=True)
