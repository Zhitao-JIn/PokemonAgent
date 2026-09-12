"""静态核对（六件，全部 `ast`/正则，不 import 本仓任何模块）：

1. **图序**：`episode/episode_graph.py` 的 `add_node` 顺序 == `web/src/App.tsx` 的
   `CHAIN_PHASES.key` 顺序。**为什么需要它**：那张相位表曾经停在更早的图形状上两个月
   没人发现（`ROADMAP.md:1136` 那次「`verify_and_summarize` 取代
   `verify_steps`+`summarize`」只改了代码没改前端），而"前端格子数与图节点数一致"一直
   只是**约定**。本脚本把它变成断言：**有序列表逐条相同**才算过。
2. **一节点一文件 + 文件名 = 节点名**（§5.3-①/⑤）：从两张 `<level>_graph.py` 抽
   `add_node` 字面量，核对每个名字都有一个同名实现文件（episode 的在七个域目录下，
   run 的平铺在包根）——**两张图各一次，所以会打两行 OK**。
3. **交界键表是真的**（§5.3-②）：`EpisodeInput`/`EpisodeOutput` 声明的每个键，必须在
   **父 `RunState` 与子 `EpisodeRunState` 里都存在**（F1/F8：传递靠键名交集，没有别名
   机制；改名只改一边的表现是"值静默不传"，不报错）。
4. **散件清零 + context 只有一个类型**（§5.3-③/④）：`harness/` 根下只允许清单里的几个
   `.py`（防"半年后又长出一个 `xxx_utils.py`"）；`*.py` 里 `Runtime[...]` 的类型参数与
   `context_schema=` 的实参只能是 `HarnessDeps`（防"哪天有人给子图单独声明一个
   context_schema"——F10 实测那**不报错**，只会让子图节点静默读到不存在的属性）。
5. **端口签名只用信封**（§5.3-⑥）：`tools/interface/ports.py` 里每张协议的每个方法，
   注解里出现的名字只要能在 import 表里找到来源，来源就必须是 `pokemon_agent.schemas`。
   **为什么需要它**：端口是 harness 与 tool 之间唯一的那条线，签名里塞进某个模块的
   领域类型（`ModelCallLog` 这种），等于让 harness 被迫去认识那个模块——`tools/interface/`
   那次拆分白做。这条最容易在"顺手加个方法"时破，所以挂成断言。
6. **trace 自持**（§5.3-⑦）：`pokemon_agent/trace/**` 下**不许出现任何指向
   `pokemon_agent` 其它部分的 import**（绝对路径写法；相对 import 都是包内自家，
   不算）。**为什么需要它**：`trace` 被当作**独立模块**对待——它只认自己的词表
   （`TraceKind`/`Source`/`EventType`）与 `payload: dict[str, str]` 裸字段，不认识
   `ModelCall` 这类业务类型；"业务对象 → 裸字段"的转换是 tool 层的事
   （`tools/trace/render.py`）。这条边界一旦破（有人往 trace 里塞一个业务类的字段
   类型），`trace` 就重新绑死在调用方身上、无法单独替换。**只看 import 语句，不看
   docstring 里提到的路径**——所以用 `ast` 而不是 `grep`。

两侧各怎么读：

- **Python 侧**：`ast` 解析 `<level>_graph.py`，取装配函数里每个
  `graph.add_node(<字符串字面量>, ...)` 的第一个参数，按出现顺序。
- **TS 侧**：`web/src/App.tsx` 不是 Python，`ast` 用不上——用正则从 `CHAIN_PHASES`
  数组块里按序抽出 `key: "..."` 的值。**只认字面量**，不做表达式求值。

顺序口径：`add_node` 的书写顺序就是执行顺序（v3 起两侧统一），所以这里比的是
"有序列表相等"，不是"集合相等"。

**2026-09-12（步 4 / 步 5）**：抽到两张图 + §5.3 的五条机械保证（②③④ 步 4 挂上、
⑥ 步 5 补上）。③ 那一笔在**步 5 销完**：`trace_write.py` 已随 D8-③ 下沉
`tools/trace/model_calls.py`，`HARNESS_ROOT_ALLOWED` 不再为它留位——所以那份清单是**终态**；
⑥ 是步 5 那次"`ModelCallLog` 该不该进端口签名"讨论的产物，规则对、就该钉住。

用法：`python scripts/check_graph_phases.py`。
退出码 0 = 全部一致；1 = 有漂移，并逐条打印差异。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "pokemon_agent" / "harness"
EPISODE_DIR = HARNESS_DIR / "episode"
RUN_DIR = HARNESS_DIR / "run"
EPISODE_GRAPH_PATH = EPISODE_DIR / "episode_graph.py"
RUN_GRAPH_PATH = RUN_DIR / "run_graph.py"
EPISODE_STATE_PATH = EPISODE_DIR / "episode_state.py"
PORTS_PATH = ROOT / "pokemon_agent" / "tools" / "interface" / "ports.py"
TRACE_DIR = ROOT / "pokemon_agent" / "trace"
RUN_STATE_PATH = RUN_DIR / "run_state.py"
WEB_PATH = ROOT / "web" / "src" / "App.tsx"

HARNESS_ROOT_ALLOWED = {
    "__init__.py",
    "deps.py",
    "auto_reviewer.py",
    "run_data_center.py",
}
"""`harness/` 根下允许出现的 `.py`（§5.3-③ 的清单，**步 5 后是终态**）。

- `deps.py`：全图唯一的 context，不属于任何一张图（D3 修订）；
- `auto_reviewer.py` / `run_data_center.py`：两个顶层实现（不是图的一部分）。

`trace_write.py` 曾是这份清单里唯一一笔"待销账"，步 5 随 D8-③ 下沉
`tools/trace/model_calls.py` 之后销掉——③ 从"未挂"到"已挂"的最后一步就是它。
"""

RUN_FACADE = {"harness.py"}
"""`run/` 包根下**不是节点**的那个文件：`RunHarness` 薄类（外部调用面，D1 的落地形态）。

它既不带 `run_` 前缀（不属于"图长什么样"），也不在 `add_node` 字面量里（不是顶点）
——"一节点一文件"核对必须显式放它过去。判据与核验脚本 H 块"包根下允许的第三类"
同源：包根只许有 ① 结构性 `<level>_*.py`、② 本层节点、③ 本层外部调用面（两层里
只有 run 有）。多出第四种就是漂移。
"""

_PHASE_ARRAY_HEAD = "const CHAIN_PHASES"
_PHASE_ARRAY_TAIL = "\n];"
_KEY_RE = re.compile(r'(?<![\w$])key:\s*"([^"]+)"')
"""`key: "..."` 的字面量。负向后顾排除 `fromKey:`——那个字段与节点身份无关。"""

_ADD_NODE_RE = re.compile(r'add_node\(\s*"([a-z_]+)"')
_RUNTIME_TYPE_RE = re.compile(r"Runtime\[\s*([A-Za-z_][\w.]*)\s*\]")
_CONTEXT_SCHEMA_RE = re.compile(r"context_schema\s*=\s*([A-Za-z_][\w.]*)")


class Drift(Exception):
    """一处不一致——收集起来一起报，别让人修一次跑一次。"""


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def graph_node_names(path: Path, func_name: str) -> list[str]:
    """从装配函数里按书写顺序抽出 `add_node` 的第一个字符串字面量。"""
    compile_fn = next(
        (
            node
            for node in ast.walk(_parse(path))
            if isinstance(node, ast.FunctionDef) and node.name == func_name
        ),
        None,
    )
    if compile_fn is None:
        raise Drift(f"找不到 {path.relative_to(ROOT)} 的 {func_name}()")

    names: list[str] = []
    for node in ast.walk(compile_fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_node"):
            continue
        if not node.args:
            raise Drift(f"{path.name}: add_node() 少了第一个参数")
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            raise Drift(
                f"{path.name}: add_node() 的第一个参数必须是字符串字面量，"
                f"实际是 {ast.dump(first)[:80]}"
            )
        names.append(first.value)
    return names


def node_impl_owners(pkg_dir: Path, *, nodes_in_domains: bool) -> dict[str, str]:
    """抽出"实现文件（或包）→ 它归属的节点名"（§5.3-①/⑤）。

    规则：**节点文件名 = 图里 `add_node` 的字面量**。

    - `episode/`：节点住七个域目录，所以取**深度 ≥ 2** 的 `.py`（深度 2 的用文件名当
      节点名）；某个节点体量大到拆成包（`store_object_semantic_memory/`）时用**包名**
      当节点名，包内辅助件（`rules.py`）不再单独算节点——所以文件与目录两处都收。
    - `run/`：节点平铺在包根，取**非结构性**（不带 `run_` 前缀、不是 `__init__.py`）的
      `.py`；`harness.py`（外部调用面）不是节点，靠"不在 `add_node` 字面量里"自然排除。
    """
    owners: dict[str, str] = {}
    if nodes_in_domains:
        for path in sorted(pkg_dir.rglob("*.py")):
            rel = path.relative_to(pkg_dir)
            if len(rel.parts) < 2 or path.name == "__init__.py":
                continue
            owners[str(rel)] = path.stem if len(rel.parts) == 2 else rel.parts[1]
        for path in sorted(pkg_dir.rglob("*")):
            rel = path.relative_to(pkg_dir)
            if path.is_dir() and len(rel.parts) == 2 and not path.name.startswith("__"):
                owners[f"{rel}/"] = path.name
        return owners

    for path in sorted(pkg_dir.glob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("run_") or path.name in RUN_FACADE:
            continue
        owners[path.name] = path.stem
    return owners


def pydantic_field_names(path: Path, class_name: str) -> list[str]:
    """抽一个 Pydantic 模型声明的字段名（只认类体里的 `名字: 类型` 注解）。"""
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    raise Drift(f"{path.relative_to(ROOT)} 里找不到类 {class_name}")


def web_phase_keys() -> list[str]:
    """从 `CHAIN_PHASES` 数组块里按序抽出 `key: "..."` 的字面量。"""
    text = WEB_PATH.read_text(encoding="utf-8")
    start = text.index(_PHASE_ARRAY_HEAD)
    end = text.index(_PHASE_ARRAY_TAIL, start)
    return _KEY_RE.findall(text[start:end])


def check_graph_order() -> None:
    """① 图序 == 观测台相位表（只对 episode 图：web 只画那一张链）。"""
    nodes = graph_node_names(EPISODE_GRAPH_PATH, "compile_episode_graph")
    phases = web_phase_keys()
    if nodes == phases:
        print(f"OK  {len(nodes)} nodes; graph order == web CHAIN_PHASES order")
        for index, name in enumerate(nodes):
            print(f"  {index:2d}  {name}")
        return

    lines = [
        "DRIFT: episode/episode_graph.py 的 add_node 与 web CHAIN_PHASES.key 不一致",
        f"  graph: {len(nodes)} nodes",
        f"  web:   {len(phases)} phases",
    ]
    for index in range(max(len(nodes), len(phases))):
        left = nodes[index] if index < len(nodes) else "—"
        right = phases[index] if index < len(phases) else "—"
        marker = " " if left == right else "!"
        lines.append(f" {marker} {index:2d}  graph={left:<40} web={right}")
    raise Drift("\n".join(lines))


def check_node_files(
    label: str, graph_path: Path, func_name: str, pkg_dir: Path, *, nodes_in_domains: bool
) -> None:
    """② 一节点一文件 + 文件名 = 节点名（两张图各跑一次，所以打两行 OK）。"""
    nodes = graph_node_names(graph_path, func_name)
    files = node_impl_owners(pkg_dir, nodes_in_domains=nodes_in_domains)
    missing = sorted(set(nodes) - set(files.values()))
    extra = sorted(set(files.values()) - set(nodes))
    if missing or extra:
        lines = [f"DRIFT: {label} 图的节点与实现文件对不上（§5.3-①/⑤）"]
        if missing:
            lines.append(f"  有节点、没实现文件：{missing}")
        if extra:
            lines.append(f"  有实现文件、没这个节点：{extra}")
            lines.extend(f"    {rel}  →  {owner}" for rel, owner in files.items() if owner in extra)
        raise Drift("\n".join(lines))

    print(f"OK  {len(nodes)} nodes; {label} 每个节点都有同名实现文件（名字 == add_node 字面量）")


def check_boundary_keys() -> None:
    """③ 交界键表是真的：每个声明的键都存在于两岸 state（§5.3-②）。"""
    parent = set(pydantic_field_names(RUN_STATE_PATH, "RunState"))
    child = set(pydantic_field_names(EPISODE_STATE_PATH, "EpisodeRunState"))
    declared: list[tuple[str, str]] = [
        (model, field)
        for model in ("EpisodeInput", "EpisodeOutput")
        for field in pydantic_field_names(EPISODE_GRAPH_PATH, model)
    ]

    problems: list[str] = []
    for model, field in declared:
        if field not in parent:
            problems.append(f"  {model}.{field} 在父 RunState 里不存在（子图的初值/回程靠同名键）")
        if field not in child:
            problems.append(f"  {model}.{field} 在子 EpisodeRunState 里不存在")
    if problems:
        raise Drift("DRIFT: 交界键表与两岸 state 不一致（§5.3-②）\n" + "\n".join(problems))

    names = ", ".join(f"{model}.{field}" for model, field in declared)
    print(f"OK  {len(declared)} 个交界键都存在于两岸 state（{names}）")


def check_harness_root() -> None:
    """④-a 散件清零：`harness/` 根下不留计划外的 `.py`（§5.3-③）。"""
    loose = sorted(
        path.name
        for path in HARNESS_DIR.glob("*.py")
        if path.name not in HARNESS_ROOT_ALLOWED
    )
    if loose:
        raise Drift(
            "DRIFT: harness/ 根下出现了计划外的 .py（§5.3-③）\n"
            f"  {loose}\n"
            "  （散件只能有两个下落：并进它的宿主节点，或下沉到 tool 层）"
        )
    print(f"OK  harness/ 根下只有清单里的 {len(HARNESS_ROOT_ALLOWED)} 个 .py（散件已清零）")


def check_context_type() -> None:
    """④-b context 只有一个类型：`Runtime[...]` 与 `context_schema=` 都只能是 `HarnessDeps`。"""
    problems: list[str] = []
    for path in sorted(HARNESS_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for found in _RUNTIME_TYPE_RE.findall(line):
                if found != "HarnessDeps":
                    problems.append(f"  {where}:{lineno} `Runtime[{found}]` 不是 HarnessDeps")
            for found in _CONTEXT_SCHEMA_RE.findall(line):
                if found != "HarnessDeps":
                    problems.append(f"  {where}:{lineno} `context_schema={found}` 不是 HarnessDeps")
    if problems:
        raise Drift("DRIFT: context 出现了第二个类型（§5.3-④/F10）\n" + "\n".join(problems))
    print("OK  context 只有一个类型（HarnessDeps）")


def check_port_signatures() -> None:
    """⑤-b 端口签名只用信封：协议方法的注解不许出现非 `schemas` 来的类型。

    判据机械：`ports.py` 的 import 表给出每个名字的来源模块；协议方法里注解
    出现的 `Name` 只要在表里，来源就必须以 `pokemon_agent.schemas` 开头。内建
    （`int`/`str`/`list`）与 `typing` 的东西（`None`、`Protocol`）要么不在表里、
    要么是内建，自然放过。
    """
    tree = _parse(PORTS_PATH)
    origin: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                origin[alias.asname or alias.name] = node.module or ""
        elif isinstance(node, ast.Import):
            for alias in node.names:
                origin[alias.asname or alias.name] = alias.name

    problems: list[str] = []
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        if not any(isinstance(base, ast.Name) and base.id == "Protocol" for base in cls.bases):
            continue
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            annotations = [
                arg.annotation for arg in [*fn.args.args, *fn.args.kwonlyargs] if arg.annotation
            ]
            if fn.returns is not None:
                annotations.append(fn.returns)
            for annotation in annotations:
                for inner in ast.walk(annotation):
                    if not isinstance(inner, ast.Name):
                        continue
                    module = origin.get(inner.id)
                    if module is not None and not module.startswith("pokemon_agent.schemas"):
                        problems.append(
                            f"  {cls.name}.{fn.name}: `{inner.id}` 来自 `{module}`"
                            f"（端口签名只许 schemas 的类型）"
                        )
    if problems:
        raise Drift("DRIFT: 端口签名出现了非 schemas 的类型（§5.3-⑥）\n" + "\n".join(problems))
    print("OK  所有端口的签名只用 schemas 信封类型（没有领域类型混进签名）")


def check_trace_self_contained() -> None:
    """⑦ trace 自持：`pokemon_agent/trace/**` 不许 import 本仓其它部分。

    判据机械：`ast` 解析每个 `.py`，只看 `import` / `from ... import` 语句——
    绝对路径写法的模块名只要以 `pokemon_agent` 开头，就必须也以
    `pokemon_agent.trace` 开头（自身）；相对 import（`level >= 1`）天然是包内
    自家，放过。**docstring 里提到的路径不算**，所以用 `ast` 而不是 `grep`——
    本包 docstring 里到处写着"消费方写 `from pokemon_agent.trace import X`"。
    """
    problems: list[str] = []
    for path in sorted(TRACE_DIR.rglob("*.py")):
        tree = _parse(path)
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                module = node.module or ""
                if _is_foreign_import(module):
                    problems.append(f"  {rel}:{node.lineno} → from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_foreign_import(alias.name):
                        problems.append(f"  {rel}:{node.lineno} → import {alias.name}")
    if problems:
        raise Drift(
            "DRIFT: trace 包 import 了本仓其它部分（§5.3-⑦，trace 应当自持）\n"
            + "\n".join(problems)
            + "\n  trace 只认自己的词表与 payload: dict[str, str] 裸字段；"
            "业务对象 → 裸字段的转换属于 tool 层（tools/trace/render.py）。"
        )
    print("OK  trace 包对 pokemon_agent 其余部分零 import（自持）")


def _is_foreign_import(module: str) -> bool:
    """这个模块名是不是"本仓的、但不属于 trace 自己"？"""
    if module == "pokemon_agent":
        return True
    return module.startswith("pokemon_agent.") and not module.startswith("pokemon_agent.trace")


def main() -> int:
    """跑完六件核对，返回进程退出码（0 = 全部一致，1 = 有漂移）。

    不"第一次失败就退出"：各处独立，一次跑完把所有差异摆出来，省得改一处跑一次。
    """
    failures: list[str] = []
    steps = (
        ("图序", check_graph_order),
        (
            "episode 节点文件",
            lambda: check_node_files(
                "episode",
                EPISODE_GRAPH_PATH,
                "compile_episode_graph",
                EPISODE_DIR,
                nodes_in_domains=True,
            ),
        ),
        (
            "run 节点文件",
            lambda: check_node_files(
                "run", RUN_GRAPH_PATH, "compile_run_graph", RUN_DIR, nodes_in_domains=False
            ),
        ),
        ("交界键表", check_boundary_keys),
        ("harness 根", check_harness_root),
        ("context 类型", check_context_type),
        ("端口签名", check_port_signatures),
        ("trace 自持", check_trace_self_contained),
    )
    for label, step in steps:
        try:
            step()
        except Drift as exc:
            print(str(exc))
            failures.append(label)

    if failures:
        print(f"\nFAIL  {len(failures)} 处漂移：{failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
