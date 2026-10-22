"""`trace` 包的边界守卫：出边为零、依赖面只剩白名单三个第三方、出口名字固定。

**为什么这个文件值钱**：`trace/__init__.py` 的 docstring 反复强调"本包对
`pokemon_agent` 其余部分零 import——拷走即可复用"，但这条以前只有
`scripts/check_trace_self_contained.py` 在守，而脚本没人跑就没人知道。
这里把同一件事搬进 pytest：改坏边界的人会看到红的用例，而不是一份没人执行的脚本。

**扫描逻辑与脚本 A 项同一套**：`ast` 走全部 import（含函数内、条件分支里的），
相对 import 按 PEP 328 解析成绝对模块名，然后只认"解析后落在 `pokemon_agent.trace`
之外"的那几条。`scripts/` 不是包，测试不 import 它，逻辑在下面自带一份。

**离线**：只读 `pokemon_agent/trace/**.py` 的源码文本，不 import 第三方 SDK、
不连网。
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pokemon_agent.trace

_TRACE_ROOT = pathlib.Path(pokemon_agent.trace.__file__).parent

# trace 是独立第三方模块，依赖面就这么大（顶层 `pydantic` + 函数内 `httpx` / `langfuse`）。
_ALLOWED_THIRD_PARTY = {"pydantic", "httpx", "langfuse"}


def _py_files() -> list[pathlib.Path]:
    return sorted(p for p in _TRACE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _package_of(path: pathlib.Path) -> list[str]:
    """该文件所在的点分包名（相对 import 按它解析）。`__init__.py` 的包就是它自己那层。"""
    return ["pokemon_agent", "trace", *path.relative_to(_TRACE_ROOT).parts[:-1]]


def _imports_of(path: pathlib.Path) -> list[tuple[int, str]]:
    """该文件全部 import → `[(行号, 绝对模块名)]`；相对 import 按 PEP 328 解析。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _package_of(path)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                found.append((node.lineno, node.module or ""))
            else:
                base = package[: len(package) - (node.level - 1)]
                tail = [node.module] if node.module else []
                found.append((node.lineno, ".".join(base + tail)))
    return found


def _report(offenders: list[str]) -> str:
    return "trace 包边界被破坏：\n" + "\n".join(offenders)


def test_the_trace_package_imports_nothing_else_from_pokemon_agent() -> None:
    """出边为零：解析后落在 `pokemon_agent.trace` 之外的 `pokemon_agent.*` import 一条都不许有。"""
    offenders: list[str] = []
    for path in _py_files():
        for lineno, module in _imports_of(path):
            if not (module == "pokemon_agent" or module.startswith("pokemon_agent.")):
                continue
            if module == "pokemon_agent.trace" or module.startswith("pokemon_agent.trace."):
                continue
            offenders.append(
                f"trace/{path.relative_to(_TRACE_ROOT).as_posix()}:{lineno}  import {module}"
            )

    assert offenders == [], _report(offenders)


def test_the_trace_package_only_uses_standard_library_and_allowed_third_party_modules() -> None:
    """除标准库与 `{pydantic, httpx, langfuse}` 外不许有别的第三方 import。

    加依赖要有意识地改白名单——不然后端悄悄绑上某个 SDK，"拷走即可复用"就失效了。
    """
    offenders: list[str] = []
    for path in _py_files():
        for lineno, module in _imports_of(path):
            top = module.split(".")[0]
            if not top or top == "pokemon_agent":
                continue  # 包内相对 import 与出边归上一条守
            if top in sys.stdlib_module_names or top in _ALLOWED_THIRD_PARTY:
                continue
            offenders.append(
                f"trace/{path.relative_to(_TRACE_ROOT).as_posix()}:{lineno}  import {module}"
            )

    assert offenders == [], _report(offenders)


def test_the_package_root_exports_exactly_the_documented_names() -> None:
    """`__all__` 就是那六个名字——出口是契约，多一个少一个都算改契约。"""
    assert set(pokemon_agent.trace.__all__) == {
        "Event",
        "EventType",
        "LangfuseTrace",
        "LocalTrace",
        "TracePort",
        "new_event_uuid",
    }
