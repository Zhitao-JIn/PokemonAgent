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
   ——大脑不知道自己在哪一局、第几步；账上也不替它记尝试序号——"第几次"由账在链上的
   位置回答（0914 跟进删 `attempt`）。
4. **重试循环 + 记账**：六条调模型的链路（`choose`/`plan`/`judge`/`verify`/
   `summarize`/`extract`）走**同一个** `_attempt_loop()`。`reflect` 不调模型，不走循环。

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
现在六条链路一致：重试耗尽就抛，由 harness 决定要不要给保守结果
（要给的话也发生在 `except` 里，trace 上看得见）。

**并组装存储形状**：`reflect` 的 `StepMemory`、`summarize` 的 `EpisodeMemory`、
`extract` 的 `KnowledgeRecord` 都在这层装配——`brain` 与 `memory` 互不认识，
两边形状的搬运只有这里做。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from pokemon_agent.brain import (
    Action,
    ActionSegment,
    BrainPort,
    EpisodeSummary,
    LearnedKnowledge,
    Reflection,
)
from pokemon_agent.brain.errors import AttemptFailed, ParseFailure, ProviderRejected
from pokemon_agent.config import (
    BRAIN_MAX_ATTEMPTS,
    MAX_RATIONALE,
    MAX_SEGMENTS,
    MAX_TIMES,
    MODEL_RETRY_BACKOFF_SECONDS,
)
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolExtractReq,
    FromHarnessToBrainToolExtractResp,
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
from pokemon_agent.schemas.memory import (
    SNAPSHOT_BLIND,
    EpisodeMemory,
    KnowledgeRecord,
    StepMemory,
)
from pokemon_agent.tools.prompts import extract as extract_prompt
from pokemon_agent.tools.prompts import run_plan as run_plan_prompt
from pokemon_agent.tools.prompts import summarize as summarize_prompt
from pokemon_agent.tools.prompts import verify as verify_prompt
from pokemon_agent.world import DIRECTION_KEYS, INTERACT_KEY

from .prompts import decide_action as decide_action_prompt
from .prompts import judge_success as judge_success_prompt

_Result = TypeVar("_Result")


def dedup_snapshots(
    entries: list[StepMemory],
) -> tuple[list[str], list[StepMemory.Observation]]:
    """把一串 `StepMemory` 摊平成 `(before, after, before, after, ...)` 的观测
    序列，去重后**一次遍历、一口气**返回两条严格对齐的列表：截图（base64
    字符串，喂 `VisionDescribeReq.images`）和它们各自对应的 `StepMemory.
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

    **为什么在 tool 层**（0915 起，从 `schemas/memory/step_memory.py` 搬来）：
    "怎么把记忆拼成发给模型的图"是**发请求的组装逻辑**，不是记忆的数据形状
    ——schemas 层只描述记录长什么样，怎么消费它们归 tool（与 prompt 渲染同
    一个归属：五条带图链路的 `images` 都在各 `BrainTool.*()` 入口用本函数拼出）。
    """
    frames: list[str] = []
    snapshots: list[StepMemory.Observation] = []
    for entry in entries:
        for obs, frame in ((entry.before, entry.before_frame), (entry.after, entry.after_frame)):
            if frame is None:
                continue
            if frames and frames[-1] == frame:
                continue
            frames.append(frame)
            snapshots.append(obs)
    return frames, snapshots


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

    # ---- 重试循环（六条链路共用：choose / plan / judge / verify / summarize / extract）----

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
        `retry_prompt`/`base_prompt`：可选——只有 `decide` 这条链路会传。
            **叠不叠纠正说明由账上的 `error_kind` 决定**（0915 分叉，见
            `_retry_prompt`）：解析类失败叠加说明；传输失败原样重问。

        **`ProviderRejected` 立即耗尽**：4xx 是服务端的明确拒绝（密钥/配额/型号），
        重试注定无用——第一轮就抛 `MaxRetriesExceeded`（`attempts=1`），
        不烧预算、不给模型叠"你上一次的输出不合法"那种张冠李戴的纠正。

        **退避是固定的**（`MODEL_RETRY_BACKOFF_SECONDS`，config）：失败后、
        且还有下一轮预算时睡 0.5s 再试——重试预算只有 3 轮，指数拉开兜不住
        多写的两行；最后一轮失败后不睡（后面是上抛，没人等这个间隔）。

        为什么收 `(第几次, 账)` 两个参数：`decide` 要用 "第几次" 渲染纠正说明的
        文案（"第 2 次尝试"），也要用 "账" 取上次的失败原因；其余链路两个都不用。
        收着不用的成本只是一个签名，比给两条链路各写一个循环便宜。

        **两种"账"的翻译在这里**：brain 吐的是 `brain.interface.ModelCall`
        （它自己的方言），本循环收进来的一律转成 `tools.interface.ModelCall`
        （tool 层的工作形状）——"字段恰好一样"是巧合，语义边界是真的。
        **账按序排列**：第 `n` 次尝试的账落在第 `n` 位——"第几次"由位置回答，
        不另盖一枚 `attempt` 戳（0914 跟进删）。
        """
        calls: list[ModelCall] = []
        for nth in range(1, BRAIN_MAX_ATTEMPTS + 1):
            try:
                result = attempt(nth, calls)
            except AttemptFailed as exc:
                call = _adopt(exc.call)
                calls.append(call)
                if call.error_kind == ProviderRejected.__name__:
                    # 4xx：重试注定无用，立即耗尽（attempts=1）。
                    raise MaxRetriesExceeded(
                        len(calls), _last_error(calls), calls, source=source
                    ) from exc
                if nth < BRAIN_MAX_ATTEMPTS:
                    time.sleep(MODEL_RETRY_BACKOFF_SECONDS)
                continue

            calls.extend(_adopt(call) for call in result.calls)
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

        **唯一会带"上一次失败"信息的链路**：解析类失败（`ParseFailure` 族）的
        下一次尝试把上次的失败原因与原始输出拼进 prompt（`retry_prompt`），
        重试携带信息增量；**传输失败原样重问**——模型根本没收到题，没什么可
        "纠正"的（0915 分叉，取代无条件叠加）。
        """
        base_prompt = decide_action_prompt.build_prompt(req)
        # **images 在这里拼**（与 prompt 同一个归属："谁问模型，谁把 req 变成
        # 请求"），素材**不另开通道**：就是 `$memories` 段落拼装出来的那批帧
        # ——`dedup_snapshots()` 与 `render_sequence()` 是同一件事的图片版/
        # 文字版（相邻去重、逐帧对应），prompt 里读到的每一步和模型看到的
        # 画面严格同源。第一步没有记忆 → 空列表 → 纯文本。
        images, _snapshots = dedup_snapshots(req.memories)

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            prompt = base_prompt if not calls else _retry_prompt(base_prompt, calls)
            return self._brain.choose(prompt=prompt, keys=list(req.space.names), images=images)

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
            after=StepMemory.Observation.model_validate(_blind(req.after).model_dump(mode="json")),
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

        **images 也在这里拼**（0915 130 收权，与 choose 同一个归属："谁问模型，
        谁把 req 变成请求"）：harness 只装素材（history），`dedup_snapshots(req.history)`
        与 `$history` 段的 `render_sequence()` 是同一件事的图片版/文字版——
        prompt 里读到的每一步和模型看到的画面逐帧同源。

        **重试是原样重问**——判定不像决策那样有"上次错在哪"可用来纠正。
        重试耗尽抛 `MaxRetriesExceeded`，由 harness 的调用点决定怎么收场。
        """
        prompt = judge_success_prompt.build_prompt(req)
        goal = req.goal.goal
        history = [entry.render(reason=False) for entry in req.history]
        images, _snapshots = dedup_snapshots(list(req.history))

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.judge(prompt=prompt, goal=goal, history=history, images=images)

        result, calls = self._attempt_loop("judge", attempt)
        return FromHarnessToBrainToolJudgeResp(done=result.done, why=result.why, calls=calls)

    # ---- 校验 ----

    def verify(self, req: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """校验：拼 prompt + 重试循环调 `Brain.verify()`。

        这里把 `entries` 投影成"可对齐的素材"（`StepMemory.render()` 的文本）——
        `verdicts.index` 因此能落回 `req.entries` 的下标。

        **prompt 在这里拼**（0913 定案）：`verify.build_prompt(req)`。

        **`include_rationale=False`**：校验看"发生了什么"，**不给决策者的论据**
        ——那是要被校验的对象，先看到就自带偏向。这个选择**显式传给 brain**
        （`BrainPort.verify` 的约定之一），不再只是渲染层的隐式行为。

        **过滤仍归 harness**：本层只把裁决原样带出去。
        """
        prompt = verify_prompt.build_prompt(req)
        rendered = [entry.render(reason=False) for entry in req.entries]
        # **images 在这里拼**（0915 130 收权，与 judge/choose 同归属）：
        # harness 只装素材（entries），去重帧由本层对同一批 entries 取——
        # 与 prompt 的 `$entries` 渲染同源。此前 `req.images` 由 harness 节点
        # 拼好递进来（外加一段"原样透传不解码"的 0913 化石注释，那是一次
        # base64/bytes 迁移留下的坑，已随字段删除）。
        images, _snapshots = dedup_snapshots(list(req.entries))

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

        **这里是 `EpisodeMemory` 两个来源的分界**：`result.summary`
        （`EpisodeSummary`）是**派生正文**——LLM 从 `req.entries` 蒸出来的；
        `req` 上那五个字段（`episode_id` / `run_id` / `goal` / `success` / `steps`）
        是**来源章**——harness 从 run state 给的。大脑不知道自己在哪一局，
        也没资格判定自己成没成，所以这五个字段只能在这里照抄、不能由它产出。

        **prompt 在这里拼**（0913 定案）：`summarize.build_prompt(req)`。

        `history` 由 `req.entries`（**已过滤的可信记录**）渲成文本传下去，
        **含决策者的论据**（`reason=True`）——蒸馏要总结"为什么这么做"，
        跟 `verify()` 的方向相反。结局（`success`/`steps`/`max_steps`）也一并传：
        蒸馏要评价"这做法值不值得复用"，没有基准就没法评。
        """
        prompt = summarize_prompt.build_prompt(req)
        # **images 在这里拼**（0915 130 收权，与 verify 同一批 entries、同一套去重）
        images, _snapshots = dedup_snapshots(list(req.entries))

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.summarize(
                prompt=prompt,
                goal=req.goal,
                history=[entry.render(reason=True) for entry in req.entries],
                success=req.success,
                steps=req.steps,
                max_steps=req.max_steps,
                images=images,
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
            markdown=summary.markdown,
        )
        return FromHarnessToBrainToolSummarizeResp(
            summary=summary, episode_memory=episode_memory, calls=calls
        )

    # ---- 世界知识抽取 ----

    def extract(self, req: FromHarnessToBrainToolExtractReq) -> FromHarnessToBrainToolExtractResp:
        """抽取：拼 prompt + 重试循环调 `Brain.extract()` → 组装 `KnowledgeRecord`。

        **和 `summarize()` 逐字同形、产物不同**：那边把 `EpisodeSummary` 装成
        `EpisodeMemory`（属于那一局），这边把 `LearnedKnowledge` 装成
        `KnowledgeRecord`（属于世界）。**来源章都是在这一层盖的**——大脑不知道
        自己在哪一局，`run_id`/`episode_id` 只有这里两边都认。

        **`source` 拼成 `{run_id}/{episode_id}`**：知识库那个家族里已经有手工
        写的先验（metadata 的 `source` 是文件名），两种来源必须在 metadata 上
        分得开——将来要"只保留 run 产出的"或"只看人工先验"时才读得出来。
        正文里不带来源（`KnowledgeRecord.render()` 只回 `text`）：读者关心
        这个世界的规则，不关心它是哪一局读到的。

        **prompt 在这里拼**（同其余五条链路）：`extract.build_prompt(req)`。

        `history` 由 `req.entries`（**已过滤的可信记录**）渲成文本传下去，
        含决策者的论据（`reason=True`）——跟 `summarize()` 同一个选择：
        "为什么这么做"里常藏着"这个世界怎么回事"，裁掉会让抽取漏掉一部分。

        **零条也是成功**：`resp.records == []` 是常态，不是失败。失败只有
        重试耗尽抛 `MaxRetriesExceeded`（`source="extract"`）。
        """
        prompt = extract_prompt.build_prompt(req)
        # **images 在这里拼**（0915 130 收权，与 verify/summarize 同一批 entries）
        images, _snapshots = dedup_snapshots(list(req.entries))

        def attempt(nth: int, calls: list[ModelCall]) -> object:
            return self._brain.extract(
                prompt=prompt,
                goal=req.goal,
                history=[entry.render(reason=True) for entry in req.entries],
                images=images,
            )

        result, calls = self._attempt_loop("extract", attempt)
        knowledge: LearnedKnowledge = result.knowledge
        source = f"{req.run_id}/{req.episode_id}"
        records = [
            KnowledgeRecord(
                topic=item.topic,
                text=item.content,
                source=source,
                run_id=req.run_id,
                episode_id=req.episode_id,
            )
            for item in knowledge.items
        ]
        return FromHarnessToBrainToolExtractResp(records=records, calls=calls)

    # ---- 规划 ----

    def plan(self, req: FromHarnessToBrainToolPlanOnceReq) -> FromHarnessToBrainToolPlanOnceResp:
        """run 级规划：拼 prompt + 重试循环（**原样重问**，无纠正说明）→ 打包整条账。

        **prompt 在这里拼**（0913 定案）：`run_plan.build_prompt(req)`。

        `goal_stack` / `history` 从 req 的素材渲成文本传下去——
        **共用 `tools.prompts.run_plan` 的渲染函数**（`goals_lines` / `history_blocks`），
        不另写一份：`run_plan.build_prompt()` 把行拼成整段塞进 prompt，
        这里把同样的行原样交给 `Brain.plan(history=…)`（brain 的约定要求
        "发生过什么"独立成块）。**分两份实现迟早漂移**，所以那层是唯一真源。

        **两个参数名是 brain 的契约，装的东西已经换过**（0914 S2）：`goal_stack`
        现在装的是**目标表的行**（表序 = 派发顺序，带状态），`history` 装的是
        **记忆折出来的块**（局索引 + 详情 + 地图事实），不再是 trace 折的"每局一行"。
        brain 侧签名一字未动——它收下的就是"已经渲染好的文本序列"，
        渲染从哪来是调用方的事（这正是铁律 2 要的形状）。
        """
        prompt = run_plan_prompt.build_prompt(req)
        goal_stack = run_plan_prompt.goals_lines(req.plan)
        history = run_plan_prompt.history_blocks(req)

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
    """按**上一次失败的类型**决定重问的 prompt（0915 分叉，取代"无条件叠加"）。

    - **解析类失败**（`ParseFailure`/`IllegalAction`/`OutputTruncated`）→ 追加
      纠正说明：模型调通了、也看到了题，是它的输出不能用——告诉它上次错在哪。
    - **传输失败**（`ToolTimeout` 等）→ **原样重问**：模型根本没收到题，
      "你上一次的输出不合法 / 别再输出同样的东西"是张冠李戴——传输失败时
      `$raw` 是空的，却劝模型改掉本来的答案。
    - `ProviderRejected` 不会走到这里（循环在第一轮就耗尽了）。

    **追加、不重新渲染**：`base_prompt` 前缀一个字节不变，多次重试尝试才能
    共享同一段 prompt 缓存。
    """
    last = attempts[-1]
    if last.error_kind not in _PARSE_ERROR_KINDS:
        return base_prompt
    return decide_action_prompt.retry_prompt(
        decide_action_prompt.RetryPromptReq(
            base_prompt=base_prompt,
            attempt=len(attempts) + 1,
            reason=last.error,
            raw=last.payload.get("raw", "")[:400],
        )
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


def _render_observation(obs) -> str:  # noqa: ANN001
    """把一帧观测渲成文本——brain 的 `Reflection` 要的就是文本。"""
    return obs.render()
