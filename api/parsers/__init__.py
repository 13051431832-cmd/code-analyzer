"""Parser factory - detects language and dispatches to the appropriate parser."""

import os
from . import python_parser, generic_parser

# Tree-sitter for JS/TS (accurate AST parsing, falls back to regex)
try:
    from . import tree_sitter_parser

    _ts_available = tree_sitter_parser.is_available()
except ImportError:
    tree_sitter_parser = None  # type: ignore[assignment]
    _ts_available = False


SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
}

# Extensions where tree-sitter provides better parsing than regex
_TS_EXTENSIONS = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})


def detect_language(file_path: str) -> str | None:
    """Detect programming language from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return SUPPORTED_EXTENSIONS.get(ext)


def detect_and_parse(file_path: str) -> dict:
    """
    Detect language and parse the file.
    Returns: {
        "functions": [{"name", "signature", "start_line", "end_line",
                        "docstring", "return_type", "param_types": {...}}],
        "classes": [{"name", "start_line", "end_line", "docstring",
                      "methods": [{"name", "signature", ..., "return_type", "param_types"}]}],
        "calls": [{"source": "func_name", "target": "target_name", "line": N}],
        "imports": [{"target": "module_or_name", "line": N}],
        "extends": [{"class": "class_name", "parent": "base_name", "line": N}]
    }
    """
    lang = detect_language(file_path)
    if not lang:
        return {"functions": [], "classes": []}

    if lang == "python":
        return python_parser.parse_python_file(file_path)

    # Use tree-sitter for JS/TS when available (100% accuracy vs ~70% regex)
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _TS_EXTENSIONS and _ts_available:
        result = tree_sitter_parser.parse_ts_file(file_path)
        # If tree-sitter returned something (non-empty functions or classes), use it
        if result.get("functions") or result.get("classes"):
            return result
        # Otherwise fall through to regex fallback

    return generic_parser.parse_generic_file(file_path)
