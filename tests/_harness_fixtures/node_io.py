"""**逐层逐格核对**——run / episode / task 三张图在账上留下的痕迹、正文契约与衔接不变式。

集成测试将真实三图的落盘账本交给这里。粒度是**每一格**：每一格在账上留什么、
那条账的正文必须有哪些字段、三层的活动序列是否符合图的拓扑、相邻层的交接值是否对得上
（`task_end.steps_used` ↔ 这个 task 的键数、`episode_end.tasks_used` ↔ 这一局派出的 task 数……）。

## 一条落盘事件长什么样

```
{uuid, kind, type, ts, meta, content}
meta    = {run_id, source, episode_id, task_id, step}   ← JSON 字符串
content = 这笔账的本体                                     ← JSON 字符串
```

`meta` 六件对每一笔账都成立（`run_id` / `branch` 由落盘层盖）。
上层的空槽填本层自己的 id（run 级账 `episode_id = task_id = run_id`），
**episode 级账的 `task_id` 位清空**（0928 定稿：episode 账不需要 task 坐标）。
`step` 三层都是**圈号**（0928 定稿）：task 级 `task_start` 落 0、每圈 `state.step + 1`；
episode 级 `episode_start` 落 0、圈中与收尾账一律 `state.step + 1`；run 级 `run_start` 落 0、
圈中与 `run_end` 一律 `state.step + 1`（`run_error` 恒 0——整局没起圈）。
帧观测的 `step` 字段（`sense_frame` 正文）不在本契约内：episode/task 层是局内累计键数、
run 层是全局累计键数（局外帧没有局内语义），三层各按各的口径。

## 按层切流（本模块的核心读法）

三层的账交错落盘（run 派一局 → 这一局的账 → run 继续；episode 派一个 task → 这个 task 的账 →
episode 继续）。切法只看 `meta`：

- **run 流**：`episode_id == run_id` 的账；
- **episode 流**：`episode_id == 这一局` 且 `task_id` 为空（0928 定稿：episode 层账
  task 位清空）的账；
- **task 流**：`episode_id == 这一局` 且 `task_id` 是某个 task 的账（一个 task 一条流）。

下层在上层流里**缩成一个记号**：run 流里每一局记成 `EPISODE`，episode 流里每个 task 记成
`TASK`，落在它第一条账出现的位置。于是每一层都是一条短序列，用一张**后继表**（`*_NEXT`）核：
每个活动后面只许跟表里那几个。表就是那张图的拓扑——少跑一格、多跑一格、顺序反了都会断。

`model_call` / `error` 两类账不进流（条数随重试浮动），它们另由正文契约与链路名核。

## 判据

1. **词表**（`check_vocabulary`）：出现的每种 `(type, kind)` 都已登记。
2. **格式**（`check_payloads`）：正文必填键、布尔字面量、`meta` 六件、`source` 值域、写账正文。
3. **流**（`check_layer_flow`）：三层各自的活动序列走得通后继表；异常收尾的局允许断在半路。
4. **覆盖**（`check_node_coverage`）：正常收尾时，除静默格与条件格外每个发账位置都留了痕。
5. **衔接**（`check_content_invariants`）：键号推进、决策与按键对得上、层间结算的计数对得上、
   检索账与结构化字段的形状。

## 证什么、不证什么

**能证**：格跑过、账的格式对、执行序与图的拓扑一致、层间交接的计数一致。
**不能证**：格**读到的 state 值**——trace 记的是产出，不是输入。
静默格（`SILENT_NODES`）跑没跑，trace 答不了，这条边界照实写在这里。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pokemon_agent.schemas.harness.domain import Termination

Event = dict[str, object]
"""一条落盘事件（`load_events()` 的产物）——`{uuid, kind, type, ts, meta, content}`。"""

Styled = tuple[str, str]
"""`(type, kind)` —— 一种账的**指纹单位**（两个字段都住封套顶层）。"""

META_KEYS: tuple[str, ...] = ("run_id", "branch", "source", "episode_id", "task_id", "step")
"""封套 `meta` 的六个键——每一笔账都恰好是这几个；存档与恢复两本账另加 `checkpoint_id`。"""

CHECKPOINT_ID_KINDS: frozenset[str] = frozenset({"checkpoint_save", "checkpoint_restore"})
"""meta 里多带 `checkpoint_id` 的账：这个 id 把新线的恢复账与父线上的分叉点连起来。"""

BOOLEAN_LOWER: frozenset[str] = frozenset({"true", "false"})
"""布尔字面量的**唯一**合法集合。"""

BOOLEAN_FIELDS: frozenset[str] = frozenset({"done", "ok", "perceived", "overturned"})
"""正文里所有布尔字段的**名字**——一套小写字面量通吃，不按账分大小写。

生产者侧由 `tests/test_trace_boolean_literals.py` 的 AST 守卫离线拦；这里是落盘后的复核。"""

TERMINATIONS: frozenset[str] = frozenset(
    {
        Termination.GOAL_DONE.value,
        Termination.WORLD_ENDED.value,
        Termination.STALLED.value,
        Termination.BUDGET_EXHAUSTED.value,
        Termination.TIME_EXHAUSTED.value,
        Termination.ACTIONS_EXHAUSTED.value,
        Termination.TASKS_EXHAUSTED.value,
        Termination.DECOMPOSITIONS_EXHAUSTED.value,
        Termination.INTERRUPTED.value,
        Termination.ERROR.value,
    }
)
"""`Termination` 的值——`task_end` / `episode_end` / `run_end` 的 `termination` 只许取这些
（`judge_verdict` 未判停时为空串）。与 `schemas/harness/domain/termination.py` 由
`check_model_call_links_match_render` 旁的 `check_terminations_match_enum` 对照。"""


# ============================================================
# 零、读法：封套三件事（kind / meta / content）
# ============================================================


def _as_object(raw: object) -> dict[str, object]:
    """把封套里那串 JSON 解回对象；不是对象（缺、坏、是数组）就给空字典。

    坏 JSON 不当场炸是**有意的**：残文件是预期内的运行期情况，而"盘上有没有残文件"
    这件事由 `check_trace` 的封套判据回答——同一件事不在两个维度各报一遍。
    """
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def meta_of(event: Event) -> dict[str, object]:
    """一条事件的 `meta`（标签面的 JSON 对象）；解不动给空字典。"""
    return _as_object(event.get("meta"))


def content_of(event: Event) -> dict[str, object]:
    """一条事件的 `content`（正文面的 JSON 对象）；解不动、或是数组就给空字典。"""
    return _as_object(event.get("content"))


def kind_of(event: Event) -> str:
    """一条事件的 `kind`——**封套顶层字段**（0914 起，此前住在 `payload.kind`）。"""
    return str(event.get("kind", ""))


def styled(event: Event) -> Styled:
    """一条事件的指纹：`(type, kind)`。"""
    return (str(event.get("type", "")), kind_of(event))


# ============================================================
# 一、格与发账位置
# ============================================================

RUN_NODES: tuple[str, ...] = (
    "begin",
    "perceive",
    "review_and_judge",
    "plan_run",
    "act",
    "summarize_run",
    "store_run_memory",
    "run_done",
)
"""run 图的 6 格 + error handler。"""

EPISODE_NODES: tuple[str, ...] = (
    "perceive",
    "review_and_judge",
    "plan_episode",
    "act",
    "episode_done",
)
"""episode 图的 5 格。"""

TASK_NODES: tuple[str, ...] = (
    "perceive",
    "review_and_judge",
    "plan_task",
    "act",
    "task_done",
)
"""task 图的 5 格。三张清单由 `check_node_list_matches_graph()` 与编译好的图对照。"""

RUN_SOURCES: tuple[str, ...] = (
    "run.begin",
    "run.sense",
    "run.perceive",
    "run.retrieve_knowledge",
    "run.review_and_judge",
    "plan_run",
    "run.act",
    "run.summarize_run",
    "run.store_run_memory",
    "run_done",
)
"""run 侧发账位置（`begin` / `act` / `run_done` 不发账）。"""

EPISODE_SOURCES: tuple[str, ...] = (
    "sense",
    "retrieve_task_memories",
    "retrieve_episode_index",
    "retrieve_knowledge_semantic_memory",
    "retrieve_object_semantic_memory",
    "review_and_judge",
    "plan_episode",
    "episode.act",
    "verify_task_memories",
    "summarize_episode",
    "leave_chapter",
    "close_episode",
)
"""episode 侧发账位置——格内**单元名**（格名与 source 分家：组合格自己不发账）。"""

TASK_SOURCES: tuple[str, ...] = (
    "task.sense",
    "detect_stall",
    "store_step_episode_memory",
    "store_object_semantic_memory",
    "close_step",
    "retrieve_act_memories",
    "get_action_space",
    "task.review_and_judge",
    "plan_task",
    "act",
    "verify_act_memories",
    "summarize_task",
    "close_task",
)
"""task 侧发账位置（按键之后的五件事在 perceive 格，act 格只按键）。"""

ENTRY_SOURCES: tuple[str, ...] = (
    "run_entry.new_run",
    "episode_entry.begin_episode",
    "task_entry.begin_task",
)
"""图外入口：episode / task 的 `*_start` 由各自入口发；`new_run` 只发它亲手接住的 `run_error`
（`run_start` / `run_end` 在 run 图的 `begin` / `run_done`；
`episode_error` / `task_error` 在上一层的 `act`）。"""

CHECKPOINT_SOURCES: tuple[str, ...] = ("checkpoint.save", "checkpoint.restore")
"""存档一族的发账位置（`harness/checkpoint/`）：存档点由图外入口与 run 的 `act` 调用，
账归存档器自己记。"""

KNOWN_SOURCES: frozenset[str] = frozenset(
    RUN_SOURCES + EPISODE_SOURCES + TASK_SOURCES + ENTRY_SOURCES + CHECKPOINT_SOURCES
)
"""`meta.source` 的值域——**所有会发账的位置**。错字、空串、随手编的名字当场炸。"""

NODE_FINGERPRINTS: dict[str, tuple[Styled, ...]] = {
    # ---- run ----
    "run.begin": (("lifecycle", "run_start"),),
    "run.sense": (("view", "sense_frame"),),
    "run.perceive": (
        ("memory_io", "read_episode_memory"),
        ("memory_io", "read_object_memory"),
        ("memory_io", "read_run_memory"),
    ),
    "run.retrieve_knowledge": (("memory_io", "read_knowledge"),),
    "run.review_and_judge": (("llm_outcome", "judge_verdict"),),
    "plan_run": (("llm_outcome", "plan_verdict"),),
    "run.act": (
        ("lifecycle", "episode_error"),
        ("memory_io", "read_episode_memory"),
        ("memory_io", "write_episode_memory"),
    ),
    "run.summarize_run": (("model_call", "summarize_run_call"),),
    "run.store_run_memory": (("memory_io", "write_run_memory"),),
    "run_done": (("lifecycle", "run_end"),),
    # ---- episode ----
    "sense": (("view", "sense_frame"),),
    "retrieve_task_memories": (("memory_io", "read_task_memory"),),
    "retrieve_episode_index": (("memory_io", "read_episode_memory"),),
    "retrieve_knowledge_semantic_memory": (("memory_io", "read_knowledge"),),
    "retrieve_object_semantic_memory": (("memory_io", "read_object_memory"),),
    "review_and_judge": (("llm_outcome", "judge_verdict"),),
    "plan_episode": (("llm_outcome", "decompose_verdict"),),
    "episode.act": (("lifecycle", "task_error"),),
    "verify_task_memories": (("llm_outcome", "verify_verdict"),),
    "summarize_episode": (("memory_io", "write_episode_memory"),),
    "leave_chapter": (("memory_io", "read_episode_memory"), ("memory_io", "write_episode_memory")),
    "close_episode": (("lifecycle", "episode_end"),),
    # ---- task ----
    "get_action_space": (("act", "get_action_space"),),
    "task.review_and_judge": (("llm_outcome", "judge_verdict"),),
    "plan_task": (("llm_outcome", "choose_verdict"),),
    "act": (("act", "act_call"),),
    "task.sense": (("view", "sense_frame"),),
    "detect_stall": (("act", "check_stall"),),
    "store_step_episode_memory": (("memory_io", "write_act_memory"),),
    "store_object_semantic_memory": (("memory_io", "write_object_memory"),),
    "close_step": (("lifecycle", "advance_step"),),
    "retrieve_act_memories": (("memory_io", "read_act_memory"),),
    "verify_act_memories": (("llm_outcome", "verify_verdict"),),
    "summarize_task": (("memory_io", "write_task_memory"),),
    "close_task": (("lifecycle", "task_end"),),
}
"""发账位置 → 它的**产出指纹**（`check_node_coverage` 按 `(source, type, kind)` 找痕）。"""

CELL_SOURCES: dict[str, tuple[str, ...]] = {
    "run.begin": ("run.begin",),
    "run.perceive": ("run.sense", "run.perceive", "run.retrieve_knowledge"),
    "run.review_and_judge": ("run.review_and_judge",),
    "run.plan_run": ("plan_run",),
    "run.act": ("run.act",),
    "run.run_done": ("run_done",),
    "run.summarize_run": ("run.summarize_run",),
    "run.store_run_memory": ("run.store_run_memory",),
    "episode.perceive": (
        "sense",
        "retrieve_task_memories",
        "retrieve_episode_index",
        "retrieve_knowledge_semantic_memory",
        "retrieve_object_semantic_memory",
    ),
    "episode.review_and_judge": ("review_and_judge",),
    "episode.plan_episode": ("plan_episode",),
    "episode.act": ("episode.act",),
    "episode.episode_done": (
        "verify_task_memories",
        "summarize_episode",
        "leave_chapter",
        "close_episode",
    ),
    "task.perceive": (
        "task.sense",
        "detect_stall",
        "store_step_episode_memory",
        "store_object_semantic_memory",
        "close_step",
        "retrieve_act_memories",
        "get_action_space",
    ),
    "task.review_and_judge": ("task.review_and_judge",),
    "task.plan_task": ("plan_task",),
    "task.act": ("act",),
    "task.task_done": ("verify_act_memories", "summarize_task", "close_task"),
}
"""`层.格` → 格内发账的单元（= `meta.source` 的值）。

空元组 = 这一格自己不发账（见 `SILENT_NODES`）。"""

SILENT_NODES: dict[str, str] = {}
"""**设计上不写账**的格——它们跑没跑 trace 答不了。

（格内的 `merge_retrieval` 单元同理不写账：它只把四路检索拼进 `ep_ctx`。）"""

CONDITIONAL_NODES: dict[str, str] = {
    "run.summarize_run": "无任何局摘要时不调模型，只写空章与 call_exhausted。",
    "plan_episode": (
        "只在任务链空时拆（首圈 / 链走完 / 上一个 task 失败被清空）；首圈就判停的局不经过它。"
    ),
    "plan_task": (
        "首圈就判停的 task 一个键都不按（整个 run 按过键就必须有痕，见 KEY_CHAIN_SOURCES）。"
    ),
    "act": "同上。",
    "detect_stall": "同上。",
    "store_step_episode_memory": "同上。",
    "close_step": "同上。",
    "store_object_semantic_memory": "只在判定出 object 交互事件时才写 `write_object_memory`。",
    "verify_act_memories": "本 task 没有 ActMemory 时跳过。",
    "summarize_task": "本 task 没有 ActMemory 时跳过。",
    "verify_task_memories": "本局没有 TaskMemory 时跳过。",
    "summarize_episode": "本局没有 TaskMemory 时跳过（改由 leave_chapter 补空章）。",
    "leave_chapter": "本局有 TaskMemory（走了蒸馏）时不补。",
    "run.act": (
        "只在整局抛错时发账（补空章 `write_episode_memory` + `episode_error`）；正常派局不另记。"
    ),
    "episode.act": (
        "只在 task 抛错时发 `task_error`；正常派 task 不另记（task 的账由 task 层自己发）。"
    ),
}
"""**条件触发**的发账位置 + 条件——条件不成立时零痕迹是正常的。"""

KEY_CHAIN_SOURCES: frozenset[str] = frozenset(
    {
        "plan_task",
        "act",
        "detect_stall",
        "store_step_episode_memory",
        "close_step",
    }
)
"""一键的完整链：账上**只要出现过一条 `act_call`**，这几格就一个都不许缺
（条件格的豁免作废）。"""

CLOSING_SOURCES: frozenset[str] = frozenset(
    {
        "verify_task_memories",
        "summarize_episode",
        "leave_chapter",
        "close_episode",
    }
)
"""episode 收尾链——这一局异常收尾（`episode_error`）时它们没跑是正常的。"""


# ============================================================
# 二、三层活动流的后继表
# ============================================================

EPISODE_TOKEN = "EPISODE"
"""run 流里代表"派出去的一局"的记号（落在那一局第一条账的位置）。"""

TASK_TOKEN = "TASK"
"""episode 流里代表"派出去的一个 task"的记号（落在那个 task 第一条账的位置）。"""

START = "^"
"""后继表里"流的开头"。"""

RUN_NEXT: dict[str, frozenset[str]] = {
    START: frozenset({"run_start"}),
    "run_start": frozenset({"sense_frame"}),
    "sense_frame": frozenset({"read_episode_memory"}),
    "read_episode_memory": frozenset({"read_object_memory"}),
    "read_object_memory": frozenset({"read_run_memory"}),
    "read_run_memory": frozenset({"read_knowledge"}),
    "read_knowledge": frozenset({"judge_verdict", "settle_goal"}),
    "settle_goal": frozenset({"judge_verdict"}),
    "judge_verdict": frozenset({"plan_verdict", "write_run_memory"}),
    "write_run_memory": frozenset({"run_end"}),
    "plan_verdict": frozenset({EPISODE_TOKEN}),
    EPISODE_TOKEN: frozenset({"sense_frame"}),
}
"""run 图：`begin[run_start]` → `perceive[run.sense 的 sense_frame → read_episode_memory →
read_object_memory → read_run_memory → read_knowledge]` →
`review_and_judge[(定案 settle_goal) → judge_verdict]` →
`plan_run[plan_verdict（插话重问只落最后一版）]` → `act[一局]` → perceive …；
判停后 `run_done[run_end]`。
（整局抛错时 `act` 记的 `write_episode_memory` / `episode_error` 挂在那一局名下，进 episode 流。）

首圈没有上一局可盖章，所以 `read_knowledge` 可以直接接 `judge_verdict`。
`run.sense` 每圈都取帧（0928 起）：run_start 之后与每一局（EPISODE 记号）之后的第一笔都是它。"""

RUN_ENDS: frozenset[str] = frozenset({"run_end", "run_error"})
"""run 流的合法结尾。`run_error` 可以出现在任何位置之后（见 `check_layer_flow`）。"""

EPISODE_NEXT: dict[str, frozenset[str]] = {
    START: frozenset({"episode_start"}),
    "episode_start": frozenset({"sense_frame"}),
    "sense_frame": frozenset({"read_task_memory"}),
    "read_task_memory": frozenset({"read_episode_memory"}),
    "read_episode_memory": frozenset(
        {"read_knowledge", "read_object_memory", "write_episode_memory", "episode_end"}
    ),
    "read_knowledge": frozenset({"read_object_memory"}),
    "read_object_memory": frozenset({"judge_verdict", "settle_task"}),
    "settle_task": frozenset({"judge_verdict"}),
    "judge_verdict": frozenset(
        {"decompose_verdict", TASK_TOKEN, "verify_verdict", "read_episode_memory", "episode_end"}
    ),
    "decompose_verdict": frozenset({TASK_TOKEN}),
    TASK_TOKEN: frozenset({"sense_frame"}),
    "verify_verdict": frozenset({"write_episode_memory", "episode_end"}),
    "write_episode_memory": frozenset({"episode_end"}),
}
"""episode 图：`perceive[sense_frame → read_task_memory → read_episode_memory → (read_knowledge)
→ read_object_memory]`（`read_knowledge` 只在首圈、场景变化、有 task 失败时出现）
→ `review_and_judge[(settle_task) → judge_verdict]` →
`plan_episode[decompose_verdict（没有 PENDING 才拆）]` →
`act[一个 task]` → perceive …；
判停后 `episode_done[(verify_verdict → write_episode_memory) → episode_end]`
（本局没有 TaskMemory 时标与蒸都跳过，改由 `leave_chapter` 先查
`read_episode_memory`、没有才补空章 `write_episode_memory`）。

异常收尾的局：run 的 `act` 同样先查再补空章（`read_episode_memory` →
`write_episode_memory`，source `run.act`），再记 `episode_error`。"""

EPISODE_ENDS: frozenset[str] = frozenset({"episode_end"})

TASK_NEXT: dict[str, frozenset[str]] = {
    START: frozenset({"task_start"}),
    "task_start": frozenset({"sense_frame"}),
    "sense_frame": frozenset({"check_stall", "read_act_memory"}),
    "check_stall": frozenset({"write_act_memory"}),
    "write_act_memory": frozenset({"write_object_memory", "advance_step"}),
    "write_object_memory": frozenset({"write_object_memory", "advance_step"}),
    "advance_step": frozenset({"read_act_memory"}),
    "read_act_memory": frozenset({"get_action_space"}),
    "get_action_space": frozenset({"judge_verdict"}),
    "judge_verdict": frozenset({"choose_verdict", "verify_verdict", "task_end"}),
    "choose_verdict": frozenset({"act_call"}),
    "act_call": frozenset({"sense_frame"}),
    "verify_verdict": frozenset({"write_task_memory", "task_end"}),
    "write_task_memory": frozenset({"task_end"}),
}
"""task 图：`perceive[sense_frame → (check_stall → write_act_memory → write_object_memory?
→ advance_step) → read_act_memory → get_action_space]` → `review_and_judge[judge_verdict]`
→ `plan_task[choose_verdict]` → `act[act_call(key|script 形)]`
→ perceive …；判停后 `task_done[(verify_verdict → write_task_memory) → task_end]`。

`sense` 每圈都取帧（`sense_frame`）；首圈还没按过键，`sense_frame` 直接接 `read_act_memory`。"""

TASK_ENDS: frozenset[str] = frozenset({"task_end"})
"""task 流的合法结尾。`task_error`（episode 的 `act` 接住 task 抛错时记）可以接在任何活动后面。"""


# ============================================================
# 三、每种账的正文契约：必填键 + 这笔记的是什么
# ============================================================
#
# **必填键指的是 `content` 里的键**（0914 封套改造）：`kind` / `source` / 坐标
# 全都在封套与 `meta` 上，正文里不再各抄一份。此前这里每个字符串都以 `kind` 打头
# ——那是旧形状的残留，不是"这条账真需要那个键"。

CONTRACTS: dict[Styled, tuple[frozenset[str], str]] = {}


def _contract(styled_key: Styled, keys: str, why: str) -> None:
    """登记一种账的正文必填键（`keys` 是空格分隔的字段名）。"""
    CONTRACTS[styled_key] = (frozenset(keys.split()), why)


# ---- run / episode 边界 ----
_contract(
    ("lifecycle", "run_start"),
    "goals success_criteria run_goal run_criteria",
    "新 run 的开始（两条平行的目标数组 + run 级总目标）",
)
_contract(
    ("lifecycle", "run_end"),
    "total succeeded termination judge_reason",
    "run 正常收尾（成功率是 total/succeeded，不另记）",
)
_contract(
    ("lifecycle", "run_error"),
    "error",
    "run 异常收尾（`error` 是异常快照；**不带结算三件**——那时结算根本没算出来，"
    "照抄一份写死的零等于声称这个 run 一局都没跑）",
)
_contract(
    ("lifecycle", "episode_start"), "goal_id goal success_criteria max_steps", "这一局的判据快照"
)
_contract(
    ("lifecycle", "episode_end"),
    "termination judge_reason tasks_used acts_used reason",
    "这一局的结算",
)
_contract(
    ("lifecycle", "task_start"),
    "goal success_criteria max_steps total_acts",
    "这个 task 的判据快照与局内累计键数基数",
)
_contract(
    ("lifecycle", "task_end"), "termination judge_reason steps_used reason", "这个 task 的结算"
)
_contract(
    ("lifecycle", "task_error"),
    "error",
    "这个 task 异常收尾（episode 的 `act` 接住时记；`AgentError` 兜成失败的 task，这一局继续）",
)
_contract(
    ("lifecycle", "settle_goal"),
    "goal_id status episode_id attempts audit note overturned fail_streak",
    "run 级目标表盖章 + 人审表态",
)
_contract(
    ("lifecycle", "settle_task"),
    "task_id status round audit note overturned abandoned fail_streak",
    "episode 级任务表盖章 + 人审表态 + 被放弃的剩余条目（abandoned 是数组）",
)
_contract(
    ("lifecycle", "episode_error"),
    "error",
    "这一局异常收尾（`error` 是异常快照；成没成、几步都由 `kind` 自己回答，"
    '不再记恒定的 `success="false"` / `steps="-1"`）',
)
_contract(("lifecycle", "advance_step"), "next_step", "步号推进（close_step）")

# ---- 观测 ----
_contract(
    ("view", "sense_frame"),
    "status facts done",
    "三层 sense 取到的一帧（run/episode 视觉档 / task 层轻档；`place` 有值才出现、"
    "`scene` 只在 task 层、`frame` 是 base64 PNG、`ram` 是内存读数对象，没有就缺省，都不进必填表）",
)

# ---- 记忆读：六条读口**一个形状**（`content = {query, refs}`）----
_READ_SHAPE = "query refs"
_READ_WHY = {
    "read_act_memory": "本 task 的 ActMemory（task.perceive）",
    "read_episode_memory": "跨局摘要记忆检索",
    "read_run_memory": "run 记忆检索",
    "read_knowledge": "知识库检索（主循环）",
    "read_object_memory": "地图事实检索",
    "read_task_memory": "本局 TaskMemory（episode.perceive）",
}
for _kind, _why in _READ_WHY.items():
    _contract(("memory_io", _kind), _READ_SHAPE, _why)

# ---- 记忆写：四本账的正文**就是记录本体**（坐标与身份在封套/`meta` 上）----
_WRITE_BODY_KEYS: dict[str, str] = {
    "write_act_memory": "before action after",
    "write_task_memory": (
        "reason summary reusable_patterns critical_decisions failure_points quality_score"
        " quality_rationale tags markdown"
    ),
    "write_object_memory": "outcome object_kind place actor_place button",
    "write_run_memory": (
        "reason summary reusable_patterns critical_decisions failure_points quality_score"
        " quality_rationale applicable_scenes tags markdown"
    ),
    "write_episode_memory": (
        "reason summary reusable_patterns critical_decisions failure_points quality_score"
        " quality_rationale applicable_scenes tags markdown"
    ),
}
_WRITE_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "uuid",
        "kind",
        "type",
        "started_at",
        "ended_at",
        "meta",
        "content",
        "source",
        "run_id",
        "branch",
        "episode_id",
        "task_id",
        "step",
        "before_frame",
        "after_frame",
        "first_frame",
        "last_frame",
        "goal",
        "success",
        "termination",
        "steps",
        "steps_used",
        "total_acts",
        "acts_used",
    }
)
"""写账的正文里**不许出现**的键——**封套六件 + `meta` 六件 + 四张帧 + 来源章**。

- `uuid` / `kind` / `type` / `ts` / `meta` / `content`：封套自己的字段；
- `source` / `run_id` / `branch` / `episode_id` / `task_id` / `step`：`meta` 上的标签
  （0914 之前它们与正文混在同一个 payload 里，这正是封套改造要拆开的两层）；
- `before_frame` / `after_frame` / `first_frame` / `last_frame`：**base64 PNG，不是正文**——
  画面真源是
  `memory/step_memory/*.json`，账里再存一份会把一条写账顶到几百 KB。

- `goal` / `success` / `termination` / `steps` / `steps_used` / `total_acts` / `acts_used`：
  **来源章**——真源在 `task_start`/`task_end`、`episode_start`/`episode_end`，正文只装蒸馏内容。

**`kind` / `type` 在禁列里，没有例外**（0914 跟进）：它们是封套的名字，正文里
出现就叫撞名——记录自己的那两个概念已经改名（`ObjectFactEvent` 的判别键叫
`outcome`、物体类别叫 `object_kind`），谁再把 `type`/`kind` 塞回正文，这里当场炸。"""
_WRITE_WHY = {
    "write_act_memory": "一条按键情景记忆落库（正文 = `ActMemory` 去掉坐标与两张图）",
    "write_task_memory": "一条 task 记忆落库（正文 = 蒸馏各字段 + markdown；章与代表帧不落）",
    "write_object_memory": "一条对象交互事件落库（正文 = 事件本体，物体格在 `content.place`）",
    "write_run_memory": "整次 run 的派生摘要落库，来源章不落正文",
    "write_episode_memory": "一局的跨局摘要落库（正文 = 蒸馏各字段 + `markdown`，**章不落**）",
}
for _kind, _body_keys in _WRITE_BODY_KEYS.items():
    _contract(("memory_io", _kind), _body_keys, _WRITE_WHY[_kind])


# ---- 决策与判定 ----
_contract(
    ("llm_outcome", "choose_verdict"),
    "sequence",
    "一次决策交出的整条链（`action`/两个计数能从 sequence"
    "推出来、`attempt` 能从调用账的位置推出来，都不另记；那次成功的请求与原文"
    "在调用账里，2026-09-27 字段适配起不再复制）",
)
_contract(
    ("llm_outcome", "judge_verdict"),
    "termination fail_streak judge_reason audit human_note",
    "本层的终止裁决（三层共用；audit = 人对「已达成」的表态，没问人为空）",
)
_contract(
    ("llm_outcome", "decompose_verdict"),
    "tasks why human_note",
    "episode 级拆解结论（tasks 是数组）",
)
_contract(
    ("llm_outcome", "verify_verdict"),
    "checked negative",
    "校验汇总（那次成功的请求与原文在调用账里，2026-09-27 字段适配起不再复制）",
)
_contract(
    ("llm_outcome", "plan_verdict"),
    "pushed_goals updates why human_note",
    "run 级规划结论（pushed_goals / updates 是数组；停机不归规划）",
)

# ---- 动作域 ----
# `act_call` 两形（P5）：key 形必填 `sequence`、script 形必填 `script/args/ok/code`
# ——两形必填键不同，`check_payloads` 对这条特殊分支，此处登记的是 key 形（并保 vocabulary 完整）。
_contract(
    ("act", "act_call"),
    "sequence",
    "一个键的执行（单段数组）；脚本形另带 script/args/ok/code（见 check_payloads 分支）",
)
_contract(("act", "get_action_space"), "names", "这一步允许的动作名（掩码；数组）")
_contract(("act", "check_stall"), "stall_key stall_count", "停摆快照")

# ---- 错误：**三个闭集**（0914），三条**同带 `link`** ----
_contract(
    ("error", "call_failed"),
    "link exception reason",
    "某条链的**某一次尝试**失败（`exception` 给异常类名、`reason` 给异常消息原文；"
    "是第几次由账在链上的位置回答，不另记）",
)
_contract(
    ("error", "call_exhausted"),
    "link",
    "某条链**重试预算耗尽**（整条链的结论；最后一次为什么失败在同链最后一条"
    "`call_failed` / `summary_parse_error` 上，不另抄一份 `reason`）",
)
_contract(
    ("error", "summary_parse_error"),
    "link reason",
    "蒸馏答了但解析不了（`link` 为 `summarize` / `summarize_task`；取代那次的 `call_failed`）",
)

# ---- 存档一族（`docs/checkpoint/spec.md`）：**不进流**，条数随存档开关浮动 ----
_contract(("lifecycle", "checkpoint_save"), "level manifest_path", "存下一份存档（id 在 meta）")
_contract(
    ("lifecycle", "checkpoint_restore"),
    "level manifest_path",
    "从存档恢复出新执行线（新执行线第一条账；id 在 meta，父线由同 id 的存档账推出）",
)
_contract(("error", "checkpoint_error"), "checkpoint_id stage error", "存档失败，run 照常继续")

CHECKPOINT_KINDS: frozenset[str] = frozenset(
    {"checkpoint_save", "checkpoint_restore", "checkpoint_error"}
)
"""存档一族三本账：旁路记账，不属于任何一张图的拓扑，所以不进流。"""

# ---- 问人两本账（`harness/reviewing.py`）：**不进流**，条数随人插话几轮浮动 ----
_contract(
    ("lifecycle", "review_inject"),
    "form_kind reply answered by wait_s",
    "插话一次：表单种类、人的回话、是否真答、等了多久",
)
_contract(
    ("lifecycle", "review_audit"),
    "form_kind verdict note answered by wait_s",
    "审一次：审的是什么、认 / 推翻与理由、是否真答、等了多久",
)

REVIEW_KINDS: frozenset[str] = frozenset({"review_inject", "review_audit"})
"""问人两本账：同一格可问多轮（带着回话重问），条数与模型调用账一样浮动，所以不进流。"""

ERROR_KINDS: frozenset[str] = frozenset({"call_failed", "call_exhausted", "summary_parse_error"})
"""错误族的**三个成员**（`TraceKind` 里那三个）。

**0914 之前这一族是开集**：落盘 `kind` 取 `type(exc).__name__`——网关的
`APIStatusError`、`OutputTruncated`、任何异常都可能落进来。于是"封套 kind 必在
词表内"这条判据不得不留一个特例：登记表按族收（"必填键 = `{reason, link, attempt}`"），
判据写成"没登记过、又带一条真链路"就算这一族。**开集进不了枚举**，现在按
失败模式分三档，逐个登记得完，特例与那套"先查表再按形状收"的写法一起删掉。"""

MODEL_CALL_LINKS: tuple[str, ...] = (
    "sense",
    "choose",
    "plan",
    "decompose",
    "judge",
    "verify",
    "summarize_episode",
    "summarize_task",
    "summarize_run",
)
"""九个 `MODEL_CALL` 的链路名——与 `direct/trace/render.py::_CALL_LINK` 逐字同源。

**链路名只落错误账的 `content.link`**：调用账自己的 `kind`（`choose_call`）
已经说明是哪条链了，不必在正文里再写一遍。

分两处写就有漂移风险，`check_model_call_links_match_render()` 在跑的时候把两边对一遍
（这里是核对脚本，能 import 到真源，所以是**对照**而不是各抄一份）。"""

MODEL_CALL_KINDS: tuple[str, ...] = tuple(f"{link}_call" for link in MODEL_CALL_LINKS)
"""七个调用账的 `kind`——**由链路名按词形规则派生**（`<链路>_call`，见 `TraceKind`）。

不各抄一份：两张表逐字对应就是那条命名规则的全部内容，抄成两处只多一个可漂移的点。
`check_model_call_links_match_render()` 把这份派生与渲染层对照一遍（键集必须是
这七个、值集必须是 `MODEL_CALL_LINKS`）。"""

MODEL_CALL_REQUIRED: frozenset[str] = frozenset({"ok", "prompt"})
"""每条 `*_call` 正文都有的键。

`ok` / `prompt` 由 `brain/brain.py` 各处写进 payload。**没有 `attempt`**
（0914 跟进删）："第几次"由账在链上的位置回答。**`kind` 不在这里**——它是封套字段，
0913–0914 之前挤在 payload 里，现在只在封套上有一份。"""

MODEL_CALL_ON_SUCCESS: frozenset[str] = frozenset(
    {"input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens", "raw"}
)
"""`ok == "true"` 时额外必须有的键——成功那次一定算得出 token 数与原文。"""

EXTRA_PER_LINK: dict[str, frozenset[str]] = {
    "judge": frozenset({"why"}),
    "verify": frozenset({"verdicts"}),
}
"""某些链路在账单上多挂的字段（`judge_call` / `verify_call` 的渲染追加项）。

`judge` 只多一份 `why`（判定依据）——**它原先还多一个 `depth`**，0914 删：
那个数一局之内恒定（`episode_goals` 只在 `dispatch` 写一次）、又是"末位才是
当前目标"的推出物，且顶着 `depth` 的名字跟层级无关，见 CHANGELOG 第 91 条。

`images`（发给模型的图，PNG data URI 列表）也不在这里：它只在多模态调用上
出现，而多模态与否取决于**这次调用带没带图**
（`judge` 第 0 步可能不问、`decide` 从来不看图），不是链路的固有属性。
0915 起 `images` 直接进账（发给什么存什么），曾经的 `n_images` 同日删——
张数从 `images` 可数，不留第二个能对不上的数。"""


# ============================================================
# 四、判据
# ============================================================


def check_vocabulary(events: Sequence[Event]) -> None:
    """**每一种出现的账都在词表里。** 没登记 → 有节点写了新账而核对没跟上，炸。

    这条是"核对本身不会悄悄失效"的保证：图里加了节点、加了新账，本模块没跟上的话，
    这里立刻报出那个陌生的 `(type, kind)`，而不是让新账静默溜过下面所有判据。

    `*_call` 按链路逐个登记（七个 kind 由 `MODEL_CALL_KINDS` 给出）；错误族三个成员
    也在 `CONTRACTS` 里——**这一条没有"按形状收"的例外**（见 `ERROR_KINDS`）。
    """
    known = set(CONTRACTS) | {("model_call", kind) for kind in MODEL_CALL_KINDS}
    unknown = sorted({styled(event) for event in events if styled(event) not in known})
    assert not unknown, (
        f"账上出现了没登记的事件种类 {unknown}——新账要同步进 node_io.CONTRACTS"
        "（否则它不会经过任何格式核对）"
    )


def check_payloads(events: Sequence[Event]) -> None:
    """**每种账的正文必填键齐全、值域合法，且每笔账的封套都对。**

    这是"预计格式"那一问的落点，四件事：

    1. 正文必填键（`CONTRACTS`）——`*_call` 另有一套（公共键恒有，**成功那次**
       还必须有 token 四件套与原文：失败那次的正文只有 `ok`/`prompt`）；
    2. 布尔字面量（`_check_boolean_fields`）；
    3. **标签面**（`_check_meta`）：每笔账的 `meta` 恰好是那六件；
    4. **发账位置**（`_check_source`）：`source` 非空、且是个真位置名；
       四本写账再加一条正文形状（`_check_write_body`）。
    """
    for event in events:
        key = styled(event)
        content = content_of(event)
        if key[0] == "model_call":
            _check_model_call_payload(content, key)
            continue
        required, why = _contract_for(key)
        if key == ("act", "act_call"):
            # 两形（P5）：key 形必有 sequence；script 形必有 script/args/ok/code。
            required = (
                frozenset({"sequence"})
                if "sequence" in content
                else frozenset({"script", "args", "ok", "code"})
            )
        missing = sorted(required - set(content))
        assert not missing, f"{key} 缺必填字段 {missing}（{why}）"
    _check_boolean_fields(events)
    _check_meta(events)
    _check_source(events)
    _check_write_body(events)


def _contract_for(key: Styled) -> tuple[frozenset[str], str]:
    """这一条账的 `(必填键, 说明)`——**先过 `check_vocabulary()`**，没登记就是它的错。"""
    contract = CONTRACTS.get(key)
    assert contract is not None, f"{key} 没有契约——先过 check_vocabulary()"
    return contract


def _check_meta(events: Sequence[Event]) -> None:
    """每笔账的 `meta` **恰好是那六件标签**（存档 / 恢复账另加 `checkpoint_id`），坐标不空，
    `step` 是非负整数。

    多出来的键说明有人绕开 `TraceTool.append` 自己拼 meta——"同一件事两处说"的开始。
    `step` 由 `req.step`（`int`）直接落盘，收成字符串会让排序与比较各说各话。
    """
    for event in events:
        meta = meta_of(event)
        expected = set(META_KEYS) | (
            {"checkpoint_id"} if kind_of(event) in CHECKPOINT_ID_KINDS else set()
        )
        assert set(meta) == expected, (
            f"{styled(event)} 的 meta 键是 {sorted(meta)}，应为 {sorted(expected)}"
        )
        for key in ("run_id", "branch", "episode_id"):
            assert str(meta[key]).strip(), f"{styled(event)} 的 meta.{key} 是空的"
        # task 位三态（0928 定稿）：run 层账放 run_id、episode 层账清空、
        # task 层账放真 task 号——与 episode_id 同值的旧口径是历史账，新账不许出现。
        task_id = str(meta["task_id"])
        if task_id and task_id != str(meta["run_id"]):
            assert task_id != str(meta["episode_id"]), (
                f"{styled(event)} 的 meta.task_id 与 episode_id 同值——"
                "episode 级账的 task 位已清空（0928 定稿），别再按旧口径占位"
            )
        step = meta["step"]
        assert isinstance(step, int) and not isinstance(step, bool) and step >= 0, (
            f"{styled(event)} 的 meta.step 应是非负整数，实为 {step!r}"
        )


def _check_source(events: Sequence[Event]) -> None:
    """`source`：这条账从哪个位置发出——非空，且在 `KNOWN_SOURCES` 里。

    `kind` 只回答"哪本账"；同一个 `write_episode_memory` 有三个合法生产者（`summarize_episode`
    正文版 / `leave_chapter` 与 `run.act` 空章版），所以要靠 `source` 分开。
    """
    for event in events:
        key = styled(event)
        source = str(meta_of(event).get("source", ""))
        assert source, f"{key} 的 source 是空的——每笔账都要说清是哪个位置发的"
        assert source in KNOWN_SOURCES, (
            f"{key} 的 source 是 {source!r}，不是个真发送位置"
            f"（三层单元 + {len(ENTRY_SOURCES)} 个图外入口，见 KNOWN_SOURCES）"
        )


def _check_write_body(events: Sequence[Event]) -> None:
    """四本写账的正文：**就是记录本体**（三条）。

    1. **不把已经住在别处的东西抄回来**（`_WRITE_FORBIDDEN_KEYS`）：身份、坐标、
       两张帧、以及封套那六个名字，正文里再出现一次就是"同一件事两处说"——
       而两处迟早会不一样。**禁列里没有例外**：`write_object_memory` 的记录本来叫
       `type`/`kind`，与封套撞名 → 记录那两个字段已改名（`outcome` / `object_kind`），
       正文从此与封套的词表不相交；
    2. **知识账的正文是数组**：一批一条账，逐元素只许有 `topic` / `content`
       （`KnowledgeRecord.source` 不进账：它由 `meta` 的 `run_id`/`episode_id`
       推得出来、又在批内恒定，见 `render.knowledge_write` 的说明）；
    3. **正文非空**：空的写账等于没写，而"这一局什么都没读到"是**不写账**的
       （`render.knowledge_write` 的入口断言），两者混起来读账的人分不出。

    "缺没缺"那一半归 `CONTRACTS`（`_WRITE_BODY_KEYS` 是必填键表），这里管"多没多"。
    """
    for event in events:
        key = styled(event)
        if key[0] != "memory_io" or key[1] not in _WRITE_WHY:
            continue
        content = content_of(event)
        leaked = sorted(set(content) & _WRITE_FORBIDDEN_KEYS)
        assert not leaked, (
            f"{key} 的正文里出现了 {leaked}——那些键已经住在封套或 `meta` 上"
            f"（{_WRITE_WHY[key[1]]}）；正文只装记录本体"
        )
        assert content, f"{key} 的正文是空的"


def _parsed_content(event: Event) -> object:
    """`content` 解回来的**原始**形状（数组也算）——`content_of` 只留对象，这里要全的。"""
    try:
        return json.loads(str(event.get("content", "null")))
    except json.JSONDecodeError:
        return None


def _check_model_call_payload(content: dict[str, object], key: Styled) -> None:
    """账单的四组键：公共 + 成功时 + 该链路专属。

    **`ok` 的字面量域不在这里核**——它是布尔字段，统一归 `_check_boolean_fields`
    那份扁平名单管（一件事只有一个地方说）。这里只在它等于 `"true"` 时决定
    "成功那次必须多出哪几个键"。
    """
    required = set(MODEL_CALL_REQUIRED) | set(EXTRA_PER_LINK.get(key[1], frozenset()))
    if content.get("ok") == "true":
        required |= MODEL_CALL_ON_SUCCESS
    missing = sorted(required - set(content))
    assert not missing, f"{key} 的账单缺字段 {missing}（ok={content.get('ok')!r}）"
    for field in ("input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"):
        if field in content:
            assert str(content[field]).isdigit(), f"{key} 的 {field} 不是整数：{content[field]!r}"


def _check_boolean_fields(events: Sequence[Event]) -> None:
    """**所有布尔字段都写小写**——一份字段名单、一套字面量，没有例外。

    这条曾经是"按字段 + 按账查表"的（见 `BOOLEAN_FIELDS` 的说明），现在只需要
    一次集合运算：名字在这份名单里的字段，值必须是 `true`/`false`。
    """
    for event in events:
        content = content_of(event)
        for field in BOOLEAN_FIELDS & content.keys():
            value = content[field]
            assert value in BOOLEAN_LOWER, (
                f"{styled(event)} 的 {field} 应是 {sorted(BOOLEAN_LOWER)}（**小写**），"
                f"实为 {value!r}——账本只有一套布尔字面量"
            )


def _keys_of(event: Event, field: str) -> list[str]:
    """把 `sequence` 展开成一串按键名（`times` 按次数重复）。

    展开是必须的：`choose_verdict` 记的是"段"（`up×4`），`act_call` key 形记的是"键"
    （一次一个 `up`），
    两者的对账只有在同一个粒度上才做得成——这正是执行层那一层摊平的逆运算。

    `sequence` 是**对象数组**（`render.action_presses` 直接放 `model_dump()` 的结果，
    0914 起不再 `json.dumps` 成字符串），所以这里直接迭代、不解 JSON；
    "它必须是数组"这件事另由 `_check_structured_content` 守着。
    """
    segments = content_of(event).get(field, [])
    assert isinstance(segments, list), f"{kind_of(event)} 的 {field} 应是数组"
    keys: list[str] = []
    for segment in segments:
        keys.extend([str(segment.get("name", ""))] * int(segment.get("times", 1)))
    return keys


def _check_read_accounts(events: Sequence[Event]) -> None:
    """检索账**内容自洽**：说了问了什么（`query`），命中清单是**字符串数组**（`refs`）。

    **`query` 为空在这一族里没有合法情形**：六条读口各有一条实打实的检索条件
    （四条等值过滤、两条 BM25 检索词），写不出条件就是漏交——而漏交之后
    "命中为空"就永远解释不清（是条件错了还是库里没有）。

    **空 `refs` 就是 0 条**，不是特例：这一路没命中是合法的。

    ⚠ **`count` 已删**（0914 跟进）：它做过"检索器承诺几条"的第二个来源，
    但六条读口**都是 `len(<同一个集合>)`**——`read_step` 数 `memories`、
    `read_episode_memory` 数 `episode_memories`、两条 knowledge 数 `contents`（与
    `sources` 成对产出、恒等长）、`read_object_memory` 数 `events`、`read_verify_step`
    数 `entries`。既然 `refs` 现在是数组、`count` 恒等于它的长度，那个字段就是
    纯粹的派生——**留着只会多一个能和真相对不上的地方**。

    **为什么以前不是数组**：`refs` 曾是**裸字符串**（调用方各拼各的格式：坐标
    写 `(ep, step)`、知识写文件名、物体写 `12:13:8`），于是本模块当时不得不维
    一张"哪条读口按什么数条数"的表——`read_knowledge` 的 5 个文件名一个括号
    都没有，把"一律数括号"那条判据当场打成假警。**把结构化数据落成字符串，
    代价就转嫁给每个读它的人**；`content` 已经是 JSON 之后，这份代价没有理由
    再付（同 `facts` / `sequence` 去双重编码那一条）。
    """
    for event in events:
        kind = kind_of(event)
        if kind not in _READ_WHY:
            continue
        content = content_of(event)
        assert str(content.get("query", "")), (
            f"{kind} 没记检索条件（`query` 为空）——每条读口都说得出自己问了什么"
        )
        refs = content.get("refs")
        assert isinstance(refs, list) and all(isinstance(r, str) for r in refs), (
            f"{kind} 的 refs 应是字符串数组（命中清单），实为 {type(refs).__name__}；内容 {refs!r}"
        )
        # timings 是可选键（只有 read_knowledge 带，0928 324）：出现了就核形状——
        # 分段耗时必须是 `{段名: 秒}` 的数字字典。缺段/多段不管（归因自己读）。
        timings = content.get("timings")
        if timings is not None:
            assert isinstance(timings, dict) and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in timings.values()
            ), (
                f"{kind} 的 timings 应是 {{段名: 秒}} 的数字字典，实为 {timings!r}"
                "——分段耗时是观测数据，不是随便什么都能塞的口袋"
            )


_STRUCTURED_CONTENT: dict[str, dict[str, type]] = {
    "sense_frame": {"facts": dict},
    "settle_task": {"abandoned": list},
    "choose_verdict": {"sequence": list},
    "act_call": {"sequence": list, "args": dict, "events": list},
}
"""正文里那几处**结构化数据**的期望类型——「别再 `json.dumps` 一次」。

0914 之前它们全是"装着 JSON 的字符串"塞在正文里，而正文**当时本身就是 JSON 串**，
等于双重编码；封套改造后正文就是 JSON 对象，里面的结构化数据直接放对象/数组。
这条判据就是那个决定的运行时证据：谁把它们改回字符串，这里当场炸。
"""


def _check_structured_content(events: Sequence[Event]) -> None:
    """结构化字段真的是对象/数组——防双重编码回潮（见 `_STRUCTURED_CONTENT`）。"""
    for event in events:
        content = content_of(event)
        kind = kind_of(event)
        for field, expected in _STRUCTURED_CONTENT.get(kind, {}).items():
            if kind == "act_call" and field not in content:
                continue  # 两形：key 形没有 args/events，script 形没有 sequence
            value = content.get(field)
            assert isinstance(value, expected), (
                f"{kind_of(event)} 的 {field} 应是 {expected.__name__}，"
                f"实为 {type(value).__name__}——正文已经是 JSON，里面别再 `json.dumps` 一次"
            )


def check_run_markers(events: Sequence[Event]) -> None:
    """run 级记号：`run_id` 唯一，且每个 `episode_id` 都挂在它下面。

    两个维度都从 `meta` 解回来（0914 起封套顶层没有它们了）。
    """
    run_ids = {str(meta_of(e).get("run_id", "")) for e in events}
    assert len(run_ids) == 1, f"一个 run 的账里出现了多个 run_id：{sorted(run_ids)}"
    run_id = run_ids.pop()
    assert run_id, "事件的 run_id 是空的"
    for event in events:
        episode_id = _episode_of(event)
        assert episode_id == run_id or episode_id.startswith(f"{run_id}-"), (
            f"episode_id {episode_id!r} 不属于 run {run_id!r}"
        )


def check_model_call_links_match_render() -> None:
    """七条链路名与本模块记的那份**逐字同一组**，且七个 `kind` 与之**成对**。

    这里是核对脚本，能 import 到真源，所以是**对照**而不是各写一份。
    """
    from pokemon_agent.direct.trace.render import _CALL_LINK
    from pokemon_agent.schemas.harness import TraceKind

    rendered_links = sorted(str(link) for link in _CALL_LINK.values())
    rendered_kinds = sorted(str(kind) for kind in _CALL_LINK)
    assert rendered_links == sorted(MODEL_CALL_LINKS), (
        f"node_io 记的链路名 {sorted(MODEL_CALL_LINKS)} 与渲染层的 {rendered_links} 不一致"
    )
    # `MODEL_CALL_KINDS` 由链路名派生（`<链路>_call`）——这条把那个派生逼到真源上，
    # 而不是"看着像是对的"。
    assert rendered_kinds == sorted(MODEL_CALL_KINDS), (
        f"`<链路>_call` 这条词形规则与渲染层对不上："
        f"渲染层的七个 kind 是 {rendered_kinds}，派生出来的是 {sorted(MODEL_CALL_KINDS)}"
        f"（枚举成员：{[str(k) for k in TraceKind if str(k).endswith('_call')]}）"
    )


def check_node_list_matches_graph(
    run_nodes: Sequence[str], episode_nodes: Sequence[str], task_nodes: Sequence[str]
) -> None:
    """本模块的三张格清单与**编译好的三张图**对得上（`__start__`/`__end__` 由调用方摘掉），
    且 `CELL_SOURCES` 恰好覆盖这三张图的每一格。"""
    for label, mine, graph in (
        ("run", RUN_NODES, run_nodes),
        ("episode", EPISODE_NODES, episode_nodes),
        ("task", TASK_NODES, task_nodes),
    ):
        assert sorted(mine) == sorted(graph), (
            f"{label} 图的格与 node_io 记的对不上：\n  图 {sorted(graph)}\n  这里 {sorted(mine)}"
        )
    cells = {f"run.{n}" for n in RUN_NODES}
    cells |= {f"episode.{n}" for n in EPISODE_NODES} | {f"task.{n}" for n in TASK_NODES}
    assert cells == set(CELL_SOURCES), (
        f"CELL_SOURCES 与三张图的格不一致：多 {sorted(set(CELL_SOURCES) - cells)}，"
        f"缺 {sorted(cells - set(CELL_SOURCES))}"
    )


def check_terminations_match_enum() -> None:
    """`TERMINATIONS` 与 `Termination` 枚举逐值一致（核对脚本能 import 真源，所以是对照）。"""
    from pokemon_agent.schemas.harness.domain import Termination

    assert {t.value for t in Termination} == TERMINATIONS, (
        f"node_io.TERMINATIONS {sorted(TERMINATIONS)} 与枚举 "
        f"{sorted(t.value for t in Termination)} 不一致"
    )


# ---- 按层切流 ----


def run_id_of(events: Sequence[Event]) -> str:
    """这批账的 run_id（`check_run_markers` 保证唯一）。"""
    for event in events:
        return str(meta_of(event).get("run_id", ""))
    return ""


def branch_of(event: Event) -> str:
    """这笔账属于哪条执行线（未经恢复为 `"main"`）。"""
    return str(meta_of(event).get("branch", "main"))


def branch_view(events: Sequence[Event], branch: str = "main") -> list[Event]:
    """一条执行线看得见的账：父线截至分叉点 + 自己的全部账（checkpoint spec §六）。

    血缘从账本身读：恢复出来的执行线第一条账是 `checkpoint_restore`，meta 带 `checkpoint_id`；
    同 id 的 `checkpoint_save` 在哪条线上，那条线就是父线，它本身就是分叉点（含它），逐级上溯。
    核对时按执行线分别核。与 `TraceTool.read_events` 各推一遍，互为对照。
    """
    own = [event for event in events if branch_of(event) == branch]
    if not own or kind_of(own[0]) != "checkpoint_restore":
        return own
    checkpoint_id = meta_of(own[0])["checkpoint_id"]
    saves = [
        event
        for event in events
        if kind_of(event) == "checkpoint_save"
        and meta_of(event).get("checkpoint_id") == checkpoint_id
    ]
    assert len(saves) == 1, (
        f"执行线 {branch} 的存档 {checkpoint_id} 对上 {len(saves)} 条 checkpoint_save"
    )
    parent = branch_view(events, branch_of(saves[0]))
    uuids = [str(event.get("uuid", "")) for event in parent]
    cut = str(saves[0].get("uuid", ""))
    assert cut in uuids, f"执行线 {branch} 的分叉点 {cut} 不在父线 {branch_of(saves[0])} 的账里"
    return [*parent[: uuids.index(cut) + 1], *own]


def _is_activity(event: Event) -> bool:
    """进流的账：`model_call` / `error` 两类不进（条数随重试浮动）；存档与问人的账不进（旁路）。"""
    return (
        str(event.get("type", "")) not in ("model_call", "error")
        and str(event.get("kind", "")) not in CHECKPOINT_KINDS | REVIEW_KINDS
    )


def run_stream(events: Sequence[Event]) -> list[tuple[str, Event]]:
    """run 流：run 级账按序，每一局在它第一条账处缩成一个 `EPISODE` 记号。"""
    run_id = run_id_of(events)
    out: list[tuple[str, Event]] = []
    seen: set[str] = set()
    for event in events:
        if not _is_activity(event):
            continue
        episode_id = _episode_of(event)
        if episode_id == run_id:
            out.append((kind_of(event), event))
        elif episode_id not in seen:
            seen.add(episode_id)
            out.append((EPISODE_TOKEN, event))
    return out


def episode_ids(events: Sequence[Event]) -> list[str]:
    """这一 run 派出去的局，按派出顺序。"""
    return [_episode_of(event) for token, event in run_stream(events) if token == EPISODE_TOKEN]


def episode_stream(events: Sequence[Event], episode_id: str) -> list[tuple[str, Event]]:
    """episode 流：这一局自己的账按序，每个 task 在它第一条账处缩成一个 `TASK` 记号。"""
    out: list[tuple[str, Event]] = []
    seen: set[str] = set()
    for event in events:
        if not _is_activity(event) or _episode_of(event) != episode_id:
            continue
        task_id = _task_of(event)
        if not task_id:
            out.append((kind_of(event), event))
        elif task_id not in seen:
            seen.add(task_id)
            out.append((TASK_TOKEN, event))
    return out


def task_streams(events: Sequence[Event], episode_id: str) -> dict[str, list[Event]]:
    """这一局里每个 task 的活动流（按派出顺序的有序字典）。"""
    streams: dict[str, list[Event]] = {}
    for event in events:
        if not _is_activity(event) or _episode_of(event) != episode_id:
            continue
        task_id = _task_of(event)
        if task_id:
            streams.setdefault(task_id, []).append(event)
    return streams


def _episode_of(event: Event) -> str:
    """这条账挂在哪一局（`meta.episode_id`）。"""
    return str(meta_of(event).get("episode_id", ""))


def _task_of(event: Event) -> str:
    """这条账挂在哪个 task（`meta.task_id`）。"""
    return str(meta_of(event).get("task_id", ""))


def _source_of(event: Event) -> str:
    """这条账从哪个位置发出（`meta.source`）。"""
    return str(meta_of(event).get("source", ""))


def _step_of(event: Event) -> int:
    """`meta.step`。"""
    return int(str(meta_of(event).get("step", 0)))


def episode_status(events: Sequence[Event], episode_id: str) -> str:
    """这一局怎么收尾：`closed`（episode_end）/ `failed`（episode_error）/ `open`（都没有）。"""
    for event in events:
        if _episode_of(event) != episode_id:
            continue
        if kind_of(event) == "episode_end":
            return "closed"
        if kind_of(event) == "episode_error":
            return "failed"
    return "open"


# ---- 流的判据 ----


def _walk(
    tokens: Sequence[str],
    table: dict[str, frozenset[str]],
    ends: frozenset[str],
    label: str,
    *,
    allow_truncated: bool,
) -> None:
    """一条流必须走得通后继表：每一步都在上一步的后继集合里，且（没截断时）停在合法结尾。"""
    previous = START
    for index, token in enumerate(tokens):
        allowed = table.get(previous, frozenset())
        assert token in allowed, (
            f"{label} 第 {index} 个活动 {token!r} 不能跟在 {previous!r} 后面"
            f"——允许的是 {sorted(allowed)}；整条流 {list(tokens)}"
        )
        previous = token
    if not allow_truncated:
        assert previous in ends, (
            f"{label} 停在 {previous!r}，没走到结尾 {sorted(ends)}；整条流 {list(tokens)}"
        )


def check_layer_flow(events: Sequence[Event], episode_id: str | None = None) -> None:
    """**三层活动流都走得通各自的后继表**（顺序 = 图的拓扑 = 输入依赖）。

    - run 流：`run_error` 可以接在任何活动后面、并结束这条流；
    - episode 流：异常收尾的局（`episode_error`）必须以它结尾
      （前面可以紧挨一条 `run.act` 补的空章），
      之前的部分只要求是合法前缀；
    - task 流：以 `task_error` 结尾的 task 之前只要求是合法前缀；此外只有异常收尾那一局的
      **最后一个** task 允许断在半路。

    `episode_id` 给了就只核那一局（run 流照核）；不给就核这一 run 的全部局。
    """
    run_tokens = [token for token, _ in run_stream(events)]
    if run_tokens and run_tokens[-1] == "run_error":
        _walk(run_tokens[:-1], RUN_NEXT, RUN_ENDS, "run 流", allow_truncated=True)
    else:
        _walk(run_tokens, RUN_NEXT, RUN_ENDS, "run 流", allow_truncated=False)

    targets = [episode_id] if episode_id else episode_ids(events)
    for target in targets:
        status = episode_status(events, target)
        pairs = episode_stream(events, target)
        tokens = [token for token, _ in pairs]
        label = f"episode {target} 的流"
        if status == "failed":
            assert tokens[-1] == "episode_error", (
                f"{label} 异常收尾却不以 episode_error 结尾：{tokens}"
            )
            body = pairs[:-1]
            while (
                body
                and body[-1][0] in ("read_episode_memory", "write_episode_memory")
                and _source_of(body[-1][1]) == "run.act"
            ):
                body = body[:-1]
            _walk([t for t, _ in body], EPISODE_NEXT, EPISODE_ENDS, label, allow_truncated=True)
        else:
            _walk(tokens, EPISODE_NEXT, EPISODE_ENDS, label, allow_truncated=status == "open")
        streams = task_streams(events, target)
        for index, (task_id, stream) in enumerate(streams.items()):
            last = index == len(streams) - 1
            kinds = [kind_of(e) for e in stream]
            errored = bool(kinds) and kinds[-1] == "task_error"
            _walk(
                kinds[:-1] if errored else kinds,
                TASK_NEXT,
                TASK_ENDS,
                f"task {task_id} 的流",
                allow_truncated=errored or (last and status != "closed"),
            )


def check_node_coverage(events: Sequence[Event], episode_id: str) -> list[str]:
    """**每个该留痕的发账位置都留了痕**（按 `source` + 指纹找）。返回零痕迹的位置清单。

    不算漏的：`CONDITIONAL_NODES`（条件未触发；但按过键的 run 里 `KEY_CHAIN_SOURCES` 必须齐）；
    这一局**异常收尾**时再加上收尾链、
    `plan_episode` 与整个 task 层（半路死掉的局，后面的格没跑是结果不是漏）。
    """
    seen = {(str(meta_of(e).get("source", "")), styled(e)) for e in events}
    missing = [
        source
        for source, fingerprints in NODE_FINGERPRINTS.items()
        if not any((source, fingerprint) in seen for fingerprint in fingerprints)
    ]
    known_ok = set(CONDITIONAL_NODES)
    if any(kind_of(e) == "act_call" for e in events):
        known_ok -= KEY_CHAIN_SOURCES
    if episode_status(events, episode_id) != "closed":
        known_ok |= set(CLOSING_SOURCES) | set(TASK_SOURCES) | {"plan_episode"}
    unexplained = [source for source in missing if source not in known_ok]
    assert not unexplained, (
        f"episode {episode_id} 所在的 run 里这些位置零痕迹，且不是条件未触发：{unexplained}"
        "——要么跑了没记账，要么路由把它跳过了"
    )
    return missing


def check_content_invariants(events: Sequence[Event], episode_id: str) -> None:
    """**衔接与内容的不变式**——相邻格、相邻层的接口值对得上。

    - task 内：账面步号是圈号（dispatch 落 0、每圈取帧 +1）——`act_call` 从 1 起逐动作 +1、
      `advance_step.next_step` 等于它自己的步号、`task_start.total_acts` 是局内累计键数基数
      （与账面步号解耦）；每条 `choose_verdict` 的首段就是紧跟的那一键；
    - task ↔ episode：`task_end.steps_used` = 这个 task 的键数；派出去的 task 都出自先前的拆解；
    - episode ↔ run：`episode_end.tasks_used` = 派出的 task 数、`acts_used` = 这一局的键数；
      账面步号圈号语义 episode 版（0928 定稿）：`episode_start` 落 0、`episode_end` 落
      `tasks_used + 1`（收尾账同圈中式）；
    - 结算：`termination` 取值合法，且不另记 `success` / `done`（都由它推出）；
    - 检索账与结构化字段的形状（`_check_read_accounts` / `_check_structured_content`）。
    """
    streams = task_streams(events, episode_id)
    planned: set[str] = set()
    for token, event in episode_stream(events, episode_id):
        if token == "decompose_verdict":
            tasks = content_of(event).get("tasks")
            assert isinstance(tasks, list) and tasks, "decompose_verdict 的 tasks 应是非空数组"
            ids = [str(t.get("task_id", "")) for t in tasks]
            assert len(set(ids)) == len(ids), f"decompose_verdict 里 task_id 重复：{ids}"
            planned |= set(ids)
        elif token == TASK_TOKEN:
            task_id = _task_of(event)
            assert task_id in planned, f"task {task_id} 被派出去了，但此前没有哪一版拆解给过它"

    _check_task_stamps(events, episode_id)

    total_acts = 0
    for task_id, stream in streams.items():
        total_acts += _check_task_keys(task_id, stream)

    for event in events:
        if _episode_of(event) != episode_id:
            continue
        if kind_of(event) == "episode_start":
            assert _step_of(event) == 0, f"episode_start 落在第 {_step_of(event)} 步，开局账应为 0"
        if kind_of(event) != "episode_end":
            continue
        content = content_of(event)
        _check_settlement("episode_end", content)
        assert int(str(content.get("tasks_used", -1))) == len(streams), (
            f"episode_end.tasks_used={content.get('tasks_used')}，账上派出了 {len(streams)} 个 task"
        )
        assert int(str(content.get("acts_used", -1))) == total_acts, (
            f"episode_end.acts_used={content.get('acts_used')}，账上按了 {total_acts} 个键"
        )
        assert _step_of(event) == int(str(content.get("tasks_used", -1))) + 1, (
            f"episode_end 落在第 {_step_of(event)} 步，收尾圈号应为 tasks_used + 1"
            f"（圈号语义 0928 定稿）"
        )

    episode_events = [e for e in events if _episode_of(e) == episode_id]
    _check_read_accounts(episode_events)
    _check_structured_content(episode_events)


def _check_task_stamps(events: Sequence[Event], episode_id: str) -> None:
    """episode 的盖章：每次盖的是**刚结束的那个 task**，放弃的都是还没派的条目；
    正常收尾的局里每个派出去的 task 都恰好盖过一次章。"""
    last_task = ""
    stamped: list[str] = []
    dispatched: list[str] = []
    for token, event in episode_stream(events, episode_id):
        if token == TASK_TOKEN:
            last_task = _task_of(event)
            dispatched.append(last_task)
        elif token == "settle_task":
            content = content_of(event)
            assert content.get("task_id") == last_task, (
                f"settle_task 盖的是 {content.get('task_id')!r}，刚结束的 task 是 {last_task!r}"
            )
            assert content.get("status") in ("completed", "failed"), (
                f"settle_task.status={content.get('status')!r} 应为 completed / failed"
            )
            gone = content.get("abandoned") or []
            assert not set(gone) & set(dispatched), f"放弃了已经派出去的 task：{gone}"
            assert not gone or content.get("status") == "failed", "只有定案为失败才放弃剩余条目"
            stamped.append(last_task)
    if episode_status(events, episode_id) == "closed":
        assert stamped == dispatched, f"派出的 task {dispatched} 与盖过章的 {stamped} 对不上"


def _check_task_keys(task_id: str, stream: Sequence[Event]) -> int:
    """一个 task 内的键号、决策与按键、结算计数。返回这个 task 的键数。"""
    presses = [e for e in stream if kind_of(e) == "act_call"]
    if stream and kind_of(stream[0]) == "task_start":
        # 步号语义（0928 二次定稿）：账面步号是 task 内圈号——dispatch 落第 0 步、
        # 每圈取帧 +1，按键圈号即键序号；content.total_acts 是局内累计键数基数
        # （记忆 / 帧槽键控用），与账面步号解耦。
        assert _step_of(stream[0]) == 0, (
            f"task {task_id} 的 task_start 落在第 {_step_of(stream[0])} 步，dispatch 应为 0"
        )
        start = int(str(content_of(stream[0]).get("total_acts", -1)))
        assert start >= 0, f"task {task_id} 的 total_acts 缺失或为负：{start}"
        for offset, press in enumerate(presses):
            assert _step_of(press) == offset + 1, (
                f"task {task_id} 第 {offset + 1} 键落在第 {_step_of(press)} 步，应为 {offset + 1}"
            )
    for event in stream:
        if kind_of(event) == "advance_step":
            next_step = int(str(content_of(event).get("next_step", -1)))
            assert next_step == _step_of(event), (
                f"advance_step 对不上：落在第 {_step_of(event)} 步，next_step 却是 {next_step}"
            )
    decided: list[str] = []
    for event in stream:
        if kind_of(event) == "choose_verdict":
            script = content_of(event).get("script")
            if isinstance(script, dict):
                decided.append(f"script:{script.get('name')}")
                continue
            keys = _keys_of(event, "sequence")
            assert keys, f"task {task_id} 的 think 没给出任何键"
            decided.append(keys[0])
        elif kind_of(event) == "act_call":
            content = content_of(event)
            if "sequence" in content:
                keys = _keys_of(event, "sequence")
                assert len(keys) == 1, (
                    f"act_call key 形只应记一个键，这条记了 {len(keys)} 个：{keys}"
                )
                assert decided and keys[0] == decided[-1], (
                    f"task {task_id} 按的 {keys[0]!r} 不是刚决策的首键 {decided[-1:]!r}"
                )
            else:
                name = f"script:{content.get('script')}"
                assert decided and name == decided[-1], (
                    f"task {task_id} 跑的 {name!r} 不是刚决策的脚本 {decided[-1:]!r}"
                )
    for event in stream:
        if kind_of(event) == "task_end":
            content = content_of(event)
            _check_settlement("task_end", content)
            assert int(str(content.get("steps_used", -1))) == len(presses), (
                f"task {task_id} 的 steps_used={content.get('steps_used')}，"
                f"账上按了 {len(presses)} 键"
            )
    return len(presses)


def _check_settlement(label: str, content: dict[str, object]) -> None:
    """结算账：`termination` 取值合法，且不另记 `success` / `done`（都由它推出）。"""
    termination = str(content.get("termination", ""))
    assert termination in TERMINATIONS, (
        f"{label}.termination={termination!r} 不在 {sorted(TERMINATIONS)}"
    )
    leaked = sorted({"success", "done"} & set(content))
    assert not leaked, f"{label} 另记了 {leaked}——它们由 termination 推出，不再落账"


def check_run_invariants(events: Sequence[Event]) -> None:
    """run 级衔接：每次盖章盖的是**刚结束的那一局**；`run_end.total` = 派出的局数。"""
    last_episode = ""
    stamps = 0
    for token, event in run_stream(events):
        if token == EPISODE_TOKEN:
            last_episode = _episode_of(event)
        elif token == "settle_goal":
            stamps += 1
            content = content_of(event)
            assert content.get("episode_id") == last_episode, (
                f"settle_goal 盖的是 {content.get('episode_id')!r}，刚结束的一局是 {last_episode!r}"
            )
            assert content.get("status") in ("completed", "failed"), (
                f"settle_goal.status={content.get('status')!r} 应为 completed / failed"
            )
        elif token == "run_end":
            content = content_of(event)
            dispatched = len(episode_ids(events))
            assert int(str(content.get("total", -1))) == dispatched, (
                f"run_end.total={content.get('total')}，账上派出了 {dispatched} 局"
            )
            assert stamps == dispatched, f"派出 {dispatched} 局，只盖了 {stamps} 次章"
