"""`LangfuseTrace` 的用法示范与契约钉子：注入 fake client，全程零联网。

**为什么这个文件值钱**：Langfuse 路径把项目事件封套塞进 Langfuse observation、
把 scope 层级映射成父子 span——这一整层
转换没有任何编译器保护，错一步就是"trace 落了但读不回"或"层级锚点挂错"。
一条测试就是一句话的可执行版本（`AGENTS.md` 第五节）。

**全部离线**：SDK client 用 `tests/_fake_langfuse.py` 的记录型假件注入
（`LangfuseTrace(trace_id=…, client=…)` 的 `client` 形参就是给契约测试留的口）。
不连服务、不要密钥、不碰模拟器、不调模型、不往启动目录写任何文件。

**三步就是全部用法**：构造（trace_id 由调用方 seed 出、注入假 client）→
append（meta 带盖章好的 run_id/branch）→ read_events（读回）。
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from _fake_langfuse import FakeLangfuseClient

from pokemon_agent.trace import LangfuseTrace, TracePort

_UUID_V7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def _trace(client: FakeLangfuseClient, seed: str = "run-1") -> LangfuseTrace:
    """造一个绑定假 client 的 `LangfuseTrace`。

    trace_id 由调用方 seed 出（0927 定案：后端零持有执行线身份，tool 层/测试
    同款两步——`create_trace_id(seed=run_id)` → 递 trace_id）。
    """
    return LangfuseTrace(trace_id=client.create_trace_id(seed=seed), client=client)


def _meta(
    episode_id: str = "ep-1",
    task_id: str = "task-1",
    step: int = 0,
    branch: str = "main",
    **extra: Any,
) -> dict[str, Any]:
    """一笔账的最小签名信息（与 harness 一次交齐的四件同形，含盖章的两件）。

    缺省按 task 层账的形状：task_id 是真 task 号（0928 定稿位约定：run 级账两位都
    放 run_id、episode 级账的 task 位清空，见 `run/begin` 的位约定）。
    `run_id` / `branch` 由调用方盖（tool 层在生产路径盖，测试里在这里盖）。
    """
    return {
        "source": "test",
        "run_id": "run-1",
        "branch": branch,
        "episode_id": episode_id,
        "task_id": task_id,
        "step": step,
        **extra,
    }


# ---- 协议与 ID ----


def test_langfuse_trace_satisfies_the_trace_port_protocol() -> None:
    """结构化满足 `TracePort`（append / read_events / flush / shutdown 四件齐）。"""
    trace = _trace(FakeLangfuseClient())

    assert isinstance(trace, TracePort)


def test_a_non_empty_trace_id_is_required() -> None:
    """trace_id 是本模块唯一的身份件，空串在构造期就拒绝。"""
    with pytest.raises(ValueError, match="trace_id"):
        LangfuseTrace(trace_id="", client=FakeLangfuseClient())


def test_the_same_seed_shares_one_trace_and_different_seeds_do_not() -> None:
    """同一 `seed` 恒得同一 Langfuse trace_id；不同 run 不共 trace。

    seed → trace_id 的确定性在调用方两步（`create_trace_id(seed=…)` → 递
    trace_id）——同 seed 的多次构造因此得到同一条 trace_id。
    构造期不落 observation——observation 要到首笔账才有。
    """
    client = FakeLangfuseClient()

    first = _trace(client, seed="run-a")
    second = _trace(client, seed="run-a")
    third = _trace(client, seed="run-b")
    first.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {})
    second.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {})
    third.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {})

    # 每个实例的 branch scope 按创建顺序排：前两个属 run-a，第三个属 run-b。
    branch_ids = [
        o.trace_context["trace_id"] for o in client.observations if o.name == "branch:main"
    ]
    assert len(branch_ids) == 3
    assert branch_ids[0] == branch_ids[1], "同 seed 恒同 trace"
    assert branch_ids[0] != branch_ids[2], "不同 run 不混在同一 trace"


# ---- 封套与盖章 ----


def test_meta_arrives_stamped_and_passes_through_verbatim() -> None:
    """`meta` 已由调用方（tool 层）盖好 `run_id` / `branch`，本模块透传不重盖。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    event_uuid = trace.append("lifecycle", "advance_step", _meta(step=3), {"next_step": 4})

    events = trace.read_events()
    assert len(events) == 1
    stamped = json.loads(events[0].meta)
    assert stamped["run_id"] == "run-1", "盖章过的 run_id 原样落进 observation"
    assert stamped["branch"] == "main"
    assert stamped["step"] == 3, "调用方交的键原样保留"
    assert _UUID_V7.fullmatch(event_uuid), "合法路径照常返回本地事件 uuid"


def test_meta_without_run_id_or_branch_is_refused() -> None:
    """缺 `run_id` / `branch` 的 meta 当场拒绝——本模块零持有执行线身份。"""
    trace = _trace(FakeLangfuseClient())
    bare = {"source": "test", "episode_id": "", "task_id": "", "step": 0}

    with pytest.raises(AssertionError, match="run_id / branch"):
        trace.append("lifecycle", "advance_step", bare, {})


def test_envelope_roundtrips_unicode_nested_and_literal_values_losslessly() -> None:
    """封套可无损解码：Unicode、嵌套对象、布尔、空值、数值类型全保真。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    content = {
        "text": "中文🎉",
        "nested": {"list": [1, 2.5, True, None], "empty": ""},
        "flag": False,
    }

    trace.append("view", "sense_frame", _meta(step=1), content)

    (event,) = trace.read_events()
    assert isinstance(event.meta, str) and isinstance(event.content, str)
    decoded = json.loads(event.content)
    assert decoded == content, "content 原样往返"
    assert decoded["nested"]["list"][2] is True and decoded["nested"]["list"][3] is None
    assert decoded["text"] == "中文🎉"
    assert json.loads(event.meta)["episode_id"] == "ep-1"


def test_append_returns_the_local_uuid_not_an_observation_id() -> None:
    """返回值是本地事件 UUID（v7 布局），与 Langfuse observation ID 两回事。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    first = trace.append("lifecycle", "advance_step", _meta(step=0), {})
    second = trace.append("lifecycle", "advance_step", _meta(step=1), {})

    assert _UUID_V7.fullmatch(first) and _UUID_V7.fullmatch(second)
    assert first != second
    observation = client.observation_of(first)
    assert observation.id != first, "observation ID 由 SDK 生成，不冒充本地事件 UUID"
    envelope = observation.output["pokemon_trace"]
    assert envelope["uuid"] == first, "封套 uuid 与返回值同值，可互相对账"
    assert envelope["kind"] == "advance_step" and envelope["type"] == "lifecycle"
    assert observation.metadata["local_event_uuid"] == first
    assert observation.metadata["event_kind"] == "advance_step"


def test_events_are_sorted_by_ended_at_then_seq() -> None:
    """`read_events` 按 `(ended_at, seq)` 严格升序——同刻账按 append 序决胜（0928 325）。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    for step in range(5):
        trace.append("lifecycle", "advance_step", _meta(step=step), {})

    events = trace.read_events()
    keys = [(e.ended_at, e.seq) for e in events]
    assert keys == sorted(keys)
    assert [json.loads(e.meta)["step"] for e in events] == [0, 1, 2, 3, 4]


def test_real_start_and_end_times_pass_through_the_envelope() -> None:
    """调用方记的真实起止原样进封套（不单调化、不补记账时刻）。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    trace.append(
        "model_call",
        "choose_call",
        _meta(step=1),
        {"prompt": "…"},
        started_at=100.0,
        ended_at=103.5,
    )

    (event,) = trace.read_events()
    assert (event.started_at, event.ended_at) == (100.0, 103.5), "操作真实起止逐字落封套"


# ---- observation 类型映射 ----


def test_every_observation_carries_the_adapter_version() -> None:
    """逐账 `version="0.1.0"`（2026-09-27 字段适配定案），scope 锚同样带。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    run_uuid = trace.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {})
    trace.append("lifecycle", "episode_start", _meta(task_id=""), {})
    trace.append("act", "press_key", _meta(step=1), {"key": "a"})

    assert client.observation_named("branch:main").version == "0.1.0"
    assert client.observation_of(run_uuid).version == "0.1.0"
    assert all(o.version == "0.1.0" for o in client.observations), "scope 锚与账统一带版本"


def test_a_model_call_is_a_generation_with_model_and_usage() -> None:
    """`type == "model_call"` → generation；模型名、token 数与请求面从 content 投影。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    content = {
        "model": "deepseek-flash",
        "input_tokens": 120,
        "output_tokens": 30,
        "prompt": "…",
        "raw": '{"keys":["a"]}',
        "images": ["data:image/png;base64,AAAA"],
    }

    event_uuid = trace.append("model_call", "choose_call", _meta(step=1), content)

    observation = client.observation_of(event_uuid)
    assert observation.name == "step:1 choose_call", "task 层操作账名带 step 前缀"
    assert observation.as_type == "generation"
    assert observation.model == "deepseek-flash"
    assert observation.usage_details == {"input": 120, "output": 30}
    assert observation.input == {"prompt": "…", "images": ["data:image/png;base64,AAAA"]}, (
        "generation 的 input 是发出去的请求（prompt/images），供 Dashboard 直读"
    )
    assert observation.output["pokemon_trace"]["content"] == content, "投影不改动封套本体"


def test_an_error_event_is_a_langfuse_event_with_error_level() -> None:
    """错误账用 Langfuse event + ERROR level，status_message 带账名。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    content = {"link": "choose", "exception": "ParseFailure", "reason": "…"}

    trace.append("error", "call_failed", _meta(step=1), content)

    observation = client.observation_named("call_failed")
    assert observation.level == "ERROR"
    assert observation.status_message == "call_failed"
    assert observation.as_type is None, "错误走 create_event，不是 span/generation"
    assert observation.output["pokemon_trace"]["content"] == content


def test_a_retrieve_account_is_a_retriever_with_the_query_as_input() -> None:
    """六条 RAG 读口 → retriever 类型，input 投 `query`（检索的请求面）；refs 不重复投。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    content = {"query": "episode_id=ep-1", "refs": ["(ep-1, 3)", "(ep-1, 4)"]}

    event_uuid = trace.append("memory_io", "read_act_memory", _meta(step=2), content)

    observation = client.observation_of(event_uuid)
    assert observation.as_type == "retriever"
    assert observation.input == {"query": "episode_id=ep-1"}, "input=这次检索的请求面"
    assert observation.version == "0.1.0"
    assert observation.output["pokemon_trace"]["content"] == content, "投影不改动封套本体"


def test_plain_events_are_spans_with_empty_input() -> None:
    """非模型账是 span 且 input=None——它们的"输入"没有独立语义，真源在封套。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    trace.append("lifecycle", "episode_start", _meta(task_id=""), {})
    trace.append("lifecycle", "task_start", _meta())

    event_uuid = trace.append("act", "press_key", _meta(step=2), {"key": "a"})

    observation = client.observation_of(event_uuid)
    task_obs = client.observation_named("task_start")
    assert observation.as_type == "span"
    assert observation.input is None, "占位 uuid 已废：该值在 metadata 里，input 不重复"
    assert observation.trace_context == {
        "trace_id": task_obs.trace_context["trace_id"],
        "parent_span_id": task_obs.id,
    }, "step 不建 scope（0928 定稿）：操作账直接挂 task_start 锚下"


# ---- scope 层级 ----


def test_scope_tree_uses_real_parent_ids_down_the_chain() -> None:
    """branch → run_start → episode → task 的父子链逐级真实；操作账挂 task 锚、不建 step scope。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    run_uuid = trace.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {})
    episode_uuid = trace.append("lifecycle", "episode_start", _meta(task_id=""), {})
    task_uuid = trace.append("lifecycle", "task_start", _meta(), {})
    sense_uuid = trace.append("view", "sense_frame", _meta(step=0), {})

    branch_scope = client.observation_named("branch:main")
    run_obs = client.observation_of(run_uuid)
    episode_obs = client.observation_of(episode_uuid)
    task_obs = client.observation_of(task_uuid)
    sense_obs = client.observation_of(sense_uuid)

    assert "parent_span_id" not in branch_scope.trace_context, (
        "branch scope 是顶层锚，构造期不建、首笔账时建"
    )
    assert branch_scope.metadata["scope_kind"] == "branch"
    assert run_obs.trace_context["parent_span_id"] == branch_scope.id, (
        "run_start 挂 branch scope 下，本身注册为 run 层锚"
    )
    assert episode_obs.trace_context["parent_span_id"] == run_obs.id, (
        "episode_start 挂 run_start（run_start 账本身就是 run 层锚）"
    )
    assert task_obs.trace_context["parent_span_id"] == episode_obs.id, (
        "task_start 挂 episode scope（episode_start 账本身就是 scope）"
    )
    assert episode_obs.name == "episode_start", (
        "episode 层账不标 step——task 位已清空（0928 定稿），不再是 step 归属方"
    )
    assert sense_obs.trace_context["parent_span_id"] == task_obs.id, (
        "操作账挂 task 锚下——step 不建 scope（0928 定稿）"
    )
    assert sense_obs.name == "step:0 sense_frame", "step 号前缀标注在账名上"


def test_run_level_events_hang_below_the_run_start_anchor() -> None:
    """run 层收尾账（settle_goal / run_end）挂 run_start 锚下，不散在 branch scope。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    run_uuid = trace.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {})
    settle_uuid = trace.append("lifecycle", "settle_goal", _meta(episode_id="", task_id=""), {})
    end_uuid = trace.append("lifecycle", "run_end", _meta(episode_id="", task_id=""), {})

    run_obs = client.observation_of(run_uuid)
    assert client.observation_of(settle_uuid).trace_context["parent_span_id"] == run_obs.id
    assert client.observation_of(end_uuid).trace_context["parent_span_id"] == run_obs.id


def test_operations_in_the_same_step_are_labelled_not_scoped() -> None:
    """同一 task/step 的多笔操作账不建 step scope——step 号标注在账名、全挂同一个 task 锚。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    trace.append("lifecycle", "episode_start", _meta(task_id=""), {})
    trace.append("lifecycle", "task_start", _meta())

    first = trace.append("view", "sense_frame", _meta(step=3), {})
    second = trace.append("act", "press_key", _meta(step=3), {})

    task_obs = client.observation_named("task_start")
    first_obs = client.observation_of(first)
    second_obs = client.observation_of(second)
    assert first_obs.name == "step:3 sense_frame", "step 号前缀标在账名上，不建 scope"
    assert second_obs.name == "step:3 press_key"
    assert first_obs.trace_context["parent_span_id"] == task_obs.id
    assert second_obs.trace_context["parent_span_id"] == task_obs.id
    assert not [o for o in client.observations if re.fullmatch(r"step:\d+", o.name)], (
        "step scope 整层不存在（0928 定稿）——前缀账名是 `step:N {kind}`，不是裸 step:N"
    )


# ---- 读侧：筛选、跳过、错误 ----


def test_read_events_filters_by_and_of_equality() -> None:
    """meta 筛选是 AND-of-equalities，与 LocalTrace 同一条语义。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    trace.append(
        "lifecycle", "advance_step", _meta(episode_id="ep-1", task_id="task-1", step=0), {}
    )
    trace.append(
        "lifecycle", "advance_step", _meta(episode_id="ep-2", task_id="task-2", step=1), {}
    )

    assert len(trace.read_events({"episode_id": "ep-1", "task_id": "task-1"})) == 1
    assert len(trace.read_events({"run_id": "run-1"})) == 2, "盖过章的键照常可筛"
    assert trace.read_events({"episode_id": "不存在的局"}) == []
    assert len(trace.read_events(None)) == 2, "None = 不过滤"


def test_read_events_skips_observations_without_the_project_envelope() -> None:
    """没有 `pokemon_trace` 封套的 observation（外部 instrumented）跳过不报错。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    trace.append("lifecycle", "advance_step", _meta(step=0), {})
    client._create(
        trace_context={"trace_id": client.observations[0].trace_context["trace_id"]},
        name="external-otel-span",
        as_type="span",
        output={"some": "foreign payload"},
    )
    client._create(
        trace_context={"trace_id": client.observations[0].trace_context["trace_id"]},
        name="json-string-output",
        as_type="span",
        output=json.dumps(
            {
                "pokemon_trace": {
                    "uuid": "018f0000-0000-7000-8000-000000000000",
                    "seq": 0,
                    "kind": "advance_step",
                    "type": "lifecycle",
                    "started_at": 1.0,
                    "ended_at": 1.0,
                    "meta": {},
                    "content": {},
                }
            }
        ),
    )

    events = trace.read_events()

    assert len(events) == 2, "外来的跳过；output 是 JSON 字符串的封套照样解码"
    assert any(e.uuid == "018f0000-0000-7000-8000-000000000000" for e in events)


def test_read_events_propagates_query_errors() -> None:
    """API 查询失败原样抛出，不伪装成空列表。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    client.fail_get_many = RuntimeError("observations api down")

    with pytest.raises(RuntimeError, match="observations api down"):
        trace.read_events()


# ---- 分页 ----


def test_reading_follows_cursor_pages_to_the_end() -> None:
    """多页 cursor 全部收齐才返回；每页查询都钉住 trace_id 与时间边界。

    这几笔账不带 episode/task——不建 step scope，trace 里恰好 6 个 observation
    （branch scope + 5 笔账），每页 2 条 → 3 次查询。
    """
    client = FakeLangfuseClient()
    trace = _trace(client)
    for step in range(5):
        trace.append("lifecycle", "advance_step", _meta(episode_id="", task_id="", step=step), {})
    client.page_size = 2

    events = trace.read_events()

    assert len(client.get_many_calls) == 3, "6 条 × 每页 2 → 3 次查询"
    assert [json.loads(e.meta)["step"] for e in events] == [0, 1, 2, 3, 4], "跨页不丢、序不乱"
    for call in client.get_many_calls:
        assert call["trace_id"] == client.observations[0].trace_context["trace_id"], (
            "每页都带 trace_id 限定数据集"
        )
        assert "from_start_time" in call and "to_start_time" in call, "每页都带时间边界"
        assert call["fields"] and call["limit"], "字段选择与页大小按规格传"


def test_pagination_stops_when_the_cursor_is_missing_or_repeats() -> None:
    """无 cursor 收尾、卡死游标跳出——两种退出场景都不死循环。"""
    single_client = FakeLangfuseClient()
    single = _trace(single_client)
    single.append("lifecycle", "advance_step", _meta(episode_id="", task_id="", step=0), {})

    assert len(single.read_events()) == 1, "无 cursor：单页返回全部"
    assert len(single_client.get_many_calls) == 1

    stuck_client = FakeLangfuseClient()
    stuck_client.page_size = 3
    stuck_client.stuck_cursor = "same"
    repeated = _trace(stuck_client)
    for _step in range(3):
        repeated.append("lifecycle", "advance_step", _meta(episode_id="", task_id=""), {})

    events = repeated.read_events()

    assert len(events) == 2, (
        "卡死游标收一页空数据就退出：第一页 3 行里 2 条带封套的账、第二页空、不重复堆叠"
    )
    assert len(stuck_client.get_many_calls) == 2
    assert stuck_client.get_many_calls[0].get("cursor") is None
    assert stuck_client.get_many_calls[1].get("cursor") == "same"


# ---- 生命周期 ----


def test_run_end_and_run_error_flush_the_sdk_queue() -> None:
    """run 收尾两本账触发 flush；显式 flush / shutdown 各自委托给 client。"""
    client = FakeLangfuseClient()
    trace = _trace(client)

    trace.append("lifecycle", "run_end", _meta(episode_id="", task_id=""), {})
    assert client.flush_count == 1, "run_end 自带一次 flush"

    trace.flush()
    assert client.flush_count == 2

    trace.shutdown()
    assert client.shutdown_count == 1


def test_a_flush_failure_is_recorded_not_raised() -> None:
    """flush 失败记 warning 不外溢——run 收场不被观测侧拖死。"""
    client = FakeLangfuseClient()
    trace = _trace(client)
    client.fail_flush = RuntimeError("queue jammed")

    trace.append("lifecycle", "run_error", _meta(episode_id="", task_id=""), {})
    trace.flush()

    assert client.flush_count == 2, "两次调用都到了 SDK，失败被记下而非炸出"
