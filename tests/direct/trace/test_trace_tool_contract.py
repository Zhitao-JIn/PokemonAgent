"""`TraceTool` 门面的契约：签名校验、执行线盖戳、失败尝试独立成账、工厂转发落盘根。

**这些用例钉的是 direct 层门面，不是 `trace` 模块**：`meta` 缺键被拒、`run_id`
不许调用方传、`count` 已废、`build(trace_root=…)` 要把根转发下去——每一条都是
`TraceTool` 自己加的规则，`LocalTrace` 对它们一无所知。它们原先混在
`tests/trace/test_trace_store.py` 里（那个文件的名字与内容早就不副实：一半测门面、
一半测 trace 本身），CP1 把这 7 条**逐字**搬来这里——断言、docstring、用例名一行
不改，旧文件随之删除；trace 本身的落盘与读语义改由 `tests/trace/` 直接对着
`LocalTrace` 测。

**全部离线**：落盘根一律 `tmp_path`，不连网、不碰模拟器、不调模型。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    ModelCall,
    TraceKind,
)
from pokemon_agent.trace import LocalTrace


def _tool(tmp_path: pathlib.Path, run_id: str = "test-run") -> TraceTool:
    """造一个写到 `tmp_path` 的 `TraceTool`（不经 `TraceTool.build()`——不传
    `trace_root` 的话产物会落进启动目录的 `tracelog/`）。

    这里也顺带示范 `TraceTool` 的依赖注入形态：它收任何 `TracePort`，
    mock 与真实实现可无痛互换。`run_id` 住 tool 层（0927 定案：执行线标识
    由本层 append 时盖进 meta，`LocalTrace` 对它零持有）。
    """
    return TraceTool(LocalTrace(root=tmp_path), run_id=run_id)


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


def test_call_kind_is_the_account_name_and_a_failed_attempt_is_its_own_event(
    tmp_path: pathlib.Path,
) -> None:
    """`*_call` 的 `kind` **就是账名**；失败那一笔另补一条 `call_failed`，链路走 `content.link`。

    "账单"与"失败模式"是两件事：前者答"花了多少钱"，后者答"为什么没拿到东西"。
    所以重试链展开成 N 条调用账 + 失败那几次各自一条错误账。
    """
    tool = _tool(tmp_path)
    tool.append(
        FromHarnessToTraceToolAppendReq(
            meta={"source": "think_action", "episode_id": "ep-1", "task_id": "ep-1", "step": 1},
            kind=TraceKind.CHOOSE_CALL,
            calls=[
                ModelCall(payload={"raw": "{}", "ok": "true", "prompt": "…"}),
                ModelCall(
                    payload={"ok": "false", "prompt": "…"},
                    error_kind="ParseFailure",
                    error="Expecting ',' delimiter",
                ),
            ],
        )
    )

    events = tool.read_events()
    model_calls = [e for e in events if e.type == "model_call"]
    errors = [e for e in events if e.type == "error"]

    assert [e.kind for e in model_calls] == ["choose_call", "choose_call"]  # 两次尝试两条账
    # 失败那一笔是**另一条事件**：账名答失败模式，链路名走 `content.link`。
    assert [e.kind for e in errors] == ["call_failed"]
    assert json.loads(errors[0].content) == {
        "link": "choose",
        "exception": "ParseFailure",
        "reason": "Expecting ',' delimiter",
    }


def test_meta_is_the_harness_signature_and_is_forwarded_verbatim(
    tmp_path: pathlib.Path,
) -> None:
    """`meta` 是 harness 的签名信息：调用方一次交齐，tool 盖章后转发。

    `run_id` 与 `branch` 是执行线标识——它们住 `TraceTool`（0927 定案），
    由 `_stamp_meta` 盖进最前。所以盘上的顺序是 run_id、branch 打头，
    后面跟着调用方交的几件。
    """
    tool = _tool(tmp_path, run_id="run-0914")
    tool.append(_step_advance(step=3, episode_id="run-0914-ep1"))

    (event,) = tool.read_events()
    meta = json.loads(event.meta)

    assert meta == {
        "run_id": "run-0914",
        "branch": "main",
        "source": "close_step",
        "episode_id": "run-0914-ep1",
        "task_id": "run-0914-ep1",
        "step": 3,
    }


def test_a_signature_missing_a_key_is_refused(tmp_path: pathlib.Path) -> None:
    """`meta` 三件缺一不可——少一件，这条账在盘上就说不全"谁发的、落在哪"。"""
    tool = _tool(tmp_path)
    req = _step_advance()
    req.meta = {"source": "close_step", "step": 0}  # 少 episode_id

    with pytest.raises(AssertionError, match="meta 少了"):
        tool.append(req)


def test_an_empty_source_in_the_signature_is_refused(tmp_path: pathlib.Path) -> None:
    """`source` 空着就炸——同 kind 可能有两个生产者，缺了它只能靠猜。"""
    tool = _tool(tmp_path)
    req = _step_advance()
    req.meta = {"source": "", "episode_id": "ep-1", "task_id": "ep-1", "step": 0}

    with pytest.raises(AssertionError, match="meta.source 是空的"):
        tool.append(req)


def test_a_caller_supplied_run_id_is_refused(tmp_path: pathlib.Path) -> None:
    """`run_id` 不归调用方——它是落盘实例的标识，落盘那一层自己知道。"""
    tool = _tool(tmp_path)
    req = _step_advance()
    req.meta = {
        "source": "close_step",
        "episode_id": "ep-1",
        "task_id": "ep-1",
        "step": 0,
        "run_id": "test-run",
    }

    with pytest.raises(AssertionError, match="run_id"):
        tool.append(req)


def test_a_caller_supplied_count_is_refused(tmp_path: pathlib.Path) -> None:
    """`req.count` 同理已废——命中条数恒等于 `refs` 的长度，那个字段是纯派生。"""
    tool = _tool(tmp_path)
    req = _step_advance()
    req.count = 3

    with pytest.raises(AssertionError, match="交了一份 count"):
        tool.append(req)


def test_build_factory_forwards_the_trace_root(tmp_path: pathlib.Path) -> None:
    """`TraceTool.build(trace_root=…)` 是启动参数进来的那条正路。

    `--trace-root` → `build_real(trace_root=…)` → `TraceTool.build(trace_root=…)`
    → `LocalTrace(root=…)`——这条钉住工厂那一环：落盘位置就是给定的根。
    传的是 **str**（命令行进来的就是字符串）：钉住 store 侧的 str → Path 归一
    （探针实测过不归一会 `TypeError`）。
    """
    tool = TraceTool.build(run_id="run-0916", trace_root=str(tmp_path))

    tool.append(_step_advance())

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1, "落盘位置应是给定的 trace_root，不是缺省根"
