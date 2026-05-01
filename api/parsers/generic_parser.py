import re
import os

# Regex patterns to detect function/method definitions in various languages
FUNCTION_PATTERNS: dict[str, list[re.Pattern]] = {
    "javascript": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+\*?\s*(\w+)\s*\("),
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\().*=>?\s*"),
        re.compile(r"^(?:export\s+)?(?:async\s+)?\(?\s*\w+\s*\)?\s*=>"),
    ],
    "typescript": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+\*?\s*(\w+)\s*\("),
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[=:]\s*(?:async\s+)?(?:function|\().*=>?\s*"),
        re.compile(r"^(?:public|private|protected|static|readonly|export)?\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*:"),
        re.compile(r"^(?:public|private|protected|static)?\s*get\s+(\w+)\s*\("),
        re.compile(r"^(?:public|private|protected|static)?\s*set\s+(\w+)\s*\("),
    ],
    "go": [
        re.compile(r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\("),
    ],
    "java": [
        re.compile(r"^(?:public|private|protected|static|final|abstract|synchronized|native|\s)*\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+)?\s*\{?\s*$"),
    ],
    "rust": [
        re.compile(r"^(?:pub\s+)?(?:unsafe\s+)?fn\s+(\w+)\s*<"),
        re.compile(r"^(?:pub\s+)?(?:unsafe\s+)?fn\s+(\w+)\s*\("),
    ],
}

CLASS_PATTERNS: dict[str, list[re.Pattern]] = {
    "javascript": [
        re.compile(r"^(?:export\s+)?class\s+(\w+)"),
    ],
    "typescript": [
        re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"),
        re.compile(r"^(?:export\s+)?interface\s+(\w+)"),
    ],
    "java": [
        re.compile(r"^(?:public|private|protected|static|final|abstract)?\s*(?:class|interface|enum)\s+(\w+)"),
    ],
    "rust": [
        re.compile(r"^(?:pub\s+)?(?:unsafe\s+)?(?:struct|enum|trait|impl)\s+(\w+)"),
        re.compile(r"^(?:pub\s+)?(?:unsafe\s+)?trait\s+(\w+)"),
        re.compile(r"^(?:pub\s+)?(?:unsafe\s+)?impl(?:\s+<[^>]+>)?\s+(\w+)"),
    ],
}

GO_STRUCT_PATTERN = re.compile(r"^type\s+(\w+)\s+struct")

# NOTE: Go has no classes; this catches structs and interfaces
CLASS_PATTERNS["go"] = [
    re.compile(r"^type\s+(\w+)\s+(?:struct|interface)"),
]

# Return type extraction patterns per language
# These extract the return type annotation from function/method signatures.
RETURN_TYPE_PATTERNS: dict[str, re.Pattern] = {
    "typescript": re.compile(r"\)\s*:\s*(\w+(?:<[^>]*>)?(?:\s*\|\s*\w+(?:<[^>]*>)?)*)\s*(?:\{|=>|;)"),
    "go": re.compile(r"\)\s*(\(\s*[\w\s,*\[\]]+\s*\)|\w+(?:\[\])?)\s*(?:\{|$)"),
    "java": re.compile(r"\)\s*(?:throws\s+\w+\s*)?\{?\s*$"),
    "rust": re.compile(r"\)\s*(?:->\s*(\w+(?:<[^>]*>)?(?:\s*\|\s*\w+(?:<[^>]*>)?)*))\s*(?:\{|where)"),
}

# Parameter type extraction: regex to parse "name: Type" from function signatures
PARAM_TYPE_PATTERN = re.compile(r"(\w+)\s*:\s*(\w+(?:<[^>]*>)?(?:\s*\|\s*\w+(?:<[^>]*>)?)?)")

COMMENT_PATTERNS: dict[str, list[str]] = {
    "javascript": ["//", "/*"],
    "typescript": ["//", "/*"],
    "go": ["//", "/*"],
    "java": ["//", "/*"],
    "rust": ["//", "/*", "///", "//!"],
}

# Block-level comment detection for docstring extraction
BLOCK_COMMENT_PATTERN = re.compile(r"/\*([\s\S]*?)\*/", re.MULTILINE)
LINE_COMMENT_PATTERN = re.compile(r"//(.+)$", re.MULTILINE)

# Call detection: match word(s) followed by (
CALL_PATTERN = re.compile(r"([a-zA-Z_]\w*)\s*\(")

# Keywords that look like function calls but aren't
CALL_SKIP_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "else", "then",
    "with", "elif", "when", "yield", "throw", "delete", "typeof",
    "instanceof", "void", "await", "yield", "assert", "print", "println",
    "super", "new",
})

# Import detection patterns per language
IMPORT_PATTERNS: dict[str, list[re.Pattern]] = {
    "javascript": [
        re.compile(r"import\s+(?:\w+\s+from\s+)?['\"]([^'\"]+)['\"]"),
        re.compile(r"(?:const|let|var)\s+\w+\s*=\s*require\s*\(\s*['\"]([^'\"]+)['\"]"),
    ],
    "typescript": [
        re.compile(r"import\s+(?:\w+\s+from\s+)?['\"]([^'\"]+)['\"]"),
        re.compile(r"(?:const|let|var)\s+\w+\s*=\s*require\s*\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"import\s+(?:type\s+)?\{[^}]*\}\s+from\s+['\"]([^'\"]+)['\"]"),
    ],
    "go": [
        re.compile(r"import\s+['\"]([^'\"]+)['\"]"),
        re.compile(r'import\s+`([^`]+)`'),
    ],
    "java": [
        re.compile(r"import\s+(?:static\s+)?([\w.]+);"),
    ],
    "rust": [
        re.compile(r"use\s+([\w:]+)"),
    ],
}

# Extends/Implements detection patterns
EXTENDS_PATTERNS: dict[str, list[re.Pattern]] = {
    "javascript": [
        re.compile(r"class\s+(\w+)\s+extends\s+(\w+)"),
    ],
    "typescript": [
        re.compile(r"class\s+(\w+)\s+extends\s+(\w+)"),
        re.compile(r"class\s+(\w+)\s+implements\s+(\w+)"),
        re.compile(r"interface\s+(\w+)\s+extends\s+(\w+)"),
    ],
    "go": [
        re.compile(r"type\s+(\w+)\s+interface\s+\{?"),
    ],
    "java": [
        re.compile(r"class\s+(\w+)\s+extends\s+(\w+)"),
        re.compile(r"class\s+(\w+)\s+implements\s+(\w+)"),
        re.compile(r"interface\s+(\w+)\s+extends\s+(\w+)"),
    ],
    "rust": [
        re.compile(r"impl\s+(\w+)\s+for\s+(\w+)"),
        re.compile(r"trait\s+(\w+)(?:\s*:\s*(\w+))?"),
    ],
}


def _detect_language(file_path: str) -> str | None:
    """Detect language based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    mapping = {
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
    return mapping.get(ext)


def _extract_line_comment(lines: list[str], line_no: int, lang: str) -> str:
    """Try to extract the comment immediately above a definition as a pseudo-docstring."""
    comment_lines = []
    idx = line_no - 2  # line above (0-indexed)
    comment_markers = COMMENT_PATTERNS.get(lang, ["//", "/*"])

    while idx >= 0:
        stripped = lines[idx].strip()
        if not stripped:
            break  # blank line = stop
        # Check if it's a comment
        is_comment = any(stripped.startswith(m) for m in comment_markers)
        if not is_comment and stripped.startswith("*"):
            # Allow continuation of /* ... */ style
            is_comment = True
        if not is_comment:
            break
        comment_lines.insert(0, stripped)
        idx -= 1

    return " ".join(c.strip("/*/ ") for c in comment_lines) if comment_lines else ""


def _extract_js_ts_signature(lines: list[str], start_idx: int, lang: str) -> str:
    """
    For JS/TS, try to build a full signature by collecting lines until the opening '{' or '=>'.
    Returns the detected function name and full signature.
    """
    sig_parts = []
    brace_depth = 0
    for i in range(start_idx, min(start_idx + 15, len(lines))):
        line = lines[i]
        sig_parts.append(line.rstrip())
        # Check for opening {
        brace_depth += line.count("{") - line.count("}")
        if brace_depth > 0 or "=>" in line:
            break
        if ";" in line and brace_depth == 0:
            break
    return " ".join(p.strip() for p in sig_parts)


def _estimate_end_lines(lines: list[str], functions: list[dict]) -> list[dict]:
    """Estimate end_line for each function using next definition at same indent."""
    sorted_funcs = sorted(functions, key=lambda f: f["start_line"])
    total_lines = len(lines)
    for i, func in enumerate(sorted_funcs):
        if i + 1 < len(sorted_funcs):
            func["end_line"] = sorted_funcs[i + 1]["start_line"] - 1
        else:
            func["end_line"] = total_lines
    return sorted_funcs


def _extract_return_type(signature: str, lang: str) -> str | None:
    """Extract return type from a function signature using language-specific patterns."""
    if lang not in RETURN_TYPE_PATTERNS:
        return None
    pattern = RETURN_TYPE_PATTERNS[lang]
    m = pattern.search(signature)
    if m:
        return m.group(1).strip()
    return None


def _extract_param_types(signature: str) -> dict[str, str]:
    """Extract parameter name -> type mapping from a function signature."""
    params: dict[str, str] = {}
    # Find the parameter list between parentheses
    m = re.search(r'\(([^)]*)\)', signature)
    if not m:
        return params
    param_text = m.group(1)
    for match in PARAM_TYPE_PATTERN.finditer(param_text):
        params[match.group(1)] = match.group(2)
    return params


def _extract_calls(lines: list[str], func_name: str, start: int, end: int) -> list[dict]:
    """Extract function calls from a range of lines using regex."""
    calls = []
    end = min(end, len(lines))
    for line_no in range(start - 1, end):
        line = lines[line_no]
        for match in CALL_PATTERN.finditer(line):
            name = match.group(1)
            if name not in CALL_SKIP_KEYWORDS:
                calls.append({
                    "source": func_name,
                    "target": name,
                    "line": line_no + 1
                })
    return calls


def parse_generic_file(file_path: str) -> dict:
    """
    Parse a non-Python file using regex heuristics.
    Returns same format as python_parser.parse_python_file(), extended with
    calls, imports, and extends fields.
    """
    lang = _detect_language(file_path)
    if not lang:
        return {"functions": [], "classes": [], "calls": [], "imports": [], "extends": []}

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    func_patterns = FUNCTION_PATTERNS.get(lang, [])
    class_patterns = CLASS_PATTERNS.get(lang, [])

    result: dict = {"functions": [], "classes": [], "calls": [], "imports": [], "extends": []}
    seen_funcs: set[tuple[str, int]] = set()
    seen_classes: set[str] = set()

    for idx, line in enumerate(lines):
        stripped = line.strip()
        line_no = idx + 1

        # Skip comment-only lines and empty lines at top level
        if not stripped:
            continue

        # Try class/struct patterns first
        for pattern in class_patterns:
            m = pattern.search(stripped)
            if m:
                name = m.group(1)
                if name not in seen_classes:
                    seen_classes.add(name)
                    docstring = _extract_line_comment(lines, line_no, lang)
                    result["classes"].append({
                        "name": name,
                        "start_line": line_no,
                        "end_line": line_no,
                        "docstring": docstring,
                        "methods": []
                    })
                break

        # Try function patterns
        for pattern in func_patterns:
            m = pattern.search(stripped)
            if m:
                name = m.group(1)
                # Skip common keywords that look like functions
                if name in CALL_SKIP_KEYWORDS:
                    continue
                key = (name, line_no)
                if key not in seen_funcs:
                    seen_funcs.add(key)
                    docstring = _extract_line_comment(lines, line_no, lang)
                    full_sig = _extract_js_ts_signature(lines, idx, lang) if lang in ("javascript", "typescript") else stripped
                    return_type = _extract_return_type(full_sig, lang)
                    param_types = _extract_param_types(full_sig)
                    result["functions"].append({
                        "name": name,
                        "signature": full_sig,
                        "start_line": line_no,
                        "end_line": line_no,
                        "docstring": docstring,
                        "return_type": return_type,
                        "param_types": param_types,
                    })
                break

    # --- Post-processing: estimate end lines, extract calls, imports, extends ---

    # Estimate function end lines for call extraction
    result["functions"] = _estimate_end_lines(lines, result["functions"])

    # Extract calls from each function body
    for func in result["functions"]:
        func_calls = _extract_calls(lines, func["name"], func["start_line"], func["end_line"])
        result["calls"].extend(func_calls)

    # Extract imports
    import_patterns = IMPORT_PATTERNS.get(lang, [])
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for pattern in import_patterns:
            m = pattern.search(stripped)
            if m:
                result["imports"].append({
                    "target": m.group(1),
                    "line": idx + 1
                })

    # Extract extends/implements
    extends_patterns = EXTENDS_PATTERNS.get(lang, [])
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for pattern in extends_patterns:
            m = pattern.search(stripped)
            if m:
                if lang == "rust" and "impl" in stripped and "for" in stripped:
                    # Rust impl Trait for Type: child=Type, parent=Trait
                    result["extends"].append({
                        "class": m.group(2),
                        "parent": m.group(1),
                        "line": idx + 1
                    })
                elif lang in ("go",):
                    # Go interface
                    pass
                elif m.lastindex and m.lastindex >= 2:
                    result["extends"].append({
                        "class": m.group(1),
                        "parent": m.group(2),
                        "line": idx + 1
                    })

    return result
