"""`node_io` 的用法示范：**三层账怎么算"逐格都对上了"，以及错在哪会被抓**。

样本不是手写的：`_fake_run.run_fake()` 用假大脑 / 假世界把**真的三张图**跑一遍，落盘账本
就是 harness 真实会发的形状。正例是三种局面（正常两局 / task 失败后重拆 / 半路抛错的局）；
反例每条只改正常样本的**一处**，断言核对当场炸，且炸出来的话指得回那一处。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from _fake_run import every, never, run_fake
from _harness_fixtures import node_io

from pokemon_agent.harness.episode.episode_graph import compile_episode_graph
from pokemon_agent.harness.run.run_graph import compile_run_graph
from pokemon_agent.harness.task.task_graph import compile_task_graph

EP1 = "r1-ep1"


@pytest.fixture(scope="module")
def normal(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    """正常的 run：两局，每局两个 task，每个 task 两键。"""
    return run_fake(tmp_path_factory.mktemp("normal"))


@pytest.fixture
def events(normal: list[dict]) -> list[dict]:
    """正常样本的一份可改副本。"""
    return copy.deepcopy(normal)


def _check_all(events: list[dict]) -> None:
    """`check_harness` 的那一串核对。"""
    node_io.check_run_markers(events)
    node_io.check_vocabulary(events)
    node_io.check_payloads(events)
    node_io.check_layer_flow(events)
    node_io.check_run_invariants(events)
    for episode_id in node_io.episode_ids(events):
        node_io.check_node_coverage(events, episode_id)
        node_io.check_content_invariants(events, episode_id)


def _content(event: dict) -> dict:
    return json.loads(event["content"])


def _set_content(event: dict, key: str, value: object) -> None:
    content = _content(event)
    content[key] = value
    event["content"] = json.dumps(content, ensure_ascii=False)


def _meta(event: dict) -> dict:
    return json.loads(event["meta"])


def _set_meta(event: dict, key: str, value: object) -> None:
    meta = _meta(event)
    meta[key] = value
    event["meta"] = json.dumps(meta, ensure_ascii=False)


def _find(events: list[dict], kind: str, *, nth: int = 0) -> dict:
    return [e for e in events if e["kind"] == kind][nth]


def _drop(events: list[dict], kind: str, *, nth: int = 0) -> list[dict]:
    target = _find(events, kind, nth=nth)
    return [e for e in events if e is not target]


# ============================================================
# 正例：三种局面都过全部核对
# ============================================================


def test_a_normal_run_passes_every_check(events: list[dict]) -> None:
    _check_all(events)
    assert node_io.episode_ids(events) == ["r1-ep1", "r1-ep2"]


def test_a_failed_task_is_followed_by_a_fresh_decomposition(tmp_path: Path) -> None:
    """task 靠预算收场（失败）→ 剩余链被清空 → 下一圈重拆；账照样走得通。"""
    events = run_fake(tmp_path, task=never, episode=every(2), run=lambda asked: True)
    _check_all(events)
    stream = [token for token, _ in node_io.episode_stream(events, EP1)]
    assert stream.count("decompose_verdict") == 2
    ends = [_content(e)["termination"] for e in events if e["kind"] == "task_end"]
    assert ends == ["budget_exhausted", "budget_exhausted"]
    stamps = [_content(e) for e in events if e["kind"] == "settle_task"]
    assert [(s["task_id"], s["status"], s["round"], s["abandoned"]) for s in stamps] == [
        ("g1-t1", "failed", "1", ["g1-t2"]),
        ("g1-t3", "failed", "2", ["g1-t4"]),
    ], "失败定案后同一版剩下的条目被放弃；重拆的是第 2 版、id 接着往下数"


class _OverturnFirstJudgement:
    """首次审 episode 的达成裁决时推翻，其余认账。"""

    def __init__(self) -> None:
        self.audited: list[str] = []

    def inject(self, req):  # noqa: ANN001
        from pokemon_agent.schemas.harness import FromHarnessToReviewerInjectResp

        return FromHarnessToReviewerInjectResp(text="", answered=True)

    def audit(self, req):  # noqa: ANN001
        from pokemon_agent.schemas.harness import AuditVerdict, FromHarnessToReviewerAuditResp

        self.audited.append(req.episode_id)
        if req.episode_id == EP1 and self.audited.count(EP1) == 1:
            return FromHarnessToReviewerAuditResp(
                verdict=AuditVerdict.OVERTURN, note="其实没到", answered=True
            )
        return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT, answered=True)


def test_a_judge_overturn_leaves_task_settlements_mechanical(tmp_path: Path) -> None:
    """推翻 episode 的达成裁决后，task 的机械结算和来源账仍一致。"""
    reviewer = _OverturnFirstJudgement()

    events = run_fake(tmp_path, episode=every(2), run=every(1), reviewer=reviewer)

    _check_all(events)
    stamps = [_content(e) for e in events if e["kind"] == "settle_task"]
    assert stamps and all(s["status"] == "completed" for s in stamps)
    assert all(s["overturned"] == "false" and s["audit"] == "" for s in stamps)
    assert all(not s["abandoned"] for s in stamps)
    assert reviewer.audited == [EP1, "r1"]
    end = next(_content(e) for e in events if e["kind"] == "task_end")
    assert end["termination"] == "goal_done"


def test_a_task_that_breaks_mid_way_fails_and_the_episode_goes_on(tmp_path: Path) -> None:
    """第二键上世界抛错：episode 的 `act` 接住。

    记 `task_error`、这个 task 盖成失败，这一局照常收尾。
    """
    events = run_fake(tmp_path, fail_on_press=2, run=lambda asked: True)
    _check_all(events)
    assert node_io.episode_status(events, EP1) == "closed"
    errors = [e for e in events if e["kind"] == "task_error"]
    assert len(errors) == 1 and _meta(errors[0])["source"] == "episode.act"
    broken = _meta(errors[0])["task_id"]
    stamp = next(
        e for e in events if e["kind"] == "settle_task" and _content(e)["task_id"] == broken
    )
    assert _content(stamp)["status"] == "failed"


def test_an_episode_that_breaks_is_closed_by_the_run_act(tmp_path: Path) -> None:
    """首次拆解就抛错：run 的 `act` 接住——补空章、记 `episode_error`，收尾链与 task 层不算漏。"""
    events = run_fake(tmp_path, fail_on_decompose=1, run=lambda asked: True)
    _check_all(events)
    assert node_io.episode_status(events, EP1) == "failed"
    tail = [(e["kind"], _meta(e)["source"]) for e in events if _meta(e)["episode_id"] == EP1][-2:]
    assert tail == [("write_episode_memory", "run.act"), ("episode_error", "run.act")]
    missing = node_io.check_node_coverage(events, EP1)
    assert "close_episode" in missing and "close_task" in missing


# ============================================================
# 静态：清单与真源对得上
# ============================================================


def _nodes(graph: object) -> list[str]:
    names = list(graph.get_graph().nodes)  # type: ignore[attr-defined]
    return [name for name in names if name not in ("__start__", "__end__")]


def test_the_cell_lists_match_the_three_compiled_graphs() -> None:
    node_io.check_node_list_matches_graph(
        _nodes(compile_run_graph()), _nodes(compile_episode_graph()), _nodes(compile_task_graph())
    )
    node_io.check_model_call_links_match_render()
    node_io.check_terminations_match_enum()


def test_every_cell_either_names_its_sources_or_is_silent() -> None:
    for cell, sources in node_io.CELL_SOURCES.items():
        if sources:
            assert set(sources) <= node_io.KNOWN_SOURCES, cell
        else:
            assert cell in node_io.SILENT_NODES, f"{cell} 不发账却没登记为静默格"
    assert set(node_io.NODE_FINGERPRINTS) <= node_io.KNOWN_SOURCES
    assert set(node_io.CONDITIONAL_NODES) <= set(node_io.NODE_FINGERPRINTS)


# ============================================================
# 反例：流（顺序 / 缺格 / 多格）
# ============================================================


def test_a_press_before_its_decision_is_caught(events: list[dict]) -> None:
    think, press = _find(events, "choose_verdict"), _find(events, "act_call")
    i, j = events.index(think), events.index(press)
    events[i], events[j] = events[j], events[i]
    with pytest.raises(AssertionError, match="不能跟在"):
        node_io.check_layer_flow(events)


def test_a_missing_act_memory_write_is_caught(events: list[dict]) -> None:
    with pytest.raises(AssertionError, match="write_act_memory|advance_step"):
        node_io.check_layer_flow(_drop(events, "write_act_memory"))


def test_an_episode_round_without_its_observation_is_caught(events: list[dict]) -> None:
    # nth=2：全局第 0 个 sense_frame 是 run 层的、第 1 个是 episode 层的（0928 起
    # run/episode 每圈各取一帧），这里 drop 的是 task 流的第一个。
    with pytest.raises(AssertionError, match="observe|read_act_memory"):
        node_io.check_layer_flow(_drop(events, "sense_frame", nth=2))


def test_a_task_that_never_closes_in_a_closed_episode_is_caught(events: list[dict]) -> None:
    with pytest.raises(AssertionError, match="没走到结尾"):
        node_io.check_layer_flow(_drop(events, "task_end"))


def test_a_run_that_skips_the_stamp_is_caught(events: list[dict]) -> None:
    with pytest.raises(AssertionError, match="盖了|不能跟在"):
        trimmed = _drop(events, "settle_goal")
        node_io.check_layer_flow(trimmed)
        node_io.check_run_invariants(trimmed)


def test_a_source_that_leaves_no_trace_is_caught(events: list[dict]) -> None:
    trimmed = [e for e in events if _meta(e)["source"] != "detect_stall"]
    with pytest.raises(AssertionError, match="detect_stall"):
        node_io.check_node_coverage(trimmed, EP1)


# ============================================================
# 反例：层间衔接
# ============================================================


def test_a_task_that_miscounts_its_keys_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "task_end"), "steps_used", "5")
    with pytest.raises(AssertionError, match="steps_used"):
        node_io.check_content_invariants(events, EP1)


def test_an_episode_that_miscounts_its_tasks_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "episode_end"), "tasks_used", "7")
    with pytest.raises(AssertionError, match="tasks_used"):
        node_io.check_content_invariants(events, EP1)


def test_an_episode_that_miscounts_its_keys_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "episode_end"), "acts_used", "9")
    with pytest.raises(AssertionError, match="acts_used"):
        node_io.check_content_invariants(events, EP1)


def test_a_broken_step_advance_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "advance_step"), "next_step", "9")
    with pytest.raises(AssertionError, match="advance_step"):
        node_io.check_content_invariants(events, EP1)


def test_a_press_that_is_not_the_decided_key_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "act_call"), "sequence", [{"name": "b", "times": 1}])
    with pytest.raises(AssertionError, match="首键"):
        node_io.check_content_invariants(events, EP1)


def test_a_dispatched_task_that_no_plan_gave_is_caught(events: list[dict]) -> None:
    verdict = _find(events, "decompose_verdict")
    tasks = _content(verdict)["tasks"]
    _set_content(verdict, "tasks", [dict(t, task_id=f"other-{i}") for i, t in enumerate(tasks)])
    with pytest.raises(AssertionError, match="拆解"):
        node_io.check_content_invariants(events, EP1)


def test_a_settlement_that_still_records_success_is_caught(events: list[dict]) -> None:
    """成没成由 `termination` 推出，结算账里再记一份 `success` 就是第二个真相来源。"""
    _set_content(_find(events, "task_end"), "success", "true")
    with pytest.raises(AssertionError, match="推出"):
        node_io.check_content_invariants(events, EP1)


def test_an_unknown_termination_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "episode_end"), "termination", "gave_up")
    with pytest.raises(AssertionError, match="termination"):
        node_io.check_content_invariants(events, EP1)


def test_a_stamp_on_the_wrong_episode_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "settle_goal", nth=1), "episode_id", EP1)
    with pytest.raises(AssertionError, match="刚结束的一局"):
        node_io.check_run_invariants(events)


def test_a_run_total_that_disagrees_with_the_dispatches_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "run_end"), "total", "3")
    with pytest.raises(AssertionError, match="run_end.total"):
        node_io.check_run_invariants(events)


# ============================================================
# 反例：词表 / 封套 / 正文
# ============================================================


def test_an_unregistered_kind_is_caught(events: list[dict]) -> None:
    events[3]["kind"] = "made_up"
    with pytest.raises(AssertionError, match="没登记"):
        node_io.check_vocabulary(events)


def test_a_meta_that_grows_its_own_key_is_caught(events: list[dict]) -> None:
    _set_meta(events[0], "extra", 1)
    with pytest.raises(AssertionError, match="meta 键"):
        node_io.check_payloads(events)


def test_a_meta_step_that_is_a_string_is_caught(events: list[dict]) -> None:
    _set_meta(events[0], "step", "0")
    with pytest.raises(AssertionError, match="非负整数"):
        node_io.check_payloads(events)


def test_an_episode_shaped_task_id_is_caught(events: list[dict]) -> None:
    """episode 层账 task 位清空（0928 定稿）——与 episode_id 同值的旧口径占位当场拦下。"""
    _set_meta(_find(events, "episode_start"), "task_id", EP1)
    with pytest.raises(AssertionError, match="task_id"):
        node_io.check_payloads(events)


def test_an_unknown_source_is_caught(events: list[dict]) -> None:
    _set_meta(_find(events, "write_act_memory"), "source", "store_steps")
    with pytest.raises(AssertionError, match="不是个真发送位置"):
        node_io.check_payloads(events)


def test_a_payload_missing_a_required_field_is_caught(events: list[dict]) -> None:
    event = _find(events, "task_start")
    content = _content(event)
    del content["total_acts"]
    event["content"] = json.dumps(content)
    with pytest.raises(AssertionError, match="total_acts"):
        node_io.check_payloads(events)


def test_a_write_body_that_repeats_the_chapter_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "write_task_memory"), "termination", "goal_done")
    with pytest.raises(AssertionError, match="termination"):
        node_io.check_payloads(events)


def test_a_write_body_that_carries_a_frame_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "write_act_memory"), "before_frame", "iVBOR…")
    with pytest.raises(AssertionError, match="before_frame"):
        node_io.check_payloads(events)


def test_a_capital_boolean_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "sense_frame", nth=1), "done", "False")
    with pytest.raises(AssertionError, match="小写"):
        node_io.check_payloads(events)


def test_a_read_whose_refs_are_not_an_array_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "read_act_memory"), "refs", "a,b")
    with pytest.raises(AssertionError, match="字符串数组"):
        node_io.check_content_invariants(events, EP1)


def test_a_read_that_never_says_what_it_asked_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "read_episode_memory", nth=1), "query", "")
    with pytest.raises(AssertionError, match="query"):
        node_io.check_content_invariants(events, EP1)


def test_a_structured_field_that_became_a_json_string_again_is_caught(events: list[dict]) -> None:
    _set_content(_find(events, "sense_frame", nth=2), "facts", "{}")
    with pytest.raises(AssertionError, match="facts"):
        node_io.check_content_invariants(events, EP1)


def test_a_run_id_that_is_not_shared_by_every_event_is_caught(events: list[dict]) -> None:
    _set_meta(events[-1], "run_id", "r2")
    with pytest.raises(AssertionError, match="多个 run_id"):
        node_io.check_run_markers(events)


# ============================================================
# 错误族：三个闭集成员，同带 `link`
# ============================================================


def _error(kind: str, content: dict) -> dict:
    meta = {
        "run_id": "r1",
        "branch": "main",
        "source": "summarize_task",
        "episode_id": EP1,
        "task_id": "g1-t1",
        "step": 2,
    }
    return {
        "uuid": "e",
        "kind": kind,
        "type": "error",
        "started_at": 0.0,
        "ended_at": 0.0,
        "meta": json.dumps(meta),
        "content": json.dumps(content, ensure_ascii=False),
    }


@pytest.mark.parametrize(
    ("kind", "content"),
    [
        ("call_failed", {"link": "choose", "exception": "ParseFailure", "reason": "x"}),
        ("call_exhausted", {"link": "judge"}),
        ("summary_parse_error", {"link": "summarize_task", "reason": "不是 JSON"}),
    ],
)
def test_each_error_account_passes_with_its_fields(kind: str, content: dict) -> None:
    events = [_error(kind, content)]
    node_io.check_vocabulary(events)
    node_io.check_payloads(events)


def test_an_error_account_missing_its_link_is_caught() -> None:
    events = [_error("summary_parse_error", {"reason": "x"})]
    with pytest.raises(AssertionError, match="link"):
        node_io.check_payloads(events)


def test_error_accounts_stay_out_of_the_flow(events: list[dict]) -> None:
    """错误账（与调用账）条数随重试浮动，不进流：插一条进来流照样走得通。"""
    events.insert(40, _error("call_failed", {"link": "choose", "exception": "E", "reason": "x"}))
    node_io.check_layer_flow(events)
