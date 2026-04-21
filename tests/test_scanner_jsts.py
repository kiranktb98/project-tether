"""Tests for the multi-language scanner (JavaScript, TypeScript, TSX)."""

from __future__ import annotations

from pathlib import Path

from tether.bootstrap.scanner import (
    _parse_file,
    scan_project,
    supported_extensions,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

def test_js_top_level_function(tmp_path: Path) -> None:
    f = tmp_path / "a.js"
    f.write_text("export function add(a, b) { return a + b; }\n", encoding="utf-8")
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert syms.language == "javascript"
    names = [fn.name for fn in syms.functions]
    assert "add" in names
    sig = next(fn.signature for fn in syms.functions if fn.name == "add")
    assert "function add" in sig
    assert "(a, b)" in sig


def test_js_arrow_function_as_top_level(tmp_path: Path) -> None:
    f = tmp_path / "arrow.js"
    f.write_text("const mul = (a, b) => a * b;\n", encoding="utf-8")
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert any(fn.name == "mul" for fn in syms.functions)


def test_js_class_methods_with_underscore_skipped(tmp_path: Path) -> None:
    f = tmp_path / "cls.js"
    f.write_text(
        """
        export class Calc {
          constructor(x) { this.x = x; }
          double() { return this.x * 2; }
          _private() {}
        }
        """,
        encoding="utf-8",
    )
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert len(syms.classes) == 1
    cls = syms.classes[0]
    assert cls.name == "Calc"
    method_names = [m.name for m in cls.methods]
    assert "constructor" in method_names
    assert "double" in method_names
    assert "_private" not in method_names


def test_js_module_docstring_from_leading_block_comment(tmp_path: Path) -> None:
    f = tmp_path / "doc.js"
    f.write_text(
        "/**\n * Utility math helpers.\n */\nexport function id(x) { return x; }\n",
        encoding="utf-8",
    )
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert "Utility math helpers" in syms.module_docstring


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------

def test_ts_function_with_type_annotations(tmp_path: Path) -> None:
    f = tmp_path / "t.ts"
    f.write_text(
        "export function greet(name: string): string { return 'hi ' + name; }\n",
        encoding="utf-8",
    )
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert syms.language == "typescript"
    sig = next(fn.signature for fn in syms.functions if fn.name == "greet")
    assert "name: string" in sig


def test_ts_generic_class(tmp_path: Path) -> None:
    f = tmp_path / "g.ts"
    f.write_text(
        """
        export class Box<T> {
          value: T;
          constructor(v: T) { this.value = v; }
          unwrap(): T { return this.value; }
        }
        """,
        encoding="utf-8",
    )
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert len(syms.classes) == 1
    cls = syms.classes[0]
    assert cls.name == "Box"
    assert {m.name for m in cls.methods} == {"constructor", "unwrap"}


# ---------------------------------------------------------------------------
# TSX
# ---------------------------------------------------------------------------

def test_tsx_component_and_hook(tmp_path: Path) -> None:
    f = tmp_path / "W.tsx"
    f.write_text(
        """
        export const Widget = ({label}: {label: string}) => <div>{label}</div>;
        export function useCounter(init: number) { return [init, () => {}]; }
        """,
        encoding="utf-8",
    )
    syms = _parse_file(f, tmp_path)
    assert syms is not None
    assert syms.language == "tsx"
    names = {fn.name for fn in syms.functions}
    assert {"Widget", "useCounter"}.issubset(names)


# ---------------------------------------------------------------------------
# scan_project integration
# ---------------------------------------------------------------------------

def test_scan_project_picks_up_all_supported_languages(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "def py_fn(x): return x\n")
    _write(tmp_path / "src" / "b.js", "export function js_fn(a) { return a; }\n")
    _write(tmp_path / "src" / "c.ts", "export function ts_fn(a: number): number { return a; }\n")
    _write(tmp_path / "src" / "d.tsx", "export const D = () => <p/>;\n")

    scan = scan_project(tmp_path)
    by_lang = {f.language for f in scan.files}
    assert by_lang == {"python", "javascript", "typescript", "tsx"}


def test_scan_project_honours_language_filter(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "def py_fn(x): return x\n")
    _write(tmp_path / "src" / "b.js", "export function js_fn(a) { return a; }\n")

    scan = scan_project(tmp_path, languages=["python"])
    assert {f.language for f in scan.files} == {"python"}
    assert all(f.path.endswith(".py") for f in scan.files)


def test_scan_project_typescript_includes_tsx(tmp_path: Path) -> None:
    """Selecting 'typescript' should also pick up .tsx files — users
    typing `language: typescript` don't want their React components
    silently dropped."""
    _write(tmp_path / "src" / "a.ts", "export function f(): void {}\n")
    _write(tmp_path / "src" / "b.tsx", "export const B = () => <p/>;\n")

    scan = scan_project(tmp_path, languages=["typescript"])
    langs = {f.language for f in scan.files}
    assert langs == {"typescript", "tsx"}


def test_scan_project_polyglot_alias(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "def f(): pass\n")
    _write(tmp_path / "b.ts", "export function g(): void {}\n")

    scan = scan_project(tmp_path, languages=["polyglot"])
    assert {f.language for f in scan.files} == {"python", "typescript"}


def test_scan_project_skips_node_modules(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.js", "export function keep() {}\n")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "export function drop() {}\n")

    scan = scan_project(tmp_path)
    paths = [f.path for f in scan.files]
    assert any("a.js" in p for p in paths)
    assert not any("node_modules" in p for p in paths)


def test_supported_extensions_covers_all_languages() -> None:
    exts = set(supported_extensions())
    for e in (".py", ".js", ".jsx", ".ts", ".tsx"):
        assert e in exts
