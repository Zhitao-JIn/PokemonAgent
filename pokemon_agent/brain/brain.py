"""Brain —— **一切需要 LLM 才能回答的问题，都在这个类里。**

它不是"一个模型"，是**一组互不通气的模型技能**的容器：

    choose_once  看着当前画面和可用动作，问一次模型选下一步  decide_llm
                 （重试循环在 Harness，同步调用，见 `docs/ROADMAP.md`）
    judge    看着当前画面和任务目标，判达成没达成       judge_llm
    reflect  把这一步整理成一条可检索的经验            （本版无模型调用）
    verify_and_summarize  校验本局 step 记忆 + 只用可信的蒸馏摘要（一次调用）  verify_llm（缺省同 judge_llm）
    plan_once  看 run 级历史 + 目标栈，问一次模型该压什么/该不该收尾  plan_llm（缺省同 judge_llm）
                 （重试循环在 `harness/run/plan.py::ask_planner_with_retry`，同步调用，
                 跟 choose_once 同一个分工——
                 run 级规划是"另一种要问模型的问题"，不是要接触的另一个外部
                 模块，所以不单独开一个 tool，见 `pokemon_agent/tools/__init__.py`）

**它不写 trace，也不知道自己在哪一局。** 四个方法都不收 `step`（
`verify_and_summarize` 额外收 `episode_id`/`run_id`——只用于把蒸馏结果组装成
`EpisodeMemory`，判定本身不依赖"我是谁"），构造函数里也没有 `TracePort`——
账（`ModelCall`）跟着结果交给 Harness。规则只有一句：**谁控制循环，谁记账。**

**`choose` 和 `judge` 必须分开。** 让做决策的模型顺便回答"我成功了吗"是误差同源：
它读错画面 → 以为达成了 → 判成功，错得越离谱数字越好看。隔离靠两条硬约束维持：
`judge()` 看得到最近几步**发生了什么**，但拿不到决策者对那几步的任何说辞；
`judge_llm` 是**另一个 provider 实例**，哪怕型号相同。

**无状态**（铁律 1）：没有任何跨步骤的实例变量，构造函数存的是不可变的协作者；
连续两次用相同参数调 `choose()`，行为必须完全一致。只认识 Protocol（铁律 2）。

完整论证——为什么这仍不是独立真值——见 `docs/spec/brain/SPEC.md`。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import ValidationError

from pokemon_agent.errors import (
    DecisionAttemptFailed,
    IllegalAction,
    OutputTruncated,
    ParseFailure,
    PlanAttemptFailed,
)
from pokemon_agent.providers import JudgeProvider, LLMProvider, ModelCall
from pokemon_agent.schemas.brain import (
    ChooseOnceReq,
    ChooseOnceResp,
    JudgeReq,
    JudgeResp,
    PlanOnceReq,
    PlanOnceResp,
    ReflectReq,
    ReflectResp,
    VerifyAndSummarizeReq,
    VerifyAndSummarizeResp,
)

from .interface import (
    MAX_RATIONALE,
    MAX_SEGMENTS,
    MAX_TIMES,
    Action,
    ActionSegment,
    EpisodeSummary,
    RunPlan,
    StepVerifyVerdict,
)
from pokemon_agent.schemas.memory import SNAPSHOT_BLIND, EpisodeMemory, StepMemory
from pokemon_agent.schemas.providers import LlmCompleteReq, VisionDescribeReq
from pokemon_agent.world import INTERACT_KEY, ActionSpace, Observation

DIRECTION_KEYS = frozenset({"up", "down", "left", "right"})


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


def _create_episode_memory(
    episode_id: str,
    run_id: str,
    goal: str,
    success: bool,
    steps: int,
    resp: EpisodeSummary,
) -> EpisodeMemory:
    """把 LLM 蒸馏出的 `EpisodeSummary` 和这一局的元信息组装成一条 `EpisodeMemory`。

    这是通信层（`EpisodeSummary`）到存储层（`EpisodeMemory`）的**显式适配点**：
    两边的经验本体字段同构、但各自独立定义，这里做字段搬运。蒸馏器原来住在
    memory 层（ROADMAP 16：memory 只做读写，不承担组装），上移到 brain——
    蒸馏和它的产物组装是同一个产出动作的两半。

    前置条件：由调用方（`Brain.verify_and_summarize()`）保证 `success`/`steps`
        来自 harness 对这一局的结算，不是这里要重新计算的东西。
    """
    return EpisodeMemory(
        episode_id=episode_id,
        run_id=run_id,
        goal=goal,
        success=success,
        steps=steps,
        summary=resp.summary,
        reusable_patterns=resp.reusable_patterns,
        critical_decisions=resp.critical_decisions,
        failure_points=resp.failure_points,
        quality_score=resp.quality_score,
        quality_rationale=resp.quality_rationale,
        applicable_scenes=resp.applicable_scenes,
        tags=resp.tags,
        filename=resp.filename,
        markdown=resp.markdown,
    )


class Brain:
    """`BrainPort` 的唯一实现。"""

    def __init__(
        self,
        decide_llm: LLMProvider,
        judge_llm: JudgeProvider,
        verify_llm: JudgeProvider | None = None,
        plan_llm: LLMProvider | None = None,
    ) -> None:
        """依赖全部注入，类型标成接口而非实现（CLAUDE.md 第三节第 3 条）。

        `judge_llm` 单独一个参数、哪怕和 `decide_llm` 同型号：换判定模型时只改装配处，
        manifest 里两条链路也才看得出是可以分别选型的。

        `verify_llm`：step 校验+蒸馏（`verify_and_summarize`）用的模型，单独一个参数——
        跟 `judge_llm` 同理，哪怕型号相同也不共用同一个 provider 实例，manifest
        才看得出这条链路可以单独换型号/调参。缺省（`None`）回退到 `judge_llm`：
        两者都是"独立判定"性质，不传时沿用旧行为（复用同一个判定模型）。

        `plan_llm`：run 级规划（`plan_once`）用的模型，同样单独一个参数、
        缺省回退到 `judge_llm`——跟 `verify_llm` 同理：规划和判定都不是"决策"，
        分组更接近，装配处（`build.py`）实际也一直把这条链路的模型跟
        judge/verify 放在同一个供应商（火山方舟）下。类型是纯 `LLMProvider`
        （不是 `JudgeProvider`）：`plan_once` 只读 trace 历史文字和目标栈，
        不带图，不需要 `describe()`。

        `judge_llm`/`verify_llm` 的类型是 `JudgeProvider`（`LLMProvider` +
        `VisionProvider`），不是纯 `LLMProvider`——`judge()`/
        `verify_and_summarize()` 带得到截图时会走 `describe()` 问一次多模态，一张图都
        凑不齐时才退化成 `complete()`；`decide_llm`/`plan_llm` 不受影响，这两条
        链路本来就不该看图（见模块文档"choose 和 judge 必须分开"那段，这里不是
        同一件事，但同理不该无端扩大它们的职责）。

        **没有 `max_retries`**——决策重试的预算和循环都在 Harness
        （`DECISION_MAX_RETRIES`，见 `docs/ROADMAP.md`），大脑不知道
        "问几次"这件事，只知道"问一次"。

        存下四个 provider，此后不再变——prompt 全部由调用方拼好递进来。
        """
        self._decide = decide_llm
        self._judge_llm = judge_llm
        self._verify_llm = verify_llm or judge_llm
        self._plan_llm = plan_llm or judge_llm
        # `decide_action.md`/`judge_success.md`/`step_verify.md`/`run_plan.md`
        # 完全不在这里——四个方法都只接收调用方（Harness）已经拼好的 prompt
        # 字符串，`Brain` 不知道 `pokemon_agent.prompts` 这个包的存在，谁调用
        # 它、prompt 从哪来，`Brain` 不关心。

    # ---- 决策 ----

    def choose_once(self, req: ChooseOnceReq) -> ChooseOnceResp:
        """一次决策尝试：问一次模型、解析。**不重试**——重试是 Harness 的循环。

        **只有一个输入参数**：`req.prompt` 由调用方经
        `pokemon_agent.prompts.decide_action.build_prompt(req)` 拼好（重试时
        再叠 `retry_prompt()`，回填进同一个 req 的 `prompt` 字段）——`Brain`
        只管拿 `req.prompt` 问模型，不知道、也不需要知道它是怎么拼出来的；
        `req.space` 用来校验解析出的动作。
        后置条件：成功时返回的 `ChooseOnceResp.action` 属于 `req.space`，
        `calls` 恰好这一次尝试的一条账（多次尝试的累积由 Harness 那层的
        `brain_utils.choose_with_retry` 做），`recalled` 是 `req.memories`
        投影成的 `(episode_id, step)` 列表——**全部产物**打包一起交回去，
        不是散的元组。
        失败：解析不出来 / 选了不存在的键 / 被截断，抛 `DecisionAttemptFailed`
        （附这次的账）——"什么算失败"仍是大脑的判断，只是"要不要再问一次"
        交给了 Harness。

        步骤 1：调模型。
        步骤 2：解析，失败就把账封进异常抛出去；成功就打包成 `ChooseOnceResp` 交回去。
        """
        space = req.space

        # 步骤 1：调模型。
        completion = self._decide.complete(LlmCompleteReq(prompt=req.prompt))

        # 步骤 2：解析。
        parsed: Action | None = None
        kind = reason = ""
        try:
            # 截断要**先于**解析检查，否则它会伪装成"少了个右括号"的 ParseFailure。
            if completion.truncated:
                raise OutputTruncated(completion.completion_tokens)
            parsed = self._parse(completion.text, space)
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
                "input_tokens": str(completion.prompt_tokens),
                "output_tokens": str(completion.completion_tokens),
                "cached_tokens": str(completion.cached_tokens),
                "reasoning_tokens": str(completion.reasoning_tokens),
                "ok": str(parsed is not None),
                "raw": completion.text,
                "prompt": req.prompt,
            },
            error_kind=kind,
            error=reason,
        )
        if parsed is None:
            raise DecisionAttemptFailed(call)

        # 出口断言（postcondition）：大脑不会产出空动作或空间外的按键。
        # `_parse` 已逐段校验过，这里是运行时全覆盖的兜底证明。
        assert parsed.sequence, "choose_once() returned an action with an empty sequence"
        assert all(space.contains(seg.name) for seg in parsed.sequence), (
            f"brain chose key outside {space.names}"
        )
        recalled = [f"({m.episode_id}, {m.step})" for m in req.memories]
        return ChooseOnceResp(action=parsed, calls=[call], recalled=recalled)

    # ---- 规划（run 级）----

    def plan_once(self, req: PlanOnceReq) -> PlanOnceResp:
        """一次 run 级规划尝试：问一次模型、解析。**不重试**——重试是 Harness
        的循环，跟 `choose_once()` 同一个分工（见 `docs/ROADMAP.md` "重试循环
        该不该从 brain 挪到 harness"）。

        **只有一个输入参数**：`req.prompt` 由调用方经
        `pokemon_agent.prompts.run_plan.build_prompt(req)` 拼好、回填进同一个
        req——`Brain` 只管拿 `req.prompt` 问模型，不知道、也不需要知道它是
        怎么拼出来的。**不带纠正重试**：`run_plan` 的重试是原样重问，不像
        `decide_action` 那样叠加纠正说明，所以这里没有 `retry_prompt()`
        这类方法。

        步骤 1：调模型（`plan_llm`，纯文本，不带图）。
        步骤 2：解析，失败就把账封进异常抛出去；成功就打包成 `PlanOnceResp` 交回去。
        """
        # 步骤 1：调模型。
        completion = self._plan_llm.complete(LlmCompleteReq(prompt=req.prompt))

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
                "ok": str(parsed is not None),
                "raw": completion.text,
                "prompt": req.prompt,
            },
            error_kind=kind,
            error=reason,
        )
        if parsed is None:
            raise PlanAttemptFailed(call)

        return PlanOnceResp(plan=parsed, calls=[call])

    # ---- 判定 ----

    def judge(self, req: JudgeReq) -> JudgeResp:
        """判断这个目标达成了没有。**永远返回 JudgeResp，不抛异常。**

        判不出来就是"没达成"加一条失败记录——判定器坏掉时表现是成功率悄悄变 0，
        必须能在失败模式分布里看见它。

        **只有一个输入参数**：`req.prompt` 由调用方经
        `pokemon_agent.prompts.judge_success.build_prompt(req)` 拼好、回填进
        同一个 req——`Brain` 不管拼装，只管拿 `req.prompt` 问模型。渲染本身
        可能抛的 `KeyError` 由调用方兜住（渲染已经不在这个 try 里了，这里只兜
        模型调用失败）。
        """
        try:
            text, n_in, n_out, n_cached, n_reason = self._ask(
                self._judge_llm, req.prompt, req.images
            )
        except Exception as exc:  # noqa: BLE001  判定器不该让整局崩掉
            # 这里捕的是**预期外异常（含 bug）**——取舍是：判定器不值得为一局的
            # 成败把内部 bug 暴露出来，代价是 judge 里的 bug 会静默（表现为
            # 成功率悄悄变 0，且 trace 的 judge_call 带 `why=判定调用失败：Xxx`）。
            return JudgeResp(
                done=False,
                why=f"判定调用失败：{type(exc).__name__}",
                call=ModelCall(
                    # judge 不重试（`attempt` 恒为 "1"）——见
                    # `docs/ROADMAP.md`"judge 链路的 MODEL_CALL 缺 attempt 字段"。
                    payload={
                        "ok": "False",
                        "attempt": "1",
                        "prompt": req.prompt,
                        "n_images": str(len(req.images)),
                    },
                    error_kind=type(exc).__name__,
                    error=f"{exc}",
                ),
            )

        done, why, kind = self._parse_verdict(text)
        return JudgeResp(
            done=done,
            why=why,
            call=ModelCall(
                payload={
                    "input_tokens": str(n_in),
                    "output_tokens": str(n_out),
                    "cached_tokens": str(n_cached),
                    "reasoning_tokens": str(n_reason),
                    "raw": text,
                    "ok": str(not kind),
                    # judge 不重试，`attempt` 恒为 "1"——同上，不是漏记，是没有第二次。
                    "attempt": "1",
                    "prompt": req.prompt,
                    # 带没带图直接影响这次判定看到了什么——没有这一项，回头分不清
                    # "这次判错是因为没带图"还是"带了图还是判错了"。
                    "n_images": str(len(req.images)),
                },
                error_kind=kind,
                error=why if kind else "",
            ),
        )

    @staticmethod
    def _ask(
        provider: JudgeProvider, prompt: str, images: Sequence[bytes]
    ) -> tuple[str, int, int, int, int]:
        """问一次判定器：`images` 非空就带图问（`describe()`），空的话退化成
        纯文本（`complete()`）——一张便利副本缺失（`StepMemory` 没留下截图
        文件名，或者文件确实不在磁盘上）不该让整条判定链路直接失败，降级成
        纯文本判定总比抛异常/硬编一个失败结果强。

        两种 provider 返回的字段名不一样（`LlmCompleteResp.prompt_tokens`/
        `completion_tokens` vs `VisionDescribeResp.input_tokens`/
        `output_tokens`，`cached_tokens` 字段名倒是两边一致）——这里统一抹平成
        `(text, 输入 token, 输出 token, 命中缓存 token, 思考 token)` 五元组，
        `judge()`/`verify_and_summarize()` 都不用关心这次走的是哪条路。
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

    # ---- step 记忆校验 + 蒸馏（独立判定器，一次调用问完两件事） ----

    def verify_and_summarize(self, req: VerifyAndSummarizeReq) -> VerifyAndSummarizeResp:
        """校验本局 step 记忆哪些可信，只用可信的那些蒸馏成一条跨局摘要。
        **永远返回 VerifyAndSummarizeResp，不抛异常。**

        校验与蒸馏合在**一次调用**（取舍：省一次模型往返，代价是校验与摘要
        同生共死——合并的完整论证见 `docs/ROADMAP.md`"verify_steps 与
        summarize 合并"一条，这是用户明确要的取舍，不是遗漏）。

        蒸馏前把关的动机：step 记忆是模型自述（`reflect` 拼的
        before/action/after），没有验证——直接当事实喂蒸馏，错误操作会被
        蒸馏成经验并跨局传播。这条防线体现在**同一次输出里的两段结构**
        （先 `verdicts` 逐条判可信，再 `summary` 只引用可信的部分），而不是
        两次调用之间的先后关系——真正的防线一直是"prompt 里写死了摘要只能
        引用 reliable 的记录"，不是"这是不是独立的第二次调用"。

        **只有一个输入参数**：`req.prompt` 由调用方经
        `pokemon_agent.prompts.verify_and_summarize.build_prompt(req)` 拼好、
        回填进同一个 req——`Brain` 不管拼装，只管拿 `req.prompt` 问模型。

        调用/解析失败时：`verdicts` 全部标不可靠（宁可少喂不可把错的当对的），
        `summary` 为 `None`（调用方据此决定这一局这次不写跨局摘要，只记一条
        错误）。
        """
        count = len(req.entries)
        try:
            text, n_in, n_out, n_cached, n_reason = self._ask(
                self._verify_llm, req.prompt, req.images
            )
        except Exception as exc:  # noqa: BLE001  校验/蒸馏都不该让整局崩掉（同 judge）
            return VerifyAndSummarizeResp(
                verdicts=[
                    StepVerifyVerdict(
                        index=i, reliable=False, why=f"合并调用失败：{type(exc).__name__}"
                    )
                    for i in range(count)
                ],
                summary=None,
                call=ModelCall(
                    # 不重试，`attempt` 恒为 "1"——同 judge/原 verify_steps。
                    payload={
                        "ok": "False",
                        "attempt": "1",
                        "prompt": req.prompt,
                        "n_images": str(len(req.images)),
                    },
                    error_kind=type(exc).__name__,
                    error=f"{exc}",
                ),
                why=f"合并调用失败：{type(exc).__name__}",
            )

        verdicts, summary = self._parse_verify_and_summarize(text, count)
        episode_memory = (
            _create_episode_memory(
                episode_id=req.episode_id,
                run_id=req.run_id,
                goal=req.goal,
                success=req.success,
                steps=req.steps,
                resp=summary,
            )
            if summary is not None
            else None
        )
        return VerifyAndSummarizeResp(
            verdicts=verdicts,
            summary=summary,
            episode_memory=episode_memory,
            call=ModelCall(
                payload={
                    "input_tokens": str(n_in),
                    "output_tokens": str(n_out),
                    "cached_tokens": str(n_cached),
                    "reasoning_tokens": str(n_reason),
                    "raw": text,
                    "ok": str(summary is not None),
                    "attempt": "1",
                    "prompt": req.prompt,
                    "n_images": str(len(req.images)),
                },
            ),
            why="" if summary is not None else "合并输出解析不出合法 summary",
        )

    @staticmethod
    def _parse_verify_and_summarize(
        text: str, count: int
    ) -> tuple[list[StepVerifyVerdict], EpisodeSummary | None]:
        """把合并输出解析成 `(verdicts, summary)`。

        `verdicts` 解析失败/畸形时**全部标不可靠**（保守兜底，逻辑同原
        `Brain._parse_verify`：按 `count` 补全、强制按 `index` 顺序输出）；
        `summary` 段解析失败/缺失时为 `None`——两段解析互不影响对方：外层
        JSON 解析不出来时两者都用保守默认值，外层解析成功但 `summary` 那部分
        字段不全时，`verdicts` 仍然正常返回（这一局的可信过滤没有理由因为
        摘要那半写坏了而跟着丢）。
        """
        try:
            raw = json.loads(_strip_json_fence(text))
            assert isinstance(raw, dict)
        except Exception:  # noqa: BLE001  输出畸形，两段都保守兜底
            return (
                [
                    StepVerifyVerdict(index=i, reliable=False, why="合并输出解析失败")
                    for i in range(count)
                ],
                None,
            )

        verdicts = Brain._verdicts_from_raw(raw.get("verdicts"), count)

        summary_data = raw.get("summary")
        summary: EpisodeSummary | None = None
        if isinstance(summary_data, dict):
            try:
                data = dict(summary_data)
                filename = str(data.pop("filename", "episode_memory"))
                markdown = str(data.pop("markdown", ""))
                summary = EpisodeSummary(
                    summary=data["summary"],
                    reusable_patterns=data.get("reusable_patterns", []),
                    critical_decisions=data.get("critical_decisions", []),
                    failure_points=data.get("failure_points", []),
                    quality_score=data["quality_score"],
                    quality_rationale=data["quality_rationale"],
                    applicable_scenes=data.get("applicable_scenes", []),
                    tags=data.get("tags", []),
                    filename=filename,
                    markdown=markdown,
                )
            except Exception:  # noqa: BLE001  summary 段畸形，留 None，verdicts 不受影响
                summary = None

        return verdicts, summary

    @staticmethod
    def _verdicts_from_raw(raw: object, count: int) -> list[StepVerifyVerdict]:
        """把已经反序列化的 `verdicts` 数组（可能是 `None`/畸形）对齐成与
        `count` 等长的判定列表；解析失败/畸形时**全部标不可靠**。

        原 `Brain._parse_verify` 的核心逻辑原样保留（模型可能漏条、乱序、
        重复：按 `count` 补全、强制按 `index` 顺序输出），只是入参从"整段
        文本"改成"已经解析出的数组"——合并输出的 `verdicts` 只是外层 JSON
        对象里的一个字段，不需要再单独 `json.loads` 一次。
        """
        try:
            by_index = {
                int(item["index"]): item
                for item in raw
                if isinstance(item, dict) and "index" in item
            }
        except Exception:  # noqa: BLE001  畸形，保守兜底
            return [
                StepVerifyVerdict(index=i, reliable=False, why="校验输出解析失败")
                for i in range(count)
            ]

        verdicts: list[StepVerifyVerdict] = []
        for i in range(count):
            item = by_index.get(i)
            if item is None:
                verdicts.append(
                    StepVerifyVerdict(index=i, reliable=False, why="校验遗漏该条，按不可靠处理")
                )
            else:
                verdicts.append(
                    StepVerifyVerdict(
                        index=i,
                        reliable=bool(item.get("reliable", False)),
                        why=str(item.get("why", "")),
                    )
                )
        return verdicts

    # ---- 记忆整理 ----

    def reflect(self, req: ReflectReq) -> ReflectResp:
        """把这一步整理成一条经验：**看到什么 → 为什么 → 做了什么 → 变成什么**。

        **只有一个输入参数**：`req` 打包前后两帧观测和这次的动作——跟其他
        三个方法同一个规则，模块间调用只认一个 req。

        **本版不调模型**：四样东西都已经在 req 里，让模型再复述一遍只会引入
        它自己的措辞偏差，还多烧一次调用。要不要上模型是以后的事，
        接口按"可能会调"设计（返回记忆条目而不是就地写库）。

        **这个方法自己不写库**：写库是状态变更，而大脑无状态。
        `episode_id` 也留空由 Harness 盖章——大脑不知道自己在哪一局。

        把前后两帧和这次动作拼成一条可检索的记忆条目返回。
        """
        # **只接受单键动作。** 连按在执行层已经展开成一步一步，`reflect` 是给
        # "哪一步"写记忆的——收到多段链说明调用方没展开，那是 harness 的 bug，
        # 就地拦下好过悄悄只取第一段的论据。
        assert len(req.action.sequence) == 1, "reflect() 只接受单键动作（连按应在执行层展开）"
        segment = req.action.sequence[0]
        assert segment.rationale, "reflect() got an action without a rationale"

        return ReflectResp(
            entry=StepMemory(
                before=self._snapshot(self._blind(req.before)),
                # 论据来自**这一步所属的那一段**：它是对"这一下为什么按"成立的
                # 适用条件。链级的那句"为什么要交出这串动作"对单个键不成立，
                # 归 `thought`（只进 trace）。
                rationale=list(segment.rationale),
                action=req.action.describe(),
                after=self._snapshot(self._blind(req.after)),
                step=req.before.step,
                # `episode_id` 由 Harness 盖章——大脑不知道自己在哪一局。
                episode_id="",
            )
        )

    @staticmethod
    def _snapshot(obs: Observation) -> StepMemory.Observation:
        """把 world 的真身 `Observation` 转成 `StepMemory` 自己的快照类型。

        `StepMemory.Observation` 是跟 `world.Observation` 字段一致但类不互相
        引用的内部类型（边界见 `schemas/memory/datastore/step_memory.py`
        的说明）——这里是**唯一**认识两边形状、需要做这次转换的地方：大脑
        本来就要在 `reflect()` 里把 `Observation` 组装进 `StepMemory`，是
        天然的转换点。`mode="json"` 把枚举/内部类都拍平成普通 dict/字符串，
        字段名两边一致，`model_validate()` 不需要逐字段手写映射。
        """
        return StepMemory.Observation.model_validate(obs.model_dump(mode="json"))

    @staticmethod
    def _blind(obs: Observation) -> Observation:
        """滤掉不该进记忆的字段（`SNAPSHOT_BLIND`），构造记忆用的那份观测。

        记忆里每一项都必须跨步骤成立，`known_objects`/`knowledge`
        不成立——前者是跨 episode 流水，后者本就不是"这一帧看到了什么"。
        过滤只发生在写记忆这一步，大脑决策时看到的仍是完整观测。

        **`perceived` 必须原样带过去**（它不是被滤掉的字段，是"这一帧有没有
        被看过"这个事实本身）：链内按键只做纯 RAM 观测，那些帧的
        `scene`/`overlay`/`dialog_text` **不是空的，是没读过**——丢掉这个标记，
        记忆渲染出来就跟"读过、只是这些字段为空"长得一模一样，读记忆的
        大脑/判定器会被引到错误的结论上。
        """
        return Observation(
            step=obs.step,
            place=obs.place,
            status=obs.status,
            # `Facts.exclude()` 直接改结构化字段，不走"渲染成文本再反解"那一趟——
            # `obs.facts` 本来就是 `Facts` 模型，这里只是拿掉几个不该进记忆的
            # 动态字段。
            facts=obs.facts.exclude(SNAPSHOT_BLIND),
            done=obs.done,
            perceived=obs.perceived,
        )

    # ---- 内部 ----

    @staticmethod
    def _parse_plan(text: str) -> RunPlan:
        """把规划模型的原始文本输出解析成 `RunPlan`；失败抛 `ParseFailure`。

        先剥 ```json 围栏（模型最常见的格式偏差，`choose_once`/`_parse` 同样
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

    def _parse(self, text: str, space: ActionSpace) -> Action:
        """把 LLM 输出解析成 `Action`，不合法就抛 `ParseFailure` / `IllegalAction`。"""
        # 步骤 1：剥 ```json 围栏。
        stripped = _strip_json_fence(text)

        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ParseFailure(text, f"not valid json ({exc.msg})") from exc

        if not isinstance(raw, dict):
            raise ParseFailure(text, "top level is not an object")

        # 只剩按键一类动作，所以没有"先取 intent 再分叉"那一段。
        # **论据在段上，不在顶层。** 顶层出现 rationale 是旧格式（整条链共用一条
        # 论据），静默忽略它等于替模型做了一个没留痕的决定：它以为自己写对了，
        # 而记忆里一条论据都不会有。
        if "rationale" in raw:
            raise ParseFailure(
                text,
                "'rationale' must be inside each sequence segment, not at the top level",
            )

        raw_sequence = raw.get("sequence")
        if not isinstance(raw_sequence, list) or not raw_sequence:
            raise ParseFailure(text, "'sequence' must be a non-empty array")
        # **段数有上限**（理由见 `MAX_SEGMENTS`）：段级论据让输出量随段数增长，
        # 而一次决策按多少个键直接决定这一圈烧掉多少执行力。
        if len(raw_sequence) > MAX_SEGMENTS:
            raise ParseFailure(text, f"too many segments ({len(raw_sequence)} > {MAX_SEGMENTS})")

        sequence = []
        for index, segment in enumerate(raw_sequence, start=1):
            where = f"segment {index}"
            if not isinstance(segment, dict) or not isinstance(segment.get("action"), str):
                raise ParseFailure(text, f"each sequence item needs an action ({where})")
            name = segment["action"]
            times = self._parse_times(text, segment)
            rationale = self._parse_rationale(text, segment, where)
            # **`a` 只按一次，在这里就定死。**
            #
            # 链内按键只做**纯 RAM 观测**，而对话文字只有视觉模型读得出来——连按三次
            # 推完整段对话，那几句一帧都没被看到，最后一次还会把对话框关掉，判定器
            # 看到一个没有对话框的画面，**一局本该成功的 episode 被静默记成失败**。
            # `a` 的收益全在中间帧上，**连按对它从来没有意义**。
            #
            # 夹在这里而不是 world 里：动作合法性是解析期的事，让非法的东西一路
            # 走到执行层再被悄悄改写，大脑就会以为自己按了三次。写死成 1 之后，
            # 交给 world 的链**就是真正会发生的那条链**。
            if name == INTERACT_KEY:
                times = 1
            sequence.append(ActionSegment(name=name, times=times, rationale=rationale))
        # **多段链：中间只能是方向键，结尾允许一个 `a`。**
        #
        # 中间帧看不到，所以链体里只放"闭眼也不丢信息"的移动键。链尾不一样：
        # 链尾那一帧本来就会被感知，`a` 打开的对话框/菜单**正好出现在这一帧**，
        # 证据没有丢。这样"走过去再按一下"就能一次决策做完，省掉一次视觉调用。
        # `a` 仍然只允许出现一次、且必须在末尾——出现在中间就等于把它产出的
        # 那几帧对话丢掉了（`times` 在上面已经写死成 1）。
        if len(sequence) > 1:
            body, tail = sequence[:-1], sequence[-1]
            body_bad = [seg.name for seg in body if seg.name not in DIRECTION_KEYS]
            tail_bad = tail.name not in DIRECTION_KEYS and tail.name != INTERACT_KEY
            if body_bad or tail_bad:
                raise ParseFailure(
                    text,
                    "multi-step sequence may contain only directional keys, "
                    f"plus at most one trailing {INTERACT_KEY!r}",
                )

        for segment in sequence:
            if not space.contains(segment.name):
                raise IllegalAction(segment.name, space.names)

        return Action(
            thought=self._parse_thought(text, raw),
            sequence=sequence,
        )

    @staticmethod
    def _parse_times(text: str, values: dict[str, object]) -> int:
        """解析按键段次数，把外部格式错误转成可重试的 ParseFailure。"""
        raw_times = values.get("times", 1)
        try:
            times = int(raw_times)
        except (TypeError, ValueError) as exc:
            raise ParseFailure(text, "times must be an integer") from exc
        if not 1 <= times <= MAX_TIMES:
            raise ParseFailure(text, f"times must be between 1 and {MAX_TIMES}")
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

    @staticmethod
    def _parse_rationale(text: str, values: dict[str, object], where: str) -> list[str]:
        """取出**这一段**的论据。

        超过 `MAX_RATIONALE` 条走 `ParseFailure` 而不是静默截断：模型认为需要
        3 条是有分量的，悄悄丢掉第 3 条等于替它做了一个没有留痕的决定。

        `where` 是错误信息里的位置（"segment 2"）——论据挂在每一段上，只报
        "missing 'rationale'" 的话，一条 4 段的链出错时定位不到是哪一段。

        容忍裸字符串写法，校验条数，返回论据列表。
        """
        rationale = values.get("rationale")
        if isinstance(rationale, str):
            rationale = [rationale]
        if not isinstance(rationale, list):
            raise ParseFailure(text, f"missing 'rationale' in {where}")

        items = [str(r).strip() for r in rationale if str(r).strip()]
        if not items:
            raise ParseFailure(text, f"missing 'rationale' in {where}")
        if len(items) > MAX_RATIONALE:
            raise ParseFailure(
                text, f"too many rationale items in {where} ({len(items)} > {MAX_RATIONALE})"
            )
        return items
