"""决策层 Brain 对外接口模型（`ChooseOnceReq` 等裸名 req/resp，与 providers 的
`LlmCompleteReq` 同规则——接口模型不带 From/To 前缀）。

本文件是 `schemas/brain/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.brain import X`，不深到子目录。
harness 发起的交互信封归 `schemas/harness/`（发起方 A 处）。

**动作 / 目标 / 任务实体、模型解析产物（计划 / 校验结论 / 局摘要）不在这里**：
`Action`/`EpisodeSummary`/`Goal`/`RunPlan`/`StepVerifyVerdict`/
`Task`（以及 `MAX_RATIONALE`/`MAX_TIMES`）原来放在 `domain/` 子目录，
现在跟着"协议物理挨着它自己的实现"这条原则搬到了 `pokemon_agent.brain.interface`
——消费方改写 `from pokemon_agent.brain import Task` 这样各自认模块，
详见 CHANGELOG 对应条目。
"""

__all__ = [
    "ChooseOnceReq",
    "ChooseOnceResp",
    "JudgeReq",
    "JudgeResp",
    "PlanOnceReq",
    "PlanOnceResp",
    "ReflectReq",
    "ReflectResp",
    "VerifyAndSummarizeReq",
    "VerifyAndSummarizeResp",
]
from .communication.ChooseOnceReq import ChooseOnceReq
from .communication.ChooseOnceResp import ChooseOnceResp
from .communication.JudgeReq import JudgeReq
from .communication.JudgeResp import JudgeResp
from .communication.PlanOnceReq import PlanOnceReq
from .communication.PlanOnceResp import PlanOnceResp
from .communication.ReflectReq import ReflectReq
from .communication.ReflectResp import ReflectResp
from .communication.VerifyAndSummarizeReq import VerifyAndSummarizeReq
from .communication.VerifyAndSummarizeResp import VerifyAndSummarizeResp
