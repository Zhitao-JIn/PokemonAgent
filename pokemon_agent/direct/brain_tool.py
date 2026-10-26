"""brain 能力的 tool 层门面：**一个容器（`BrainTool`）+ 九个能力对象**。

**harness 与 brain 是两个互不认识的世界**——harness 侧是装满了
`Observation`/`ActionSpace`/`ActMemory` 的信封，brain 侧只认 prompt 文本和
一撮裸字段。这一层就是两边之间唯一的桥，做四件事（每一件都是"brain 不该知道的"）：

1. **渲染**：把信封里的世界对象变成 brain 认得的文本
   （观测 → `before`/`after`、记忆 → `history`、动作空间 → prompt 里的按键说明）。
2. **规范化的世界语义**：`a` 只按一次、多段链中间只能方向键——这些是
   **这个世界**对动作的要求（换一个世界就不成立），不是大脑的规则。
   `INTERACT_KEY` 因此定义在这一层。
3. **盖章坐标**：`episode_id`/`step` 由 harness 给、在这里装进 `ActMemory`
   ——大脑不知道自己在哪一局、第几步；账上也不替它记尝试序号——"第几次"由账在链上的
   位置回答（0914 跟进删 `attempt`）。
4. **重试循环 + 记账**：调模型的链路（`choose`/`plan`/`decompose`/`judge`/`verify`/
   `summarize`/`summarize_task`）走**同一个** `_attempt_loop()`。`reflect` 不调模型，不走循环。

**0922 185：函数变对象，按层分发**（用户定稿）。原先的方法是 `BrainTool`
一个类上的兄弟，harness 三层各拿整张口——run 层能看见 `choose`、task 层能
看见 `judge`，全靠约定不调。现在每个能力是一个**独立的对象**（`Planner`/
`Decomposer`/`Chooser`/`Judger`/`Reflector`/`Verifier`/`Summarizer`/`TaskSummarizer`，
都住本层、签名只吃信封），`BrainTool` 退化成**装配容器**：`build()` 造 Brain 与 provider、
组装八个对象；`build.py` 把每层需要的对象分发给三个 runtime。于是
"不属于本层的方法"在结构上看不见，mock 按对象换（铁律 4：一份协议一份假实现）。

**重试的分工**（2026-09-13 定稿，取代此前的"a+c 方案"）：

    brain  ──抛 AttemptFailed（带这一次的账）──▶  tool
    tool   ──重试 retry.brain_max_attempts 次──▶  成功：resp 带整条账
                                         耗尽：抛 MaxRetriesExceeded（带整条账 + source）
    harness ──except MaxRetriesExceeded──▶ 决定怎么收场（失败这一局 / 路由 review / …）

**为什么 loop 必须在这里而不是 brain**：失败之后该怎么办依赖调用方的处境
（决策失败让这一局失败、规划失败交人工、校验失败可以降级继续），
brain 是第三方模块，不知道这些。它只回答"这一次成没成"。

**这里没有降级，只有重试**：`judge`/`verify`/`summarize` 曾在 brain 里把调用失败
吞成"看起来正常的业务结果"（`done=False` / 全标不可靠 / `summary=None`）。那个
兜底已整个取消——它让"链路坏了"与"业务结论就是如此"在数据里分不开。
现在各条链路一致：重试耗尽就抛，由 harness 决定要不要给保守结果
（要给的话也发生在 `except` 里，trace 上看得见）。

**并组装存储形状**：`reflect` 的 `ActMemory`、`summarize_task` 的 `TaskMemory`、
`summarize` 的 `EpisodeMemory` 都在这层装配——`brain` 与 `memory` 互不认识，
两边形状的搬运只有这里做。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar, cast

from pydantic import BaseModel

from pokemon_agent.backoff import backoff_seconds
from pokemon_agent.brain import (
    Action,
    ActionSegment,
    BrainPort,
    EpisodeSummary,
    RunSummary,
    ScriptArg,
    ScriptSignature,
)
from pokemon_agent.brain.errors import (
    AttemptFailed,
    EmptyCompletion,
    ParseFailure,
    ProviderRejected,
    ToolTimeout,
)
from pokemon_agent.deadline import Deadline
from pokemon_agent.direct.budget_provider import BudgetProvider, TimeoutProvider
from pokemon_agent.direct.call_policy import CallPolicy
from pokemon_agent.direct.judge_prompt_params import judge_prompt_params
from pokemon_agent.direct.node_brain_factory import BrainLayer, NodeBrainFactory
from pokemon_agent.direct.planning_validation import validate_result
from pokemon_agent.errors import BudgetExhausted, MaxRetriesExceeded
from pokemon_agent.prompt import (
    DecideActionParams,
    DecomposeParams,
    OutputRetryParams,
    PromptGateway,
    RenderedPrompt,
    RunPlanParams,
    SummarizeParams,
    SummarizeRunParams,
    SummarizeTaskParams,
    VerifyParams,
)
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeResp,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeRunResp,
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToBrainToolSummarizeTaskResp,
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToBrainToolVerifyResp,
    ModelCall,
)
from pokemon_agent.schemas.memory import (
    SNAPSHOT_BLIND,
    ActMemory,
    EpisodeMemory,
    RunMemory,
    TaskMemory,
)
from pokemon_agent.settings import (
    ActionLimitsConfig,
    ModelsConfig,
    RequestTimeoutsConfig,
    RetryConfig,
)
from pokemon_agent.world import (
    DIRECTION_KEYS,
    INTERACT_KEY,
    TERRAIN_MEANING,
    ActionEntry,
)

BrainLink = Literal["text", "judge", "verify", "plan"]
"""`BrainTool.build(links=…)` 可选的四条模型链路（对应配置文件 `models` 段的四个条目）。"""

_Result = TypeVar("_Result")


def cap_images(frames: Sequence[str], cap: int) -> list[str]:
    """保留最新 cap 张并返回副本；调用方保证 cap > 0。本检查点先落地，后续才接线。

    L0 / L1 / run 蒸馏后续使用；L2 的帧与文字逐帧对应，不调用本函数。
    """
    assert cap > 0, "cap_images() needs a positive cap"
    return list(frames[-cap:])


def collect_frames(memories: Sequence[EpisodeMemory | TaskMemory]) -> list[str]:
    """依次收集每条记忆的首末帧，跳过 None，按字符串相等去重并保留首次位置。

    返回独立列表，不限制数量；调用方另行过帽。
    """
    frames: list[str] = []
    seen: set[str] = set()
    for memory in memories:
        for frame in (memory.first_frame, memory.last_frame):
            if frame is not None and frame not in seen:
                seen.add(frame)
                frames.append(frame)
    return frames


def dedup_snapshots(
    entries: list[ActMemory],
) -> tuple[list[str], list[ActMemory.Observation]]:
    """把一串 `ActMemory` 摊平成 `(before, after, before, after, ...)` 的观测
    序列，去重后**一次遍历、一口气**返回两条严格对齐的列表：截图（base64
    字符串，喂 `VisionDescribeReq.images`）和它们各自对应的 `ActMemory.
    Observation` 快照（给调用方转文字，比如"当前观测"要渲成 `$observation`）。
    **两条列表长度、顺序永远一一对应**——`frames[i]` 就是 `snapshots[i]`
    这份观测的那张截图。

    两条列表由构造保证一一对应，调用方不必自己论证"这个索引对应那份观测"
    （靠"最后一条的 after 就是当前观测"去猜索引，只在 history 非空且连续时
    成立，猜错了没人报错、只是悄悄喂错内容）。不需要 `snapshots` 的调用方
    用 `_` 丢弃第二个返回值。

    去重规则（跟 `render_sequence()` 是同一件事的图片版）：相邻两条之间
    `entries[i].after_frame` 和 `entries[i+1].before_frame` 本来就是同一帧
    画面（`store_step_episode_memory()` 是同一份观测先存成上一条的 after，
    `close_step()` 再把它扶正成下一条的 before，编码结果自然相等），
    图片不该重复发一遍——每多发一张图，多模态请求就多花一份 token。去重只看
    **字符串是否等于上一张已经收进来的**：同一帧画面编出来的 base64 永远
    逐字节相等，不会出现"内容相同但字符串不同"需要额外判断的情况；反过来，
    不连续的两条（比如中间有一步权限被拒没能落库）编码结果天然不同，不会
    被误判成重复。

    **没有截图的观测不进这两条列表**（`before_frame`/`after_frame` 为
    `None`，比如那一步感知失败没能落盘）——它们既进不了图片列表，就没有
    "这张图对应哪份观测"这件事，两条列表必须永远等长，宁可这份观测彻底不
    出现，也不能让长度对不上。

    **为什么在 tool 层**（0915 起，从 `schemas/memory/datastore/act_memory.py` 搬来）：
    "怎么把记忆拼成发给模型的图"是**发请求的组装逻辑**，不是记忆的数据形状
    ——schemas 层只描述记录长什么样，怎么消费它们归 tool（与 prompt 渲染同
    一个归属：五条带图链路的 `images` 都在各能力对象的入口用本函数拼出）。
    """
    frames: list[str] = []
    snapshots: list[ActMemory.Observation] = []
    for entry in entries:
        for obs, frame in ((entry.before, entry.before_frame), (entry.after, entry.after_frame)):
            if frame is None:
                continue
            if frames and frames[-1] == frame:
                continue
            frames.append(frame)
            snapshots.append(obs)
    return frames, snapshots


# ---- 规划 ----


class Planner:
    """`PlanPort` 的实现：run 级规划的信封翻译器。run 层 runtime 持它。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def plan(self, req: FromHarnessToBrainToolPlanOnceReq) -> FromHarnessToBrainToolPlanOnceResp:
        """渲染本轮规划并保留同源目标表与历史；重试保留全部调用账与版本戳。"""
        params = RunPlanParams.model_validate(req.model_dump(mode="json"))
        rendered_prompt = render_and_stamp(self._prompt_gateway, "run_plan", params, [])
        current_prompt = rendered_prompt
        goal_stack = self._prompt_gateway.render_history("run_plan", params, part="goals")
        history = self._prompt_gateway.render_history("run_plan", params)
        images = cap_images(collect_frames(req.details), self._policy.image_cap)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            nonlocal current_prompt
            current_prompt = _retry_prompt(rendered_prompt, calls, self._prompt_gateway)
            result = self._brain.plan(
                prompt=current_prompt.text,
                goal_stack=goal_stack,
                history=history,
                max_push=req.max_push,
                images=images,
                thinking=_thinking_after(calls),
            )
            return validate_result(result, [e.status.value for e in req.plan])

        result, calls = _attempt_loop(
            "plan",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=lambda: current_prompt,
        )
        return FromHarnessToBrainToolPlanOnceResp(plan=result.plan, calls=calls)


# ---- 拆解 ----


class Decomposer:
    """`DecomposePort` 的实现：episode 级拆解的信封翻译器。episode 层 runtime 持它。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def decompose(
        self, req: FromHarnessToBrainToolDecomposeReq
    ) -> FromHarnessToBrainToolDecomposeResp:
        """以原始字段渲染拆解与 context；结构校验失败重问，每次尝试在收编后盖章。"""
        params = DecomposeParams.model_validate(
            {**req.model_dump(mode="json"), "terrain_meanings": TERRAIN_MEANING}
        )
        rendered_prompt = render_and_stamp(self._prompt_gateway, "decompose", params, [])
        current_prompt = rendered_prompt
        goal = f"{req.goal.goal}（判据：{req.goal.criteria}）"
        context = self._prompt_gateway.render_history("decompose", params)
        images = cap_images(collect_frames(req.task_memories), self._policy.image_cap)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            nonlocal current_prompt
            current_prompt = _retry_prompt(rendered_prompt, calls, self._prompt_gateway)
            result = self._brain.decompose(
                prompt=current_prompt.text,
                goal=goal,
                context=context,
                max_tasks=req.max_tasks,
                images=images,
                thinking=_thinking_after(calls),
            )
            return validate_result(result, [e.status.value for e in req.task_table])

        result, calls = _attempt_loop(
            "decompose",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=lambda: current_prompt,
        )
        return FromHarnessToBrainToolDecomposeResp(decomposition=result.decomposition, calls=calls)


# ---- 决策 ----


def decide_prompt_params(
    req: FromHarnessToBrainToolChooseOnceReq, *, max_segments: int
) -> DecideActionParams:
    """转换决策原料；调用方保证段数上限为正。"""
    assert max_segments > 0
    data = req.model_dump(mode="json")
    data["observation"] = data.pop("obs")
    data.update(
        max_segments=max_segments,
        terrain_meanings=TERRAIN_MEANING,
    )
    return DecideActionParams.model_validate(data)


class Chooser:
    """`ChoosePort` 的实现：决策的信封翻译器。episode 层 runtime 持它；
    task 层将来持自己的实例（受限 space / 换策略时只换这一个对象）。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        action_limits: ActionLimitsConfig,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._limits = action_limits
        self._deadline = deadline

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """渲染决策并执行解析或传输重试；返回规范化动作及全部调用账。"""
        params = decide_prompt_params(req, max_segments=self._limits.max_segments)
        rendered_prompt = render_and_stamp(self._prompt_gateway, "decide_action", params, [])
        current_prompt = rendered_prompt
        # **images 在这里拼**（与 prompt 同一个归属："谁问模型，谁把 req 变成
        # 请求"），素材**不另开通道**：就是 `$memories` 段落拼装出来的那批帧
        # ——`dedup_snapshots()` 与 `render_sequence()` 是同一件事的图片版/
        # 文字版（相邻去重、逐帧对应），prompt 里读到的每一步和模型看到的
        # 画面严格同源。第一步没有记忆 → 空列表 → 纯文本。
        images, _snapshots = dedup_snapshots(req.memories)
        scripts = [
            _signature(e)
            for e in req.space.entries
            if e.kind == "script" and req.space.enabled(e.name)
        ]

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            nonlocal current_prompt
            current_prompt = _retry_prompt(
                rendered_prompt, calls, self._prompt_gateway, include_action_space_note=True
            )
            return self._brain.choose(
                prompt=current_prompt.text,
                keys=list(req.space.names),
                images=images,
                scripts=scripts,
            )

        result, calls = _attempt_loop(
            "choose",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=lambda: current_prompt,
        )
        return FromHarnessToBrainToolChooseOnceResp(
            action=self._normalize(result.action),
            calls=calls,
        )

    def _normalize(self, action: Action) -> Action:
        """施加**这个世界的**动作语义规则，返回规范化后的动作。

        三条规则（都是从 brain 搬来的——它们是世界知识，不是决策知识）：

        1. **`a` 只按一次**：链内按键只做纯 RAM 观测，而对话文字只有视觉模型
           读得出来——连按三次推完整段对话，那几句一帧都没被看到，最后一次还会
           把对话框关掉，判定器看到一个没有对话框的画面，**一局本该成功的
           episode 被静默记成失败**。`a` 的收益全在中间帧上，连按对它从来没有意义。
        2. **多段链的中间只能是方向键**：中间帧看不到，所以链体里只放"闭眼也不
           丢信息"的移动键。
        3. **链尾允许一个 `a`**：链尾那一帧本来就会被感知，`a` 打开的对话框正好
           出现在这一帧，证据没有丢。所以"走过去再按一下"能一次决策做完。

        上限（`action_limits.max_segments` / `max_times`）也在这里校验——
        prompt 渲染与这里的校验读同一份配置，不会自相矛盾。

        **改写不留痕、也不上抛**（2026-09-13 删 `normalized`）：规则 1 施加在
        "连按 `a`"这种**本就没有意义的写法**上，改写的结果与模型原意等价——
        报出去只是让 trace 多一个字段、多一处要维护的状态，没有一个消费者。
        对比：**校验失败**（超上限、链体出现非方向键）仍然抛 `ParseFailure`
        ——那是模型真的写错了，必须让它重写。

        **校验失败抛 `ParseFailure`**（本层的内部信号）：它跟"模型幻觉了按键"
        是同一类东西（外部输入不合法），所以由同一个重试循环接住再问一次。

        脚本调用原样放行：参数的语义校验归 world 的执行器。
        """
        if action.script is not None:
            return action
        segments: list[ActionSegment] = []
        for index, segment in enumerate(action.sequence, start=1):
            name, times = segment.name, segment.times

            if times > self._limits.max_times:
                raise _illegal(f"segment {index}: times {times} > {self._limits.max_times}")

            if name == INTERACT_KEY and times != 1:
                times = 1

            segments.append(ActionSegment(name=name, times=times))

        if len(segments) > self._limits.max_segments:
            raise _illegal(f"{len(segments)} segments > {self._limits.max_segments}")

        if len(segments) > 1:
            body_bad = [s.name for s in segments[:-1] if s.name not in DIRECTION_KEYS]
            tail = segments[-1].name
            tail_bad = tail not in DIRECTION_KEYS and tail != INTERACT_KEY
            if body_bad or tail_bad:
                raise _illegal(
                    "multi-step sequence may contain only directional keys, "
                    f"plus at most one trailing {INTERACT_KEY!r}"
                )

        return Action(sequence=segments)


def _signature(entry: ActionEntry) -> ScriptSignature:
    """world 的脚本条目 `ActionEntry` → brain 的 `ScriptSignature`
    （只留解析要用的名字、类型、是否必填）。"""
    return ScriptSignature(
        name=entry.name,
        params=[
            ScriptArg(name=p.name, type=p.type, required=p.default is None) for p in entry.params
        ],
    )


# ---- 反思 ----


class Reflector:
    """`ReflectPort` 的实现：把一次操作的两帧观测装成 `ActMemory`（本链路**不调模型**）。"""

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """用两帧结构化观测组装记忆，不调用模型或网关。

        前置：请求提供两帧任务观测和本步动作、坐标。
        后置：保留快照与结果，仅剥离 SNAPSHOT_BLIND 中的检索字段；请求不变。
        """
        entry = ActMemory(
            before=ActMemory.Observation.model_validate(_blind(req.before).model_dump(mode="json")),
            action=req.action.describe(),
            after=ActMemory.Observation.model_validate(_blind(req.after).model_dump(mode="json")),
            step=req.step,
            episode_id=req.episode_id,
            result=req.result,
        )
        return FromHarnessToBrainToolReflectResp(entry=entry)


# ---- 判定 ----


class Judger:
    """`JudgePort` 的实现：判定的信封翻译器。episode 层 runtime 持它。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """渲染本层执行证据并判定；不允许的中断按解析失败重试，调用账保留版本戳。"""
        params = judge_prompt_params(req)
        rendered_prompt = render_and_stamp(self._prompt_gateway, "judge_success", params, [])
        prompt = rendered_prompt.text
        goal = req.goal.goal
        history = self._prompt_gateway.render_history("judge_success", params)
        if not req.history:
            images = cap_images(
                collect_frames([*req.task_memories, *req.episode_memories]), self._policy.image_cap
            )
        else:
            images, _snapshots = dedup_snapshots(list(req.history))

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            result = self._brain.judge(prompt=prompt, goal=goal, history=history, images=images)
            if result.interrupted and not req.allow_interrupt:
                call = result.calls[-1].model_copy(
                    update={
                        "error_kind": "ParseFailure",
                        "error": "本层不允许 interrupted",
                        "payload": {**result.calls[-1].payload, "ok": "false"},
                    }
                )
                raise AttemptFailed(call)
            return result

        result, calls = _attempt_loop(
            "judge",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=rendered_prompt,
        )
        return FromHarnessToBrainToolJudgeResp(
            decision=result.decision, why=result.why, calls=calls
        )


# ---- 校验 ----


class Verifier:
    """`VerifyPort` 的实现：校验的信封翻译器。episode/task 层 runtime 持它。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def verify(self, req: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """校验完整素材；网关渲染 prompt 与逐条素材，所有尝试在收编后盖章。"""
        params = VerifyParams.model_validate(req.model_dump(mode="json"))
        rendered_prompt = render_and_stamp(self._prompt_gateway, "verify", params, [])
        prompt = rendered_prompt.text
        records = self._prompt_gateway.render_history("verify", params)
        # **images 在这里拼**（0915 130 收权，与 judge/choose 同归属）：
        # harness 只装素材（entries），帧由本层对同一批 entries 取——
        # ActMemory 取 before/after 帧，TaskMemory 取首末代表帧；
        # 与 prompt 的 `$entries` 渲染同源。
        images = _verify_images(req.entries)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.verify(
                prompt=prompt,
                entries=records,
                goal=req.goal,
                knowledge=req.knowledge,
                images=images,
            )

        result, calls = _attempt_loop(
            "verify",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=rendered_prompt,
        )
        return FromHarnessToBrainToolVerifyResp(verdicts=result.verdicts, calls=calls)


def _verify_images(entries: list[ActMemory | TaskMemory]) -> list[str]:
    """校验用的截图序列：相邻去重后摊平成一张网格图的原料。

    ActMemory 每条贡献 `(before_frame, after_frame)`，TaskMemory 每条贡献
    `(first_frame, last_frame)`；`None`（感知失败没落盘/没取到代表帧）不进
    序列，与上一张逐字节相等的也不进（同一帧不重发，多模态按张计费）。
    """
    frames: list[str] = []
    for entry in entries:
        if isinstance(entry, TaskMemory):
            candidates = (entry.first_frame, entry.last_frame)
        else:
            candidates = (entry.before_frame, entry.after_frame)
        for frame in candidates:
            if frame is None or (frames and frames[-1] == frame):
                continue
            frames.append(frame)
    return frames


# ---- 蒸馏 ----


class Summarizer:
    """`SummarizePort` 的实现：蒸馏的信封翻译器。episode 层 runtime 持它。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def summarize(
        self, req: FromHarnessToBrainToolSummarizeReq
    ) -> FromHarnessToBrainToolSummarizeResp:
        """蒸馏本局素材并组装 EpisodeMemory；来源章由请求提供，每次尝试保留版本戳。"""
        params = SummarizeParams.model_validate(
            {**req.model_dump(mode="json"), "success": req.success}
        )
        rendered_prompt = render_and_stamp(self._prompt_gateway, "summarize", params, [])
        prompt = rendered_prompt.text
        records = self._prompt_gateway.render_history("summarize", params)
        # **images 在这里拼**（0923 189：原料是 TaskMemory，取各条的代表帧去重）
        seen: set[str] = set()
        images: list[str] = []
        for m in req.entries:
            for f in (m.first_frame, m.last_frame):
                if f and f not in seen:
                    seen.add(f)
                    images.append(f)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.summarize(
                prompt=prompt,
                goal=req.goal,
                history=records,
                success=req.success,
                steps=req.steps,
                max_steps=req.max_steps,
                images=images,
            )

        result, calls = _attempt_loop(
            "summarize_episode",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=rendered_prompt,
        )
        summary: EpisodeSummary = result.summary
        episode_memory = EpisodeMemory(
            episode_id=req.episode_id,
            run_id=req.run_id,
            run_goal=req.run_goal,
            goal_id=req.goal_id,
            first_frame=req.entries[0].first_frame,
            last_frame=req.entries[-1].last_frame,
            goal=req.goal,
            steps=req.steps,
            acts_used=req.acts_used,
            termination=req.termination.value,
            reason=summary.reason,
            summary=summary.summary,
            reusable_patterns=summary.reusable_patterns,
            critical_decisions=summary.critical_decisions,
            failure_points=summary.failure_points,
            quality_score=summary.quality_score,
            quality_rationale=summary.quality_rationale,
            applicable_scenes=summary.applicable_scenes,
            tags=summary.tags,
            markdown=summary.markdown,
        )
        return FromHarnessToBrainToolSummarizeResp(
            summary=summary, episode_memory=episode_memory, calls=calls
        )


# ---- 世界知识抽取 ----


# ---- task 蒸馏 ----


class RunSummarizer:
    """RunSummarizePort 的实现：复用蒸馏 provider 和重试预算，盖 run 来源章。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def summarize_run(
        self, req: FromHarnessToBrainToolSummarizeRunReq
    ) -> FromHarnessToBrainToolSummarizeRunResp:
        """蒸馏最终目标表与局记忆；请求保证条目非空，所有尝试保留活动版本戳。"""
        params = SummarizeRunParams.model_validate(req.model_dump(mode="json"))
        rendered_prompt = render_and_stamp(self._prompt_gateway, "summarize_run", params, [])
        prompt = rendered_prompt.text
        records = self._prompt_gateway.render_history("summarize_run", params)
        images = cap_images(collect_frames(req.episode_memories), self._policy.image_cap)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.summarize_run(
                prompt=prompt,
                goal=req.run_goal,
                history=records,
                success=req.success,
                steps=req.episodes,
                max_steps=req.max_episodes,
                images=images,
            )

        result, calls = _attempt_loop(
            "summarize_run",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=rendered_prompt,
        )
        summary: RunSummary = result.summary
        memory = RunMemory(
            run_id=req.run_id,
            run_goal=req.run_goal,
            episodes=req.episodes,
            succeeded=req.succeeded,
            acts_used=req.acts_used,
            termination=req.termination.value,
            **summary.model_dump(),
        )
        return FromHarnessToBrainToolSummarizeRunResp(
            summary=summary, run_memory=memory, calls=calls
        )


class TaskSummarizer:
    """`TaskSummarizePort` 的实现：task 蒸馏的信封翻译器。task 层 runtime 持它。"""

    def __init__(
        self,
        brain: BrainPort,
        *,
        policy: CallPolicy,
        deadline: Deadline | None = None,
        prompt_gateway: PromptGateway,
    ) -> None:
        self._brain = brain
        self._prompt_gateway = prompt_gateway
        self._policy = policy
        self._deadline = deadline

    def summarize_task(
        self, req: FromHarnessToBrainToolSummarizeTaskReq
    ) -> FromHarnessToBrainToolSummarizeTaskResp:
        """蒸馏本 task 的素材并组装 TaskMemory；请求保证条目非空，失败账随异常返回。"""
        params = SummarizeTaskParams.model_validate(
            {**req.model_dump(mode="json"), "success": req.success}
        )
        rendered_prompt = render_and_stamp(self._prompt_gateway, "summarize_task", params, [])
        prompt = rendered_prompt.text
        records = self._prompt_gateway.render_history("summarize_task", params)
        images, _snapshots = dedup_snapshots(list(req.entries))

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.summarize(
                prompt=prompt,
                goal=req.goal,
                history=records,
                success=req.success,
                steps=req.steps_used,
                max_steps=req.max_steps,
                images=images,
            )

        result, calls = _attempt_loop(
            "summarize_task",
            attempt,
            policy=self._policy,
            deadline=self._deadline,
            rendered_prompt=rendered_prompt,
        )
        summary: EpisodeSummary = result.summary
        first = next((e.before_frame for e in req.entries if e.before_frame), None)
        last = next((e.after_frame for e in reversed(req.entries) if e.after_frame), None)
        memory = TaskMemory(
            run_id=req.run_id,
            episode_id=req.episode_id,
            entry_id=req.entry_id,
            task_id=req.task_id,
            goal=req.goal,
            termination=req.termination.value,
            reason=summary.reason,
            steps_used=req.steps_used,
            total_acts=req.entries[0].step if req.entries else 0,
            summary=summary.summary,
            reusable_patterns=summary.reusable_patterns,
            critical_decisions=summary.critical_decisions,
            failure_points=summary.failure_points,
            quality_score=summary.quality_score,
            quality_rationale=summary.quality_rationale,
            tags=summary.tags,
            first_frame=first,
            last_frame=last,
            markdown=summary.markdown,
        )
        return FromHarnessToBrainToolSummarizeTaskResp(summary=summary, memory=memory, calls=calls)


# ---- 容器 ----


@dataclass
class BrainTool:
    """九个能力对象的**装配容器**（0922 185 起——它自己不再实现任何方法）。

    `build()` 是组装的唯一入口：造 Brain 与 provider（型号名只在这里落地）、
    组装九个对象。`build.py` 把每层需要的对象**分发给三个 runtime**——
    runtime 字段持的是能力对象（`PlanPort`/`ChoosePort`/…），不是本容器；
    容器只在装配期活着。
    """

    planner: Planner
    decomposer: Decomposer
    chooser: Chooser
    judger: Judger
    reflector: Reflector
    verifier: Verifier
    summarizer: Summarizer
    task_summarizer: TaskSummarizer
    run_summarizer: RunSummarizer

    @classmethod
    def build(
        cls,
        *,
        links: Sequence[BrainLink],
        layer: BrainLayer | None = None,
        models: ModelsConfig,
        retry: RetryConfig,
        request_timeouts: RequestTimeoutsConfig,
        action_limits: ActionLimitsConfig,
        image_cap: int,
        prompt_registry: str | None = None,
        vision_dump_dir: str | None = None,
        deadline: Deadline | None = None,
    ) -> BrainTool:
        """按需装配：`links` 列出这一层要的链路，没列的位置 provider 为 `None`。

        - run 层：`links=("plan", "judge")` → `planner` + `judger`；
        - episode 层：`links=("plan", "judge", "verify")` → `decomposer` 与其余；
        - task 层：`links=("text", "judge", "verify")` → `chooser` 等。

        `layer`标识节点所属层；models.node_thinking配置的节点覆盖链路默认值。
        节点覆盖使用独立provider，不在请求之间更改共享实例；旧调用方无节点覆盖时可省略layer。

        型号、温度、输出上限、超时、思考开关全部取自 `models`；重试预算与退避取自 `retry`；
        `prompt_registry` 为 None 时用随包空表，相对路径按仓库根解析；网关由九个能力对象共享。
        各链路的单请求时限取自 `request_timeouts`（规划与拆解取 `models.plan.timeout_s`）；
        `action_limits` 同时约束决策 prompt 与动作校验。没配的链路被调用时，`Brain` 方法入口的
        assert 当场拦下；容器造出来就是终态，中途改选型没有语义。

        **签名收配置段而不是 `BrainLlmConfig`**：`build.py` 对 brain **零 import**，
        `BrainLlmConfig` 在本方法内部构造，"协议归属、实现归属、接线归属"三者对齐。

        后置条件：造出来的 provider 互不相同（`judge` 与 `decide` 不共用是硬约束，见 `Brain`
        模块 docstring）。
        """
        from pokemon_agent.brain import Brain, BrainLlmConfig, LinkSpec
        from pokemon_agent.brain.build_llm_providers import build_llm_providers

        registry_path = Path(prompt_registry) if prompt_registry is not None else None
        if registry_path is not None and not registry_path.is_absolute():
            registry_path = Path(__file__).resolve().parents[2] / registry_path
        prompt_gateway = PromptGateway(registry_path)

        def spec(link: BrainLink) -> LinkSpec | None:
            if link not in links:
                return None
            chosen = getattr(models, link)
            return LinkSpec(
                model=chosen.model,
                temperature=chosen.temperature,
                max_tokens=chosen.max_tokens,
                timeout_s=chosen.timeout_s,
                thinking=getattr(chosen, "thinking", False),
                cache_marker=chosen.cache_marker,
            )

        config = BrainLlmConfig(
            text=spec("text"),
            judge=spec("judge"),
            verify=spec("verify"),
            plan=spec("plan"),
            json_mode=models.json_mode,
            vision_dump_dir=vision_dump_dir,
        )

        def build_brain(configuration: BrainLlmConfig) -> BrainPort:
            """按固定选型构建独立provider；节点覆盖不修改共享实例。"""
            decide, judge_llm, verify_llm, plan_llm = build_llm_providers(configuration)
            bounded = [
                BudgetProvider(cast(TimeoutProvider, provider), deadline, limit, source)
                if provider is not None
                else None
                for provider, limit, source in (
                    (decide, request_timeouts.choose, "choose"),
                    (judge_llm, request_timeouts.judge, "judge"),
                    (verify_llm, request_timeouts.verify, "verify"),
                    (plan_llm, models.plan.timeout_s, "plan"),
                )
            ]
            decide, judge_llm, verify_llm, plan_llm = bounded
            return Brain(
                decide_llm=decide,
                judge_llm=judge_llm,
                verify_llm=verify_llm,
                plan_llm=plan_llm,
            )

        brain = build_brain(config)
        nodes = NodeBrainFactory(brain, config, models, layer, build_brain)

        def policy(capability: str, link: BrainLink, timeout_s: float) -> CallPolicy:
            return CallPolicy(
                retry=retry,
                request_timeout_s=timeout_s,
                image_cap=image_cap,
                thinking_node=nodes.node(capability),
                thinking=nodes.thinking(capability, link),
            )

        return cls(
            planner=Planner(
                nodes.brain("plan", "plan"),
                policy=policy("plan", "plan", models.plan.timeout_s),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            decomposer=Decomposer(
                nodes.brain("decompose", "plan"),
                policy=policy("decompose", "plan", models.plan.timeout_s),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            chooser=Chooser(
                nodes.brain("choose", "text"),
                policy=policy("choose", "text", request_timeouts.choose),
                action_limits=action_limits,
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            judger=Judger(
                nodes.brain("judge", "judge"),
                policy=policy("judge", "judge", request_timeouts.judge),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            reflector=Reflector(),
            verifier=Verifier(
                nodes.brain("verify", "verify"),
                policy=policy("verify", "verify", request_timeouts.verify),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            summarizer=Summarizer(
                nodes.brain("summarize", "verify"),
                policy=policy("summarize", "verify", request_timeouts.summarize),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            run_summarizer=RunSummarizer(
                nodes.brain("summarize_run", "verify"),
                policy=policy("summarize_run", "verify", request_timeouts.summarize),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
            task_summarizer=TaskSummarizer(
                nodes.brain("summarize_task", "verify"),
                policy=policy("summarize_task", "verify", request_timeouts.summarize),
                deadline=deadline,
                prompt_gateway=prompt_gateway,
            ),
        )


# ---- 内部辅助 ----


def render_and_stamp(
    gateway: PromptGateway,
    task: str,
    params: BaseModel,
    calls: Sequence[ModelCall],
) -> RenderedPrompt:
    """渲染任务并为全部尝试盖章；调用方传入 _adopt 之后的 tool 层 ModelCall。

    前置条件：所有调用账已经收编；保留已有 payload 与错误字段，原位追加三项版本信息。
    后置条件：每条账的三项信息与返回的 RenderedPrompt 一致。
    """
    assert all(isinstance(call, ModelCall) for call in calls), "Stamp only adopted tool calls"
    rendered = gateway.render(task, params)
    _stamp_calls(calls, rendered)
    return rendered


def _stamp_calls(
    calls: Sequence[ModelCall], rendered: RenderedPrompt, policy: CallPolicy | None = None
) -> None:
    """为已收编尝试追加版本及节点开关；保留单次重试覆盖和原始账项。"""
    stamp = {
        "prompt_task": rendered.task,
        "prompt_version": rendered.version,
        "prompt_hash": rendered.hash,
    }
    for call in calls:
        call.payload.update(stamp)
        if policy is not None and policy.thinking_node is not None:
            call.payload["thinking_node"] = policy.thinking_node
            call.payload["thinking_configured"] = str(policy.thinking).lower()
            call.payload["thinking_effective"] = (
                call.payload.get("thinking_override")
                if call.payload.get("thinking_override") in ("true", "false")
                and not call.payload.get("images")
                else str(policy.thinking).lower()
            )
    assert all(all(call.payload[key] == value for key, value in stamp.items()) for call in calls)


def _attempt_loop(
    source: str,
    attempt: Callable[[int, list[ModelCall]], _Result],
    *,
    retry_prompt: Callable[[str, list[ModelCall]], str] | None = None,
    base_prompt: str = "",
    policy: CallPolicy,
    deadline: Deadline | None = None,
    rendered_prompt: RenderedPrompt | Callable[[], RenderedPrompt] | None = None,
) -> tuple[_Result, list[ModelCall]]:
    """brain 各链路共用的重试循环：**成功带整条账返回 / 耗尽带整条账抛异常**。

    `source`：链路名（`"choose"`/`"plan"`/`"judge"`/…），进 `MaxRetriesExceeded`
        让 harness 分辨是谁完了。
    `attempt`：第 `n` 次尝试的函数，收 `(第几次, 目前累积的账)` 返回结果。
        它内部调 brain，失败时 brain 抛 `AttemptFailed`（带这次的账）。
    `retry_prompt`/`base_prompt`：可选——只有 `decide` 这条链路会传。
        **叠不叠纠正说明由账上的 `error_kind` 决定**（0915 分叉，见
        `_retry_prompt`）：解析类失败叠加说明；传输失败原样重问。

    **`ProviderRejected` 立即耗尽**：4xx 是服务端的明确拒绝（密钥/配额/型号），
    重试注定无用——第一轮就抛 `MaxRetriesExceeded`（`attempts=1`），
    不烧预算、不给模型叠"你上一次的输出不合法"那种张冠李戴的纠正。

    **预算所有失败共用**：最多 `policy.retry.brain_max_attempts` 次（含首次）。
    **退避看刚失败的那次**（`backoff.backoff_seconds`）：不是超时睡 1s；是超时睡 2s、
    再超时 4s。耗尽那一轮不睡（后面是上抛，没人等这个间隔）。

    为什么收 `(第几次, 账)` 两个参数：`decide` 要用 "第几次" 渲染纠正说明的
    文案（"第 2 次尝试"），也要用 "账" 取上次的失败原因；其余链路两个都不用。
    收着不用的成本只是一个签名，比给两条链路各写一个循环便宜。

    **两种"账"的翻译在这里**：brain 吐的是 `brain.interface.ModelCall`
    （它自己的方言），本循环收进来的一律转成 `tools.interface.ModelCall`
    （tool 层的工作形状）——"字段恰好一样"是巧合，语义边界是真的。
    **账按序排列**：第 `n` 次尝试的账落在第 `n` 位——"第几次"由位置回答，
    不另盖一枚 `attempt` 戳（0914 跟进删）。
    """

    def active_prompt() -> RenderedPrompt:
        assert rendered_prompt is not None
        return rendered_prompt() if callable(rendered_prompt) else rendered_prompt

    calls: list[ModelCall] = []
    while True:
        if deadline is not None:
            deadline.allowed(policy.request_timeout_s, source, calls)
        try:
            result = attempt(len(calls) + 1, calls)
        except BudgetExhausted as exc:
            pending = [_adopt(call) for call in exc.calls] if rendered_prompt else exc.calls
            if rendered_prompt is not None:
                _stamp_calls(pending, active_prompt(), policy)
            raise BudgetExhausted(source, [*calls, *pending], exc.reason) from exc
        except AttemptFailed as exc:
            call = _adopt(exc.call)
            if rendered_prompt is not None:
                _stamp_calls([call], active_prompt(), policy)
            calls.append(call)
            if (
                call.error_kind == ProviderRejected.__name__
                or len(calls) >= policy.retry.brain_max_attempts
            ):
                raise MaxRetriesExceeded(
                    len(calls), _last_error(calls), calls, source=source
                ) from exc
            timeouts = sum(c.error_kind == ToolTimeout.__name__ for c in calls)
            delay = backoff_seconds(call.error_kind == ToolTimeout.__name__, timeouts, policy.retry)
            if deadline is not None:
                deadline.allowed(policy.request_timeout_s, source, calls, delay_s=delay)
            time.sleep(delay)
            continue

        pending = [_adopt(call) for call in result.calls]
        if rendered_prompt is not None:
            _stamp_calls(pending, active_prompt(), policy)
        calls.extend(pending)
        return result, calls


def _thinking_after(calls: list[ModelCall]) -> bool | None:
    """plan / decompose 这一次尝试的思考开关。

    之前有过一次 `EmptyCompletion` 就强制关，否则沿用装配。

    `calls`：本次调用目前累积的账。返回 `False` = 这一次关思考；`None` = 不覆盖 provider 的设置。
    """
    if any(call.error_kind == EmptyCompletion.__name__ for call in calls):
        return False
    return None


def _adopt(call: object) -> ModelCall:
    """把 **brain 方言的**一条账转成 tool 层的工作形状。

    两个类字段此刻恰好一样（`payload`/`error_kind`/`error`），所以这是三个字段
    的搬运——**但它不是白搬**：`brain` 不认识 `tools.interface`（铁律 2 的依赖
    方向），而重试循环、盖章、随异常带出整条账这些都是 tool 层的事。类型边界
    划在这里，"brain 能换实现"才不被一条隐式共享类型绑死。
    """
    return ModelCall(
        payload=dict(call.payload),
        error_kind=call.error_kind,
        error=call.error,
    )


def _illegal(why: str) -> Exception:
    """构造一次"世界语义校验失败"——走 `ParseFailure` 家族，可被重试。"""
    return ParseFailure("", why)


def _retry_prompt(
    base_prompt: RenderedPrompt,
    attempts: list[ModelCall],
    gateway: PromptGateway,
    *,
    include_action_space_note: bool = False,
) -> RenderedPrompt:
    """解析失败组合纠正版本；首次调用和传输失败保留原始版本。

    `include_action_space_note` 只有决策打开：动作空间那段说明只对 choose 成立。
    """
    if not attempts or attempts[-1].error_kind not in _PARSE_ERROR_KINDS:
        return base_prompt
    last = attempts[-1]
    return gateway.render(
        "output_retry",
        OutputRetryParams(
            base_prompt=base_prompt.text,
            attempt=len(attempts) + 1,
            reason=last.error,
            raw=cast(str, last.payload.get("raw", ""))[:400],
            include_action_space_note=include_action_space_note,
        ),
    )


# 会叠加纠正说明的 `error_kind` 集合：模型看到了题、但输出不能用。
# `ValidationError` 在 brain.choose 里已折算成 `ParseFailure`；`ProviderRejected`
# 到不了重试的第二轮；其余（`ToolTimeout` 等）都是"模型没收到题"，原样重问。
_PARSE_ERROR_KINDS = {"ParseFailure", "IllegalAction", "OutputTruncated"}


def _last_error(attempts: list[ModelCall]) -> str:
    """把最后一次尝试的失败信息折成一句话。"""
    if not attempts:
        return "no attempts recorded"
    last = attempts[-1]
    return f"{last.error_kind}: {last.error}"


def _blind(obs):  # noqa: ANN001, ANN202
    """滤掉不该进记忆的字段（`SNAPSHOT_BLIND`），构造记忆用的那份观测。

    过滤只发生在写记忆这一步，大脑/世界看到的仍是完整观测。
    """
    return obs.model_copy(update={"facts": obs.facts.exclude(SNAPSHOT_BLIND)})
