"""Bootstrap Phase: open draft ledger in $EDITOR for user review."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from rich.console import Console

from tether.bootstrap.proposer import ProposedFeature
from tether.ledger.schema import EdgeCase, EdgeCaseFrequency, Feature, Ledger
from tether.ledger.store import save_ledger, validate_ledger_file
from tether.ledger.queries import apply_must_handle_rule

console = Console()

_REVIEW_INSTRUCTIONS = """\
# Tether feature ledger — review required
#
# These are tether's guesses about your project's features.
# Edit freely:
#   - Delete features that don't make sense
#   - Merge duplicates (just keep one)
#   - Add features tether missed
#   - Correct file paths
#   - Edit descriptions
#
# The accuracy of everything tether does later depends on this
# ledger being correct. Take 5 minutes now to review it.
#
# When you save and close this file, tether will validate the YAML
# and write the final .tether/ledger.yaml.
#
# Lines starting with '#' are comments and will be stripped.
# ============================================================

"""


def proposals_to_draft_yaml(proposals: list[ProposedFeature]) -> str:
    """Convert proposals to a human-editable YAML draft string."""
    features = []
    for i, prop in enumerate(proposals, start=1):
        features.append({
            "id": f"f{i}",
            "name": prop.name,
            "description": prop.description,
            "status": "active",
            "files": prop.files,
            "guessed_edge_cases": prop.guessed_edge_cases,
        })
    return yaml.dump(
        {"features": features},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def open_editor_for_review(draft_yaml: str) -> str:
    """Open the draft in $EDITOR and return the edited content.

    Falls back to printing instructions and asking for manual editing
    if no terminal editor is available.
    """
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        prefix="tether_draft_",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(_REVIEW_INSTRUCTIONS)
        tmp.write(draft_yaml)
        tmp_path = Path(tmp.name)

    if editor:
        try:
            subprocess.run([editor, str(tmp_path)], check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            console.print(
                f"[yellow]Could not open editor '{editor}'.[/yellow] "
                f"Please edit [cyan]{tmp_path}[/cyan] manually, then press Enter."
            )
            input()
    else:
        console.print(
            f"\n[yellow]No $EDITOR set.[/yellow] "
            f"Please edit [cyan]{tmp_path}[/cyan] manually, then press Enter to continue."
        )
        input()

    return tmp_path.read_text(encoding="utf-8")


def strip_comments(yaml_text: str) -> str:
    """Remove comment lines (starting with #) from YAML text."""
    lines = [ln for ln in yaml_text.splitlines() if not ln.lstrip().startswith("#")]
    return "\n".join(lines)


def parse_reviewed_ledger(edited_yaml: str) -> tuple[Ledger, list[str]]:
    """Parse edited YAML into a Ledger. Returns (ledger, errors)."""
    cleaned = strip_comments(edited_yaml)
    try:
        raw = yaml.safe_load(cleaned)
    except yaml.YAMLError as e:
        return Ledger(), [f"YAML parse error: {e}"]

    if raw is None or "features" not in raw:
        return Ledger(), ["No 'features' key found in ledger YAML"]

    ledger = Ledger()
    errors: list[str] = []

    for i, feat_raw in enumerate(raw.get("features", [])):
        if not isinstance(feat_raw, dict):
            errors.append(f"Feature {i}: expected a dict, got {type(feat_raw)}")
            continue
        if "id" not in feat_raw or "name" not in feat_raw:
            errors.append(f"Feature {i}: missing 'id' or 'name'")
            continue

        try:
            feature = Feature(
                id=feat_raw["id"],
                name=feat_raw["name"],
                description=feat_raw.get("description", ""),
                status=feat_raw.get("status", "active"),
                files=feat_raw.get("files", []),
            )
            feature.add_history("added", "Initial bootstrap")
            ledger.features.append(feature)
        except Exception as e:
            errors.append(f"Feature {feat_raw.get('id', i)}: {e}")

    return ledger, errors


def run_review_flow(
    proposals: list[ProposedFeature],
    ledger_path: str | Path,
    history_dir: str | Path,
    *,
    yes: bool = False,
) -> Ledger:
    """Full review flow: draft -> editor -> validate -> save.

    Loops until the user produces valid YAML.
    Pass yes=True to skip the editor and auto-accept proposals (useful for CI
    or non-interactive environments).
    """
    draft_yaml = proposals_to_draft_yaml(proposals)

    if yes:
        ledger, errors = parse_reviewed_ledger(draft_yaml)
        if errors:
            console.print("[red]Auto-accept failed:[/red]")
            for err in errors:
                console.print(f"  [red]*[/red] {err}")
            raise RuntimeError("Bootstrap proposals failed validation")
        save_ledger(ledger, ledger_path, history_dir=history_dir, snapshot=True)
        console.print(
            f"\n[green]OK[/green] Ledger written to [cyan]{ledger_path}[/cyan] "
            f"with {len(ledger.features)} features (auto-accepted, v{ledger.version}).\n"
            f"[dim]Tip: edit [cyan]{ledger_path}[/cyan] to correct any mis-identified features.[/dim]"
        )
        return ledger

    console.print(
        f"\n[bold]Review the proposed ledger[/bold]\n"
        f"Opening your editor with {len(proposals)} proposed features...\n"
    )

    while True:
        edited = open_editor_for_review(draft_yaml)
        ledger, errors = parse_reviewed_ledger(edited)

        if errors:
            console.print("\n[red]Validation errors:[/red]")
            for err in errors:
                console.print(f"  [red]*[/red] {err}")
            console.print("\nPlease fix the errors and try again.")
            # Use the edited content as the base for the next round
            draft_yaml = strip_comments(edited)
            continue

        if not ledger.features:
            console.print(
                "[yellow]Warning:[/yellow] No features in the ledger. "
                "Add at least one feature, or press Ctrl+C to cancel."
            )
            draft_yaml = strip_comments(edited)
            continue

        break

    save_ledger(ledger, ledger_path, history_dir=history_dir, snapshot=True)
    console.print(
        f"\n[green]OK[/green] Ledger written to [cyan]{ledger_path}[/cyan] "
        f"with {len(ledger.features)} features (v{ledger.version})."
    )
    return ledger
