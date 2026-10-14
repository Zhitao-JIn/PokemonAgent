"""`build_real` 的 trace 后端透传核对：装配点只递裸字段，选择收在 tool 工厂。

**为什么用 AST 而不真跑 `build_real`**：装配点第一行就 `GameTools.build(rom)`
——真跑它会拉起 PyBoy / ROM，而本项目红线明确"测试不碰模拟器"。backend 透传
是纯接线事实（`build_real(trace_backend=…)` → `TraceTool.build(backend=…)`），
静态核对调用点的关键字实参就是这句话的可执行版本——与
`scripts/check_trace_self_contained.py` 用 AST 核对 import 边界同一条思路。

**默认值单独钉**：`trace_backend` 的签名缺省是 `None`，没传时取
`pokemon_agent.config.TRACE_BACKEND`——系统缺省只有这一处真源，且必须是 `"local"`。
"""

from __future__ import annotations

import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[2] / "pokemon_agent"
BUILD_PY = PKG / "build.py"
CONFIG_PY = PKG / "config.py"


def _build_real(tree: ast.Module) -> ast.FunctionDef:
    """找到 `build_real` 函数定义；找不着是装配点被改名的信号，当场炸。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_real":
            return node
    raise AssertionError("build.py 里没有 build_real——装配点被改名了？")


def _trace_tool_build_keywords(tree: ast.Module) -> dict[str, ast.expr]:
    """`build.py` 里 `TraceTool.build(...)` 调用点的关键字实参表（按形参名索引）。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "build"
            and isinstance(func.value, ast.Name)
            and func.value.id == "TraceTool"
        ):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
    raise AssertionError("build.py 里没有 TraceTool.build(...) 调用点——装配链断了？")


def test_build_real_forwards_the_backend_choice_to_the_trace_tool_factory() -> None:
    """`trace_backend` 原样递进 `TraceTool.build(backend=…)`——选择点只在 tool 层。"""
    tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))

    keywords = _trace_tool_build_keywords(tree)

    backend = keywords.get("backend")
    assert isinstance(backend, ast.Name) and backend.id == "trace_backend", (
        "backend 关键字必须直接吃 `trace_backend` 形参，不做二次加工"
    )
    trace_root = keywords.get("trace_root")
    # trace_root 仅 local 后端消费——langfuse 传了会被 TraceTool.build 拒收（335），
    # 所以装配点按后端条件转发：`trace_root if trace_backend == "local" else None`。
    assert (
        isinstance(trace_root, ast.IfExp)
        and isinstance(trace_root.body, ast.Name)
        and (trace_root.body.id == "trace_root")
    ), "local 分支必须原样递 trace_root"
    assert isinstance(trace_root.orelse, ast.Constant) and trace_root.orelse.value is None, (
        "langfuse 分支必须传 None（TraceTool.build 对 langfuse + trace_root 拒收）"
    )


def _module_constant(path: pathlib.Path, name: str) -> ast.expr:
    """模块顶层 `NAME = …` 赋值的右值；找不着当场炸。"""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
    raise AssertionError(f"{path.name} 里没有顶层常量 {name}")


def test_default_trace_is_local_and_explicit_langfuse_keeps_its_probe() -> None:
    """`trace_backend` 签名缺省 `None` → 回落 `config.TRACE_BACKEND`，后者必须是 `\"local\"`。

    同时钉住探针：选 langfuse 时 `build_real` 必须先调 `assert_server_ready()`——
    SDK 是异步批量发送，服务不在场时写入侧静默丢账，这一枪要挡在 run 开始之前。
    """
    tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))
    fn = _build_real(tree)

    args = [*fn.args.args, *fn.args.kwonlyargs]
    padded = [None] * (len(args) - len(fn.args.defaults)) + list(fn.args.defaults)
    defaults = {
        arg.arg: default for arg, default in zip(args, padded, strict=False) if default is not None
    }

    backend_default = defaults.get("trace_backend")
    assert isinstance(backend_default, ast.Constant) and backend_default.value is None, (
        "trace_backend 签名缺省必须是 None——系统缺省只住 config.TRACE_BACKEND 一处"
    )
    system_default = _module_constant(CONFIG_PY, "TRACE_BACKEND")
    assert isinstance(system_default, ast.Constant) and system_default.value == "local", (
        f"config.TRACE_BACKEND 必须是 'local'，实际是 {ast.dump(system_default)}"
    )
    fallbacks = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and [getattr(v, "id", None) for v in node.values] == ["trace_backend", "TRACE_BACKEND"]
    ]
    assert fallbacks, "build_real 必须以 `trace_backend or TRACE_BACKEND` 回落到系统缺省"

    calls = [
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "assert_server_ready" in calls, (
        "build_real 选 langfuse 时必须先调 assert_server_ready()——启动前探针不许拆"
    )
