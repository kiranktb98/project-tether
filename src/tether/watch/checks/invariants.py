"""Watch check: static invariant check using tree-sitter snapshots.

Detects when a function signature changes or an exported symbol disappears
without any LLM calls — purely structural.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tether.bootstrap.scanner import FileSymbols, _parse_file


@dataclass
class InvariantViolation:
    kind: str           # "signature_changed" | "symbol_removed"
    symbol: str
    detail: str


@dataclass
class InvariantResult:
    violations: list[InvariantViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0


# In-memory snapshot store: path -> FileSymbols at last snapshot
_snapshots: dict[str, FileSymbols] = {}


def take_snapshot(file_path: str | Path, project_root: str | Path = ".") -> None:
    """Capture the current symbol state of a file for future comparison."""
    path = Path(file_path)
    root = Path(project_root)
    syms = _parse_file(path, root)
    if syms is not None:
        key = str(path.resolve())
        _snapshots[key] = syms


def check_invariants(
    file_path: str | Path,
    project_root: str | Path = ".",
) -> InvariantResult:
    """Compare current file state against the last snapshot.

    Returns violations for changed signatures or removed symbols.
    """
    path = Path(file_path)
    root = Path(project_root)
    key = str(path.resolve())

    if key not in _snapshots:
        # No snapshot yet — take one and return clean
        take_snapshot(path, root)
        return InvariantResult()

    old_syms = _snapshots[key]
    new_syms = _parse_file(path, root)
    if new_syms is None:
        return InvariantResult()

    violations: list[InvariantViolation] = []

    # Build maps
    old_fns = {f.name: f.signature for f in old_syms.functions}
    new_fns = {f.name: f.signature for f in new_syms.functions}
    old_cls = {c.name: {m.name: m.signature for m in c.methods} for c in old_syms.classes}
    new_cls = {c.name: {m.name: m.signature for m in c.methods} for c in new_syms.classes}

    # Check top-level functions
    for fname, old_sig in old_fns.items():
        if fname not in new_fns:
            violations.append(InvariantViolation(
                kind="symbol_removed",
                symbol=fname,
                detail=f"Function '{fname}' was removed",
            ))
        elif new_fns[fname] != old_sig:
            violations.append(InvariantViolation(
                kind="signature_changed",
                symbol=fname,
                detail=f"Signature changed: '{old_sig}' -> '{new_fns[fname]}'",
            ))

    # Check classes and public methods
    for cname, old_methods in old_cls.items():
        if cname not in new_cls:
            violations.append(InvariantViolation(
                kind="symbol_removed",
                symbol=cname,
                detail=f"Class '{cname}' was removed",
            ))
            continue
        new_methods = new_cls[cname]
        for mname, old_sig in old_methods.items():
            if mname not in new_methods:
                violations.append(InvariantViolation(
                    kind="symbol_removed",
                    symbol=f"{cname}.{mname}",
                    detail=f"Method '{cname}.{mname}' was removed",
                ))
            elif new_methods[mname] != old_sig:
                violations.append(InvariantViolation(
                    kind="signature_changed",
                    symbol=f"{cname}.{mname}",
                    detail=(
                        f"Method signature changed: "
                        f"'{old_sig}' -> '{new_methods[mname]}'"
                    ),
                ))

    # Update snapshot after check
    _snapshots[key] = new_syms

    return InvariantResult(violations=violations)


def clear_snapshots() -> None:
    """Clear all snapshots (useful for testing)."""
    _snapshots.clear()
