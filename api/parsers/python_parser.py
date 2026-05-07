import ast


def parse_python_file(file_path: str) -> dict:
    """
    Parse a Python file using AST and return:
    {
        "functions": [{"name", "signature", "start_line", "end_line", "docstring"}],
        "classes": [{"name", "start_line", "end_line", "docstring", "methods": [...]}],
        "calls": [{"source": "func_name", "target": "target_name", "line": line_num}],
        "imports": [{"target": "module_or_name", "line": line_num}],
        "extends": [{"class": "class_name", "parent": "base_name", "line": line_num}]
    }
    """
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    result: dict = {"functions": [], "classes": [], "calls": [], "imports": [], "extends": []}

    # Track function/method name -> line range for call attribution
    func_ranges: dict[str, tuple[int, int]] = {}

    def _extract_function(node, is_method=False):
        """Extract a function/method definition, recursing for nested functions."""
        args = [arg.arg for arg in node.args.args]
        param_types = {}
        for arg in node.args.args:
            if arg.annotation:
                param_types[arg.arg] = _ast_node_to_type_str(arg.annotation)
        return_type = _ast_node_to_type_str(node.returns) if node.returns else None
        signature = f"{node.name}({', '.join(args)})"
        entry = {
            "name": node.name,
            "signature": signature,
            "start_line": node.lineno,
            "end_line": node.end_lineno,
            "docstring": ast.get_docstring(node) or "",
            "return_type": return_type,
            "param_types": param_types,
        }
        if not is_method:
            result["functions"].append(entry)
        func_ranges[node.name] = (node.lineno, node.end_lineno)

        # Recurse into function body for nested/inner functions
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _extract_function(child)
        return entry

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _extract_function(node)

        elif isinstance(node, ast.ClassDef):
            methods = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entry = _extract_function(child, is_method=True)
                    methods.append(entry)
                    # Also recurse into method for nested functions
                    for nested in ast.iter_child_nodes(child):
                        if isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            _extract_function(nested)

            result["classes"].append({
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "docstring": ast.get_docstring(node) or "",
                "methods": methods
            })

            # Extract base classes for EXTENDS relationships
            for base in node.bases:
                base_name = _node_name(base)
                if base_name:
                    result["extends"].append({
                        "class": node.name,
                        "parent": base_name,
                        "line": base.lineno,
                        "rel_type": "EXTENDS",
                    })

    # Extract all CALLS by walking the entire AST
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _node_name(node.func)
            if target:
                source = _find_enclosing_func(node.lineno, func_ranges)
                result["calls"].append({
                    "source": source or "<module>",
                    "target": target,
                    "line": node.lineno
                })

    # Extract top-level IMPORTS
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "target": alias.name,
                    "line": node.lineno
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                result["imports"].append({
                    "target": full,
                    "line": node.lineno
                })

    return result


def _node_name(node: ast.AST) -> str | None:
    """Extract a human-readable name from a Name or Attribute node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    return None


def _ast_node_to_type_str(node) -> str | None:
    """Convert an AST type annotation node to a string representation."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    elif isinstance(node, ast.Subscript):
        value = _ast_node_to_type_str(node.value) or ""
        slice_str = _ast_node_to_type_str(node.slice) or ""
        return f"{value}[{slice_str}]"
    elif isinstance(node, ast.Tuple):
        elements = [_ast_node_to_type_str(e) or "" for e in node.elts]
        return f"({', '.join(elements)})"
    elif isinstance(node, ast.Constant):
        return str(node.value)
    elif isinstance(node, ast.List):
        elements = [_ast_node_to_type_str(e) or "" for e in node.elts]
        return f"[{', '.join(elements)}]"
    elif isinstance(node, ast.BinOp):
        left = _ast_node_to_type_str(node.left) or ""
        right = _ast_node_to_type_str(node.right) or ""
        op = ast.dump(node.op)
        if "BitOr" in op:
            return f"{left} | {right}"
        return f"{left} {op} {right}"
    elif isinstance(node, ast.Index):  # Python < 3.9
        return _ast_node_to_type_str(node.value)
    return None


def _find_enclosing_func(line: int, func_ranges: dict[str, tuple[int, int]]) -> str | None:
    """Find the function/method whose line range contains the given line."""
    best: str | None = None
    best_start = 0
    for name, (start, end) in func_ranges.items():
        if start <= line <= end:
            if best is None or start > best_start:
                best = name
                best_start = start
    return best
