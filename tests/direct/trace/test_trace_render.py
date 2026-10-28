"""`render.py` 的**正文**形状示范：同类事件一个形状，且不留名不副实的字段。

**为什么这个文件值钱**：这几列的格式没有编译器保护——核对脚本
（`tests/_harness_fixtures/node_io.py`）只查键名和少数逻辑关系（"空 refs 则 count
为 0"这类），"偷偷把 `[0]` 前缀加回来"这种回归它**拦不住**，只能等真机跑完、
人去看日志时才发现。这几条测试是这件事唯一的机械保障。

**0914 封套改造之后，渲染函数只管 `(type, kind, content)` 三件**：`kind` 就是
`req.kind`（没有翻译表），`content` 是**正文**——`meta`（`source` / 坐标）归
`TraceTool.append` 拼，`uuid` / `ts` 归落盘层盖。所以这里断言的都是**正文**：
封套那一层由 `tests/test_trace_store.py` 管。

它是用法示范，不是覆盖率任务：造一个最简 req、调一次渲染、断言那一列的形状。
见 `CHANGELOG.md` 2026-09-14 第 91 条。
"""

from __future__ import annotations

import json

from _harness_fixtures import node_io

from pokemon_agent.brain import Action, ActionSegment, Task
from pokemon_agent.direct.trace import render
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    ModelCall,
    TraceKind,
)
from pokemon_agent.schemas.memory import (
    ActMemory,
    EpisodeMemory,
    RunMemory,
    TaskMemory,
)
from pokemon_agent.world import Observation


def _run_start(goals: list[str]) -> dict[str, object]:
    """run 边界：`run_goals` 是 run 的**初始目标表**（`list[Task]`）。"""
    return render.run_start(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_START,
            meta={
                "source": "run_entry.new_run",
                "episode_id": "ep-1",
                "task_id": "ep-1",
                "step": 0,
            },
            run_goals=[
                Task(task_id=f"t{i}", goal=g, success_criteria="到位", max_steps=20)
                for i, g in enumerate(goals)
            ],
        )
    ).content


def _observe(*, frame: str | None = None) -> dict[str, object]:
    """task 层 `sense` 取到的一帧（内存观测）。"""
    return render.sense_frame(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={"source": "task.sense", "episode_id": "ep-1", "task_id": "t1", "step": 1},
            obs=Observation(
                step=1,
                facts={
                    "where": "1 号道路 (13,7)",
                    "facing": "up",
                    "neighbors": "上：可走；下：可走",
                    "walk_map": "…",
                    "map_id": 12,
                },
            ),
            frame=frame,
        )
    ).content


def test_run_start_renders_goals_as_parallel_arrays() -> None:
    """`goals` / `success_criteria` 是两条平行数组，条数自己数得出来，不另记 `goal_count`。"""
    body = _run_start(["走到草丛", "拿到徽章"])
    assert body["goals"] == ["走到草丛", "拿到徽章"]
    assert body["success_criteria"] == ["到位", "到位"]


def test_an_observation_carries_its_frame_only_when_one_exists() -> None:
    """`sense_frame` 正文：结构化事实 + 两个小写布尔；有图才带 `frame` 键，没图就省略（不写 null）。

    目标不在观察账里——它在 `episode_start` / `task_start` 上已经逐字记着。
    """
    body = _observe(frame="Zm9v")
    assert body["frame"] == "Zm9v"
    assert "perceived" not in body
    assert body["done"] == "false"
    assert isinstance(body["facts"], dict) and body["facts"]["map_id"] == 12
    assert "goals" not in body
    assert "frame" not in _observe(), "没图时不该出现 frame 键"


def test_judge_verdict_carries_no_depth() -> None:
    """判定的**结论**不记 `depth`：那个数记的是"当前目标在活跃投影里排第几"，
    一局之内恒定（`episode_goals` 只在 `dispatch` 写一次），且跟层级无关。
    """
    content = render.judge_verdict(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_VERDICT,
            meta={"source": "judge", "episode_id": "ep-1", "task_id": "ep-1", "step": 1},
            judge_reason="没达成",
        )
    ).content

    assert set(content) == {
        "termination",
        "decision",
        "judge_trigger",
        "planning_round",
        "fail_streak",
        "judge_reason",
        "audit",
        "human_note",
    }


def test_judge_call_bill_keeps_only_the_reason() -> None:
    """判定的**账单**只多挂一份 `why`（判定依据），不再多挂 `depth`。

    `kind` 也不在正文里——它是封套字段（0913–0914 之前挤在 payload 里，
    封套改造之后只在外面有一份）。
    """
    events = render.judge_call(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_CALL,
            meta={"source": "judge", "episode_id": "ep-1", "task_id": "ep-1", "step": 1},
            calls=[ModelCall(payload={"ok": "false", "prompt": "…"})],
            why="没达成",
        )
    )

    assert [set(event.content) for event in events] == [{"ok", "prompt", "why"}]


def test_a_renderer_only_hands_back_type_kind_and_content() -> None:
    """渲染层的出口是**三元组**，`kind` 逐字就是 `req.kind`（没有翻译表）。

    0914 之前渲染函数还会往正文里塞一个 `kind`、并且按 18 处不同的名字给它改名；
    现在"哪本账"只由 `req.kind` 说一次，落到封套上不再有第二个来源。
    """
    rendered = render.memory_write(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_ACT_MEMORY,
            meta={
                "source": "store_step_episode_memory",
                "episode_id": "ep-1",
                "task_id": "ep-1",
                "step": 0,
            },
            entry=_step_memory(),
        )
    )

    assert rendered.type == "memory_io"
    assert rendered.kind == "write_act_memory" == TraceKind.WRITE_ACT_MEMORY
    assert "kind" not in rendered.content, "正文里没有第二个 kind"


# ---- 四本写账：正文就是记录本体 ----


RUN = "runstate-20260914T1200"
EP = "runstate-20260914T1200-ep1"


def _step_memory() -> ActMemory:
    obs = ActMemory.Observation(facts={"overlay": "none"}, step=3)
    return ActMemory(
        before=obs,
        action="up",
        after=obs,
        step=3,
        episode_id=EP,
        run_id=RUN,
        observations=[],
        outcome=None,
    )


def _writes() -> dict[str, object]:
    """三个写口各渲染一次——正文形状逐个验，封套不在这条路上（见模块 docstring）。"""
    episode = EpisodeMemory(
        episode_id=EP,
        run_id=RUN,
        goal="走到草丛",
        termination="goal_done",
        steps=3,
        summary="往北走",
        quality_score=0.8,
        quality_rationale="可复用",
        # `markdown` **给了值**：正好用来证明它在正文里原样带着，
        # 而不是"没给所以没有"。
        markdown="# 本局\n",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    run_memory = RunMemory(
        run_id=RUN,
        run_goal="总目标",
        episodes=1,
        succeeded=1,
        summary="复盘",
        quality_score=0.8,
        quality_rationale="可复用",
        markdown="# run\n",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    rendered = {
        "write_act_memory": render.memory_write(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.WRITE_ACT_MEMORY,
                meta={
                    "source": "store_step_episode_memory",
                    "episode_id": EP,
                    "task_id": EP,
                    "step": 3,
                },
                entry=_step_memory(),
            )
        ),
        "write_task_memory": render.task_memory_write(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.WRITE_TASK_MEMORY,
                meta={"source": "task_done", "episode_id": EP, "task_id": EP, "step": 3},
                memory=TaskMemory(
                    run_id=RUN,
                    episode_id=EP,
                    task_id="t1",
                    goal="走到草丛",
                    termination="goal_done",
                    reason="chain_done",
                    steps_used=3,
                    total_acts=0,
                    summary="走到草丛",
                    quality_score=0.8,
                    quality_rationale="可复用",
                    markdown="# 本 task\n",
                    facts=[],
                    pointers=[],
                    index={"headline": "", "keys": [], "evidence": []},
                ),
            )
        ),
        "write_run_memory": render.run_memory_write(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.WRITE_RUN_MEMORY,
                meta={
                    "source": "run.store_run_memory",
                    "episode_id": RUN,
                    "task_id": RUN,
                    "step": 1,
                },
                memory=run_memory,
            )
        ),
        "write_episode_memory": render.episode_memory_write(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.WRITE_EPISODE_MEMORY,
                meta={"source": "verify_and_summarize", "episode_id": EP, "task_id": EP, "step": 3},
                memory=episode,
            )
        ),
    }
    return {str(event.kind): event.content for event in rendered.values()}


def test_write_episode_content_is_the_memory_body() -> None:
    """`write_episode_memory` 的正文面 = 库里那条记录的正文面：**蒸馏各字段 + `markdown`**。

    两件事各钉一个理由：

    - **`markdown` 在**：键名照抄模型字段（0914 99 撤了 97 那次"账上叫 `text`"
      的改名）——账与模型逐字可比，查一个键只需要看一个地方。库里那一面叫
      `text` 是**存储实现的名字**（`store.put(text=…)`），不是账跟着改的理由；
    - **章不在**（`goal`/`success`/`steps`）：真源在
      `episode_start` / `episode_end` 两条边界账上。

    **没有再判 `filename` / `chapter_only`**：那两个字段 0914 98/99 已从模型上
    整个删掉（前者早年给 LLM 用它命名文件、改 uuid 之后无人读；后者是"这条记录
    有没有正文"的第二份真相，而正文空不空本来就看得见），判一个不存在的键
    只会把"字段回来了"和"字段还在"混在一起。
    """
    body = _writes()["write_episode_memory"]

    assert set(body) == {
        "index",
        "summary",
        "reusable_patterns",
        "critical_decisions",
        "failure_points",
        "quality_score",
        "quality_rationale",
        "applicable_scenes",
        "tags",
        "markdown",
        "reason",
    }
    assert body["markdown"] == "# 本局\n", "值要一字不动"


def test_write_content_is_the_record_body_not_the_envelope() -> None:
    """四本写账的正文**只装记录本体**——封套 / `meta` 已有的那几样不许再抄一遍。

    两件事一起钉：

    - **身份、坐标、帧不溜回来**（`node_io._WRITE_FORBIDDEN_KEYS`）：它们各有归宿，
      正文里再出现一次就是"同一件事两处说"，而两处迟早会不一样（0914 之前它们
      和正文混在同一个 payload 里，"以哪一份为准"永远说不清）。
      **禁列 = 封套六件 + `meta` 四件 + 两张帧，没有例外**——`kind` / `type` 是
      封套的名字，正文键从此与封套词表不相交；
    - **两边同表**：核对脚本（`node_io`）与渲染层各存一份"正文必填键"表，且刻意
      不互相 import（核对脚本只读账、不读实现）——代价是这个漂移风险，判据就是
      这条测试：三本写账**真渲一遍**，把出来的键集与 node_io 那张表对一遍
      （缺一个键，真机核对侧就会把一批本来合规的账判成"缺必填字段"）。
    """
    writes = _writes()

    for kind, keys in node_io._WRITE_BODY_KEYS.items():
        body = writes[kind]
        leaked = sorted(set(body) & node_io._WRITE_FORBIDDEN_KEYS)
        assert not leaked, f"{kind} 的正文里抄回了已经住在封套/`meta` 上的 {leaked}"
        missing = sorted(frozenset(keys.split()) - set(body))
        assert not missing, (
            f"{kind} 的正文少了 {missing}——node_io 那份表要跟着改，或者渲染层漏了字段"
        )


def test_a_run_error_does_not_fabricate_the_settlement() -> None:
    """异常收尾**只带 `error`**——不照抄 `run_end` 那三件结算（0914 跟进）。

    这条账是在"结算还没算出来"的时候写的（异常从 `run()` 里逃出去，`RunResp`
    根本没生成）。照抄一份写死的 `0` / `0` / `0.0` 不是"还没算"，而是**声称这个
    run 一局都没跑**——崩在第 5 局的 run 也会被写成 `total=0`，**那是假信息**，
    比缺字段更坏。两型共有字段的便利抵不过"报一个错的数"。
    """
    content = render.run_error(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_ERROR,
            meta={
                "source": "run_entry.new_run",
                "episode_id": "runstate",
                "task_id": "runstate",
                "step": 0,
            },
            error="GraphRecursionError: Recursion limit of 25 reached",
        )
    ).content

    assert content == {"error": "GraphRecursionError: Recursion limit of 25 reached"}


def test_a_think_account_carries_only_the_sequence() -> None:
    """`choose_verdict` 记结构化动作链；`input` / `output` 不在此账
    （2026-09-27 字段适配：那次成功的请求与原文在 `choose_call` 账里，不复制）。

    **没有 `attempt`**（0914 跟进删）："第几次"由调用账的位置回答。
    """
    content = render.choose_verdict(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_VERDICT,
            meta={"source": "think_action", "episode_id": EP, "task_id": EP, "step": 0},
            action=_action(),
        )
    ).content

    assert set(content) == {"sequence"}
    assert content["sequence"][0]["name"] == "up"


def test_a_read_account_hands_the_manifest_through_as_a_list() -> None:
    """读口正文是 `{query, refs}`，**`refs` 是数组**（0914 跟进）。

    它当年是拼成一行的字符串，于是判据侧得记住"哪条读口按什么数条数"（坐标里带
    空格、文件名不带）；清单压成字符串，代价就转嫁给每个读它的人。现在
    `content` 是 JSON，清单就交清单本身——命中条数就是它的长度，不必再单列一个
    `count`（那个字段已废成墓碑，见 `FromHarnessToTraceToolAppendReq.count`）。
    """
    content = render.retrieve_node(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_ACT_MEMORY,
            meta={
                "source": "task.perceive",
                "episode_id": EP,
                "task_id": EP,
                "step": 0,
            },
            query="episode_id=ep1",
            refs=["(ep1, 1)", "(ep1, 2)"],
        )
    ).content

    assert content == {"query": "episode_id=ep1", "refs": ["(ep1, 1)", "(ep1, 2)"]}


def test_structured_content_is_an_object_not_a_json_string() -> None:
    """`facts` / `sequence` **直接放对象**——正文本身就是 JSON，里面别再 `json.dumps` 一次。

    0914 之前它们是"装着 JSON 的字符串"塞在里面（而正文当时也是一串 JSON），
    读的人得多解一层。这条钉住那次去双重编码，回潮就在这儿炸。
    """
    assert isinstance(_observe()["facts"], dict)

    segments = render.act_call(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.ACT_CALL,
            meta={"source": "act", "episode_id": EP, "task_id": EP, "step": 0},
            action=_action(),
        )
    ).content["sequence"]

    assert isinstance(segments, list) and isinstance(segments[0], dict)
    assert json.dumps(segments, ensure_ascii=False)  # 落盘那一层序列化得动


def _action() -> Action:
    """一个单段动作——`choose_verdict` 与 `act_call` 两个入口都走 `action_presses`。"""
    return Action(sequence=[ActionSegment(name="up", times=1)])


def test_a_summary_parse_failure_is_its_own_error_not_a_call_failure() -> None:
    """蒸馏链"答了但解析不了"记 `summary_parse_error`（带链路名），不再记 `call_failed`；
    别的失败（调不通）仍是 `call_failed`。"""
    meta = {"source": "summarize_task", "episode_id": "ep-1", "task_id": "t1", "step": 3}
    events = render.model_call(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SUMMARIZE_TASK_CALL,
            meta=meta,
            calls=[
                ModelCall(payload={"ok": "false"}, error_kind="ParseFailure", error="不是 JSON"),
                ModelCall(payload={"ok": "false"}, error_kind="ProviderRejected", error="429"),
            ],
        )
    )

    assert [e.kind for e in events] == [
        TraceKind.SUMMARIZE_TASK_CALL,
        TraceKind.SUMMARY_PARSE_ERROR,
        TraceKind.SUMMARIZE_TASK_CALL,
        TraceKind.CALL_FAILED,
    ]
    assert events[1].content == {"link": "summarize_task", "reason": "不是 JSON"}


def test_a_parse_failure_outside_the_summary_links_stays_a_call_failure() -> None:
    """解析失败只在两条蒸馏链上单列；决策链的解析失败仍记 `call_failed`。"""
    events = render.model_call(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_CALL,
            meta={"source": "plan_task", "episode_id": "ep-1", "task_id": "t1", "step": 3},
            calls=[ModelCall(payload={"ok": "false"}, error_kind="ParseFailure", error="x")],
        )
    )

    assert [e.kind for e in events] == [TraceKind.CHOOSE_CALL, TraceKind.CALL_FAILED]


def test_summary_ledgers_keep_index_without_facts_or_pointers() -> None:
    writes = _writes()

    for name in ("write_task_memory", "write_episode_memory", "write_run_memory"):
        assert "index" in writes[name]
        assert not {"facts", "pointers"} & set(writes[name])
