"""
Unit tests for the tree-sitter based JS/TS parser.

Tests function detection, class detection, methods, and TypeScript-specific
features like generics and type annotations. Uses temp files to verify
the parser works end-to-end.

Runs locally without Docker. Skips tests if tree-sitter not installed.
"""

import os
import sys
import pytest
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api.parsers.tree_sitter_parser import parse_ts_file, is_available

tree_sitter_available = is_available()


def _parse_code(code: str, suffix: str) -> dict:
    """Write code to a temp file and parse it with tree-sitter."""
    with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as f:
        f.write(code)
        path = f.name
    try:
        return parse_ts_file(path)
    finally:
        os.unlink(path)


# ── Availability ──


def test_is_available():
    """tree-sitter should be available in this environment."""
    assert tree_sitter_available, (
        "tree-sitter not installed. Run: pip install tree-sitter tree-sitter-javascript tree-sitter-typescript"
    )


# ── JavaScript Tests ──


@pytest.mark.skipif(not tree_sitter_available, reason="tree-sitter not installed")
class TestJavaScriptParser:

    def test_regular_function(self):
        code = "function hello(name) { return name; }"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "hello"
        assert f["signature"] == "hello(name)"
        assert f["start_line"] == 1
        assert f["end_line"] == 1

    def test_arrow_function(self):
        code = "const add = (a, b) => a + b;"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "add"
        assert f["signature"] == "add(a, b)"

    def test_arrow_multiline(self):
        code = "const foo = () => {\n  return 42;\n};"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "foo"
        assert f["start_line"] == 1
        assert f["end_line"] == 3

    def test_async_function(self):
        code = "async function fetchData(url) { const r = await fetch(url); return r.json(); }"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "fetchData"
        assert "async" in f["signature"]
        assert f["signature"] == "async fetchData(url)"

    def test_generator_function(self):
        code = "function* gen() { yield 1; yield 2; }"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "gen"

    def test_export_default_function(self):
        code = "export default function run() { return 42; }"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "run"

    def test_named_export_function(self):
        code = "export function exportedFunc(input) { return input * 2; }"
        result = _parse_code(code, '.js')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "exportedFunc"

    def test_class_with_methods(self):
        code = """class MyClass {
  constructor(value) { this.value = value; }
  getName() { return this.value; }
  static getClassName() { return "MyClass"; }
  async process(data) { return data; }
}"""
        result = _parse_code(code, '.js')
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "MyClass"
        assert cls["start_line"] == 1
        assert cls["end_line"] == 6
        methods = cls["methods"]
        assert len(methods) == 4
        method_names = [m["name"] for m in methods]
        assert "constructor" in method_names
        assert "getName" in method_names
        assert "getClassName" in method_names
        assert "process" in method_names

    def test_function_calls(self):
        code = """function caller() {
  return callee(42);
}"""
        result = _parse_code(code, '.js')
        calls = result["calls"]
        assert len(calls) >= 1
        call_targets = [c["target"] for c in calls]
        assert "callee" in call_targets
        assert all(c["source"] == "caller" for c in calls if c["target"] == "callee")

    def test_no_duplicate_functions(self):
        """Same function should not be reported twice."""
        code = "function foo() { return 1; }\nfunction bar() { return 2; }"
        result = _parse_code(code, '.js')
        names = [f["name"] for f in result["functions"]]
        assert names == ["foo", "bar"]
        assert len(names) == 2


# ── TypeScript Tests ──


@pytest.mark.skipif(not tree_sitter_available, reason="tree-sitter not installed")
class TestTypeScriptParser:

    def test_typed_function(self):
        code = "function greet(name: string): void { console.log(name); }"
        result = _parse_code(code, '.ts')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "greet"
        assert "string" in f["signature"]
        assert ": void" in f["signature"]

    def test_generic_function(self):
        code = "function firstElement<T>(arr: T[]): T | undefined { return arr[0]; }"
        result = _parse_code(code, '.ts')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "firstElement"

    def test_arrow_generic(self):
        code = "const identity = <T>(arg: T): T => arg;"
        result = _parse_code(code, '.ts')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "identity"
        assert "T" in f.get("return_type", "")

    def test_exported_function(self):
        code = "export function exportedFn(input: number): number { return input * 2; }"
        result = _parse_code(code, '.ts')
        assert len(result["functions"]) == 1
        f = result["functions"][0]
        assert f["name"] == "exportedFn"

    def test_public_static_method(self):
        code = """class Service {
  public static getInstance(): Service { return new Service(); }
}"""
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "Service"
        methods = cls["methods"]
        assert len(methods) >= 1
        m = methods[0]
        assert m["name"] == "getInstance"
        assert "static" in m["signature"]
        assert ": Service" in m["signature"]

    def test_async_generic_method(self):
        code = """class Service {
  public async fetch<T>(url: string): Promise<T> { const r = await fetch(url); return r.json() as T; }
}"""
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 1
        methods = result["classes"][0]["methods"]
        method_names = [m["name"] for m in methods]
        assert "fetch" in method_names
        fetch = [m for m in methods if m["name"] == "fetch"][0]
        assert "async" in fetch["signature"]

    def test_getter_setter(self):
        code = """class Service {
  private _val: number = 0;
  get currentValue(): number { return this._val; }
  set currentValue(v: number) { this._val = v; }
}"""
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 1
        methods = result["classes"][0]["methods"]
        assert len(methods) == 2

    def test_abstract_class(self):
        code = """abstract class BaseRepository<T> {
  abstract find(id: string): Promise<T | null>;
  public count(): number { return 0; }
}"""
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "BaseRepository"
        assert len(cls["methods"]) >= 2

    def test_interface_declaration(self):
        code = """interface User {
  name: string;
  email: string;
}"""
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "User"

    def test_type_alias_not_class(self):
        """Type aliases should NOT create class entries."""
        code = "type UserID = string;"
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 0

    def test_return_type_stripped(self):
        """Return type annotation should not have double colons."""
        code = "function greet(name: string): void { return; }"
        result = _parse_code(code, '.ts')
        f = result["functions"][0]
        assert "::" not in f["signature"]
        assert f["signature"] == "greet(name: string): void"

    def test_interface_method_signatures(self):
        """Interface method signatures should be extracted."""
        code = """interface Repository<T> {
  find(id: string): Promise<T | null>;
  save(entity: T): Promise<void>;
}"""
        result = _parse_code(code, '.ts')
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert len(cls["methods"]) >= 2
        method_names = [m["name"] for m in cls["methods"]]
        assert "find" in method_names
        assert "save" in method_names


# ── Fallback behavior ──


def test_empty_file():
    """Empty file should return empty structure."""
    result = _parse_code("", '.js')
    assert result == {"functions": [], "classes": [], "calls": [], "imports": [], "extends": []}


def test_comment_only():
    """File with only comments should return empty structure."""
    result = _parse_code("// just a comment\n/* block */", '.js')
    assert result["functions"] == []
    assert result["classes"] == []


def test_unknown_extension():
    """Parser should return empty structure for unknown extensions."""
    result = _parse_code("function foo() {}", '.unknown')
    assert result == {"functions": [], "classes": [], "calls": [], "imports": [], "extends": []}
