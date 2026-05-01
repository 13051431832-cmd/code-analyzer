import re
import os

# Regex patterns to detect function/method definitions in various languages
FUNCTION_PATTERNS: dict[str, list[re.Pattern]] = {
    "javascript": [
        # Pattern 1: function declaration (supports async, generators, export default, generics)
        re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*(\w+)\s*(?:<[^>]+>)?\s*\("),
        # Pattern 2: const/let/var = function() { (indented or not)
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\*?\s*\([^)]*\)\s*\{"),
        # Pattern 3: const/let/var = (...) => { or => expr (indented or not)
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*=>(?:\s*\{|(?:\s|$))"),
        # Pattern 4: Class/object method definitions (indented get/set/async/static/accessor, generics)
        re.compile(r"^\s*(?:(?:async|static|accessor|get|set)\s+)*(?:get\s+|set\s+)?([a-zA-Z_$][\w$]*)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?:\{|=>|<)"),
        # Pattern 5: Arrow-function methods in class bodies like foo = () => {
        re.compile(r"^\s*(?:(?:async|static|accessor)\s+)*([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*=>(?:\s*\{|(?:\s|$))"),
    ],
    "typescript": [
        # Pattern 1: function declaration (supports generics <T> after name, generators)
        re.compile(r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*(\w+)\s*(?:<[^>]+>)?\s*\("),
        # Pattern 2: const/let/var with arrows (supports generics <T> before params)
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[=:]\s*(?:async\s+)?(?:function\s*|<[^>]*>\s*)?\(.*=>?\s*"),
        # Multi-modifier support: (?:mod|mod|...\s+)* allows unlimited modifiers
        re.compile(r"^(?:(?:public|private|protected|static|readonly|export|abstract)\s+)*(?:async\s+)?(\w+)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::|\{|=>)"),
        re.compile(r"^(?:(?:public|private|protected|static|readonly)\s+)*get\s+(\w+)\s*\("),
        re.compile(r"^(?:(?:public|private|protected|static|readonly)\s+)*set\s+(\w+)\s*\("),
    ],
    "go": [
        # Supports regular functions, methods with receivers, and generics
        re.compile(r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*(?:\[[^[\]]*\])?\s*\("),
    ],
    "java": [
        re.compile(r"^(?:(?:public|private|protected|static|final|abstract|synchronized|native)\s+)*(?:\w+(?:<[^>]*>)?(?:\[\])?\s+)*(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{?\s*$"),
    ],
    "rust": [
        # Supports: pub, pub(crate), unsafe, async, extern "C", const, and generics
        re.compile(r"^(?:(?:pub(?:\s*\(\s*crate\s*\))?)\s+)?(?:unsafe\s+)?(?:async\s+)?(?:extern\s+(?:\"[^\"]*\"\s+)?)?(?:const\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\("),
    ],
}

CLASS_PATTERNS: dict[str, list[re.Pattern]] = {
    "javascript": [
        re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"),
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

# NOTE: Go has no classes; this catches structs and interfaces
CLASS_PATTERNS["go"] = [
    re.compile(r"^type\s+(\w+)\s+(?:struct|interface)"),
]

# Return type extraction patterns per language
# These extract the return type annotation from function/method signatures.
RETURN_TYPE_PATTERNS: dict[str, re.Pattern] = {
    "typescript": re.compile(r"\)\s*:\s*(\w+(?:<[^>]*>)?(?:\s*\|\s*\w+(?:<[^>]*>)?)*)\s*(?:\{|=>|;)"),
    "go": re.compile(r"\)\s*(\(\s*[\w\s,*\[\]]+\s*\)|\w+(?:\[\])?)\s*(?:\{|$)"),
    "rust": re.compile(r"\)\s*(?:->\s*(\w+(?:<[^>]*>)?(?:\s*\|\s*\w+(?:<[^>]*>)?)*))\s*(?:\{|where)"),
}

# Java return type pattern: extract the word between last modifier and function name
JAVA_RETURN_TYPE_PATTERN = re.compile(
    r"(?:public|private|protected|static|final|abstract|synchronized|native|\s)*\s*(\w+(?:\[\])?(?:<[^>]*>)?)\s+\w+\s*\("
)

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
    "super", "new", "do", "case", "try", "finally", "class", "function",
    "continue", "break", "debugger", "default",
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
    For JS/TS, try to build a full signature by collecting lines until the opening '{' or '=>' with brace.
    Handles multi-line arrow functions where => and { are on separate lines.
    """
    sig_parts = []
    brace_depth = 0
    found_arrow = False
    for i in range(start_idx, min(start_idx + 20, len(lines))):
        line = lines[i]
        sig_parts.append(line.rstrip())
        brace_depth += line.count("{") - line.count("}")
        if "=>" in line:
            found_arrow = True
        if brace_depth > 0:
            break
        if found_arrow and brace_depth > 0:
            break
        if not found_arrow and ";" in line and brace_depth == 0:
            break
        # If we saw => but haven't found { yet, keep scanning for {
        if found_arrow:
            continue
    return " ".join(p.strip() for p in sig_parts)


def _estimate_end_lines(lines: list[str], functions: list[dict]) -> list[dict]:
    """Estimate end_line for each function using nesting-aware indentation logic."""
    if not functions:
        return functions
    sorted_funcs = sorted(functions, key=lambda f: f["start_line"])
    total_lines = len(lines)

    # Extract indentation level of each function's definition line
    func_with_indent: list[tuple[dict, int]] = []
    for f in sorted_funcs:
        if f["start_line"] <= len(lines):
            line_text = lines[f["start_line"] - 1]
            indent = len(line_text) - len(line_text.lstrip())
        else:
            indent = 0
        func_with_indent.append((f, indent))

    for i, (func, indent) in enumerate(func_with_indent):
        # Find the next definition at the same or shallower indent level
        end = total_lines
        for j in range(i + 1, len(func_with_indent)):
            next_func, next_indent = func_with_indent[j]
            if next_indent <= indent:
                end = next_func["start_line"] - 1
                break
        func["end_line"] = end

    return sorted_funcs


def _extract_java_return_type(stripped_line: str) -> str | None:
    """Extract return type from a Java method signature line."""
    m = JAVA_RETURN_TYPE_PATTERN.search(stripped_line)
    if m:
        return m.group(1).strip()
    return None


def _extract_return_type(signature: str, lang: str) -> str | None:
    """Extract return type from a function signature using language-specific patterns."""
    if lang == "java":
        return _extract_java_return_type(signature)
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

    # --- Post-processing: estimate end lines, class-method association, calls, imports, extends ---

    # Estimate function end lines for call extraction
    result["functions"] = _estimate_end_lines(lines, result["functions"])

    # Associate methods with their enclosing classes
    if result["classes"] and result["functions"]:
        # Estimate class end lines using indent-based logic
        sorted_classes = sorted(result["classes"], key=lambda c: c["start_line"])
        for i, cls in enumerate(sorted_classes):
            end = len(lines)
            for j in range(i + 1, len(sorted_classes)):
                end = sorted_classes[j]["start_line"] - 1
                break
            cls["end_line"] = end

        # For each class, find methods within its line range
        for cls in sorted_classes:
            for func in result["functions"]:
                if cls["start_line"] < func["start_line"] <= cls["end_line"]:
                    method_entry = {
                        "name": func["name"],
                        "signature": func.get("signature", ""),
                        "start_line": func["start_line"],
                        "end_line": func["end_line"],
                        "docstring": func.get("docstring", ""),
                        "return_type": func.get("return_type"),
                        "param_types": func.get("param_types", {}),
                    }
                    # Avoid duplicates
                    if not any(m["name"] == method_entry["name"] and m["start_line"] == method_entry["start_line"] for m in cls["methods"]):
                        cls["methods"].append(method_entry)

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
