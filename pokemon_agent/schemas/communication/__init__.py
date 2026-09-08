"""communication schema 包：协议信封。

只装一次**调用/交互**的消息载体——Req / Resp 对，按通信方向一个文件：
文件名 = 类名 = `From{调用方}To{被调方}{函数名}{Req|Resp}`，光读目录就读得
出「谁对谁说话、说的哪个函数」。方向词表：Harness（编排者）/ BrainTool /
MemoryTool / GameTool（tool 层四根端口）/ Brain（大脑）/ World（世界）/
MemoryTool 的存储侧 / Llm（模型）。req 读作「递给对方的请求」，
resp 读作「对方给出的响应」；req/resp 各占一个文件。

短命，用完即弃，是「系统各层怎么对话」；被持久化的数据形状见 `datastore`，
跨层传递的领域实体见 `domain`。tool 的两跳（harness↔tool、tool↔模块）
类型故意不共用，互转由 tool 显式完成——见 `tools/brain_tool.py`。

本文件同时是统一出口：`communication/` 下各文件的公开信封从这里 re-export，
消费方只写 `from pokemon_agent.schemas.communication import X`，不深到模块文件。
"""

__all__ = [
    "FromBrainToolToBrainChooseOnceReq",
    "FromBrainToolToBrainChooseOnceResp",
    "FromBrainToolToBrainJudgeReq",
    "FromBrainToolToBrainJudgeResp",
    "FromBrainToolToBrainPlanOnceReq",
    "FromBrainToolToBrainPlanOnceResp",
    "FromBrainToolToBrainReflectReq",
    "FromBrainToolToBrainVerifyAndSummarizeReq",
    "FromBrainToolToBrainVerifyAndSummarizeResp",
    "FromBrainToLlmEpisodeSummaryResp",
    "FromGameToolToWorldPerceiveOnceResp",
    "FromHarnessToBrainToolChooseOnceReq",
    "FromHarnessToBrainToolChooseOnceResp",
    "FromHarnessToBrainToolJudgeReq",
    "FromHarnessToBrainToolJudgeResp",
    "FromHarnessToBrainToolPlanOnceReq",
    "FromHarnessToBrainToolPlanOnceResp",
    "FromHarnessToBrainToolReflectReq",
    "FromHarnessToBrainToolReflectResp",
    "FromHarnessToBrainToolVerifyAndSummarizeReq",
    "FromHarnessToBrainToolVerifyAndSummarizeResp",
    "FromHarnessToMemoryToolQueryKnowledgeReq",
    "FromHarnessToMemoryToolQueryKnowledgeResp",
    "FromCheckpointToolToHarnessRestoreResp",
    "FromCheckpointToolToHarnessVoidReport",
    "FromHarnessToCheckpointToolSaveReq",
    "FromHarnessToTraceToolAppendReq",
    "GoalsEdit",
    "HarnessEpisodeOutcomeResp",
    "HumanDecision",
    "HumanReviewReqFromHarness",
    "HumanReviewRespFromFrontend",
    "PlanGoal",
    "RunOutcomeResp",
    "RunPlanResp",
    "StepVerifyVerdict",
    "TextCompletionResp",
    "TraceKind",
    "VisionCompletionReq",
    "VisionCompletionResp",
]
from .FromBrainToLlmEpisodeSummaryResp import FromBrainToLlmEpisodeSummaryResp
from .FromBrainToolToBrainChooseOnceReq import FromBrainToolToBrainChooseOnceReq
from .FromBrainToolToBrainChooseOnceResp import FromBrainToolToBrainChooseOnceResp
from .FromBrainToolToBrainJudgeReq import FromBrainToolToBrainJudgeReq
from .FromBrainToolToBrainJudgeResp import FromBrainToolToBrainJudgeResp
from .FromBrainToolToBrainPlanOnceReq import FromBrainToolToBrainPlanOnceReq
from .FromBrainToolToBrainPlanOnceResp import FromBrainToolToBrainPlanOnceResp
from .FromBrainToolToBrainReflectReq import FromBrainToolToBrainReflectReq
from .FromBrainToolToBrainVerifyAndSummarizeReq import (
    FromBrainToolToBrainVerifyAndSummarizeReq,
)
from .FromBrainToolToBrainVerifyAndSummarizeResp import (
    FromBrainToolToBrainVerifyAndSummarizeResp,
)
from .FromCheckpointToolToHarnessRestoreResp import FromCheckpointToolToHarnessRestoreResp
from .FromCheckpointToolToHarnessVoidReport import FromCheckpointToolToHarnessVoidReport
from .FromGameToolToWorldPerceiveOnceResp import FromGameToolToWorldPerceiveOnceResp
from .FromHarnessToBrainToolChooseOnceReq import FromHarnessToBrainToolChooseOnceReq
from .FromHarnessToBrainToolChooseOnceResp import FromHarnessToBrainToolChooseOnceResp
from .FromHarnessToBrainToolJudgeReq import FromHarnessToBrainToolJudgeReq
from .FromHarnessToBrainToolJudgeResp import FromHarnessToBrainToolJudgeResp
from .FromHarnessToBrainToolPlanOnceReq import FromHarnessToBrainToolPlanOnceReq
from .FromHarnessToBrainToolPlanOnceResp import FromHarnessToBrainToolPlanOnceResp
from .FromHarnessToBrainToolReflectReq import FromHarnessToBrainToolReflectReq
from .FromHarnessToBrainToolReflectResp import FromHarnessToBrainToolReflectResp
from .FromHarnessToBrainToolVerifyAndSummarizeReq import (
    FromHarnessToBrainToolVerifyAndSummarizeReq,
)
from .FromHarnessToBrainToolVerifyAndSummarizeResp import (
    FromHarnessToBrainToolVerifyAndSummarizeResp,
)
from .FromHarnessToCheckpointToolSaveReq import FromHarnessToCheckpointToolSaveReq
from .FromHarnessToMemoryToolQueryKnowledgeReq import (
    FromHarnessToMemoryToolQueryKnowledgeReq,
)
from .FromHarnessToMemoryToolQueryKnowledgeResp import (
    FromHarnessToMemoryToolQueryKnowledgeResp,
)
from .FromHarnessToTraceToolAppendReq import FromHarnessToTraceToolAppendReq
from .goals_edit import GoalsEdit
from .harness_episode_outcome import HarnessEpisodeOutcomeResp
from .human_review import (
    HumanDecision,
    HumanReviewReqFromHarness,
    HumanReviewRespFromFrontend,
)
from .run_outcome import RunOutcomeResp
from .run_plan import PlanGoal, RunPlanResp
from .step_verify import StepVerifyVerdict
from .text_completion import TextCompletionResp
from .TraceKind import TraceKind
from .vision_completion import VisionCompletionReq, VisionCompletionResp
