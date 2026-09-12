"""静态核对：`episode/graph.py` 的 `add_node` 顺序 == 观测台相位表的 `key` 顺序。

**为什么需要它**：`web/src/App.tsx` 的 `CHAIN_PHASES` 曾经停在更早的图形状上两个月没人
发现——`ROADMAP.md:1136` 那次「`verify_and_summarize` 取代 `verify_steps`+`summarize`」
只改了代码、没改前端，而"前端格子数与图节点数一致"一直只是**约定**，没有东西守着。
本脚本把它变成**断言**：两侧的**有序列表逐条相同**才算过（不只是集合相同）。

两侧各怎么读：

- **Python 侧**：`ast` 解析 `episode/graph.py`，取 `compile_episode_graph()` 里每个
  `graph.add_node(<字符串字面量>, ...)` 的第一个参数，按出现顺序。
- **TS 侧**：`web/src/App.tsx` 不是 Python，`ast` 用不上——用正则从 `CHAIN_PHASES`
  数组块里按序抽出 `key: "..."` 的值。**只认字面量**，不做表达式求值。

顺序口径：`add_node` 的书写顺序就是执行顺序（v3 起两侧统一），所以这里比的是
"有序列表相等"，不是"集合相等"。

**2026-09-12（步 0）**：图的装配从 `episode_harness._compile()` 搬到了
`episode/graph.py`（"图长什么样"与"节点怎么实现"分居两个文件），本脚本的抽取
路径随之改到这里——**节点搬了家，核对脚本必须跟着搬**，否则它会在旧文件里
找不到 `_compile` 而报错（而不是静默通过）。

用法：`python scripts/check_graph_phases.py`。
退出码 0 = 一致；1 = 漂移，并逐条打印差异。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "pokemon_agent" / "harness" / "episode" / "graph.py"
WEB_PATH = ROOT / "web" / "src" / "App.tsx"

_PHASE_ARRAY_HEAD = "const CHAIN_PHASES"
_PHASE_ARRAY_TAIL = "\n];"
_KEY_RE = re.compile(r'(?<![\w$])key:\s*"([^"]+)"')
"""`key: "..."` 的字面量。负向后顾排除 `fromKey:`——那个字段与节点身份无关。"""


def graph_node_names() -> list[str]:
    """从 `compile_episode_graph()` 里按书写顺序抽出 `add_node` 的第一个字符串字面量。"""
    tree = ast.parse(HARNESS_PATH.read_text(encoding="utf-8"), filename=str(HARNESS_PATH))
    compile_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "compile_episode_graph"
        ),
        None,
    )
    assert compile_fn is not None, "找不到 episode/graph.py 的 compile_episode_graph()"

    names: list[str] = []
    for node in ast.walk(compile_fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_node"):
            continue
        assert node.args, "add_node() 少了第一个参数"
        first = node.args[0]
        assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
            f"add_node() 的第一个参数必须是字符串字面量，实际是 {ast.dump(first)[:80]}"
        )
        names.append(first.value)
    return names


def web_phase_keys() -> list[str]:
    """从 `CHAIN_PHASES` 数组块里按序抽出 `key: \"...\"` 的字面量。"""
    text = WEB_PATH.read_text(encoding="utf-8")
    start = text.index(_PHASE_ARRAY_HEAD)
    end = text.index(_PHASE_ARRAY_TAIL, start)
    return _KEY_RE.findall(text[start:end])


def main() -> int:
    """比对两侧的有序列表，返回进程退出码（0 = 一致，1 = 漂移）。"""
    nodes = graph_node_names()
    phases = web_phase_keys()

    if nodes == phases:
        print(f"OK  {len(nodes)} nodes; graph order == web CHAIN_PHASES order")
        for index, name in enumerate(nodes):
            print(f"  {index:2d}  {name}")
        return 0

    print("DRIFT: episode/graph.py 的 add_node 与 web CHAIN_PHASES.key 不一致")
    print(f"  graph: {len(nodes)} nodes")
    print(f"  web:   {len(phases)} phases")
    width = max(len(nodes), len(phases))
    for index in range(width):
        left = nodes[index] if index < len(nodes) else "—"
        right = phases[index] if index < len(phases) else "—"
        marker = " " if left == right else "!"
        print(f" {marker} {index:2d}  graph={left:<40} web={right}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
