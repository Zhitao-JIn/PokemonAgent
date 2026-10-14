"""trace 落盘契约的用法示范（0927 双时刻版）：一事件一json + 七字段 + `(ended_at, uuid)` 排序。

**为什么这个文件值钱**：这条契约是三份定义靠人工同步维系的——trace 的协议
（`trace/interface/event.py::Event`）、trace 的实现（`trace/datastore/event.py::_Event`）、
项目的形状（`schemas/harness/domain/trace_event.py::TraceEvent`），**没有编译器保护**。
结构化满足是隐式的，字段对不上时不会报错、只会静默丢字段。
**一条测试是这件事唯一的机械保障。**

**0914 封套改造换了什么**：九个字段收成**六个**（`{uuid, kind, type, ts, meta, content}`），
`event_id` / `schema_version` / `frame_png` / 顶层 `run_id`·`episode_id`·`step`
四组一起下线或搬家。**2026-09-27 双时刻改造又换了什么**：单值 `ts` 换成操作真实
起止 `started_at` / `ended_at`（七个字段），排序键换成 `(ended_at, uuid)`；
`ts` 这一笔的调用方交、缺省由落盘层补记账时刻。

它同时是这个契约的用法示范（"测试是用法示范"）：造一个 `TraceTool`、记几笔账、
读回来——三步就是这个契约的全部。

**不连网、不碰模拟器、不调模型、不往仓库的 `tracelog/` 写**：落盘根用 `tmp_path`
（`LocalTrace(root=…)`）。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    ModelCall,
    TraceKind,
)
from pokemon_agent.trace import Event, LocalTrace

# 时间递增 uuid（v7 布局）：版本位是 7、变体位是 8/9/a/b。
_UUID_V7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json")


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


def test_trace_writes_one_json_per_event_named_by_its_uuid(tmp_path: pathlib.Path) -> None:
    """落盘形态：一条事件一个 json，**全平铺在落盘根下**，顺序认 `(ts, uuid)`。

    平铺（0916）：事件直接躺在落盘根里，既没有 `run_id/` 也没有 `events/` 那两层
    ——run 的区分交给事件 `meta.run_id`（见下面那条交集筛选的测试）。

    `TraceTool.append` 返回 `None`（见 `TraceToolPort.append`）——一笔 req 可能展开成
    多条事件，交回一个 id 说不清是哪一个；要 uuid 就读盘上的文件名。
    """
    tool = _tool(tmp_path)

    tool.append(_step_advance(0))
    tool.append(_step_advance(1))

    files = sorted(tmp_path.glob("*.json"))
    events = tool.read_events()

    assert len(files) == len(events) == 2  # 一条事件一个文件
    assert all(_UUID_V7.fullmatch(f.name) for f in files), [f.name for f in files]
    assert {f.stem for f in files} == {e.uuid for e in events}, "文件名就是事件里的 uuid"
    assert [(e.ended_at, e.seq) for e in events] == sorted((e.ended_at, e.seq) for e in events)


def test_event_has_exactly_the_seven_contract_fields(tmp_path: pathlib.Path) -> None:
    """双时刻改造后：七个字段，**一个都不多**。

    `Event` 协议与 `_Event` 实现**逐字段对齐**这件事没有编译器保护——这条测试
    就是那句话的可执行版本。"不多"这一半同样是判据：多出来的顶层键说明有人
    在封套外面另挂了一件东西，而那正是上一版形状（`payload` + 九个字段）的由来。
    """
    tool = _tool(tmp_path)
    tool.append(_step_advance())

    (event,) = tool.read_events()
    dumped = event.model_dump()

    assert set(dumped) == {
        "uuid",
        "seq",
        "kind",
        "type",
        "started_at",
        "ended_at",
        "meta",
        "content",
    }
    assert event.started_at == event.ended_at, "没记真实起止的账：start=end=记账时刻"
    assert isinstance(event, Event)  # 结构化满足 trace 自己的协议（鸭子类型）
    assert event.kind == "advance_step", "`kind` 就是账名（0914 起没有翻译表）"
    assert event.type == "lifecycle"


def test_meta_and_content_are_json_strings_with_the_run_id_stamped_in(
    tmp_path: pathlib.Path,
) -> None:
    """`meta` / `content` 在盘上是 **JSON 字符串**（需要一层转义），读端 `json.loads` 回来。

    `run_id` 由 **tool 层**盖进 `meta`（0927 定案：执行线标识住 `TraceTool`，
    append 时盖，后端零持有），所以调用方交上去的 `source`/`episode_id`/`step`
    与它并列坐在四个键里。
    """
    tool = _tool(tmp_path, run_id="run-0914")
    tool.append(_step_advance(step=3, episode_id="run-0914-ep1"))

    (path,) = tmp_path.glob("*.json")
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert set(raw) == {"uuid", "seq", "kind", "type", "started_at", "ended_at", "meta", "content"}
    assert isinstance(raw["meta"], str) and isinstance(raw["content"], str), "盘上是字符串"
    meta = json.loads(raw["meta"])
    assert set(meta) == {"run_id", "branch", "source", "episode_id", "task_id", "step"}
    assert meta == {
        "run_id": "run-0914",
        "branch": "main",
        "source": "close_step",
        "episode_id": "run-0914-ep1",
        "task_id": "run-0914-ep1",
        "step": 3,
    }
    assert json.loads(raw["content"]) == {"next_step": "4"}, "正文只剩记录本体"


def test_reading_a_slice_goes_through_meta_not_the_envelope(tmp_path: pathlib.Path) -> None:
    """按 `meta` 交集筛选：`episode_id` 住在 `meta` 里，封套上没有这一维。

    封套改造的另一半代价——读者不能再"看一眼顶层就拿局号"，必须解一次 `meta`。
    这条钉住那个行为，也钉住"没匹配的给空表、不抛"。
    """
    tool = _tool(tmp_path)
    tool.append(_step_advance(0, episode_id="ep-1"))
    tool.append(_step_advance(0, episode_id="ep-2"))

    assert [
        len(tool.read_events({"episode_id": ep, "task_id": ep})) for ep in ("ep-1", "ep-2")
    ] == [1, 1]
    assert tool.read_events({"episode_id": "不存在的局", "task_id": "不存在的局"}) == []


def test_meta_filter_is_and_of_equalities(tmp_path: pathlib.Path) -> None:
    """`meta` 筛选是**交集**（每个键都要相等），不是"命中任意一个"。

    与 `MemoryStorePort.filter` 同一条语义：各条件的候选集取交集。这条把
    "AND 不是 OR"钉住——写成 OR 的话第三条会误命中。
    """
    tool = _tool(tmp_path)
    tool.append(_step_advance(0, episode_id="ep-1"))
    tool.append(_step_advance(1, episode_id="ep-2"))

    assert len(tool.read_events({"episode_id": "ep-1", "task_id": "ep-1"})) == 1
    assert len(tool.read_events({"source": "close_step"})) == 2
    assert tool.read_events({"episode_id": "ep-1", "task_id": "ep-1", "step": 1}) == [], (
        "两条条件各命中一条、交集为空"
    )
    assert len(tool.read_events({"episode_id": "ep-1", "task_id": "ep-1", "step": 0})) == 1
    assert len(tool.read_events({})) == 2, "空 dict = 不过滤"


def test_two_runs_share_one_flat_directory_and_run_id_is_the_slice(
    tmp_path: pathlib.Path,
) -> None:
    """**平铺的代价与解法**：两个 run 的事件落在同一个目录里，靠 `meta.run_id` 分开。

    0916 之前一个 run 一个目录，读侧不用筛就天然隔离；平铺之后"这一批是谁的"
    只能问 `meta`——这条钉住那个语义。
    """
    a = _tool(tmp_path, run_id="run-a")
    b = _tool(tmp_path, run_id="run-b")
    a.append(_step_advance(0, episode_id="run-a-ep1"))
    b.append(_step_advance(0, episode_id="run-b-ep1"))

    assert len(list(tmp_path.glob("*.json"))) == 2, "两个 run 的事件平铺在同一层"
    assert [json.loads(e.meta)["run_id"] for e in a.read_events({"run_id": "run-a"})] == ["run-a"]
    assert [json.loads(e.meta)["run_id"] for e in b.read_events({"run_id": "run-b"})] == ["run-b"]
    assert len(a.read_events()) == 2, "不筛就是整个落盘根——两个 run 都看得见"


def test_a_missing_key_never_matches(tmp_path: pathlib.Path) -> None:
    """事件缺某个键时**不匹配**该条——不是"当作空值相等"。

    防的是"筛 `{"run_id": ""}` 顺手把缺 run_id 的残文件也捞出来"这一类错误：
    缺键与空值必须分开。
    """
    tool = _tool(tmp_path)
    tool.append(_step_advance(0, episode_id="ep-1"))

    assert tool.read_events({"不存在的键": "x"}) == []
    assert tool.read_events({"episode_id": "", "task_id": ""}) == [], "空值不等于缺键"


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


def test_uuid_is_the_file_name_and_lives_on_the_envelope(tmp_path: pathlib.Path) -> None:
    """`uuid` 既是文件名、又是封套字段，**同一个值**——两处互为对账。

    为什么盖章的人只能是 store：文件名是这个 uuid，而它到落盘那一刻才生成，
    渲染层根本拿不到（见 `store.new_event_uuid`、`CHANGELOG.md` 第 94 条）。
    0914 之前它挤在 payload 里跟 `kind` 并排，现在它就是封套自己的第一个字段。
    """
    tool = _tool(tmp_path)
    tool.append(_step_advance())

    (path,) = tmp_path.glob("*.json")
    (event,) = tool.read_events()

    assert event.uuid == path.stem


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


def test_default_root_is_the_startup_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不传 `root` 时落盘根是**启动目录**下的 `tracelog/`（0916 起）。

    `LocalTrace` 不再从 `__file__` 回溯仓库根——"数据落在哪"由启动方决定
    （`--trace-root` → `build_real` → `TraceTool.build` → 这里）。这条把缺省
    钉在"启动目录"上：monkeypatch.chdir 模拟"从别处启动"。
    事件就落在那个根**里面**（平铺，不再往下开 run 目录）。
    """
    monkeypatch.chdir(tmp_path)
    store = LocalTrace()

    store.append(
        "lifecycle",
        "advance_step",
        {
            "run_id": "r",
            "branch": "main",
            "source": "s",
            "episode_id": "e",
            "task_id": "e",
            "step": 0,
        },
        {},
    )

    assert (tmp_path / "tracelog").is_dir()
    assert len(store.read_events()) == 1


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
