"""Tether configuration — Pydantic schema, file I/O, and tether init flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, field_validator
from rich.console import Console
from rich.prompt import Confirm, Prompt

# Supported project languages. "polyglot" means scan every known language.
# Kept here rather than imported from the scanner so the config module
# stays import-cheap (no tree-sitter parsing work on load).
SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "polyglot")

console = Console()

# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------

class ProjectConfig(BaseModel):
    name: str = "my-project"
    root: str = "."
    language: str = "python"

    @field_validator("language")
    @classmethod
    def _validate_language(cls, v: str) -> str:
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{v}'. Must be one of: "
                f"{', '.join(SUPPORTED_LANGUAGES)}."
            )
        return v


class WatcherConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    budget_usd_per_session: float = 5.00
    ollama_base_url: str = "http://localhost:11434"


class WorkerConfig(BaseModel):
    agent: str = "claude_code"
    notes_file: str = "CLAUDE.md"
    plan_notes_file: str = ".tether/PLAN.md"
    drift_notes_file: str = ".tether/DRIFT.md"


class LedgerConfig(BaseModel):
    path: str = ".tether/ledger.yaml"
    history_dir: str = ".tether/ledger.history/"
    tests_dir: str = ".tether/tests/"


class ScanConfig(BaseModel):
    """Controls which directories the bootstrap scanner walks."""
    exclude_dirs: list[str] = Field(default_factory=list,
        description="Extra directory names to skip during bootstrap scanning "
                    "(in addition to the built-in defaults: tests, docs, examples, "
                    "__pycache__, .git, .tether, node_modules, dist, build, etc.).")


class WatchConfig(BaseModel):
    debounce_ms: int = 800
    preserve_globs: list[str] = Field(default_factory=list)
    ignore_globs: list[str] = Field(default_factory=lambda: [
        "**/__pycache__/**",
        "**/.git/**",
        ".tether/**",
        "**/node_modules/**",
    ])


class PlanConfig(BaseModel):
    impact_analysis: bool = True
    edge_case_generation: bool = True
    edge_case_count: int = 8
    ask_threshold: str = "medium"  # none|low|medium|high


class VerifyConfig(BaseModel):
    run_all_affected_tests: bool = True
    max_test_runtime_seconds: int = 30
    confidence_gate_threshold: float = 0.8
    require_confident_must_handle_tests: bool = True


class TetherConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    plan: PlanConfig = Field(default_factory=PlanConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = ".tether/config.yaml"


def load_config(config_path: str | None = None) -> TetherConfig:
    """Load config from disk, returning defaults if the file doesn't exist."""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    if not path.exists():
        return TetherConfig()
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return TetherConfig.model_validate(raw)


def save_config(cfg: TetherConfig, config_path: str | None = None) -> Path:
    """Persist config to disk. Creates parent directories if needed."""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(cfg.model_dump(), fh, default_flow_style=False, sort_keys=False)
    return path


# ---------------------------------------------------------------------------
# CLAUDE.md instructions block
# ---------------------------------------------------------------------------

_TETHER_BLOCK_START = "<!-- TETHER:INSTRUCTIONS START — managed by tether, do not edit by hand -->"
_TETHER_BLOCK_END = "<!-- TETHER:INSTRUCTIONS END -->"

CLAUDE_MD_INSTRUCTIONS = """\
<!-- TETHER:INSTRUCTIONS START — managed by tether, do not edit by hand -->
## Tether is active in this project

A tool called **tether** is helping coordinate changes in this project.
Tether maintains a "feature ledger" at `.tether/ledger.yaml` that tracks
every feature, its files, its edge cases, and its status. Before making
changes, you should consult tether and follow its guidance.

### Workflow rules

**Before making any non-trivial code change:**

1. Read `.tether/ledger.yaml` to see the current feature set.

2. Run `tether plan <file_path> --intent "<short description>"` for
   the file you're about to modify. This generates impact analysis at
   `.tether/PLAN.md`.

3. Read `.tether/PLAN.md`. If it contains "STOP — Ask user", **stop and
   ask the user about the risks before proceeding**. Do not make the
   change until the user has answered.

4. If the change adds a new feature, the plan output will also contain
   suggested edge cases. Implement the code to handle the ones marked
   `must_handle: true`.

**Before removing or replacing a feature:**

1. Edit `.tether/ledger.yaml` to mark the feature `removing`.
2. Then change the code.
3. After the change, run `tether verify` to update the ledger.

**Always check `.tether/DRIFT.md`** at the start of each turn. If it
contains a drift note, the most recent change broke something. Read the
note carefully and either fix the issue or, if the change was intentional,
update the ledger to reflect the new reality.

**After finishing a logical unit of work, run `tether verify`.** This
re-validates everything and updates the ledger.

### Why this matters

Tether catches two classes of mistakes that are otherwise easy to miss:

1. **Cross-feature regressions** — when a change to feature A
   accidentally breaks feature B because they share code.
2. **Missed edge cases** — when a new feature handles the happy path
   but misses common edge cases.

The cost of consulting tether (a few seconds per change) is much less
than the cost of discovering these mistakes hours later.
<!-- TETHER:INSTRUCTIONS END -->"""


def upsert_claude_md(notes_file: str = "CLAUDE.md") -> Path:
    """Write or update the tether instructions block in the notes file.

    If the file doesn't exist, create it with just the block.
    If the block already exists, replace it in place.
    Otherwise, prepend the block.
    """
    path = Path(notes_file)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        start_idx = existing.find(_TETHER_BLOCK_START)
        end_idx = existing.find(_TETHER_BLOCK_END)

        if start_idx != -1 and end_idx != -1:
            # Replace in-place
            before = existing[:start_idx]
            after = existing[end_idx + len(_TETHER_BLOCK_END):]
            new_content = before + CLAUDE_MD_INSTRUCTIONS + after
        else:
            # Prepend
            new_content = CLAUDE_MD_INSTRUCTIONS + "\n\n" + existing
    else:
        new_content = CLAUDE_MD_INSTRUCTIONS + "\n"

    path.write_text(new_content, encoding="utf-8")
    return path


def remove_tether_from_claude_md(notes_file: str = "CLAUDE.md") -> None:
    """Remove the tether block from the notes file (used by uninstall)."""
    path = Path(notes_file)
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    start_idx = content.find(_TETHER_BLOCK_START)
    end_idx = content.find(_TETHER_BLOCK_END)
    if start_idx == -1 or end_idx == -1:
        return
    before = content[:start_idx]
    after = content[end_idx + len(_TETHER_BLOCK_END):]
    path.write_text((before + after).strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# tether init flow
# ---------------------------------------------------------------------------

def run_init(config_path: str | None = None, verbose: bool = False) -> None:
    """Interactive setup wizard for tether init."""
    console.print("\n[bold cyan]Tether init[/bold cyan]\n")

    # Detect project name from CWD
    default_name = Path.cwd().name

    project_name = Prompt.ask(
        "Project name",
        default=default_name,
        console=console,
    )

    # Confirm API key is set
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        console.print(
            "\n[yellow]Warning:[/yellow] ANTHROPIC_API_KEY is not set. "
            "Tether's watcher model (Haiku) requires it.\n"
            "Set it before running [cyan]tether bootstrap[/cyan] or [cyan]tether watch[/cyan]."
        )

    # Build config
    cfg = TetherConfig()
    cfg.project.name = project_name

    # Write .tether/ directory structure
    tether_dir = Path(".tether")
    for subdir in ["ledger.history", "tests", "reports"]:
        (tether_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Save config
    out_path = save_config(cfg, config_path)
    console.print(f"\n[green]OK[/green] Config written to [cyan]{out_path}[/cyan]")

    # Update CLAUDE.md
    notes_path = upsert_claude_md(cfg.worker.notes_file)
    console.print(f"[green]OK[/green] Tether instructions written to [cyan]{notes_path}[/cyan]")

    # Update .gitignore (include .env so a real key isn't committed)
    _ensure_gitignore_entry(".tether/")
    _ensure_gitignore_entry(".env")

    # Scaffold a .env.example so new contributors see which vars they need
    # to set. We never overwrite an existing one — it may have been
    # customized.
    env_example_path = _ensure_env_example()
    if env_example_path:
        console.print(f"[green]OK[/green] Template written to [cyan]{env_example_path}[/cyan]")

    console.print(
        f"\n[green]Tether is ready.[/green] Run [cyan]tether bootstrap[/cyan] to scan "
        f"your codebase and build the initial feature ledger.\n"
    )


def _ensure_gitignore_entry(entry: str) -> None:
    """Add entry to .gitignore if not already present."""
    path = Path(".gitignore")
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        if any(line.strip() == entry.strip() for line in lines):
            return
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n# Tether runtime state\n{entry}\n")
    else:
        path.write_text(f"# Tether runtime state\n{entry}\n", encoding="utf-8")


_ENV_EXAMPLE_TEMPLATE = """\
# Tether reads these automatically via tether/env.py on startup.
# Copy this file to .env and fill in the values. Never commit .env itself.

# Required when watcher.provider = anthropic (the default).
# Get a key at https://console.anthropic.com/
ANTHROPIC_API_KEY=

# Not needed when watcher.provider = ollama. If you are using Ollama and
# your server isn't on the default port, set ollama_base_url in
# .tether/config.yaml instead.
"""


def _ensure_env_example() -> Path | None:
    """Create .env.example if it doesn't exist. Returns the path written,
    or None if the file already exists (in which case we leave it alone —
    the project may have customized which vars it documents)."""
    path = Path(".env.example")
    if path.exists():
        return None
    path.write_text(_ENV_EXAMPLE_TEMPLATE, encoding="utf-8")
    return path
