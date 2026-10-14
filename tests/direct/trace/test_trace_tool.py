"""`TraceTool.build` 后端选择的用法示范：local 默认不变、langfuse 显式选、未知拒绝。

**为什么这个文件值钱**：`backend` 参数是"trace 落在哪"的唯一选择点——
默认必须仍是本地 JSON（Langfuse 不许因测试变绿就翻默认），显式选 langfuse
时不许静默写本地文件、不许静默 fallback，缺配置要当场说清。这些边界没有
编译器保护，一条测试就是一句话的可执行版本。

**全部离线**：langfuse 分支用 monkeypatch 把 SDK 客户端类换成
`tests/_fake_langfuse.py` 的记录型假件（`build_client_from_environment` 是
调用时才 `from langfuse import Langfuse`，patch 模块属性正好接住）；不连服务、
密钥用明显的测试假值、不碰模拟器、不调模型。
"""

from __future__ import annotations

import json
import pathlib

import pytest
from _fake_langfuse import FakeLangfuseClient

from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.trace import LocalTrace, TracePort


def _step_advance(step: int = 0, *, episode_id: str = "ep-1") -> FromHarnessToTraceToolAppendReq:
    """一笔最小的账——`advance_step` 只有一个正文键，拿它当夹具最省。"""
    return FromHarnessToTraceToolAppendReq(
        kind=TraceKind.ADVANCE_STEP,
        meta={
            "source": "close_step",
            "episode_id": episode_id,
            "task_id": episode_id,
            "step": step,
        },
        next_step=step + 1,
    )


def _langfuse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """三件配置给明显的测试假值（不是任何真实实例的密钥）。"""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000")


def _clear_langfuse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """三件配置全部拔掉——模拟"从没配过 Langfuse"的环境。"""
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


# ---- 默认 local：行为不变、零 Langfuse 依赖 ----


def test_default_backend_is_local_and_needs_no_langfuse_config(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不传 backend 时行为与接入 Langfuse 之前逐字相同，且不读 LANGFUSE_* 配置。"""
    _clear_langfuse_env(monkeypatch)

    tool = TraceTool.build(run_id="run-1", trace_root=tmp_path)

    assert isinstance(tool, TraceTool)
    assert isinstance(tool._trace, LocalTrace), "默认后端是 LocalTrace"
    tool.append(_step_advance())
    assert len(tool.read_events()) == 1


def test_the_local_trace_lifecycle_methods_are_safe_no_ops(tmp_path: pathlib.Path) -> None:
    """LocalTrace 的 flush / shutdown 是空操作——同步落盘没有后台资源。"""
    trace = LocalTrace(root=tmp_path)

    assert isinstance(trace, TracePort)
    trace.flush()
    trace.shutdown()
    assert trace.read_events() == []


# ---- 显式 langfuse：选得中、不写本地、缺配置说得清 ----


def test_langfuse_backend_selects_langfuse_trace_and_stays_in_memory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`backend="langfuse"` 显式选择：事件进 SDK 队列，本地一个 JSON 都不落。"""
    from pokemon_agent.trace import LangfuseTrace

    _langfuse_env(monkeypatch)
    fake = FakeLangfuseClient()
    monkeypatch.setattr("langfuse.Langfuse", lambda **_kwargs: fake)
    monkeypatch.chdir(tmp_path)

    tool = TraceTool.build(run_id="run-1", backend="langfuse")

    assert isinstance(tool._trace, LangfuseTrace)
    tool.append(_step_advance(step=0))
    assert len(tool.read_events()) == 1, "append 后经假 API 可读回"
    assert not (tmp_path / "tracelog").exists(), "Langfuse 模式不写本地 trace JSON"


def test_langfuse_backend_refuses_trace_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`trace_root` 只对 local 后端生效；带上它选 langfuse 是配置矛盾，当场拒绝。"""
    _langfuse_env(monkeypatch)

    with pytest.raises(ValueError, match="trace_root"):
        TraceTool.build(backend="langfuse", trace_root="somewhere")


def test_langfuse_backend_without_config_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺 LANGFUSE_* 配置：显式失败、错误信息点名三件配置，绝不静默 fallback。"""
    _clear_langfuse_env(monkeypatch)

    with pytest.raises(RuntimeError, match="LANGFUSE_"):
        TraceTool.build(backend="langfuse")


def test_an_unknown_backend_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """backend 拼错（哪怕手滑写成正则式）在装配期就 ValueError，不拖到首笔账。"""
    _clear_langfuse_env(monkeypatch)

    with pytest.raises(ValueError, match="unknown trace backend"):
        TraceTool.build(trace_root=tmp_path, backend="lcoal")


# ---- 生命周期：TraceTool 是转发口 ----


def test_tool_lifecycle_delegates_to_the_inner_trace(tmp_path: pathlib.Path) -> None:
    """`TraceTool.flush()` / `shutdown()` 原样转给所选后端。"""
    tool = TraceTool.build(run_id="run-1", trace_root=tmp_path)
    inner = tool._trace
    calls: list[str] = []
    monkey_flush = inner.flush

    def _record_flush() -> None:
        calls.append("flush")
        monkey_flush()

    def _record_shutdown() -> None:
        calls.append("shutdown")

    inner.flush = _record_flush  # type: ignore[method-assign]
    inner.shutdown = _record_shutdown  # type: ignore[method-assign]

    tool.flush()
    tool.shutdown()

    assert calls == ["flush", "shutdown"]


def test_the_tool_stamps_run_id_and_branch_into_meta(tmp_path: pathlib.Path) -> None:
    """`run_id` / `branch` 归 tool 层盖（0927 定案）：append 时盖进 meta 头两个。

    执行线身份住 `TraceTool`（构造期常量），trace 后端零持有——local 不存、
    langfuse 只拿 trace_id。这条把"盖出来的 meta 长什么样"钉在 tool 层。
    """
    tool = TraceTool.build(run_id="run-1", trace_root=tmp_path)

    tool.append(_step_advance(step=3))

    (event,) = tool.read_events()
    meta = json.loads(event.meta)
    assert list(meta)[:2] == ["run_id", "branch"], "盖章的两件排在头两个"
    assert meta["run_id"] == "run-1" and meta["branch"] == "main"
    assert meta["step"] == 3, "调用方交的键原样保留"


def test_langfuse_lifecycle_reaches_the_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """选了 langfuse 后端时，flush / shutdown 一路传到 SDK client。"""
    _langfuse_env(monkeypatch)
    fake = FakeLangfuseClient()
    monkeypatch.setattr("langfuse.Langfuse", lambda **_kwargs: fake)

    tool = TraceTool.build(run_id="run-1", backend="langfuse")
    tool.append(_step_advance(step=0))
    tool.flush()
    tool.shutdown()

    assert fake.flush_count == 1
    assert fake.shutdown_count == 1
    events = tool.read_events()
    assert [json.loads(e.meta)["step"] for e in events] == [0]
