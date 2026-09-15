"""机械核对"trace 自持"：trace 是独立第三方模块，只有 tool 层认识它。

本项目对 `pokemon_agent.trace` 的边界有两条硬约束（`AGENTS.md` 铁律 2 + 0913
的 trace 脱钩定案），它们此前只写在 docstring 里、靠人读——本脚本把
**"自持"从一句声明变成可执行的事实**。三条检查：

- **A〔出边为零〕**：`trace/` 包内**没有任何文件** import `pokemon_agent`
  的其余部分（相对 import 解析成 `pokemon_agent.trace.*` 之后才算"自己"）。
  ⇒ "整体拷走即可当第三方模块用"这条字面成立。
- **B〔入边只在 tools/〕**：`trace/` 与 `tools/` 之外的文件**不许** import
  `pokemon_agent.trace`。⇒ trace 是独立模块，只有"桥"（tool 层）认识它；
  harness / schemas / api / build 一律经 `TraceToolPort` 或契约层说话。
- **C〔契约层不成环〕**：`schemas/harness/domain/` **不许** import
  `pokemon_agent.trace`——一旦 import 就成环（`schemas.harness` → `trace` →
  `trace.store` → `schemas.harness.domain` 半加载 → `ImportError`）。
  B 已经涵盖 C，这里单列是为了让失败信息直接指向"哪条硬约束"。

**只看 import 语句，不看 docstring 散文**：注释里提到 `pokemon_agent.trace`
是说明文字（本仓库大量存在），不是依赖边。

用法：`python scripts/check_trace_self_contained.py`（退出码 0 = 全过）。
"""

from __future__ import annotations

import ast
import pathlib
import sys
from collections.abc import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "pokemon_agent"


def _module_name(path: pathlib.Path) -> str:
    """把一个包内 .py 的路径翻译成它的点分模块名（`__init__.py` 归一成包名）。"""
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(path: pathlib.Path) -> list[str]:
    """该文件**所在的那个包**的点分名（相对 import 就是相对它解析的）。

    判据是"文件在哪个目录里"，不是"文件自己叫什么"：
    `trace/__init__.py` 与 `trace/store.py` 所在的包都是 `pokemon_agent.trace`
    ——`__init__.py` 自己的模块名就等于那个包，所以两种情形要分开取。
    """
    return (
        _module_name(path).split(".")
        if path.name == "__init__.py"
        else (_module_name(path).split(".")[:-1])
    )


def _imports_of(path: pathlib.Path) -> list[tuple[int, str]]:
    """该文件**全部** import（含函数内、含条件分支里的）→ `[(行号, 模块名)]`。

    相对 import 按 PEP 328 解析成绝对模块名，这样"`from .datastore import X`"
    与"`from pokemon_agent.trace.datastore import X`"两种写法一视同仁。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg_parts = _package_of(path)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                out.append((node.lineno, node.module or ""))
            else:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                tail = [node.module] if node.module else []
                out.append((node.lineno, ".".join(base + tail)))
    return out


def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _check_a() -> list[str]:
    """出边为零：trace 包里不许 import pokemon_agent 的其余部分。"""
    bad: list[str] = []
    for path in _py_files(PKG_ROOT / "trace"):
        for lineno, mod in _imports_of(path):
            if not mod.startswith("pokemon_agent"):
                continue
            if not mod.startswith("pokemon_agent.trace"):
                bad.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  import {mod}")
    return bad


def _check_b() -> list[str]:
    """入边只在 tools/：trace 与 tools 之外的文件不许 import pokemon_agent.trace。"""
    bad: list[str] = []
    for path in _py_files(PKG_ROOT):
        if path.relative_to(PKG_ROOT).parts[0] in {"trace", "tools"}:
            continue
        for lineno, mod in _imports_of(path):
            if mod == "pokemon_agent.trace" or mod.startswith("pokemon_agent.trace."):
                bad.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  import {mod}")
    return bad


def _check_c() -> list[str]:
    """契约层不成环：`schemas/harness/domain/` 不许 import pokemon_agent.trace。"""
    bad: list[str] = []
    for path in _py_files(PKG_ROOT / "schemas" / "harness" / "domain"):
        for lineno, mod in _imports_of(path):
            if mod == "pokemon_agent.trace" or mod.startswith("pokemon_agent.trace."):
                bad.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  import {mod}")
    return bad


CHECKS: list[tuple[str, str, Callable[[], list[str]]]] = [
    ("A", "trace 出边为零（可整体拷走）", _check_a),
    ("B", "入口只在 tools/（其余层不认 trace）", _check_b),
    ("C", "schemas/harness/domain 不成环（不 import trace）", _check_c),
]


def main() -> int:
    """跑三条检查，打印报告，返回进程退出码（0 = 全过）。"""
    failed = 0
    for name, desc, fn in CHECKS:
        violations = fn()
        if violations:
            failed += 1
            print(f"[FAIL] {name} {desc}")
            for line in violations:
                print(f"        {line}")
        else:
            print(f"[ OK ] {name} {desc}")
    if failed:
        print(f"\n{failed} 条约束被破坏——见 AGENTS.md 铁律 2 与 docs/PLAN_trace_decoupling.md")
        return 1
    print("\n✅ trace 自持：三条约束全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
