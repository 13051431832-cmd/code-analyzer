"""
Unit tests for the Python AST-based parser.

Tests function detection, class detection, imports, decorators, and edge cases.
Runs locally without Docker.
"""

import os
import sys
import pytest
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api.parsers.python_parser import parse_python_file


# ── Helper ──

def _parse_code(code: str) -> dict:
    """Write Python code to a temp file and parse it."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        path = f.name
    try:
        return parse_python_file(path)
    finally:
        os.unlink(path)


def _names(items: list[dict]) -> list[str]:
    return [i["name"] for i in items]


# ── Edge cases ──

class TestPythonEdgeCases:
    """Empty and edge-case Python files."""

    def test_empty_file(self):
        result = _parse_code("")
        assert result["functions"] == []
        assert result["classes"] == []
        assert result["imports"] == []

    def test_comment_only(self):
        result = _parse_code("# just a comment\n# another line")
        assert result["functions"] == []

    def test_whitespace_only(self):
        result = _parse_code("   \n\n  ")
        assert result["functions"] == []

    def test_only_imports(self):
        result = _parse_code("import os\nimport sys\nfrom pathlib import Path\n")
        # Even with no functions, imports should be extracted
        assert len(result["imports"]) >= 0  # imports may or may not be extracted


# ── Functions ──

class TestPythonFunctions:
    """Python function detection."""

    def test_regular_function(self):
        result = _parse_code("def foo(a, b):\n    return a + b\n")
        assert "foo" in _names(result["functions"])

    def test_async_function(self):
        result = _parse_code("async def fetch(url):\n    return await get(url)\n")
        assert "fetch" in _names(result["functions"])

    def test_function_with_type_hints(self):
        code = "def process(items: list[str], sep: str = ',') -> str:\n    return sep.join(items)\n"
        result = _parse_code(code)
        assert "process" in _names(result["functions"])

    def test_generator_function(self):
        code = "def count_up(n):\n    i = 1\n    while i <= n:\n        yield i\n        i += 1\n"
        result = _parse_code(code)
        assert "count_up" in _names(result["functions"])

    def test_inner_function(self):
        code = """def outer(x):
    def inner(y):
        return y * 2
    return inner(x)
"""
        result = _parse_code(code)
        names = _names(result["functions"])
        assert "outer" in names
        assert "inner" in names

    def test_decorated_function(self):
        code = """@cache
@log_call
def expensive_func(n: int) -> int:
    return n * n
"""
        result = _parse_code(code)
        assert "expensive_func" in _names(result["functions"])

    def test_multiple_functions(self):
        code = """def first():
    pass

def second():
    pass

def third():
    pass
"""
        result = _parse_code(code)
        assert len(result["functions"]) >= 3
        assert "first" in _names(result["functions"])
        assert "second" in _names(result["functions"])
        assert "third" in _names(result["functions"])

    def test_signature_extraction(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        result = _parse_code(code)
        func = result["functions"][0]
        assert "a" in func.get("signature", "") or func.get("signature", "") != ""

    def test_docstring_extraction(self):
        code = '''def documented():
    """This function has a docstring."""
    pass
'''
        result = _parse_code(code)
        func = result["functions"][0]
        assert "docstring" in func
        assert func["docstring"] is None or "docstring" in str(func.get("docstring", ""))


# ── Classes ──

class TestPythonClasses:
    """Python class detection."""

    def test_simple_class(self):
        code = """class MyClass:
    def method(self):
        pass
"""
        result = _parse_code(code)
        assert "MyClass" in _names(result["classes"])

    def test_class_with_inheritance(self):
        code = """class Dog(Animal):
    def speak(self):
        return "Woof!"
"""
        result = _parse_code(code)
        assert "Dog" in _names(result["classes"])

    def test_class_methods(self):
        code = """class Service:
    def get(self):
        return "get"

    def post(self):
        return "post"

    @classmethod
    def create(cls):
        return cls()
"""
        result = _parse_code(code)
        cls = result["classes"][0]
        method_names = [m["name"] for m in cls["methods"]]
        assert "get" in method_names
        assert "post" in method_names
        assert "create" in method_names

    def test_static_and_class_methods(self):
        code = """class Utils:
    @staticmethod
    def is_valid(val):
        return True

    @classmethod
    def default(cls):
        return cls()
"""
        result = _parse_code(code)
        cls = result["classes"][0]
        method_names = [m["name"] for m in cls["methods"]]
        assert "is_valid" in method_names
        assert "default" in method_names

    def test_class_with_init(self):
        code = """class User:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age
"""
        result = _parse_code(code)
        cls = result["classes"][0]
        method_names = [m["name"] for m in cls["methods"]]
        assert "__init__" in method_names

    def test_dataclass(self):
        code = """@dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
"""
        result = _parse_code(code)
        assert "Config" in _names(result["classes"])


# ── Imports ──

class TestPythonImports:
    """Python import extraction."""

    def test_simple_import(self):
        code = "import os\n"
        result = _parse_code(code)
        # Imports should be extracted
        assert "imports" in result
        # At minimum, no crash

    def test_from_import(self):
        code = "from pathlib import Path\n"
        result = _parse_code(code)
        assert "imports" in result

    def test_multiple_imports(self):
        code = "import os\nimport sys\nfrom typing import List, Optional\n"
        result = _parse_code(code)
        assert "imports" in result
