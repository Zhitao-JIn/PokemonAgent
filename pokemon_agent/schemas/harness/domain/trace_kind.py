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
   调用账一律 `<链路>_call`（**链路名本身**才是 `perception`/`decide`/…，
   它是 `link` 那一维的值域，见 `render._CALL_LINK`）；
3. **kind 唯一指认、不带派生信息**：同一个 kind 的两个生产者（`write_episode`
   由 `verify_and_summarize` 与 `review` 两处发出）靠 `meta.source` 分开，
   不靠再加一个 kind。
"""

from __future__ import annotations

from enum import StrEnum


class TraceKind(StrEnum):
    """一笔 trace 账的种类。**值就是落盘封套上的 `kind`**。"""

    # ---- run 边界（run 级账沿用项目约定：`meta.episode_id` 位放 run_id、step 恒 0）----
    RUN_START = "run_start"
    RUN_END = "run_end"
    RUN_ERROR = "run_error"

    # ---- episode 边界 ----
    EPISODE_START = "episode_start"
    EPISODE_END = "episode_end"
    EPISODE_ERROR = "episode_error"

    # ---- 账：模型调用（**七条链路各一条**）----
    # 值带上 `_call` 后缀，与 `link` 那一维（纯链路名 `decide`）区分开：
    # "一次 decide 链的调用账"叫 `decide_call`，"这条账属于哪条链"叫 `link="decide"`。
    # 链路名的唯一真源是 `tools/trace/render._CALL_LINK`。
    PERCEPTION_CALL = "perception_call"
    DECIDE_CALL = "decide_call"
    PLAN_CALL = "plan_call"
    JUDGE_CALL = "judge_call"
    VERIFY_CALL = "verify_call"
    SUMMARIZE_CALL = "summarize_call"
    EXTRACT_CALL = "extract_call"

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
    #   SUMMARY_PARSE_ERROR 蒸馏**答了但解析不了**（`link` 恒 `summarize`）。
    #
    # 此前 `CALL_EXHAUSTED` 那一档摊成五个成员（`DECISION_FAILED` / `JUDGE_FAILED` /
    # `VERIFY_FAILED` / `SUMMARIZE_FAILED` / `EXTRACT_FAILED`），渲染层把它们统统
    # 翻成同一个 `kind="MaxRetriesExceeded"`、链路名落在 `payload.link`——**五个成员
    # 说的是同一件事**，合并成一个，链路改由调用方在 `req.link` 里自报。
    CALL_FAILED = "call_failed"
    CALL_EXHAUSTED = "call_exhausted"
    SUMMARY_PARSE_ERROR = "summary_parse_error"

    # ---- 一步之内的各类事件（不经模型）----
    OBSERVE = "observe"
    THINK = "think"
    DO_ACTION = "do_action"
    """**一个键的执行**（`act` 节点）。

    0914 改名：此前叫 `act`，而它的 `type` 也是 `act`——同一本账上两个字段是同一个
    词，读账像回声。补上动词（`do_`）之后，同族另有 `get_action_space` /
    `stall_check`。
    """
    GET_ACTION_SPACE = "get_action_space"
    """这一步允许的动作名（掩码结果）。0914 改名：此前叫 `action_space`，缺动词。"""
    STALL_CHECK = "stall_check"
    AFTER_ACTION = "after_action"
    STEP_ADVANCE = "step_advance"

    # 结论类：三条账都是"某一格给了什么结论"，共用 `_verdict` 词形。
    JUDGE_VERDICT = "judge_verdict"
    VERIFY_VERDICT = "verify_verdict"
    """0914 改名：此前叫 `verify_result`——三个同类账里两个叫 verdict、一个叫
    result，读的人得记两套说法。"""
    PLAN_VERDICT = "plan_verdict"

    # ---- 记忆读：**六条读口一个形状**（`content = {count, query, refs}`）----
    #
    # 此前六条读口**共用一个派发键** `RETRIEVE_NODE`，账名由 `render.retrieve_node`
    # 按 `req.read_kind` 现翻（`"step"` → `read_step`……）——一维信息寄居在
    # "一个字段 + 一张表"里。现在六个成员各占一个 kind，`read_kind` 字段作废。
    READ_STEP = "read_step"
    READ_GLOBAL = "read_global"
    READ_KNOWLEDGE = "read_knowledge"
    READ_OBJECT = "read_object"
    READ_VERIFY_STEP = "read_verify_step"
    """0914 改名：此前叫 `read_verify_steps`——其余五条读口都是单数，只有它带 s。"""
    READ_VERIFY_KNOWLEDGE = "read_verify_knowledge"

    # ---- 记忆写：**三本账一个形状**（`content` + `meta`）----
    #
    # （`write_knowledge` 已整账删除，0914 跟进：knowledge 由人管理，根本没有
    # 计划走"模型写知识"这条路——见 CHANGELOG 补记五。）
    #
    # 0914 改名：此前成员值是 `memory_write` / `object_note` /
    # `episode_memory_write` / `knowledge_write`，而落盘账名是
    # `write_step` / `write_object` / `write_episode` / `write_knowledge`
    # ——同一个东西两个名字。现在值就是账名。
    WRITE_STEP = "write_step"
    WRITE_OBJECT = "write_object"
    WRITE_EPISODE = "write_episode"
