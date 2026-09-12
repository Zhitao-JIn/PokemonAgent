"""静态核对：全仓每一条 `import`（含函数体里的懒加载）都解析到真实模块与真实名字。

**为什么需要它**：`interfaces/schemas 集中制撤销`那几轮把类在包之间搬了家，
模块级 import 冒烟能抓到顶层失效，但抓不到**函数体里的懒加载**——
`check_memory_roundtrip.py` 的 `from pokemon_agent.schemas.world import ...` 就藏在
`main()` 里，`python -c "import <每个模块>"` 全绿而实际一跑就 `ModuleNotFoundError`。
本脚本对**任意深度**的 import 节点做解析，把这类"静态就看得出来"的失效挡在跑真机之前。

判据（只查本仓自己的包，第三方包不查）：
  1. 被导入的模块必须能被 `importlib.import_module` 导入；
  2. `from X import a, b` 里的每个名字必须在 X 上存在（`hasattr`，
     模块级 `__getattr__` 的懒加载出口也算——它触发即真导入）。

相对 import（`from .foo import bar`）按所在文件的全限定模块名解析。
`from __future__ import ...`、标准库、第三方一律跳过。

用法（必须用装了 pyboy/pydantic 的解释器，否则会误报缺依赖）：
    py -3.12 scripts/check_imports.py
退出码 0 = 全部解析成功；1 = 有失效条目（逐条打印 `文件:行号`）。
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import sys
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 自己把仓库根挂进 sys.path：`python scripts/xxx.py` 时 sys.path[0] 是 scripts/，
# 而 PYTHONPATH 未必带上根目录——不自己兜底就会把每条本仓 import 都误报成缺模块。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OWN_PACKAGES = ("pokemon_agent", "experiment", "tests")
_OWN_PREFIXES = tuple(f"{name}." for name in OWN_PACKAGES)


def _is_own(target: str) -> bool:
    """目标模块是不是本仓自己的（只查这些）。"""
    return target in OWN_PACKAGES or target.startswith(_OWN_PREFIXES)


def _module_of(path: pathlib.Path) -> str:
    """文件路径 → 它的全限定模块名（`__init__.py` 归到包名上）。"""
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _anchor(module: str, is_package: bool) -> str:
    """相对 import 的锚点包。

    契约：普通模块（`a/b/c.py`）的锚点是它的**父包** `a.b`；包本身
    （`a/b/__init__.py`）的锚点就是它自己 `a.b`——`.x` 的意思是"从锚点包里取 x"。
    """
    return module if is_package else module.rsplit(".", 1)[0]


def _resolve_relative(module: str, is_package: bool, level: int, target: str | None) -> str:
    """把相对 import 解析成全限定模块名；`level` 是点号个数。

    后置条件：锚点包上溯 `level - 1` 层，再接上 `target`（若有）。
    """
    package = _anchor(module, is_package)
    for _ in range(level - 1):
        package = package.rsplit(".", 1)[0] if "." in package else ""
    return f"{package}.{target}" if target else package


def _imports(tree: ast.AST, module: str, is_package: bool) -> Iterator[tuple[int, str, list[str]]]:
    """产出全文件（含任意深度）的 `(行号, 被导入模块全名, 要取的名字)`。

    `import a.b` 的名字列表为空——它就是"把 a.b 导进来"，没有取属性这一步。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, []
        elif isinstance(node, ast.ImportFrom):
            target = (
                _resolve_relative(module, is_package, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            yield node.lineno, target, [a.name for a in node.names if a.name != "*"]


def main() -> int:
    problems: list[str] = []
    checked = 0

    for path in sorted(p for pkg in OWN_PACKAGES for p in (ROOT / pkg).rglob("*.py")):
        module = _module_of(path)
        is_package = path.name == "__init__.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(ROOT)}: 语法错误 {exc}")
            continue

        for lineno, target, names in _imports(tree, module, is_package):
            if not target or not _is_own(target):
                continue
            checked += 1
            where = f"{path.relative_to(ROOT)}:{lineno}"
            try:
                imported = importlib.import_module(target)
            except BaseException as exc:  # noqa: BLE001 —— 任何导入期异常都算失效
                problems.append(f"{where}: 导入 `{target}` 失败：{type(exc).__name__}: {exc}")
                continue
            for name in names:
                if not hasattr(imported, name):
                    problems.append(f"{where}: `{target}` 上没有名字 `{name}`")

    if problems:
        print(f"FAIL  {checked} 条本仓 import 里有 {len(problems)} 条解析不了：")
        for line in problems:
            print(f"  - {line}")
        return 1

    print(f"OK  {checked} 条本仓 import（含函数内懒加载）全部解析到真实模块与名字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
