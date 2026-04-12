"""Static codebase scanner using tree-sitter.

Walks all .py files in the project root, extracts top-level functions,
classes, and module docstrings, and builds a file -> symbol map.
No LLM calls here — pure static analysis.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_PY_LANGUAGE = Language(tspython.language())
_PARSER = Parser(_PY_LANGUAGE)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FunctionSymbol:
    name: str
    signature: str          # e.g. "def foo(x: int, y: str) -> bool"
    is_method: bool = False
    class_name: str = ""


@dataclass
class ClassSymbol:
    name: str
    methods: list[FunctionSymbol] = field(default_factory=list)
    docstring: str = ""


@dataclass
class FileSymbols:
    path: str               # relative to project root, forward-slash
    module_docstring: str = ""
    functions: list[FunctionSymbol] = field(default_factory=list)
    classes: list[ClassSymbol] = field(default_factory=list)

    def to_yaml_dict(self) -> dict:
        return {
            "path": self.path,
            "module_docstring": self.module_docstring,
            "functions": [
                {"name": f.name, "signature": f.signature}
                for f in self.functions
            ],
            "classes": [
                {
                    "name": c.name,
                    "docstring": c.docstring,
                    "methods": [
                        {"name": m.name, "signature": m.signature}
                        for m in c.methods
                    ],
                }
                for c in self.classes
            ],
        }


@dataclass
class StaticScan:
    """Result of scanning a project root."""
    root: str
    files: list[FileSymbols] = field(default_factory=list)

    def as_chunks(self, max_files_per_chunk: int = 20) -> list[list[FileSymbols]]:
        """Split the file list into chunks for batched LLM calls."""
        result = []
        for i in range(0, len(self.files), max_files_per_chunk):
            result.append(self.files[i : i + max_files_per_chunk])
        return result


# ---------------------------------------------------------------------------
# Tree-sitter helpers
# ---------------------------------------------------------------------------

def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_docstring(node: Node, source: bytes) -> str:
    """Extract docstring from the first statement of a function/class/module body."""
    body = None
    for child in node.children:
        if child.type in ("block", "module"):
            body = child
            break
    if body is None and node.type == "module":
        body = node

    if body is None:
        return ""

    for child in (body.children if body else []):
        if child.type == "expression_statement":
            for inner in child.children:
                if inner.type == "string":
                    raw = _node_text(inner, source)
                    # Strip quotes
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and raw.endswith(q) and len(raw) > 2 * len(q):
                            return raw[len(q) : -len(q)].strip()
                        if raw.startswith(q) and raw.endswith(q):
                            return raw[len(q) : -len(q)].strip()
            break
    return ""


def _build_function_signature(node: Node, source: bytes) -> str:
    """Return 'def name(params) -> return_type' from a function_definition node."""
    parts = []
    for child in node.children:
        if child.type in ("def", "name", "parameters", "->", "type", "identifier"):
            parts.append(_node_text(child, source))
        if child.type == "block":
            break
    return " ".join(parts).strip()


def _parse_file(path: Path, root: Path) -> FileSymbols | None:
    """Parse a single Python file and return its symbols."""
    try:
        source = path.read_bytes()
    except (OSError, PermissionError):
        return None

    tree = _PARSER.parse(source)
    rel_path = str(path.relative_to(root)).replace("\\", "/")
    file_syms = FileSymbols(path=rel_path)

    root_node = tree.root_node
    file_syms.module_docstring = _get_docstring(root_node, source)

    for node in root_node.children:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                sig = _build_function_signature(node, source)
                file_syms.functions.append(FunctionSymbol(name=name, signature=sig))

        elif node.type == "class_definition":
            class_name_node = node.child_by_field_name("name")
            if not class_name_node:
                continue
            class_name = _node_text(class_name_node, source)
            cls_sym = ClassSymbol(name=class_name)
            cls_sym.docstring = _get_docstring(node, source)

            body = node.child_by_field_name("body")
            if body:
                for item in body.children:
                    if item.type == "function_definition":
                        mname_node = item.child_by_field_name("name")
                        if mname_node:
                            mname = _node_text(mname_node, source)
                            # Only public methods (skip dunder except __init__)
                            if not mname.startswith("_") or mname in ("__init__", "__call__"):
                                sig = _build_function_signature(item, source)
                                cls_sym.methods.append(
                                    FunctionSymbol(
                                        name=mname,
                                        signature=sig,
                                        is_method=True,
                                        class_name=class_name,
                                    )
                                )
            file_syms.classes.append(cls_sym)

    return file_syms


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

DEFAULT_IGNORE_DIRS = {
    "__pycache__", ".git", ".tether", "node_modules",
    ".venv", "venv", "env", ".eggs", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    # Skip test and documentation directories — they contain test fixtures
    # and generated tests, not project source features.
    "tests", "test", "docs", "examples", "fixtures",
}


def scan_project(
    root: str | Path,
    *,
    ignore_dirs: set[str] | None = None,
    max_files: int = 500,
) -> StaticScan:
    """Walk the project root, parse every .py file, return a StaticScan.

    Args:
        root:        Project root directory.
        ignore_dirs: Directory names to skip (added to the default set).
        max_files:   Hard cap on the number of files to parse.
    """
    root_path = Path(root).resolve()
    ignored = DEFAULT_IGNORE_DIRS | (ignore_dirs or set())
    scan = StaticScan(root=str(root_path))

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune ignored directories in-place (prevents descent)
        dirnames[:] = [d for d in dirnames if d not in ignored]

        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            if len(scan.files) >= max_files:
                break

            file_path = Path(dirpath) / filename
            syms = _parse_file(file_path, root_path)
            if syms is not None:
                scan.files.append(syms)

    return scan
