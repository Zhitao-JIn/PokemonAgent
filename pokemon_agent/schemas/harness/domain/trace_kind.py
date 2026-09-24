"""**全项目唯一的账名词表**：`TraceKind`。

一种 kind = 一种账。harness 组装 `FromHarnessToTraceToolAppendReq` 时声明
"这是哪笔账"，`TraceTool` 按 kind 分派到对应的渲染函数，**渲染出来的事件封套上
`kind` 就落这个值**（0914 去掉翻译表之后 `req.kind` 与 `event.kind` 逐字同值）。

**为什么归 harness**：`TraceKind` 的消费者是 harness——**21 + 6 个节点各自声明
自己记什么账**，`schemas/harness/communication/` 的 `FromHarnessToTraceToolAppendReq`
把它装进信封。所以它归 `schemas/harness/`，跟"harness 只认 schemas"这条边界一致。

**两件事分得清**：`TraceKind`（有哪几种账要记）归 harness；
**每种账的 `content` 里有哪些字段**（这笔账长什么样）归 tool 的渲染层
（`tools/trace/render.py`）——那是跨模块契约，观测台前端按字段名渲染。

## 0914 定案：它是账名词表，不是"派发键"

此前这里有两套名字：本枚举是 harness 的**派发键**，而落盘 `kind` 由渲染层另起
（`MEMORY_WRITE` → `write_step`、`RETRIEVE_NODE` → 6 种 `read_*`、`DECISION_FAILED`
→ 异常名）。35 个成员里 18 个两边不同，中间靠 `_RENDERERS` 那张翻译表连着。
现在**一套名字**：枚举值 = 落盘 `kind`，翻译表消失。

三条命名规则：

1. **一个 kind 只答"这是什么账"**——不答"谁发的"（那是 `meta.source`）、
   不答"落在哪一步"（那是 `meta.step`）；
2. **同族共享词形**：读口一律 `read_*`、写口一律 `write_*`、
   调用账一律 `<链路>_call`（**链路名本身**才是 `sense`/`choose`/…，
   它是 `link` 那一维的值域，见 `render._CALL_LINK`）；
3. **kind 唯一指认、不带派生信息**：同一个 kind 的两个生产者（`write_episode_memory`
   由 `summarize_episode` / `leave_chapter` / `run.act` 三处发出）靠 `meta.source` 分开，
   不靠再加一个 kind。

## 0924 定案（204）：请求与结论、落点逐一对得上

- **模型交互成对**：`<链路>_call` ↔ 它的结论账——`sense_call` ↔ `sense_frame`、
  `choose_call` ↔ `choose_verdict`、`plan_call` ↔ `plan_verdict`、`decompose_call` ↔
  `decompose_verdict`、`judge_call` ↔ `judge_verdict`、`verify_call` ↔ `verify_verdict`、
  `summarize_task_call` ↔ `write_task_memory`、`summarize_episode_call` ↔ `write_episode_memory`；
- **记忆读写用全名**：`read_<记忆名>` / `write_<记忆名>`（act_memory / task_memory /
  episode_memory / object_memory / knowledge）；
- **动作动词在前**：`press_key` / `check_stall` / `advance_step` / `get_action_space`；
- **生命周期三件套**：`<层>_start` 在该层入口、`<层>_end` 在该层 `*_done`、`<层>_error` 由
  **接住异常的那一格**记（task 的由 episode `act`、episode 的由 run `act`、run 的由 `new_run`）；
- **定案**：`settle_goal`（run 给目标表定案）/ `settle_task`（episode 给任务表定案）。
"""

from __future__ import annotations

from enum import StrEnum


class TraceKind(StrEnum):
    """一笔 trace 账的种类。**值就是落盘封套上的 `kind`**。"""

    # ---- run 边界（run 级账：`meta.episode_id`/`task_id` 位放 run_id、step = 已派局数）----
    # start 在 `run.begin`、end 在 `run_done`、error 在 `run_entry.new_run`。
    RUN_START = "run_start"
    RUN_END = "run_end"
    RUN_ERROR = "run_error"

    # ---- episode 边界：start 在 `begin_episode`、end 在 `close_episode`、error 在 `run.act` ----
    EPISODE_START = "episode_start"
    EPISODE_END = "episode_end"
    EPISODE_ERROR = "episode_error"

    # ---- task 边界：start 在 `begin_task`、end 在 `close_task`、error 在 `episode.act` ----
    TASK_START = "task_start"
    TASK_END = "task_end"
    TASK_ERROR = "task_error"

    # ---- 账：模型调用（**九条链路各一条**）----
    # 值带上 `_call` 后缀，与 `link` 那一维（纯链路名 `choose`）区分开：
    # "一次 choose 链的调用账"叫 `choose_call`，"这条账属于哪条链"叫 `link="choose"`。
    # 链路名的唯一真源是 `tools/trace/render._CALL_LINK`。
    SENSE_CALL = "sense_call"
    CHOOSE_CALL = "choose_call"
    PLAN_CALL = "plan_call"
    DECOMPOSE_CALL = "decompose_call"
    JUDGE_CALL = "judge_call"
    VERIFY_CALL = "verify_call"
    SUMMARIZE_EPISODE_CALL = "summarize_episode_call"
    SUMMARIZE_TASK_CALL = "summarize_task_call"

    # ---- 错误：**三个闭集**（0914 定案）----
    #
    # 此前这一族是**开集**：落盘 `kind` 取 `type(exc).__name__`（网关的
    # `APIStatusError`、`OutputTruncated`……任何异常都可能落进来），于是
    # "封套 kind 必在词表内"这条判据不得不留一个特例——`experiment/real_check/`
    # `node_io.py` 那时按"形状"收族（"没登记过、又带一条真链路"），
    # 而不是按名字登记。开集进不了枚举，所以现在分三档：
    #
    #   CALL_FAILED         某条链的**某一次尝试**失败（`content.link` 给链、
    #                       `content.attempt` 给第几次、`content.exception` 给异常类名、
    #                       `content.reason` 给异常消息原文）；
    #   CALL_EXHAUSTED      某条链**重试预算耗尽**（整条链的结论，没有"第几次"
    #                       可言，所以不带 `attempt`）；
    #   SUMMARY_PARSE_ERROR 蒸馏**答了但解析不了**（`link` 为 `summarize` / `summarize_task`；
    #                       由调用账连带产出，取代那次的 `call_failed`）。
    #
    # 此前 `CALL_EXHAUSTED` 那一档摊成五个成员（`DECISION_FAILED` / `JUDGE_FAILED` /
    # `VERIFY_FAILED` / `SUMMARIZE_FAILED` / `EXTRACT_FAILED`），渲染层把它们统统
    # 翻成同一个 `kind="MaxRetriesExceeded"`、链路名落在 `payload.link`——**五个成员
    # 说的是同一件事**，合并成一个，链路改由调用方在 `req.link` 里自报。
    CALL_FAILED = "call_failed"
    CALL_EXHAUSTED = "call_exhausted"
    SUMMARY_PARSE_ERROR = "summary_parse_error"

    # ---- 一步之内的各类事件（不经模型）----
    SENSE_FRAME = "sense_frame"
    CHOOSE_VERDICT = "choose_verdict"
    PRESS_KEY = "press_key"
    """**一个键的执行**（`act` 节点）。

    0914 改名：此前叫 `act`，而它的 `type` 也是 `act`——同一本账上两个字段是同一个
    词，读账像回声。补上动词（`do_`）之后，同族另有 `get_action_space` /
    `check_stall`。
    """
    GET_ACTION_SPACE = "get_action_space"
    """这一步允许的动作名（掩码结果）。0914 改名：此前叫 `action_space`，缺动词。"""
    CHECK_STALL = "check_stall"
    ADVANCE_STEP = "advance_step"

    # 结论类：三条账都是"某一格给了什么结论"，共用 `_verdict` 词形。
    JUDGE_VERDICT = "judge_verdict"
    VERIFY_VERDICT = "verify_verdict"
    """0914 改名：此前叫 `verify_result`——三个同类账里两个叫 verdict、一个叫
    result，读的人得记两套说法。"""
    PLAN_VERDICT = "plan_verdict"
    DECOMPOSE_VERDICT = "decompose_verdict"
    """episode 级拆解的结论：这一版任务链（`plan_verdict` 在 episode 层的对应物）。"""

    SETTLE_GOAL = "settle_goal"
    """run 级给目标表盖章（COMPLETED / FAILED）连同人审表态——目标表状态变更的留痕。"""
    SETTLE_TASK = "settle_task"
    """episode 级给任务表盖章（COMPLETED / FAILED）连同人审表态与被放弃的剩余条目。"""

    # ---- 记忆读：**六条读口一个形状**（`content = {count, query, refs}`）----
    #
    # 此前六条读口**共用一个派发键** `RETRIEVE_NODE`，账名由 `render.retrieve_node`
    # 按 `req.read_kind` 现翻（`"step"` → `read_step`……）——一维信息寄居在
    # "一个字段 + 一张表"里。现在六个成员各占一个 kind，`read_kind` 字段作废。
    READ_ACT_MEMORY = "read_act_memory"
    READ_TASK_MEMORY = "read_task_memory"
    READ_EPISODE_MEMORY = "read_episode_memory"
    READ_KNOWLEDGE = "read_knowledge"
    READ_OBJECT_MEMORY = "read_object_memory"

    # ---- 记忆写：**三本账一个形状**（`content` + `meta`）----
    #
    # （`write_knowledge` 已整账删除，0914 跟进：knowledge 由人管理，根本没有
    # 计划走"模型写知识"这条路——见 CHANGELOG 补记五。）
    #
    # 0914 改名：此前成员值是 `memory_write` / `object_note` /
    # `episode_memory_write` / `knowledge_write`，而落盘账名是
    # `write_step` / `write_object_memory` / `write_episode_memory` / `write_knowledge`
    # ——同一个东西两个名字。现在值就是账名。
    WRITE_ACT_MEMORY = "write_act_memory"
    WRITE_TASK_MEMORY = "write_task_memory"
    WRITE_OBJECT_MEMORY = "write_object_memory"
    WRITE_EPISODE_MEMORY = "write_episode_memory"
