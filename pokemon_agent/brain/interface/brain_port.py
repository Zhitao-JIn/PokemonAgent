"""Harness 认识的大脑接口：choose_once / judge / reflect / verify_and_summarize / plan_once。

**每个方法只收一个输入参数**：三个跟 LLM 打交道的方法都收一个 `*Req`，
这个 req 同时是对应 `pokemon_agent.prompts.*.build_prompt()` 的输入——调用方
先拿 req 拼 prompt，把结果回填进 req 的 `prompt` 字段，再把同一个 req 整个
交给这里的方法，不需要额外单独传 prompt 或其它参数。

原来放在顶层 `pokemon_agent/interfaces/brain/`；跟 `WorldPort`/`TracePort` 搬到
各自实现旁边是同一个道理，`pokemon_agent/interfaces/` 这个集中注册表这次整个
撤销，消费方直接 `from pokemon_agent.brain import BrainPort`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.brain import (
    ChooseOnceReq,
    ChooseOnceResp,
    JudgeReq,
    JudgeResp,
    PlanOnceReq,
    PlanOnceResp,
    ReflectReq,
    VerifyAndSummarizeReq,
    VerifyAndSummarizeResp,
)
from pokemon_agent.memory import StepMemory


@runtime_checkable
class BrainPort(Protocol):
    """Harness 认识的大脑。"""

    def choose_once(
        self, req: ChooseOnceReq
    ) -> ChooseOnceResp:
        """一次决策尝试：问一次模型、解析。**不重试**——重试循环在 Harness 手里
        （见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"）。

        req：`req.prompt` 是这次问模型用的完整 prompt——调用方经
            `pokemon_agent.prompts.decide_action.build_prompt(req)` 拼好、
            回填进同一个 req；`req.space` 用它的 `space` 校验解析出的动作。
            `BrainPort` 不提供任何"帮你拼 prompt"的方法，`Brain` 只认 req。
        后置条件：`resp.action` 的 name 属于 req.space.names；`resp.calls`
            恰好一条（这次尝试自己的账，多次尝试的累积在 Harness 那层做）；
            `resp.recalled` 是 `req.memories` 原样投影成 `(episode_id, step)`。
        失败：抛 `DecisionAttemptFailed`（附这次的账）——要不要再问一次是
            调用方的判断。
        """
        ...

    def judge(self, req: JudgeReq) -> JudgeResp:
        """判断这一个目标达成了没有。

        req：`req.prompt` 是这次问模型用的完整 prompt——调用方经
            `pokemon_agent.prompts.judge_success.build_prompt(req)` 拼好、
            回填进同一个 req。`BrainPort` 不提供任何"帮你拼 prompt"的方法，
            `Brain` 只认 req。
        后置条件：永远返回 JudgeResp，不抛异常；任何不确定都判没完成。
            注意：这条"不抛异常"的契约只覆盖 `judge()` 内部（模型调用/解析）——
            `req.prompt` 本身的拼装（可能抛 `KeyError`）发生在调用方，调用方
            要自己兜住，不能指望 `judge()` 替它兜。
        """
        ...

    def reflect(self, req: ReflectReq) -> StepMemory:
        """把这一步整理成一条可检索的经验。

        req：打包前后两帧观测和这次的动作——同其余三个方法，只收一个 req。
        前置条件：req.action.rationale 非空。
        后置条件：返回的 entry 内容完整；episode_id 留空由 Harness 盖章；本方法不写库。
        """
        ...

    def plan_once(self, req: PlanOnceReq) -> PlanOnceResp:
        """一次 run 级规划尝试：问一次模型、解析。**不重试**——重试循环在 Harness
        手里（`harness/run_plan_utils.py::ask_planner_with_retry`），跟
        `choose_once()` 是同一个分工在 run 级图上的落地——`plan` 本质上是
        "另一种要问模型的问题"，不是要接触的另一个外部模块，所以跟
        `choose_once`/`judge` 同层放进 `BrainPort`，不单独开一个 tool。

        req：`req.prompt` 是这次问模型用的完整 prompt——调用方经
            `pokemon_agent.prompts.run_plan.build_prompt(req)` 拼好、回填进
            同一个 req；`RunHarness` 只组装结构化的 req，不自己拼 prompt
            字符串。`BrainPort` 不提供任何"帮你拼 prompt"的方法，`Brain`
            只认 req。
        后置条件：`resp.calls` 恰好一条（这次尝试自己的账，多次尝试的累积在
            Harness 那层做）。
        失败：抛 `PlanAttemptFailed`（附这次的账）——要不要再问一次是
            调用方的判断。
        """
        ...

    def verify_and_summarize(
        self, req: VerifyAndSummarizeReq
    ) -> VerifyAndSummarizeResp:
        """校验本局 step 记忆哪些可信，只用可信的蒸馏成一条跨局摘要——一次
        调用问完两件事（见
        `docs/ROADMAP.md`"verify_steps 与 summarize 合并"一条）。

        req：`req.prompt` 是这次问模型用的完整 prompt——调用方经
            `pokemon_agent.prompts.verify_and_summarize.build_prompt(req)`
            拼好、回填进同一个 req；`req.entries` 的条数就是校验失败时要
            补全的条数。`BrainPort` 不提供任何"帮你拼 prompt"的方法，
            `Brain` 只认 req。
        后置条件：永远返回 VerifyAndSummarizeResp，不抛异常；verdicts 与
            req.entries 等长——解析失败时全部标不可靠（宁可少喂，不可把错的
            当对的）；summary 解析/调用失败时为 `None`，调用方据此决定这一局
            这次不写跨局摘要。同 `judge()`：这条"不抛异常"契约不覆盖 prompt
            拼装本身，调用方要自己兜住渲染失败。**明确的取舍**：一次调用
            失败，校验和摘要都拿不到——两条链路各自独立成功的韧性不存在。
        """
        ...
