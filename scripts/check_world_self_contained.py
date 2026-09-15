"""机械核对"world 自持"：world 是独立第三方模块，只有 tool 层认识它的**实现**。

本项目的第三条铁律（`AGENTS.md` 铁律 2）对四个独立模块（brain / world / memory /
trace）的要求是**实现依赖只允许落在 tool 层**；这条此前只写在 docstring 里、靠人读。
本脚本把它变成**可执行的事实**（与 `scripts/check_trace_self_contained.py` 同一份用意）。

三条检查：

- **A〔出边为零〕**：`world/` 包内**没有任何文件** import `pokemon_agent` 的其余部分
  （相对 import 解析成 `pokemon_agent.world.*` 之后才算"自己"）。
  ⇒ "整体拷走即可当第三方模块用"这条字面成立。0913 夜之前这里有两条出边：
  `pyboy_world.py` → `tools.prompts`（反向依赖，模块图上成环）与
  `errors.py` → `errors.AgentError`（P3 判据当时主动保留的例外）——都已被消掉。
- **B〔实现面只在 tools/〕**：`world/` 与 `tools/` 之外的文件**只许** import
  `pokemon_agent.world` 与 `pokemon_agent.world.interface*`（**数据形状**）。
  其余子模块（`pyboy_world` / `ram` / `errors` / `prompts`）是
  **实现与内部词汇**，只有桥认识。⇒ harness / schemas / api 一律经
  `GameToolPort` 或数据形状说话。
- **C〔装配点零 import〕**：`build.py` **一个字都不许** import `pokemon_agent.world`
  ——四个模块的实现都由 tool 层的接线工厂造（`BrainTool.build` /
  `GameTools.build` / `MemoryTool.build` / `TraceTool.build`），装配点只递裸字段。

    ⚠️ **B 与 C 的分工**：B 只管"实现面"，光靠它 `build.py` 仍可以合法地
    `from pokemon_agent.world import Observation`。C 把装配点单独收紧到零——
    理由是"装配点不该认识这个模块的任何东西"，与另外三个模块的既有事实对齐。

末尾附一份**允许的形状引用登记表**（B 放行的那 14 处），供 `AGENTS.md`
第十二节第 4 条的人工注册表对照——**它不是失败，是账本**。

**只看 import 语句，不看 docstring 散文**：注释里提到 `pokemon_agent.world`
是说明文字（本仓库大量存在），不是依赖边。

用法：`python scripts/check_world_self_contained.py`（退出码 0 = 全过）。
"""

from __future__ import annotations

import ast
import pathlib
import sys
from collections.abc import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "pokemon_agent"

WORLD = "pokemon_agent.world"
"""世界包的点分名——下面所有判据都相对它写。"""

ALLOWED_OUTSIDE_TOOLS = (WORLD, WORLD + ".interface")
"""非 tool 侧**允许** import 的 world 面：包根（统一出口）与 `interface`（协议 + 数据形状）。

白名单式而不是黑名单式：新增一个 `world/xxx.py` 时，默认它就是"实现面"、
只有 tool 层能 import——要放行得改这里，那是一次**有意识的决定**。
"""


def _module_name(path: pathlib.Path) -> str:
    """把一个包内 .py 的路径翻译成它的点分模块名（`__init__.py` 归一成包名）。"""
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(path: pathlib.Path) -> list[str]:
    """该文件**所在的那个包**的点分名（相对 import 就是相对它解析的）。

    判据是"文件在哪个目录里"，不是"文件自己叫什么"：
    `world/__init__.py` 与 `world/pyboy_world.py` 所在的包都是 `pokemon_agent.world`
    ——`__init__.py` 自己的模块名就等于那个包，所以两种情形要分开取。
    """
    return (
        _module_name(path).split(".")
        if path.name == "__init__.py"
        else (_module_name(path).split(".")[:-1])
    )


def _imports_of(path: pathlib.Path) -> list[tuple[int, str, list[str]]]:
    """该文件**全部** import（含函数内、含条件分支里的）→ `[(行号, 模块名, 取的名字)]`。

    相对 import 按 PEP 328 解析成绝对模块名，这样"`from .prompts import load`"
    与"`from pokemon_agent.world.prompts import load`"两种写法一视同仁
    ——`world/pyboy_world.py` 那处用的正是相对写法，只用 `grep '^from'` 会漏。

    第三个元素只给账本用（"这一处拿了哪几个形状"），判据只看模块名。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg_parts = _package_of(path)
    out: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name, ["(整包)"]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                mod = node.module or ""
            else:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                tail = [node.module] if node.module else []
                mod = ".".join(base + tail)
            out.append((node.lineno, mod, [alias.name for alias in node.names]))
    return out


def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    """该目录树下全部 .py（跳过缓存目录），按路径排序保证输出稳定。"""
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _is_world(mod: str) -> bool:
    """`mod` 是不是 world 包里的东西（含包自身）。"""
    return mod == WORLD or mod.startswith(WORLD + ".")


def _check_a() -> list[str]:
    """A 出边为零：world 包里不许 import pokemon_agent 的其余部分。"""
    bad: list[str] = []
    for path in _py_files(PKG_ROOT / "world"):
        for lineno, mod, _names in _imports_of(path):
            if mod.startswith("pokemon_agent") and not _is_world(mod):
                bad.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  import {mod}")
    return bad


def _check_b() -> list[str]:
    """B 实现面只在 tools/：非 tool 侧只许 import world 包根与 interface。"""
    bad: list[str] = []
    for path in _py_files(PKG_ROOT):
        if path.relative_to(PKG_ROOT).parts[0] in {"world", "tools"}:
            continue
        for lineno, mod, _names in _imports_of(path):
            if not _is_world(mod):
                continue
            if mod in ALLOWED_OUTSIDE_TOOLS or mod.startswith(WORLD + ".interface."):
                continue
            bad.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  import {mod}")
    return bad


def _check_c() -> list[str]:
    """C 装配点零 import：`build.py` 一个字都不许提 pokemon_agent.world。"""
    path = PKG_ROOT / "build.py"
    return [
        f"{path.relative_to(REPO_ROOT)}:{lineno}  import {mod}"
        for lineno, mod, _names in _imports_of(path)
        if _is_world(mod)
    ]


def _registry() -> list[str]:
    """账本：非 tool 侧对 world 数据形状的 import 点（B 放行的那些）。"""
    rows: list[str] = []
    for path in _py_files(PKG_ROOT):
        if path.relative_to(PKG_ROOT).parts[0] in {"world", "tools"}:
            continue
        for lineno, mod, names in _imports_of(path):
            if mod in ALLOWED_OUTSIDE_TOOLS or mod.startswith(WORLD + ".interface."):
                rows.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  {', '.join(names)}")
    return rows


CHECKS: list[tuple[str, str, Callable[[], list[str]]]] = [
    ("A", "world 出边为零（可整体拷走）", _check_a),
    ("B", "实现面只在 tools/（非 tool 侧只拿数据形状）", _check_b),
    ("C", "装配点 build.py 对 world 零 import（工厂全在 tool 层）", _check_c),
]


def main() -> int:
    """跑三条检查 + 打印登记表，返回进程退出码（0 = 全过）。"""
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

    rows = _registry()
    print(
        f"\n[账本] 非 tool 侧对 world 数据形状的引用：{len(rows)} 处"
        f"（允许，登记在 AGENTS.md 第十二节第 4 条）"
    )
    for line in rows:
        print(f"        {line}")

    if failed:
        print(
            f"\n{failed} 条约束被破坏——见 AGENTS.md 铁律 2 与 "
            "docs/experiences/2026-09-13-world-decoupling-audit.md"
        )
        return 1
    print("\n✅ world 自持：三条约束全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
