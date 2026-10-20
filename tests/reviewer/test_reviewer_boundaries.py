"""整个 reviewer 的依赖边界：只有 schemas 和本包能跨业务包导入。"""

import ast
from pathlib import Path

from pokemon_agent import reviewer


def test_the_entire_reviewer_imports_no_harness_brain_world_or_backend_implementation() -> None:
    for source in Path(reviewer.__file__).parent.rglob("*.py"):
        if source.name == "__main__.py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            else:
                continue
            assert all(
                not name.startswith("pokemon_agent.") or name.startswith("pokemon_agent.schemas.")
                for name in modules
            ), source
