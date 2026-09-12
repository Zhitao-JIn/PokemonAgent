"""编排层产出的契约：harness 发起的全部第一跳信封（brain_tool /
game_tool / memory_tool / reviewer / trace_tool 五个门面，外加 run → episode 这条内部边）
与人工复核实体。

Frontend 发起的信封（提交目标编辑、取帧）归 `schemas/frontend/`。
`run()` 这条边**入参与返回值都走裸字段、不包装**：`run(run_id, goals)` 返回
`(outcomes, total, succeeded, success_rate)`，要 JSON 的调用方自己拼。`RunResp`
（裸名，无 From/To）只是 `_close()` 内部组装、供 RUN_END 事件内嵌的产出模型——
记账层的信封必须内嵌模型，不摊裸字段。

本文件是 `schemas/harness/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.harness import X`，不深到 communication/ 等子目录。

**信封的"内部类型"也在这里转交**：harness 组装信封时会用到藏在字段里的领域类型
（`TraceKind` / `Source` / `ModelCall` / `ModelCallLog`…），那些类型的家各自在自己的
包（`trace` / `providers`），或者在某个信封自己的模块里（`ModelCallLog`——它只
服务于 `FromHarnessToTraceToolAppendModelCallsReq`，就定义在那个文件里），
但 **harness 从本文件拿**——"harness 只认 schemas"这条边界因此没有例外。

**`HumanDecision` 不在这里**：原来放在 `domain/human_decision.py`，现在跟着
"协议物理挨着它自己的实现"这条原则搬到了 `pokemon_agent.harness.interface`
——消费方改写 `from pokemon_agent.harness import HumanDecision` 这样各自
认模块，详见 CHANGELOG 对应条目。
"""

__all__ = [
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
    "FromHarnessToGameToolEvolveReq",
    "FromHarnessToGameToolExecuteReq",
    "FromHarnessToGameToolGetActionSpaceReq",
    "FromHarnessToGameToolGetActionSpaceResp",
    "FromHarnessToGameToolLoadStateBytesReq",
    "FromHarnessToGameToolPerceiveOnceResp",
    "FromHarnessToGameToolResetReq",
    "FromHarnessToGameToolSaveStateBytesResp",
    "FromHarnessToGameToolSaveStateReq",
    "FromHarnessToGameToolSetTaskReq",
    "FromHarnessToMemoryToolAppendObjectEventsReq",
    "FromHarnessToMemoryToolQueryEpisodeStepsReq",
    "FromHarnessToMemoryToolQueryEpisodeStepsResp",
    "FromHarnessToMemoryToolQueryEpisodeSummariesReq",
    "FromHarnessToMemoryToolQueryEpisodeSummariesResp",
    "FromHarnessToMemoryToolQueryKnowledgeReq",
    "FromHarnessToMemoryToolQueryKnowledgeResp",
    "FromHarnessToMemoryToolQueryObjectEventsAtReq",
    "FromHarnessToMemoryToolQueryObjectEventsAtResp",
    "FromHarnessToMemoryToolQueryObjectEventsReq",
    "FromHarnessToMemoryToolQueryObjectEventsResp",
    "FromHarnessToMemoryToolQueryRecentStepsReq",
    "FromHarnessToMemoryToolQueryRecentStepsResp",
    "FromHarnessToMemoryToolStoreEpisodeStepReq",
    "FromHarnessToMemoryToolStoreEpisodeSummaryReq",
    "FromHarnessToMemoryToolStoreEpisodeSummaryResp",
    "FromHarnessToMemoryToolVoidMemoryAfterReq",
    "FromHarnessToMemoryToolVoidMemoryAfterResp",
    "FromHarnessToReviewerReviewReq",
    "FromHarnessToReviewerReviewResp",
    "FromHarnessToTraceToolAppendModelCallsReq",
    "FromHarnessToTraceToolAppendReq",
    "FromHarnessToTraceToolReadDiskEventsReq",
    "FromHarnessToTraceToolReadDiskEventsResp",
    "FromHarnessToTraceToolVoidAfterReq",
    "FromRunHarnessToEpisodeHarnessRunReq",
    "FromRunHarnessToEpisodeHarnessRunResp",
    "ModelCallLog",
    "RunResp",
]

from .communication.FromHarnessToBrainToolChooseOnceReq import FromHarnessToBrainToolChooseOnceReq
from .communication.FromHarnessToBrainToolChooseOnceResp import FromHarnessToBrainToolChooseOnceResp
from .communication.FromHarnessToBrainToolJudgeReq import FromHarnessToBrainToolJudgeReq
from .communication.FromHarnessToBrainToolJudgeResp import FromHarnessToBrainToolJudgeResp
from .communication.FromHarnessToBrainToolPlanOnceReq import FromHarnessToBrainToolPlanOnceReq
from .communication.FromHarnessToBrainToolPlanOnceResp import FromHarnessToBrainToolPlanOnceResp
from .communication.FromHarnessToBrainToolReflectReq import FromHarnessToBrainToolReflectReq
from .communication.FromHarnessToBrainToolReflectResp import FromHarnessToBrainToolReflectResp
from .communication.FromHarnessToBrainToolVerifyAndSummarizeReq import (
    FromHarnessToBrainToolVerifyAndSummarizeReq,
)
from .communication.FromHarnessToBrainToolVerifyAndSummarizeResp import (
    FromHarnessToBrainToolVerifyAndSummarizeResp,
)
from .communication.FromHarnessToGameToolEvolveReq import FromHarnessToGameToolEvolveReq
from .communication.FromHarnessToGameToolExecuteReq import FromHarnessToGameToolExecuteReq
from .communication.FromHarnessToGameToolGetActionSpaceReq import (
    FromHarnessToGameToolGetActionSpaceReq,
)
from .communication.FromHarnessToGameToolGetActionSpaceResp import (
    FromHarnessToGameToolGetActionSpaceResp,
)
from .communication.FromHarnessToGameToolLoadStateBytesReq import (
    FromHarnessToGameToolLoadStateBytesReq,
)
from .communication.FromHarnessToGameToolPerceiveOnceResp import (
    FromHarnessToGameToolPerceiveOnceResp,
)
from .communication.FromHarnessToGameToolResetReq import FromHarnessToGameToolResetReq
from .communication.FromHarnessToGameToolSaveStateBytesResp import (
    FromHarnessToGameToolSaveStateBytesResp,
)
from .communication.FromHarnessToGameToolSaveStateReq import FromHarnessToGameToolSaveStateReq
from .communication.FromHarnessToGameToolSetTaskReq import FromHarnessToGameToolSetTaskReq
from .communication.FromHarnessToMemoryToolAppendObjectEventsReq import (
    FromHarnessToMemoryToolAppendObjectEventsReq,
)
from .communication.FromHarnessToMemoryToolQueryEpisodeStepsReq import (
    FromHarnessToMemoryToolQueryEpisodeStepsReq,
)
from .communication.FromHarnessToMemoryToolQueryEpisodeStepsResp import (
    FromHarnessToMemoryToolQueryEpisodeStepsResp,
)
from .communication.FromHarnessToMemoryToolQueryEpisodeSummariesReq import (
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
)
from .communication.FromHarnessToMemoryToolQueryEpisodeSummariesResp import (
    FromHarnessToMemoryToolQueryEpisodeSummariesResp,
)
from .communication.FromHarnessToMemoryToolQueryKnowledgeReq import (
    FromHarnessToMemoryToolQueryKnowledgeReq,
)
from .communication.FromHarnessToMemoryToolQueryKnowledgeResp import (
    FromHarnessToMemoryToolQueryKnowledgeResp,
)
from .communication.FromHarnessToMemoryToolQueryObjectEventsAtReq import (
    FromHarnessToMemoryToolQueryObjectEventsAtReq,
)
from .communication.FromHarnessToMemoryToolQueryObjectEventsAtResp import (
    FromHarnessToMemoryToolQueryObjectEventsAtResp,
)
from .communication.FromHarnessToMemoryToolQueryObjectEventsReq import (
    FromHarnessToMemoryToolQueryObjectEventsReq,
)
from .communication.FromHarnessToMemoryToolQueryObjectEventsResp import (
    FromHarnessToMemoryToolQueryObjectEventsResp,
)
from .communication.FromHarnessToMemoryToolQueryRecentStepsReq import (
    FromHarnessToMemoryToolQueryRecentStepsReq,
)
from .communication.FromHarnessToMemoryToolQueryRecentStepsResp import (
    FromHarnessToMemoryToolQueryRecentStepsResp,
)
from .communication.FromHarnessToMemoryToolStoreEpisodeStepReq import (
    FromHarnessToMemoryToolStoreEpisodeStepReq,
)
from .communication.FromHarnessToMemoryToolStoreEpisodeSummaryReq import (
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
)
from .communication.FromHarnessToMemoryToolStoreEpisodeSummaryResp import (
    FromHarnessToMemoryToolStoreEpisodeSummaryResp,
)
from .communication.FromHarnessToMemoryToolVoidMemoryAfterReq import (
    FromHarnessToMemoryToolVoidMemoryAfterReq,
)
from .communication.FromHarnessToMemoryToolVoidMemoryAfterResp import (
    FromHarnessToMemoryToolVoidMemoryAfterResp,
)
from .communication.FromHarnessToReviewerReviewReq import FromHarnessToReviewerReviewReq
from .communication.FromHarnessToReviewerReviewResp import FromHarnessToReviewerReviewResp
from .communication.FromHarnessToTraceToolAppendModelCallsReq import (
    FromHarnessToTraceToolAppendModelCallsReq,
    ModelCallLog,
)
from .communication.FromHarnessToTraceToolAppendReq import FromHarnessToTraceToolAppendReq
from .communication.FromHarnessToTraceToolReadDiskEventsReq import (
    FromHarnessToTraceToolReadDiskEventsReq,
)
from .communication.FromHarnessToTraceToolReadDiskEventsResp import (
    FromHarnessToTraceToolReadDiskEventsResp,
)
from .communication.FromHarnessToTraceToolVoidAfterReq import (
    FromHarnessToTraceToolVoidAfterReq,
)
from .communication.FromRunHarnessToEpisodeHarnessRunReq import FromRunHarnessToEpisodeHarnessRunReq
from .communication.FromRunHarnessToEpisodeHarnessRunResp import (
    FromRunHarnessToEpisodeHarnessRunResp,
)
from .communication.RunResp import RunResp
