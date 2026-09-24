"""Brain —— **一切需要 LLM 才能回答的问题，都在这个类里。**

它不是"一个模型"，是**一组互不通气的模型技能**的容器：

    choose     看着当前画面和可用动作，问一次模型选下一步  decide_llm
    judge      看着当前画面和目标，判达成没达成（三层共用）  judge_llm
    reflect    把这一键整理成一条可检索的经验            （本版无模型调用）
    verify     给下级记忆逐条标正 / 负样本               verify_llm（缺省同 judge_llm）
    summarize  用正负两组当参考蒸馏成一条上级记忆         verify_llm（缺省同 judge_llm）
    plan       看 run 级历史 + 目标表，问一次模型该推什么目标 / 改哪行  plan_llm
    decompose  把 episode 目标拆成只靠观测 + 固定动作空间可完成的 task 链  plan_llm

**六个调模型的方法都是「问一次」的语义，没有一个内部重试。** 失败时**一律抛
`AttemptFailed` 家族**（`DecisionAttemptFailed` / `PlanAttemptFailed` /
`DecomposeAttemptFailed` / `JudgeAttemptFailed` / `VerifyAttemptFailed` /
`SummarizeAttemptFailed`），
异常携带这一次尝试的 `ModelCall`。重试循环住 `tools/brain_tool.py`，
预算住 `pokemon_agent/config.py`——**大脑不知道"问几次"这件事**。

由此跟着两条推论：

- **没有"降级"这回事**。`judge` 曾把调用失败吞成 `done=False`、`verify` 吞成
  "全部标负"、`summarize` 吞成 `summary=None`——那是把"这条链路坏了"
  伪装成"业务结论就是如此"，在 trace 里表现为成功率悄悄变 0 而失败原因看不见。
  现在它们照抛，兜底由调用方的重试预算决定。
- **`attempt` 字段不由大脑盖**。它属于"这是第几次尝试"，只有循环控制者知道。

**它不写 trace，也不知道自己在哪一局。** 七个方法（含不调模型的
`reflect`）都不收 `step`/`episode_id`/
`run_id`——构造函数里也没有 `TracePort`——账跟着结果交给调用方。
规则只有一句：**谁控制循环，谁记账。**

**`choose` 和 `judge` 必须分开。** 让做决策的模型顺便回答"我成功了吗"是误差同源：
它读错画面 → 以为达成了 → 判成功，错得越离谱数字越好看。隔离靠两条硬约束维持：
`judge()` 看得到最近几步**发生了什么**，但拿不到决策者对那几步的任何说辞；
`judge_llm` 是**另一个 provider 实例**，哪怕型号相同。

**`verify` 和 `summarize` 分开**（曾合并为一次调用，理由是省一次模型往返）。
拆开的取舍：两次调用、两次记账，换来的是"校验失败不必然导致摘要拿不到"——
调用方可以自己决定"校验不可靠时还蒸不蒸"。

**无状态**（铁律 1）：没有任何跨步骤的实例变量，构造函数存的是不可变的协作者；
连续两次用相同参数调 `choose()`，行为必须完全一致。只认识 Protocol（铁律 2）。

**只收裸字段、只吐自己的方言。** 入参里没有本项目任何模块的类型（`Observation`/
`ActMemory`/`ActionSpace` 都不认识）——那些在进这里之前就被调用方渲染成文本了，
或者被拆成裸字段（`keys`/`images`）。返回值是 brain 自己的形状，谁要用谁转换。

完整论证——为什么这仍不是独立真值——见 `docs/spec/brain/SPEC.md`。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import ValidationError

from pokemon_agent.brain.errors import (
    DecisionAttemptFailed,
    DecomposeAttemptFailed,
    IllegalAction,
    JudgeAttemptFailed,
    OutputTruncated,
    ParseFailure,
    PlanAttemptFailed,
    SummarizeAttemptFailed,
    VerifyAttemptFailed,
)
from pokemon_agent.brain.interface import JudgeProvider, LLMProvider
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq

from .interface import (
    Action,
    ActionSegment,
    ChooseResult,
    DecomposeResult,
    Decomposition,
    EpisodeSummary,
    JudgeResult,
    ModelCall,
    PlanResult,
    Reflection,
    RunPlan,
    SummarizeResult,
    VerifyResult,
    VerifyVerdict,
)


def _strip_json_fence(text: str) -> str:
    """剥掉模型常见的 ```json 代码围栏；没有围栏则原样返回。

    模型给 JSON 包 markdown 围栏是最常见的格式偏差（brain 的决策/判定与
    run 级 plan 都实测遇到过）。只处理最外层围栏，不做任何内容修复——
    内容坏了应该让解析失败走重试，而不是在这里猜着改。
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1].removeprefix("json").strip()
    return stripped


class Brain:
    """`BrainPort` 的唯一实现。"""

    def __init__(
        self,
        decide_llm: LLMProvider | None = None,
        judge_llm: JudgeProvider | None = None,
        verify_llm: JudgeProvider | None = None,
        plan_llm: LLMProvider | None = None,
    ) -> None:
        """依赖全部注入，类型标成接口而非实现（CLAUDE.md 第三节第 3 条）。

        **四个 provider 都可以缺省（0922 184）**：按需装配——某层 runtime 只用
        brain 的一部分能力时（run 层只用 `plan`），用不到的 provider 可以不传；
        对应方法入口的 assert 会把"没配就调"当场拦下（构造前置弱化的另一半，
        assert 是它唯一的执行者）。

        `judge_llm` 单独一个参数、哪怕和 `decide_llm` 同型号：换判定模型时只改装配处，
        manifest 里两条链路也才看得出是可以分别选型的。

        `verify_llm`：step 校验 / 蒸馏（`verify`/`summarize`）用的模型，单独一个参数——
        跟 `judge_llm` 同理，哪怕型号相同也不共用同一个 provider 实例，manifest
        才看得出这条链路可以单独换型号/调参。缺省（`None`）回退到 `judge_llm`：
        两者都是"独立判定"性质，不传时沿用旧行为（复用同一个判定模型）。

        `plan_llm`：run 级规划（`plan`）用的模型，同样单独一个参数、
        缺省回退到 `judge_llm`——跟 `verify_llm` 同理：规划和判定都不是"决策"，
        分组更接近，装配处（`build.py`）实际也一直把这条链路的模型跟
        judge/verify 放在同一个供应商（火山方舟）下。类型是纯 `LLMProvider`
        （不是 `JudgeProvider`）：`plan` 是纯文本链，只用 `complete()` 一个方法
        （0915 129 定案：规划不带图）。

        `judge_llm`/`verify_llm` 的类型是 `JudgeProvider`（brain 自己的协议：
        `complete()` + `describe()`），不是纯 `LLMProvider`——`judge()`/`verify()`/
        `summarize()` 带得到截图时会走 `describe()` 问一次多模态，一张图都
        凑不齐时才退化成 `complete()`。`decide_llm` 也一样：类型虽是纯
        `LLMProvider`，`choose()` 会查 provider 实例上的 `multimodal` 布尔
        （`_OpenAICompatibleBase` 都带）——为真且有图走 `describe()`，
        否则纯文本。**转发表在 brain 这一层**，provider 的 `complete()`
        不收图、不内部分叉。
        **这份视觉能力来自 brain 自己持有的实例**（`QwenProvider`/`ArkProvider`
        都继承 `_MultimodalMixin`），不借 `world` 的任何协议。

        **没有 `max_retries`**——决策重试的预算和循环都在调用方
        （`BRAIN_MAX_ATTEMPTS`，见 `pokemon_agent/config.py`），大脑不知道
        "问几次"这件事，只知道"问一次"。

        存下四个 provider，此后不再变——prompt 全部由调用方拼好递进来。
        """
        self._decide = decide_llm
        self._judge_llm = judge_llm
        self._verify_llm = verify_llm or judge_llm
        self._plan_llm = plan_llm or judge_llm
        # `decide_action.md`/`judge_success.md`/`verify.md`/`run_plan.md`
        # 完全不在这里——六个方法都只接收调用方已经拼好的 prompt
        # 字符串，`Brain` 不知道 `pokemon_agent.prompts` 这个包的存在，谁调用
        # 它、prompt 从哪来，`Brain` 不关心。

    # ---- 决策 ----

    def choose(
        self,
        *,
        prompt: str,
        keys: Sequence[str],
        images: Sequence[str] = (),
    ) -> ChooseResult:
        """一次决策尝试：问一次模型、解析。**不重试**——重试是调用方的循环。

        **只认 `prompt` + `images`**：动作空间说明、目标栈、已知事实、记忆、
        领域知识、人类插话，以及"怎么选"的全部规则，全部由调用方拼好
        （`pokemon_agent.tools.prompts.decide_action.build_prompt()`）；图也由
        调用方（tool 层）拼好递进来。

        **转发表在这里、不在 provider 里**（0915 129）：入参带了图、且当前
        决策模型的 `multimodal` 标志为真 → 走 `describe()`（与 judge 同一条
        多模态发送路，floor 丢图检测照过）；两者缺一 → 退化纯文本
        `complete()`。`LlmCompleteReq` 是纯文本信封，provider 不内部分叉。

        后置条件：成功时返回的 `ChooseResult.action` 的每个 `name` 都在
        `keys` 内；`calls` 恰好这一次尝试的一条账（多次尝试的累积由调用方的
        重试循环做）；**动作里不含任何被调用方改写过的字段**——"这个键在
        当前世界里连按几次才有意义"是世界语义，不归大脑管。
        失败：模型调不通 / 解析不出来 / 选了不存在的键 / 被截断，都抛
        `DecisionAttemptFailed`（附这次的账）——**"要不要再问一次"交给调用方**。

        步骤 1：调模型。
        步骤 2：解析，失败就把账封进异常抛出去；成功就打包成 `ChooseResult` 交回去。
        """
        assert self._decide is not None, (
            "choose() 需要一个 decide provider——这次装配没给它（按需装配）"
        )
        # 步骤 1：调模型。**调不通也是"这一次失败"**，转成 AttemptFailed
        # 跟解析失败走同一个出口——调用方只需要 `except DecisionAttemptFailed` 一处。
        with_vision = bool(images) and bool(getattr(self._decide, "multimodal", False))
        # `sent_images` = **真发给模型的图**（发给什么存什么）：转发表退化成
        # 纯文本时为空列表，账上的 `images` 因此如实反映模型收到的东西。
        sent_images = list(images) if with_vision else []
        try:
            if sent_images:
                text, n_in, n_out, n_cached, n_reason = self._ask(self._decide, prompt, sent_images)
                # `describe()` 的响应不带截断标记——按未截断处理（该链路的
                # 截断风险在纯文本补全那条路上，多模态描述输出很短）。
                truncated = False
            else:
                completion = self._decide.complete(LlmCompleteReq(prompt=prompt))
                text, n_in, n_out, n_cached, n_reason = (
                    completion.text,
                    completion.prompt_tokens,
                    completion.completion_tokens,
                    completion.cached_tokens,
                    completion.reasoning_tokens,
                )
                truncated = completion.truncated
        except Exception as exc:  # noqa: BLE001
            call = ModelCall(
                payload={"ok": "false", "prompt": prompt, "images": sent_images},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            )
            raise DecisionAttemptFailed(call) from exc

        # 步骤 2：解析。
        parsed: Action | None = None
        kind = reason = ""
        try:
            # 截断要**先于**解析检查，否则它会伪装成"少了个右括号"的 ParseFailure。
            if truncated:
                raise OutputTruncated(n_out)
            parsed = self._parse(text, keys)
        except (ParseFailure, IllegalAction, OutputTruncated) as exc:
            kind, reason = type(exc).__name__, str(exc)
        except ValidationError as exc:
            # `ValidationError` **不是** `AgentError` 的子类，不带上会让这次
            # 尝试之外的异常穿透。正常走不到（`_parse` 已经验过），但那套校验
            # 写了两遍且没有机制保证同步——兜住，退化成一次可统计的解析失败。
            kind, reason = "ParseFailure", f"Action 字段不合法：{exc.errors()[:1]}"

        # 一次模型调用 = 一条账，成功失败都留：失败的那次同样烧了 token，
        # 而 `raw` 让改进解析器之后能离线重算，不必再花钱重跑。
        call = ModelCall(
            payload={
                "input_tokens": str(n_in),
                "output_tokens": str(n_out),
                "cached_tokens": str(n_cached),
                "reasoning_tokens": str(n_reason),
                "ok": str(parsed is not None).lower(),
                "raw": text,
                "prompt": prompt,
                # 发给什么存什么：模型真收到图的账里才有图（转发表退化成
                # 纯文本时为空列表——"带了图但没发出去"在这条账上看得见）
                "images": sent_images,
            },
            error_kind=kind,
            error=reason,
        )
        if parsed is None:
            raise DecisionAttemptFailed(call)

        # 出口断言（postcondition）：大脑不会产出空动作或调用方没给的按键。
        # `_parse` 已逐段校验过，这里是运行时全覆盖的兜底证明。
        assert parsed.sequence, "choose() returned an action with an empty sequence"
        assert all(seg.name in keys for seg in parsed.sequence), (
            f"brain chose key outside {list(keys)}"
        )
        return ChooseResult(action=parsed, calls=[call])

    # ---- 规划（run 级）----

    def plan(
        self,
        *,
        prompt: str,
        goal_stack: Sequence[str],
        history: Sequence[str],
        max_push: int,
    ) -> PlanResult:
        """一次 run 级规划尝试：问一次模型、解析。**不重试**——重试是调用方
        的循环，跟 `choose()` 同一个分工。

        **四块素材：`goal_stack` / `history` / `max_push` / `prompt`**——
        规划必须有它们，签名是那个约定的具象（见 `BrainPort.plan`）。
        本方法**不消费**前三块：它们已经由调用方渲进 `prompt` 了，
        这里收下只为让"规划要什么"在接口上立得住。

        **纯文本链**（0915 129 定案）：规划不带图——run 级判断的依据是局索引、
        详情正文与目标表，一帧"现在屏幕在哪"帮不上忙，只会白烧图费。
        账上的 `images` 恒为空列表（账形与其余链路统一）。

        失败：模型调不通 / 解析不出 `RunPlan`，都抛 `PlanAttemptFailed`（附这次的账）。

        步骤 1：调模型（`plan_llm`，纯文本）。
        步骤 2：解析，失败就把账封进异常抛出去；成功就打包成 `PlanResult` 交回去。
        """
        assert self._plan_llm is not None, (
            "plan() 需要一个 plan provider——这次装配没给它（按需装配）"
        )
        # 步骤 1：调模型。
        try:
            completion = self._plan_llm.complete(LlmCompleteReq(prompt=prompt))
        except Exception as exc:  # noqa: BLE001  调不通也是"这一次失败"
            call = ModelCall(
                payload={"ok": "false", "prompt": prompt, "images": []},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            )
            raise PlanAttemptFailed(call) from exc

        # 步骤 2：解析。
        parsed: RunPlan | None = None
        kind = reason = ""
        try:
            parsed = self._parse_plan(completion.text)
        except ParseFailure as exc:
            kind, reason = type(exc).__name__, str(exc)

        # 一次模型调用 = 一条账，成功失败都留：失败的那次同样烧了 token。
        call = ModelCall(
            payload={
                "input_tokens": str(completion.prompt_tokens),
                "output_tokens": str(completion.completion_tokens),
                "cached_tokens": str(completion.cached_tokens),
                "reasoning_tokens": str(completion.reasoning_tokens),
                "ok": str(parsed is not None).lower(),
                "raw": completion.text,
                "prompt": prompt,
                # 规划链纯文本（见 docstring），账形与其余链路统一
                "images": [],
            },
            error_kind=kind,
            error=reason,
        )
        if parsed is None:
            raise PlanAttemptFailed(call)

        return PlanResult(plan=parsed, calls=[call])

    def decompose(
        self,
        *,
        prompt: str,
        goal: str,
        context: Sequence[str],
        max_tasks: int,
    ) -> DecomposeResult:
        """一次 episode 级拆解尝试：问一次模型、解析成 `Decomposition`。**不重试**。

        素材（`goal`/`context`/`max_tasks`）已由调用方渲进 `prompt`，这里收下只为
        让"拆解要什么"在接口上立得住。纯文本链，走 `plan_llm`。

        失败：模型调不通 / 解析不出 `Decomposition`，都抛 `DecomposeAttemptFailed`。

        步骤 1：调模型。
        步骤 2：解析，失败封账抛出；成功打包成 `DecomposeResult`。
        """
        assert self._plan_llm is not None, (
            "decompose() 需要一个 plan provider——这次装配没给它（按需装配）"
        )
        assert max_tasks > 0, "decompose() got a non-positive max_tasks"
        # 步骤 1：调模型。
        try:
            completion = self._plan_llm.complete(LlmCompleteReq(prompt=prompt))
        except Exception as exc:  # noqa: BLE001  调不通也是"这一次失败"
            call = ModelCall(
                payload={"ok": "false", "prompt": prompt, "images": []},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            )
            raise DecomposeAttemptFailed(call) from exc

        # 步骤 2：解析。
        parsed: Decomposition | None = None
        kind = reason = ""
        try:
            parsed = self._parse_decomposition(completion.text)
        except ParseFailure as exc:
            kind, reason = type(exc).__name__, str(exc)
        call = ModelCall(
            payload={
                "input_tokens": str(completion.prompt_tokens),
                "output_tokens": str(completion.completion_tokens),
                "cached_tokens": str(completion.cached_tokens),
                "reasoning_tokens": str(completion.reasoning_tokens),
                "ok": str(parsed is not None).lower(),
                "raw": completion.text,
                "prompt": prompt,
                "images": [],
            },
            error_kind=kind,
            error=reason,
        )
        if parsed is None:
            raise DecomposeAttemptFailed(call)
        return DecomposeResult(decomposition=parsed, calls=[call])

    @staticmethod
    def _parse_decomposition(text: str) -> Decomposition:
        """把拆解模型的原始文本解析成 `Decomposition`；失败抛 `ParseFailure`。"""
        stripped = _strip_json_fence(text)
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ParseFailure(text, f"not valid json ({exc.msg})") from exc
        if not isinstance(raw, dict):
            raise ParseFailure(text, "top level is not an object")
        try:
            return Decomposition.model_validate(raw)
        except ValidationError as exc:
            raise ParseFailure(text, f"Decomposition 字段不合法：{exc.errors()[:1]}") from exc

    # ---- 判定 ----

    def judge(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        images: Sequence[str] = (),
    ) -> JudgeResult:
        """一次判定尝试：问一次模型、解析裁决。**不重试**——重试是调用方的循环。

        **三块素材：`goal` / `history` / `prompt`**——判定必须有它们，签名是
        那个约定的具象（见 `BrainPort.judge` 的说明）。本方法**不消费
        `goal`/`history`**：它们已经由调用方渲进 `prompt` 了，这里收下只为
        让"判定要什么"在接口上立得住。收下不读是有意的——将来判定链路要
        独立演进（比如按 `history` 长度决定要不要带图），改这一处就够。

        后置条件：成功时 `calls` 恰好一条（这次尝试自己的账）。
        失败：模型调不通、输出不是合法裁决，都抛 `JudgeAttemptFailed`
        （附这次的账）——**"要不要再问一次"交给调用方**。

        步骤 1：调模型（有图走 `describe()`，无图退化成 `complete()`）。
        步骤 2：解析裁决，失败就把账封进异常抛出去；成功就打包成 `JudgeResult`。
        """
        assert self._judge_llm is not None, (
            "judge() 需要一个 judge provider——这次装配没给它（按需装配）"
        )
        # 步骤 1：调模型。**异常也留账**——调不通的那次没烧 token，
        # 但"这次为什么不成立"必须是可统计的，所以补一条只有错误信息的账。
        text = n_in = n_out = n_cached = n_reason = ""
        kind = ""
        try:
            text, n_in, n_out, n_cached, n_reason = self._ask(self._judge_llm, prompt, images)
        except Exception as exc:  # noqa: BLE001  调不通也是"这一次失败"，转成 AttemptFailed
            kind = type(exc).__name__
            call = ModelCall(
                payload={"ok": "false", "prompt": prompt, "images": list(images)},
                error_kind=kind,
                error=f"{exc}",
            )
            raise JudgeAttemptFailed(call) from exc

        # 步骤 2：解析裁决。
        done, why, kind = self._parse_verdict(text)

        call = ModelCall(
            payload={
                "input_tokens": str(n_in),
                "output_tokens": str(n_out),
                "cached_tokens": str(n_cached),
                "reasoning_tokens": str(n_reason),
                "raw": text,
                "ok": str(not kind).lower(),
                "prompt": prompt,
                # 带没带图、带了哪几张，直接看 `images`——发给什么存什么，
                # "这次判错是没带图还是带了图也判错"从此可分。
                "images": list(images),
            },
            error_kind=kind,
            error=why if kind else "",
        )
        if kind:
            raise JudgeAttemptFailed(call)

        return JudgeResult(done=done, why=why, calls=[call])

    @staticmethod
    def _ask(
        provider: JudgeProvider | LLMProvider, prompt: str, images: Sequence[str]
    ) -> tuple[str, int, int, int, int]:
        """问一次：`images` 非空就带图问（`describe()`），空的话退化成
        纯文本（`complete()`）——一张便利副本缺失不该让整条判定链路直接失败，
        降级成纯文本判定总比抛异常/硬编一个失败结果强。

        **调用方要保证**：`images` 非空时 `provider` 真的有 `describe()`——
        `judge`/`verify`/`summarize` 的 provider 类型就带；`choose`
        的 `decide_llm` 只有 `multimodal` 标志为真才会带图进来（0915 129）。
        类型联合只是把"两个位置都可能传"写出来，运行时分派靠的是这条前置条件。

        **`images` 是 base64 字符串不是原始 bytes**：直接进
        `VisionDescribeReq.images`（`list[str]`，见
        `brain/schemas/vision.py`）——调用方（`tools/brain_tool.py`）从
        harness 的截图拿到什么就传什么，不做编解码。类型写成 `bytes` 曾是
        一处**说谎的注解**：运行时值是字符串，谁照着注解去 `b64decode`
        一步就会在构造请求时炸（0913 真机核对实测，见 CHANGELOG）。

        两种 provider 返回的字段名不一样（`LlmCompleteResp.prompt_tokens`/
        `completion_tokens` vs `VisionDescribeResp.input_tokens`/
        `output_tokens`，`cached_tokens` 字段名倒是两边一致）——这里统一抹平成
        `(text, 输入 token, 输出 token, 命中缓存 token, 思考 token)` 五元组，
        `judge()`/`verify()`/`summarize()`/`choose()` 都不用关心这次走的是哪条路。
        """
        if images:
            resp = provider.describe(VisionDescribeReq(images=list(images), prompt=prompt))
            return (
                resp.text,
                resp.input_tokens,
                resp.output_tokens,
                resp.cached_tokens,
                resp.reasoning_tokens,
            )
        completion = provider.complete(LlmCompleteReq(prompt=prompt))
        return (
            completion.text,
            completion.prompt_tokens,
            completion.completion_tokens,
            completion.cached_tokens,
            completion.reasoning_tokens,
        )

    @staticmethod
    def _parse_verdict(text: str) -> tuple[bool, str, str]:
        """解析成 `(done, why, 失败类型)`，第三项为空串表示解析成功。"""
        stripped = _strip_json_fence(text)
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            return False, f"判定输出不是合法 JSON：{text!r}", "ParseFailure"

        if not isinstance(raw, dict) or not isinstance(raw.get("done"), bool):
            return False, f"判定输出缺少布尔 done：{text!r}", "ParseFailure"

        why = raw.get("why")
        return bool(raw["done"]), str(why) if why else "（未说明）", ""

    # ---- step 记忆校验（独立判定器）----

    def verify(
        self,
        *,
        prompt: str,
        entries: Sequence[str],
        goal: str,
        knowledge: str,
        images: Sequence[str] = (),
    ) -> VerifyResult:
        """一次校验尝试：问一次模型、解析逐条裁决。**不重试**——重试是调用方的循环。

        校验的动机：step 记忆是模型自述（`reflect` 拼的 before/action/after），
        没有验证——直接当事实喂蒸馏，错误操作会被蒸馏成经验并跨局传播。

        **四块素材：`entries` / `goal` / `knowledge` /
        `prompt`**（见 `BrainPort.verify`）。本方法只**消费 `entries`**
        （数它的长度：`verdicts` 要跟它等长对齐）——其余三块收下不读，
        同样因为素材已由调用方渲进 `prompt`，签名立的是约定。

        **过滤不在这里**——本方法只判，谁想用可信的那部分自己筛。

        后置条件：成功时 `verdicts` 与 `entries` **等长**且按 `index` 顺序；
        `calls` 恰好一条。
        失败：模型调不通、输出解析不出，都抛 `VerifyAttemptFailed`（附这次的账）。

        **解析不出时会「全部标不可靠」还是抛**：抛。以前的保守兜底
        （解析失败→全部标不可靠）与"这一局记忆确实都不可信"在结果上无法区分，
        静默吞掉了"校验器坏了"这个事实。现在兜底的责任在调用方的重试预算里。
        """
        count = len(entries)

        assert self._verify_llm is not None, (
            "verify() 需要一个 verify provider——这次装配没给它（按需装配）"
        )
        # 步骤 1：调模型。
        try:
            text, n_in, n_out, n_cached, n_reason = self._ask(self._verify_llm, prompt, images)
        except Exception as exc:  # noqa: BLE001  调不通也是"这一次失败"
            call = ModelCall(
                payload={"ok": "false", "prompt": prompt, "images": list(images)},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            )
            raise VerifyAttemptFailed(call) from exc

        # 步骤 2：解析。**解析失败也走异常**——`_parse_verify` 仍返回补齐的列表，
        # 但"有没有解析成功"由它另给的标志决定，没成功就把账封进异常。
        verdicts, parse_kind, parse_reason = self._parse_verify(text, count)

        call = ModelCall(
            payload={
                "input_tokens": str(n_in),
                "output_tokens": str(n_out),
                "cached_tokens": str(n_cached),
                "reasoning_tokens": str(n_reason),
                "raw": text,
                "ok": str(not parse_kind).lower(),
                "prompt": prompt,
                "images": list(images),
            },
            error_kind=parse_kind,
            error=parse_reason,
        )
        if parse_kind:
            raise VerifyAttemptFailed(call)

        return VerifyResult(verdicts=verdicts, calls=[call])

    @staticmethod
    def _parse_verify(text: str, count: int) -> tuple[list[VerifyVerdict], str, str]:
        """解析校验输出，按 `count` 补全、强制按 `index` 顺序输出。

        返回 `(verdicts, 失败类型, 失败原因)`——第三项为空串表示解析成功。
        **解析失败时也返回一份「全部标负样本」的列表**（长度、顺序都对），
        因为调用方拿到异常后如果决定降级，要的正是这份保守结果；
        交给它比让它在异常里自己造一份更省事（`verify` 自己**不**降级，
        它照抛，降级是 tool 层的决定）。

        模型可能漏条、乱序、重复——`by_index` 按 `index` 收；漏掉的条目
        标注"校验遗漏该条"但**不算整体解析失败**（那是模型少判了一条，
        不是输出坏了，标负样本正是保守的正确答案——不确认达标就不给下游
        `summarize` 喂）。
        """
        try:
            raw = json.loads(_strip_json_fence(text))
            items = raw["verdicts"] if isinstance(raw, dict) else raw
            by_index = {
                int(item["index"]): item
                for item in items
                if isinstance(item, dict) and "index" in item
            }
        except Exception as exc:  # noqa: BLE001  畸形，保守兜底 + 上抛
            return (
                [
                    VerifyVerdict(index=i, positive=False, why="校验输出解析失败")
                    for i in range(count)
                ],
                "ParseFailure",
                f"校验输出无法解析：{type(exc).__name__}",
            )

        verdicts: list[VerifyVerdict] = []
        for i in range(count):
            item = by_index.get(i)
            if item is None:
                verdicts.append(
                    VerifyVerdict(index=i, positive=False, why="校验遗漏该条，按负样本处理")
                )
            else:
                verdicts.append(
                    VerifyVerdict(
                        index=i,
                        positive=bool(item.get("positive", False)),
                        why=str(item.get("why", "")),
                    )
                )
        return verdicts, "", ""

    # ---- 蒸馏（跨局摘要）----

    def summarize(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        success: bool,
        steps: int,
        max_steps: int,
        images: Sequence[str] = (),
    ) -> SummarizeResult:
        """一次蒸馏尝试：问一次模型、解析摘要。**不重试**——重试是调用方的循环。

        **六块素材：`goal` / `history` / `success` / `steps` / `max_steps` /
        `prompt`**（见 `BrainPort.summarize`）。本方法**全部收下、全部不读**：
        素材已由调用方过滤并渲进 `prompt`，签名立的是约定——"蒸馏必须有这几块"。

        **`history` 里的记录含决策者的论据**（蒸馏要总结"为什么这么做"，
        跟 `verify()` 相反）——这个差异由调用方在渲染时决定，
        本方法只认成品文本。

        前置条件：`history` 只装已过滤的可信记录，至少一条（归调用方保证）。

        后置条件：成功时 `summary` 非 `None`，`calls` 恰好一条。
        失败：模型调不通、输出解析不出，都抛 `SummarizeAttemptFailed`
        （附这次的账）——"这次没蒸出东西"由调用方的重试预算决定怎么收场。
        """
        assert self._verify_llm is not None, (
            "summarize() 需要一个 verify provider——这次装配没给它（按需装配）"
        )
        # 步骤 1：调模型。
        try:
            text, n_in, n_out, n_cached, n_reason = self._ask(self._verify_llm, prompt, images)
        except Exception as exc:  # noqa: BLE001  调不通也是"这一次失败"
            call = ModelCall(
                payload={"ok": "false", "prompt": prompt, "images": list(images)},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            )
            raise SummarizeAttemptFailed(call) from exc

        # 步骤 2：解析摘要。
        summary = self._parse_summary(text)

        call = ModelCall(
            payload={
                "input_tokens": str(n_in),
                "output_tokens": str(n_out),
                "cached_tokens": str(n_cached),
                "reasoning_tokens": str(n_reason),
                "raw": text,
                "ok": str(summary is not None).lower(),
                "prompt": prompt,
                "images": list(images),
            },
            error_kind="" if summary is not None else "ParseFailure",
            error="" if summary is not None else "摘要输出无法解析成 EpisodeSummary",
        )
        if summary is None:
            raise SummarizeAttemptFailed(call)

        return SummarizeResult(summary=summary, calls=[call])

    @staticmethod
    def _parse_summary(text: str) -> EpisodeSummary | None:
        """把蒸馏输出解析成 `EpisodeSummary`；解析不出来返回 `None`。

        整段输出可以是「摘要对象本身」，也可以是「带 `summary` 字段的外层对象」
        ——两种写法都收（prompt 约束一种，但解析器宽容一点不会更贵）。
        """
        try:
            raw = json.loads(_strip_json_fence(text))
        except Exception:  # noqa: BLE001  输出畸形，留 None
            return None
        if not isinstance(raw, dict):
            return None

        data = raw.get("summary") if isinstance(raw.get("summary"), dict) else raw
        data = dict(data)
        markdown = str(data.pop("markdown", ""))
        # `filename` 从输出里**丢掉**（0914 98 全退）：模型可能还在给，
        # 但字段已经不存在了——落盘用 uuid 命名，那一格从来没有读方。
        data.pop("filename", None)
        try:
            return EpisodeSummary(
                summary=data["summary"],
                reason=data.get("reason", ""),
                reusable_patterns=data.get("reusable_patterns", []),
                critical_decisions=data.get("critical_decisions", []),
                failure_points=data.get("failure_points", []),
                quality_score=data["quality_score"],
                quality_rationale=data["quality_rationale"],
                applicable_scenes=data.get("applicable_scenes", []),
                tags=data.get("tags", []),
                markdown=markdown,
            )
        except Exception:  # noqa: BLE001  字段不全，留 None
            return None

    # ---- 世界知识抽取 ----

    # ---- 记忆整理 ----

    def reflect(
        self,
        *,
        prompt: str,
        before: str,
        after: str,
        action_text: str,
    ) -> Reflection:
        """把这一步整理成一条经验：**看到什么 → 做了什么 → 变成什么**。

        **本版不调模型**：四样东西都已经在参数里，让模型再复述一遍只会引入
        它自己的措辞偏差，还多烧一次调用。`prompt` 收下但本版不消费——
        接口按"可能会调"设计（`reflect` 后面也要变成 LLM 接入），
        六个方法的形状因此统一。

        **本方法不写库**：写库是状态变更，而大脑无状态。
        **不盖章坐标**：`episode_id`/`step` 由调用方加——大脑不知道自己在哪一局、
        第几步。

        前置条件：`before`/`after` 是渲染好的文本。调用方要
        保证这一点（渲染是它的事）。
        """
        assert before, "reflect() got an empty before-snapshot text"
        assert after, "reflect() got an empty after-snapshot text"

        return Reflection(
            before=before,
            action_text=action_text,
            after=after,
        )

    # ---- 内部 ----

    @staticmethod
    def _parse_plan(text: str) -> RunPlan:
        """把规划模型的原始文本输出解析成 `RunPlan`；失败抛 `ParseFailure`。

        先剥 ```json 围栏（模型最常见的格式偏差，`choose`/`_parse` 同样
        处理）——不剥的话 `json.loads` 会在第一个反引号处报"char 0"，误导成
        空输出。
        """
        stripped = _strip_json_fence(text)
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ParseFailure(text, f"not valid json ({exc.msg})") from exc
        if not isinstance(raw, dict):
            raise ParseFailure(text, "top level is not an object")
        try:
            return RunPlan.model_validate(raw)
        except ValidationError as exc:
            raise ParseFailure(text, f"RunPlan 字段不合法：{exc.errors()[:1]}") from exc

    def _parse(self, text: str, keys: Sequence[str]) -> Action:
        """把 LLM 输出解析成 `Action`，不合法就抛 `ParseFailure` / `IllegalAction`。

        **纯结构解析**：不认识世界语义（哪个键是交互键、连按在世界里意味着
        什么）、不认识上限（段数/次数/论据条数归调用方校验）、不认识存储。
        只做三件事：剥围栏、验形状、验"这个键在不在 `keys` 里"。
        """
        # 步骤 1：剥 ```json 围栏。
        stripped = _strip_json_fence(text)

        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ParseFailure(text, f"not valid json ({exc.msg})") from exc

        if not isinstance(raw, dict):
            raise ParseFailure(text, "top level is not an object")

        # 只剩按键一类动作，所以没有"先取 intent 再分叉"那一段。
        # （0923 189 起段级 rationale 已从契约删除——模型多写的字段在这里被忽略。）
        raw_sequence = raw.get("sequence")
        if not isinstance(raw_sequence, list) or not raw_sequence:
            raise ParseFailure(text, "'sequence' must be a non-empty array")

        sequence = []
        for index, segment in enumerate(raw_sequence, start=1):
            where = f"segment {index}"
            if not isinstance(segment, dict) or not isinstance(segment.get("action"), str):
                raise ParseFailure(text, f"each sequence item needs an action ({where})")
            name = segment["action"]
            times = self._parse_times(text, segment)
            sequence.append(ActionSegment(name=name, times=times))

        for segment in sequence:
            if segment.name not in keys:
                raise IllegalAction(segment.name, list(keys))

        return Action(
            thought=self._parse_thought(text, raw),
            sequence=sequence,
        )

    @staticmethod
    def _parse_times(text: str, values: dict[str, object]) -> int:
        """解析按键段次数，把外部格式错误转成可重试的 ParseFailure。

        **不校验上限**——上限归调用方（tool/harness），大脑只保证"这是个
        正整数"。
        """
        raw_times = values.get("times", 1)
        try:
            times = int(raw_times)
        except (TypeError, ValueError) as exc:
            raise ParseFailure(text, "times must be an integer") from exc
        if times < 1:
            raise ParseFailure(text, "times must be a positive integer")
        return times

    @staticmethod
    def _parse_thought(text: str, raw: dict[str, object]) -> str:
        """缺失是一类**单独的** `ParseFailure`——"格式坏"和"不肯推理"要能分开聚合，
        但不值得为此多开一个异常类型，用 reason 字符串区分就够。

        取出推理文本，缺失或为空则抛。
        """
        thought = raw.get("thought")
        if not isinstance(thought, str) or not thought.strip():
            raise ParseFailure(text, "missing 'thought' field")
        return thought.strip()
