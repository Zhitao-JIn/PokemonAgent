"""`BrainToolPort` 的唯一实现：harness 和 `Brain` 之间那层翻译壳。

持有一个 `BrainPort`（真正的大脑）。**harness 与 brain 是两个互不认识的
世界**——harness 侧是装满了 `Observation`/`ActionSpace`/`StepMemory` 的
信封，brain 侧只认 prompt 文本和一撮裸字段。这个类就是两边之间唯一的桥。

它做四件事（每一件都是"brain 不该知道的"）：

1. **渲染**：把信封里的世界对象变成 brain 认得的文本
   （观测 → `before`/`after`、记忆 → `history`、动作空间 → prompt 里的按键说明）。
2. **规范化的世界语义**：`a` 只按一次、多段链中间只能方向键——这些是
   **这个世界**对动作的要求（换一个世界就不成立），不是大脑的规则。
   `INTERACT_KEY` 因此定义在这一层。
3. **盖章坐标**：`episode_id`/`step` 由 harness 给、在这里装进 `StepMemory`
   ——大脑不知道自己在哪一局、第几步。`attempt`（第几次尝试）同理盖在账上。
4. **重试循环 + 记账**：五条调模型的链路（`choose`/`plan`/`judge`/`verify`/
   `summarize`）走**同一个** `_attempt_loop()`。`reflect` 不调模型，不走循环。

**重试的分工**（2026-09-13 定稿，取代此前的"a+c 方案"）：

    brain  ──抛 AttemptFailed（带这一次的账）──▶  tool
    tool   ──重试 BRAIN_MAX_ATTEMPTS 次──▶  成功：resp 带整条账
                                         耗尽：抛 MaxRetriesExceeded（带整条账 + source）
    harness ──except MaxRetriesExceeded──▶ 决定怎么收场（失败这一局 / 路由 review / …）

**为什么 loop 必须在这里而不是 brain**：失败之后该怎么办依赖调用方的处境
（决策失败让这一局失败、规划失败交人工、校验失败可以降级继续），
brain 是第三方模块，不知道这些。它只回答"这一次成没成"。

**这里没有降级，只有重试**：`judge`/`verify`/`summarize` 曾在 brain 里把调用失败
吞成"看起来正常的业务结果"（`done=False` / 全标不可靠 / `summary=None`）。那个
兜底已整个取消——它让"链路坏了"与"业务结论就是如此"在数据里分不开。
现在五条链路一致：重试耗尽就抛，由 harness 决定要不要给保守结果
（要给的话也发生在 `except` 里，trace 上看得见）。

**并组装存储形状**：`reflect` 的 `StepMemory`、`summarize` 的 `EpisodeMemory`
都在这层装配——`brain` 与 `memory` 互不认识，两边形状的搬运只有这里做。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pokemon_agent.brain import (
    Action,
    ActionSegment,
    BrainPort,
    EpisodeSummary,
    Reflection,
)
from pokemon_agent.brain.errors import AttemptFailed, ParseFailure
from pokemon_agent.config import BRAIN_MAX_ATTEMPTS, MAX_RATIONALE, MAX_SEGMENTS, MAX_TIMES
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeResp,
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToBrainToolVerifyResp,
    ModelCall,
)
from pokemon_agent.schemas.memory import SNAPSHOT_BLIND, EpisodeMemory, StepMemory
from pokemon_agent.tools.prompts import run_plan as run_plan_prompt
from pokemon_agent.tools.prompts import verify_and_summarize as verify_summarize_prompt
from pokemon_agent.world import DIRECTION_KEYS, INTERACT_KEY

from .prompts import decide_action as decide_action_prompt
from .prompts import judge_success as judge_success_prompt

_Result = TypeVar("_Result")


class BrainTool:
    """`BrainToolPort` 的唯一实现。持有真正的 `Brain`（或任何 `BrainPort` 实现）。"""

    def __init__(self, brain: BrainPort) -> None:
        """接好大脑。**本对象没有状态**，纯转发+翻译+重试。"""
        self._brain = brain

    @classmethod
    def build(
        cls,
        *,
        text: str = "qwen-plus",
        judge: str = "qwen3.8-max",
        verify: str = "doubao-seed-2-1-pro-260628",
        plan: str = "doubao-seed-2-1-pro-260628",
        max_tokens: int = 25600,
    ) -> BrainTool:
        """按型号选型造一个**接了真大脑**的 tool——装配点唯一的入口。

        **为什么把"组装 config + 造 Brain + 造四个 provider"全收在这一处**
        （2026-09-13 起 S6，0913 深夜九收窄签名）："brain 的四个技能分别该接
        哪家厂商、哪个位置必须是豆包型号名"是这条链路的内部接线知识，
        装配点（`build.py`）不该知道，也不该 import `QwenProvider`/`ArkProvider`。
        收进类方法之后，`build.py` 那一侧只剩一行
        `BrainTool.build(text=..., judge=..., ...)`，**协议归属、实现归属、
        接线归属三者对齐**（协议在 `brain.interface`，接线在 `BrainTool`）。

        **签名收裸字段而不是收 `BrainLlmConfig`**（0913 深夜九）：此前签名是
        `build(config: BrainLlmConfig)`，于是 `build.py` 得先
        `from pokemon_agent.brain import BrainLlmConfig` —— 一行非 tool 层的
        brain import。改成裸字段后 `BrainLlmConfig` 在本方法内部构造，
        `build.py` 对 brain **零 import**，"只有 tool 层依赖 brain"这条命题
        至此字面成立。裸字段的选择也跟 `build_vision_provider(model)` 对齐。

        **它是 `__init__` 的糖，不是第二套装配逻辑**：内部就是
        `BrainLlmConfig(...)` + `build_llm_providers(config)` + `Brain(...)` +
        `cls(brain)`，没有任何额外判断——"谁 new 具体实现"仍然只有一个答案
        （`brain/build_llm_providers.py`），不是又多了一个真源。

        前置条件：`verify`/`plan` 的型号名是火山方舟认的豆包型号名
        （带日期后缀）——传 Qwen 型号名会在第一次调用时 404，
        本方法不替调用方验这个（它验不了，没有厂商型号表）。
        后置条件：返回的 tool 持有的 `Brain` 用四个**不同**的 provider 实例，
        `judge` 与 `decide` 不共用（判定与决策误差同源的硬约束，
        见 `Brain` 模块 docstring）——这条由 `build_llm_providers` 的出口
        断言保证。
        """
        # 导入放函数内：`brain.providers` 拖着整个厂商实现面（含 PIL），
        # 不该在 import 本模块时就连带拉起来。
        from pokemon_agent.brain import Brain, BrainLlmConfig, build_llm_providers

        config = BrainLlmConfig(
            text=text,
            judge=judge,
            verify=verify,
            plan=plan,
            max_tokens=max_tokens,
        )
        decide, judge_llm, verify_llm, plan_llm = build_llm_providers(config)
        brain = Brain(
            decide_llm=decide,
            judge_llm=judge_llm,
            verify_llm=verify_llm,
            plan_llm=plan_llm,
        )
        return cls(brain)

    # ---- 重试循环（五条链路共用）----

    def _attempt_loop(
        self,
        source: str,
        attempt: Callable[[int, list[ModelCall]], _Result],
        *,
        retry_prompt: Callable[[str, list[ModelCall]], str] | None = None,
        base_prompt: str = "",
    ) -> tuple[_Result, list[ModelCall]]:
        """brain 各链路共用的重试循环：**成功带整条账返回 / 耗尽带整条账抛异常**。

        `source`：链路名（`"decide"`/`"plan"`/`"judge"`/…），进 `MaxRetriesExceeded`
            让 harness 分辨是谁完了。
        `attempt`：第 `n` 次尝试的函数，收 `(第几次, 目前累积的账)` 返回结果。
            它内部调 brain，失败时 brain 抛 `AttemptFailed`（带这次的账）。
        `retry_prompt`/`base_prompt`：可选——只有 `decide` 这条链路会**叠加纠正
            说明**（把上次错在哪拼进 prompt），其余四条原样重问。

        为什么收 `(第几次, 账)` 两个参数：`decide` 要用 "第几次" 渲染纠正说明的
        文案（"第 2 次尝试"），也要用 "账" 取上次的失败原因；其余链路两个都不用。
        收着不用的成本只是一个签名，比给两条链路各写一个循环便宜。

        **两种"账"的翻译在这里**：brain 吐的是 `brain.interface.ModelCall`
        （它自己的方言），本循环收进来的一律转成 `tools.interface.ModelCall`
        （tool 层的工作形状）——"字段恰好一样"是巧合，语义边界是真的。
        **盖章也在这里**（`str(第几次)`）：只有循环控制者知道"这是第几次"。
        """
        calls: list[ModelCall] = []
        for nth in range(1, BRAIN_MAX_ATTEMPTS + 1):
            try:
                result = attempt(nth, calls)
            except AttemptFailed as exc:
                # 单次失败：把这次的账收进来，继续下一次。**账在盖 attempt 时补**。
                calls.append(_adopt(exc.call).with_attempt(str(nth)))
                continue

            calls.extend(_adopt(call).with_attempt(str(nth)) for call in result.calls)
            return result, calls

        raise MaxRetriesExceeded(BRAIN_MAX_ATTEMPTS, _last_error(calls), calls, source=source)

    # ---- 决策 ----

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """决策：拼 prompt → 重试循环调 `Brain.choose()` → 规范化 → 打包整条账。

        **prompt 在这里拼**（0913 定案）：harness 只装素材，本层入口调
        `decide_action.build_prompt(req)`——"谁问模型，谁把 req 变成 prompt"，
        拼装只剩这一个调用点，harness 不再有"拼好回填"那一半。

        **唯一会叠加纠正说明的链路**：下一次尝试把上次的失败原因与原始输出
        拼进 prompt（`retry_prompt`），所以重试携带信息增量。
        """
        base_prompt = decide_action_prompt.build_prompt(req)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            prompt = base_prompt if not calls else _retry_prompt(base_prompt, calls)
            return self._brain.choose(prompt=prompt, keys=list(req.space.names))

        result, calls = self._attempt_loop("decide", attempt)
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

        上限（`MAX_SEGMENTS`/`MAX_TIMES`/`MAX_RATIONALE`）也在这里校验——
        它们住在顶层 config，prompt 与校验读同一个常量，不会自相矛盾。

        **改写不留痕、也不上抛**（2026-09-13 删 `normalized`）：规则 1 施加在
        "连按 `a`"这种**本就没有意义的写法**上，改写的结果与模型原意等价——
        报出去只是让 trace 多一个字段、多一处要维护的状态，没有一个消费者。
        对比：**校验失败**（超上限、链体出现非方向键）仍然抛 `ParseFailure`
        ——那是模型真的写错了，必须让它重写。

        **校验失败抛 `ParseFailure`**（本层的内部信号）：它跟"模型幻觉了按键"
        是同一类东西（外部输入不合法），所以由同一个重试循环接住再问一次。
        """
        segments: list[ActionSegment] = []
        for index, segment in enumerate(action.sequence, start=1):
            name, times, rationale = segment.name, segment.times, list(segment.rationale)

            if len(rationale) > MAX_RATIONALE:
                raise _illegal(f"segment {index}: {len(rationale)} rationales > {MAX_RATIONALE}")
            if times > MAX_TIMES:
                raise _illegal(f"segment {index}: times {times} > {MAX_TIMES}")

            if name == INTERACT_KEY and times != 1:
                times = 1

            segments.append(ActionSegment(name=name, times=times, rationale=rationale))

        if len(segments) > MAX_SEGMENTS:
            raise _illegal(f"{len(segments)} segments > {MAX_SEGMENTS}")

        if len(segments) > 1:
            body_bad = [s.name for s in segments[:-1] if s.name not in DIRECTION_KEYS]
            tail = segments[-1].name
            tail_bad = tail not in DIRECTION_KEYS and tail != INTERACT_KEY
            if body_bad or tail_bad:
                raise _illegal(
                    "multi-step sequence may contain only directional keys, "
                    f"plus at most one trailing {INTERACT_KEY!r}"
                )

        return Action(thought=action.thought, sequence=segments)

    # ---- 反思 ----

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """反思：渲染两帧 → 调 `Brain.reflect()` → 用 `Reflection` + 坐标组装 `StepMemory`。

        **本链路不调模型**（`Brain.reflect` 是纯函数），所以**没有重试循环**——
        它没有"失败"这种中间态可重试。

        **`SNAPSHOT_BLIND` 的过滤在这里**（brain 不碰——那是存储策略）：
        记忆里每一项都必须跨步骤成立，`known_objects`/`knowledge` 不成立。
        """
        before = _render_observation(_blind(req.before))
        after = _render_observation(_blind(req.after))
        segment = req.action.sequence[0]

        reflection: Reflection = self._brain.reflect(
            prompt="",
            before=before,
            after=after,
            action_text=req.action.describe(),
            rationale=list(segment.rationale),
        )

        entry = StepMemory(
            before=StepMemory.Observation.model_validate(
                _blind(req.before).model_dump(mode="json")
            ),
            rationale=list(reflection.rationale),
            action=req.action.describe(),
            after=StepMemory.Observation.model_validate(
                _blind(req.after).model_dump(mode="json")
            ),
            step=req.step,
            episode_id=req.episode_id,
        )
        return FromHarnessToBrainToolReflectResp(entry=entry)

    # ---- 判定 ----

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """判定：拼 prompt + 重试循环调 `Brain.judge()`。

        **prompt 在这里拼**（0913 定案）：`judge_success.build_prompt(req)`。
        它可能抛 `KeyError`（模板占位符对不上，编程错误）——**本层不吞**，
        原样上抛：这里没有重试能修好一个拼错的模板。

        `goal`/`history` 按 brain 的约定**独立传一份渲染文本**——判定必须有
        这三块，`Brain.judge()` 的签名是那个约定的具象。两份内容一致（prompt
        里的 `$goal`/`$history` 就是这两样渲的），但**语义不同**：prompt 是
        "怎么判"的规则成品，这两样是"判什么"的素材。

        **重试是原样重问**——判定不像决策那样有"上次错在哪"可用来纠正。
        重试耗尽抛 `MaxRetriesExceeded`，由 harness 的调用点决定怎么收场。
        """
        prompt = judge_success_prompt.build_prompt(req)
        goal = req.goal.goal
        history = [entry.render(reason=False) for entry in req.history]

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.judge(
                prompt=prompt, goal=goal, history=history, images=list(req.images)
            )

        result, calls = self._attempt_loop("judge", attempt)
        return FromHarnessToBrainToolJudgeResp(done=result.done, why=result.why, calls=calls)

    # ---- 校验 ----

    def verify(self, req: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """校验：拼 prompt + 重试循环调 `Brain.verify()`。

        这里把 `entries` 投影成"可对齐的素材"（`StepMemory.render()` 的文本）——
        `verdicts.index` 因此能落回 `req.entries` 的下标。

        **prompt 在这里拼**（0913 定案）：
        `verify_and_summarize.build_verify_prompt(req)`。

        **`include_rationale=False`**：校验看"发生了什么"，**不给决策者的论据**
        ——那是要被校验的对象，先看到就自带偏向。这个选择**显式传给 brain**
        （`BrainPort.verify` 的约定之一），不再只是渲染层的隐式行为。

        **过滤仍归 harness**：本层只把裁决原样带出去。
        """
        prompt = verify_summarize_prompt.build_verify_prompt(req)
        rendered = [entry.render(reason=False) for entry in req.entries]
        images = [_decode(image) for image in req.images]

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.verify(
                prompt=prompt,
                entries=rendered,
                goal=req.goal,
                knowledge=req.knowledge,
                include_rationale=False,
                images=images,
            )

        result, calls = self._attempt_loop("verify", attempt)
        return FromHarnessToBrainToolVerifyResp(verdicts=result.verdicts, calls=calls)

    # ---- 蒸馏 ----

    def summarize(
        self, req: FromHarnessToBrainToolSummarizeReq
    ) -> FromHarnessToBrainToolSummarizeResp:
        """蒸馏：拼 prompt + 重试循环调 `Brain.summarize()` → 用 `EpisodeSummary`
        + harness 元信息组装 `EpisodeMemory`（存储形状的装配在 tool 层）。

        **prompt 在这里拼**（0913 定案）：
        `verify_and_summarize.build_summarize_prompt(req)`。

        `history` 由 `req.entries`（**已过滤的可信记录**）渲成文本传下去，
        **含决策者的论据**（`reason=True`）——蒸馏要总结"为什么这么做"，
        跟 `verify()` 的方向相反。结局（`success`/`steps`/`max_steps`）也一并传：
        蒸馏要评价"这做法值不值得复用"，没有基准就没法评。
        """
        prompt = verify_summarize_prompt.build_summarize_prompt(req)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.summarize(
                prompt=prompt,
                goal=req.goal,
                history=[entry.render(reason=True) for entry in req.entries],
                success=req.success,
                steps=req.steps,
                max_steps=req.max_steps,
                images=list(req.images),
            )

        result, calls = self._attempt_loop("summarize", attempt)
        summary: EpisodeSummary = result.summary
        episode_memory = EpisodeMemory(
            episode_id=req.episode_id,
            run_id=req.run_id,
            goal=req.goal,
            success=req.success,
            steps=req.steps,
            summary=summary.summary,
            reusable_patterns=summary.reusable_patterns,
            critical_decisions=summary.critical_decisions,
            failure_points=summary.failure_points,
            quality_score=summary.quality_score,
            quality_rationale=summary.quality_rationale,
            applicable_scenes=summary.applicable_scenes,
            tags=summary.tags,
            filename=summary.filename,
            markdown=summary.markdown,
        )
        return FromHarnessToBrainToolSummarizeResp(
            summary=summary, episode_memory=episode_memory, calls=calls
        )

    # ---- 规划 ----

    def plan(
        self, req: FromHarnessToBrainToolPlanOnceReq
    ) -> FromHarnessToBrainToolPlanOnceResp:
        """run 级规划：拼 prompt + 重试循环（**原样重问**，无纠正说明）→ 打包整条账。

        **prompt 在这里拼**（0913 定案）：`run_plan.build_prompt(req)`。

        `goal_stack` / `history` 从 req 的素材渲成文本传下去——
        **共用 `tools.prompts.run_plan` 的渲染函数**（`goals_lines` / `history_lines`），
        不另写一份：`run_plan.build_prompt()` 把行拼成整段塞进 prompt，
        这里把同样的行原样交给 `Brain.plan(history=…)`（brain 的约定要求
        "发生过什么"独立成块）。**分两份实现迟早漂移**，所以那层是唯一真源。
        """
        prompt = run_plan_prompt.build_prompt(req)
        goal_stack = run_plan_prompt.goals_lines(req.goals)
        history = run_plan_prompt.history_lines(req.events)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.plan(
                prompt=prompt,
                goal_stack=goal_stack,
                history=history,
                max_push=req.max_push,
            )

        result, calls = self._attempt_loop("plan", attempt)
        return FromHarnessToBrainToolPlanOnceResp(plan=result.plan, calls=calls)


# ---- 内部辅助 ----


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


def _retry_prompt(base_prompt: str, attempts: list[ModelCall]) -> str:
    """在基础 prompt 后追加纠正说明，用于失败重试的下一次尝试。

    **追加、不重新渲染**：`base_prompt` 前缀一个字节不变，多次重试尝试才能
    共享同一段 prompt 缓存。
    """
    last = attempts[-1]
    return decide_action_prompt.retry_prompt(
        decide_action_prompt.RetryPromptReq(
            base_prompt=base_prompt,
            attempt=len(attempts) + 1,
            reason=last.error,
            raw=last.payload.get("raw", "")[:400],
        )
    )


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


def _render_observation(obs) -> str:  # noqa: ANN001
    """把一帧观测渲成文本——brain 的 `Reflection` 要的就是文本。"""
    return obs.render()


def _decode(image: str) -> bytes:
    """把 base64 字符串还原成字节（harness 侧的截图是这个格式）。"""
    import base64

    return base64.b64decode(image)
