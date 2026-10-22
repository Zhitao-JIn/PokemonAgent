"""Extract literal composition dependencies for validation before the first render."""

import ast
from pathlib import Path

from .errors import PromptRegistryError


def composition_names(path: Path) -> frozenset[str]:
    """Require literal compose names so every referenced unit is checked at startup."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "compose":
            continue
        target = (
            node.args[0]
            if node.args
            else next((keyword.value for keyword in node.keywords if keyword.arg == "name"), None)
        )
        if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
            raise PromptRegistryError(f"{path}:{node.lineno}: compose name must be literal")
        names.add(target.value)
    return frozenset(names)
