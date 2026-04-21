"""Static codebase scanner using tree-sitter.

Walks the project root, extracts top-level functions, classes, and module
docstrings for every supported language (Python, JavaScript, TypeScript,
TSX) and builds a file -> symbol map. No LLM calls here — pure static
analysis.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser


# ---------------------------------------------------------------------------
# Data structures (public — used by invariants.py and bootstrap proposer)
# ---------------------------------------------------------------------------

@dataclass
class FunctionSymbol:
    name: str
    signature: str          # e.g. "def foo(x: int, y: str) -> bool" / "function foo(a, b)"
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
    language: str = "python"

    def to_yaml_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.language,
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
# Shared tree-sitter helpers
# ---------------------------------------------------------------------------

def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Language adapters
# ---------------------------------------------------------------------------

@dataclass
class _LangAdapter:
    name: str
    extensions: tuple[str, ...]
    parser: Parser
    parse_fn: Callable[["_LangAdapter", bytes], tuple[str, list[FunctionSymbol], list[ClassSymbol]]]

    def parse(self, source: bytes) -> tuple[str, list[FunctionSymbol], list[ClassSymbol]]:
        return self.parse_fn(self, source)


# -- Python --------------------------------------------------------------

def _py_get_docstring(node: Node, source: bytes) -> str:
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
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and raw.endswith(q) and len(raw) > 2 * len(q):
                            return raw[len(q) : -len(q)].strip()
                        if raw.startswith(q) and raw.endswith(q):
                            return raw[len(q) : -len(q)].strip()
            break
    return ""


def _py_build_signature(node: Node, source: bytes) -> str:
    """Return 'def name(params) -> return_type' from a function_definition node."""
    parts = []
    for child in node.children:
        if child.type in ("def", "name", "parameters", "->", "type", "identifier"):
            parts.append(_node_text(child, source))
        if child.type == "block":
            break
    return " ".join(parts).strip()


def _py_parse(adapter: _LangAdapter, source: bytes) -> tuple[str, list[FunctionSymbol], list[ClassSymbol]]:
    tree = adapter.parser.parse(source)
    root = tree.root_node
    doc = _py_get_docstring(root, source)
    functions: list[FunctionSymbol] = []
    classes: list[ClassSymbol] = []

    for node in root.children:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                sig = _py_build_signature(node, source)
                functions.append(FunctionSymbol(name=name, signature=sig))
        elif node.type == "class_definition":
            class_name_node = node.child_by_field_name("name")
            if not class_name_node:
                continue
            class_name = _node_text(class_name_node, source)
            cls = ClassSymbol(name=class_name, docstring=_py_get_docstring(node, source))
            body = node.child_by_field_name("body")
            if body:
                for item in body.children:
                    if item.type == "function_definition":
                        mname_node = item.child_by_field_name("name")
                        if mname_node:
                            mname = _node_text(mname_node, source)
                            if not mname.startswith("_") or mname in ("__init__", "__call__"):
                                msig = _py_build_signature(item, source)
                                cls.methods.append(FunctionSymbol(
                                    name=mname, signature=msig,
                                    is_method=True, class_name=class_name,
                                ))
            classes.append(cls)
    return doc, functions, classes


# -- JavaScript / TypeScript / TSX ---------------------------------------

def _js_module_docstring(root: Node, source: bytes) -> str:
    """Use the leading top-of-file comment block, if any, as a stand-in
    for a module docstring. Supports both block (/** ... */) and line
    (// ...) forms."""
    for child in root.children:
        if child.type == "comment":
            raw = _node_text(child, source).strip()
            # Strip /* */ or // prefix
            if raw.startswith("/**"):
                raw = raw[3:]
            elif raw.startswith("/*"):
                raw = raw[2:]
            if raw.endswith("*/"):
                raw = raw[:-2]
            lines = []
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("* "):
                    line = line[2:]
                elif line == "*":
                    line = ""
                elif line.startswith("//"):
                    line = line[2:].strip()
                lines.append(line)
            return "\n".join(lines).strip()
        # Only inspect the very first non-trivial node.
        if child.type not in ("comment",):
            break
    return ""


def _js_build_function_signature(name: str, params_node: Node | None, source: bytes,
                                 *, keyword: str = "function") -> str:
    params = _node_text(params_node, source) if params_node is not None else "()"
    # Normalise whitespace
    params = " ".join(params.split())
    return f"{keyword} {name}{params}".strip()


def _js_build_method_signature(name: str, params_node: Node | None, source: bytes) -> str:
    params = _node_text(params_node, source) if params_node is not None else "()"
    params = " ".join(params.split())
    return f"{name}{params}"


def _js_unwrap_export(node: Node) -> Node:
    """If node is an export_statement, return its first meaningful child;
    otherwise return node itself."""
    if node.type != "export_statement":
        return node
    for child in node.children:
        if child.type in (
            "function_declaration", "class_declaration",
            "lexical_declaration", "variable_declaration",
            "interface_declaration", "type_alias_declaration",
            "enum_declaration",
        ):
            return child
    return node


def _js_top_level_function_from_declarator(decl: Node, source: bytes) -> FunctionSymbol | None:
    """Handle `const foo = (a, b) => ...` and `const foo = function(a, b) {}`."""
    name_node = decl.child_by_field_name("name")
    value_node = decl.child_by_field_name("value")
    if name_node is None or value_node is None:
        return None
    if value_node.type not in ("arrow_function", "function", "function_expression"):
        return None
    name = _node_text(name_node, source)
    params = value_node.child_by_field_name("parameters")
    keyword = "const" if value_node.type == "arrow_function" else "function"
    sig = _js_build_function_signature(name, params, source, keyword=keyword)
    return FunctionSymbol(name=name, signature=sig)


def _js_class_methods(class_node: Node, class_name: str, source: bytes) -> list[FunctionSymbol]:
    methods: list[FunctionSymbol] = []
    body = class_node.child_by_field_name("body")
    if body is None:
        for child in class_node.children:
            if child.type == "class_body":
                body = child
                break
    if body is None:
        return methods
    for item in body.children:
        if item.type != "method_definition":
            continue
        name_node = item.child_by_field_name("name")
        params_node = item.child_by_field_name("parameters")
        if name_node is None:
            # Some grammars expose the name as a direct property_identifier
            for c in item.children:
                if c.type in ("property_identifier", "identifier"):
                    name_node = c
                    break
        if name_node is None:
            continue
        mname = _node_text(name_node, source)
        # Skip `#private` and `_private` (keep constructor/getters/setters explicit)
        if mname.startswith("#") or (mname.startswith("_") and mname != "constructor"):
            continue
        sig = _js_build_method_signature(mname, params_node, source)
        methods.append(FunctionSymbol(
            name=mname, signature=sig, is_method=True, class_name=class_name,
        ))
    return methods


def _js_parse(adapter: _LangAdapter, source: bytes) -> tuple[str, list[FunctionSymbol], list[ClassSymbol]]:
    tree = adapter.parser.parse(source)
    root = tree.root_node
    doc = _js_module_docstring(root, source)
    functions: list[FunctionSymbol] = []
    classes: list[ClassSymbol] = []

    for raw_node in root.children:
        node = _js_unwrap_export(raw_node)

        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            if name_node is not None:
                name = _node_text(name_node, source)
                sig = _js_build_function_signature(name, params_node, source)
                functions.append(FunctionSymbol(name=name, signature=sig))

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            class_name = _node_text(name_node, source)
            cls = ClassSymbol(name=class_name)
            cls.methods = _js_class_methods(node, class_name, source)
            classes.append(cls)

        elif node.type in ("lexical_declaration", "variable_declaration"):
            for decl in node.children:
                if decl.type == "variable_declarator":
                    fn = _js_top_level_function_from_declarator(decl, source)
                    if fn is not None:
                        functions.append(fn)

    return doc, functions, classes


# ---------------------------------------------------------------------------
# Language registry
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, _LangAdapter] = {
    "python": _LangAdapter(
        name="python",
        extensions=(".py",),
        parser=Parser(Language(tspython.language())),
        parse_fn=_py_parse,
    ),
    "javascript": _LangAdapter(
        name="javascript",
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        parser=Parser(Language(tsjs.language())),
        parse_fn=_js_parse,
    ),
    "typescript": _LangAdapter(
        name="typescript",
        extensions=(".ts",),
        parser=Parser(Language(tsts.language_typescript())),
        parse_fn=_js_parse,
    ),
    "tsx": _LangAdapter(
        name="tsx",
        extensions=(".tsx",),
        parser=Parser(Language(tsts.language_tsx())),
        parse_fn=_js_parse,
    ),
}


def supported_extensions(languages: list[str] | None = None) -> tuple[str, ...]:
    """Return the union of file extensions for the given languages (or all)."""
    selected = _select_languages(languages)
    out: list[str] = []
    for lang in selected:
        out.extend(lang.extensions)
    return tuple(out)


def _select_languages(languages: list[str] | None) -> list[_LangAdapter]:
    if not languages:
        return list(_LANGUAGES.values())
    selected: list[_LangAdapter] = []
    for name in languages:
        # "polyglot" is the catch-all alias used in config.
        if name == "polyglot":
            return list(_LANGUAGES.values())
        if name == "typescript":
            # TSX is a superset of TS — selecting TS also includes TSX so
            # that `.tsx` files aren't silently skipped in TypeScript
            # projects.
            selected.append(_LANGUAGES["typescript"])
            selected.append(_LANGUAGES["tsx"])
            continue
        adapter = _LANGUAGES.get(name)
        if adapter is not None:
            selected.append(adapter)
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[_LangAdapter] = []
    for a in selected:
        if a.name not in seen:
            seen.add(a.name)
            out.append(a)
    return out


def _adapter_for_path(path: Path) -> _LangAdapter | None:
    suffix = path.suffix.lower()
    for adapter in _LANGUAGES.values():
        if suffix in adapter.extensions:
            return adapter
    return None


# ---------------------------------------------------------------------------
# File-level parse
# ---------------------------------------------------------------------------

def _parse_file(path: Path, root: Path) -> FileSymbols | None:
    """Parse a single source file and return its symbols, or None if the
    file can't be read or has no registered language adapter."""
    adapter = _adapter_for_path(path)
    if adapter is None:
        return None
    try:
        source = path.read_bytes()
    except (OSError, PermissionError):
        return None

    try:
        rel_path = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        rel_path = str(path).replace("\\", "/")

    doc, functions, classes = adapter.parse(source)
    return FileSymbols(
        path=rel_path,
        module_docstring=doc,
        functions=functions,
        classes=classes,
        language=adapter.name,
    )


# ---------------------------------------------------------------------------
# Public scan
# ---------------------------------------------------------------------------

DEFAULT_IGNORE_DIRS = {
    "__pycache__", ".git", ".tether", "node_modules",
    ".venv", "venv", "env", ".eggs", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    # JS/TS ecosystem noise
    ".next", ".nuxt", ".turbo", ".parcel-cache", ".cache",
    "coverage", "out", "target",
    # Skip test and documentation directories — they contain test fixtures
    # and generated tests, not project source features.
    "tests", "test", "docs", "examples", "fixtures",
}


def scan_project(
    root: str | Path,
    *,
    ignore_dirs: set[str] | None = None,
    max_files: int = 500,
    languages: list[str] | None = None,
) -> StaticScan:
    """Walk the project root, parse every file whose extension is known to
    one of the selected languages, return a StaticScan.

    Args:
        root:        Project root directory.
        ignore_dirs: Directory names to skip (added to the default set).
        max_files:   Hard cap on the number of files to parse.
        languages:   Language names to scan (e.g. ["python", "typescript"]).
                     Defaults to all registered languages. Pass ["polyglot"]
                     to be explicit about wanting everything.
    """
    root_path = Path(root).resolve()
    ignored = DEFAULT_IGNORE_DIRS | (ignore_dirs or set())
    scan = StaticScan(root=str(root_path))

    extensions = supported_extensions(languages)
    if not extensions:
        return scan

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in ignored]

        for filename in sorted(filenames):
            # Fast extension gate — avoids touching files we'd skip anyway.
            lower = filename.lower()
            if not any(lower.endswith(ext) for ext in extensions):
                continue
            if len(scan.files) >= max_files:
                break

            file_path = Path(dirpath) / filename
            syms = _parse_file(file_path, root_path)
            if syms is not None:
                scan.files.append(syms)

    return scan
