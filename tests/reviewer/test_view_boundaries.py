"""读协议只有查询方法，reviewer 实现不引入其他业务模块。"""

import ast
from pathlib import Path

from pokemon_agent.reviewer import view
from pokemon_agent.reviewer.view import MemoryReader, TraceReader


def test_read_protocols_expose_only_one_query_method_each() -> None:
    assert {
        name
        for name, value in vars(TraceReader).items()
        if not name.startswith("_") and callable(value)
    } == {"read_events"}
    assert {
        name
        for name, value in vars(MemoryReader).items()
        if not name.startswith("_") and callable(value)
    } == {"recall"}


def test_view_imports_only_schemas_and_its_own_package() -> None:
    root = Path(view.__file__).parent
    for source in root.glob("*.py"):
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
