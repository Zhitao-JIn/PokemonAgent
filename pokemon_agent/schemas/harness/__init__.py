"""编排层产出的契约：harness 发起的全部第一跳信封（brain_tool /
game_tool / memory_tool / reviewer / trace_tool 五个门面，外加 run → episode 这条内部边）
与人工复核实体。

Frontend 发起的信封已在 0914 控制台改造中**整个删除**（`schemas/frontend/` 一并没了）
——"整栈原子替换"是观测台概念，控制台里人就在图的调用栈上，不存在脱离图的草稿面板。
见 `docs/PLAN_console_reviewer.md` §1.2。
`run()` 这条边**入参与返回值都走裸字段、不包装**：`run(run_id, goals)` 返回
`(outcomes, total, succeeded, success_rate)`，要 JSON 的调用方自己拼。`RunResp`
（裸名，无 From/To）只是 `_close()` 内部组装、供 RUN_END 事件内嵌的产出模型——
记账层的信封必须内嵌模型，不摊裸字段。

本文件是 `schemas/harness/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.harness import X`，不深到 communication/ 等子目录。

**信封的"内部类型"也在这里转交**：harness 组装信封时会用到藏在字段里的领域类型
（`TraceKind` / `TraceEvent` / `GoalEntry` / `ModelCall` / `ModelCallLog`…），
那些类型的家各自在自己的包（`ModelCall` / `ModelCallLog`——主读者是带 `calls`
字段的信封与攒账的重试循环，就住在 `communication/ModelCall.py`），
但 **harness 从本文件拿**——"harness 只认 schemas"这条边界因此没有例外。

`TraceKind` / `TraceEvent` / `GoalEntry` / `EntryStatus` 几件**就住在 `domain/` 下**：
它们是 harness 自己声明的东西（"我记哪一笔账" / "一条事件长什么样" /
"一个目标在 run 内的状态表长什么样"），消费者是 harness 与本层读取方
（读者见各自模块的文档）。0913 下午 `TraceEvent` 从 `pokemon_agent.trace`
搬过来、0914 凌晨 `GoalEntry` 从"裸 `Task` 列表 + `attempts` 平行数组"改成
状态表，两者都在 `domain/`。**全仓对 `pokemon_agent.trace` 的 import 只剩
`tools/` 一层**——trace 是独立第三方模块，只有 tool 层（桥）认识它。

**`Source` 已删**（0913 晚）：生产者维度整体下线，"这条事件由哪条链产出"
改由 `kind` 回答（`*_call` 各占一个、失败类落 `content.link`），那个字段与
`domain/source.py` 一起没了。**"谁发的"**那条维度 0914 由封套 `meta.source`
回答——那是"发送位置"，与"链路"不是一回事。

**`HumanDecision` 已删**（0914 控制台改造）：三值（continue/stop/retry）随槽机制
一起下线。人的表态现在是两处：**插话**（`Reviewer.inject()` 收一句自然语言，
回车即收）与**审**（`AuditVerdict`——认 / 推翻，住 reviewer 的 audit 信封里）。
"继续/停止"不再是人的选项，由 run 的 `review_and_judge` 判（机械三类 + 问模型）；"重试"改成
`EntryStatus` 上的一次状态迁移（`plan_run` 把 `FAILED`/`ABANDONED` 重开成 `PENDING`）。
"""

__all__ = [
    "AuditVerdict",
    "FromHarnessToBrainToolChooseOnceReq",
    "FromHarnessToBrainToolChooseOnceResp",
    "FromHarnessToBrainToolDecomposeReq",
    "FromHarnessToBrainToolDecomposeResp",
    "FromHarnessToBrainToolJudgeReq",
    "FromHarnessToBrainToolJudgeResp",
    "FromHarnessToBrainToolPlanOnceReq",
    "FromHarnessToBrainToolPlanOnceResp",
    "FromHarnessToBrainToolReflectReq",
    "FromHarnessToBrainToolReflectResp",
    "FromHarnessToBrainToolSummarizeReq",
    "FromHarnessToBrainToolSummarizeTaskReq",
    "FromHarnessToBrainToolSummarizeTaskResp",
    "FromHarnessToBrainToolSummarizeResp",
    "FromHarnessToBrainToolVerifyReq",
    "FromHarnessToBrainToolVerifyResp",
    "FromHarnessToGameToolEvolveReq",
    "FromHarnessToGameToolExecuteReq",
    "FromHarnessToGameToolGetActionSpaceReq",
    "FromHarnessToGameToolGetActionSpaceResp",
    "FromHarnessToGameToolPerceiveOnceResp",
    "FromHarnessToGameToolResetReq",
    "FromHarnessToMemoryToolAppendObjectEventsReq",
    "FromHarnessToMemoryToolQueryActMemoriesReq",
    "FromHarnessToMemoryToolQueryActMemoriesResp",
    "FromHarnessToMemoryToolQueryEpisodeSummariesReq",
    "FromHarnessToMemoryToolQueryEpisodeSummariesResp",
    "FromHarnessToMemoryToolQueryKnowledgeReq",
    "FromHarnessToMemoryToolQueryKnowledgeResp",
    "FromHarnessToMemoryToolQueryObjectEventsAtReq",
    "FromHarnessToMemoryToolQueryObjectEventsAtResp",
    "FromHarnessToMemoryToolQueryObjectEventsReq",
    "FromHarnessToMemoryToolQueryObjectEventsResp",
    "FromHarnessToMemoryToolQueryRecentActMemoriesReq",
    "FromHarnessToMemoryToolQueryRecentActMemoriesResp",
    "FromHarnessToMemoryToolRestoreMemoryReq",
    "FromHarnessToMemoryToolRestoreMemoryResp",
    "FromHarnessToMemoryToolSnapshotMemoryReq",
    "FromHarnessToMemoryToolSnapshotMemoryResp",
    "FromHarnessToMemoryToolStoreActMemoryReq",
    "FromHarnessToMemoryToolStoreEpisodeSummaryReq",
    "FromHarnessToMemoryToolStoreTaskMemoryReq",
    "FromHarnessToMemoryToolQueryTaskMemoriesReq",
    "FromHarnessToMemoryToolQueryTaskMemoriesResp",
    "FromHarnessToMemoryToolStoreEpisodeSummaryResp",
    "FromHarnessToMemoryToolStoreKnowledgeReq",
    "FromHarnessToMemoryToolStoreKnowledgeResp",
    "FromHarnessToReviewerAuditReq",
    "FromHarnessToReviewerAuditResp",
    "FromHarnessToReviewerInjectReq",
    "FromHarnessToTraceToolAppendReq",
    "GoalEntry",
    "EntryStatus",
    "ModelCall",
    "ModelCallLog",
    "RunResp",
    "TraceEvent",
    "TraceKind",
]

from .communication.FromHarnessToBrainToolChooseOnceReq import FromHarnessToBrainToolChooseOnceReq
from .communication.FromHarnessToBrainToolChooseOnceResp import FromHarnessToBrainToolChooseOnceResp
from .communication.FromHarnessToBrainToolDecomposeReq import FromHarnessToBrainToolDecomposeReq
from .communication.FromHarnessToBrainToolDecomposeResp import FromHarnessToBrainToolDecomposeResp
from .communication.FromHarnessToBrainToolJudgeReq import FromHarnessToBrainToolJudgeReq
from .communication.FromHarnessToBrainToolJudgeResp import FromHarnessToBrainToolJudgeResp
from .communication.FromHarnessToBrainToolPlanOnceReq import FromHarnessToBrainToolPlanOnceReq
from .communication.FromHarnessToBrainToolPlanOnceResp import FromHarnessToBrainToolPlanOnceResp
from .communication.FromHarnessToBrainToolReflectReq import FromHarnessToBrainToolReflectReq
from .communication.FromHarnessToBrainToolReflectResp import FromHarnessToBrainToolReflectResp
from .communication.FromHarnessToBrainToolSummarizeReq import FromHarnessToBrainToolSummarizeReq
from .communication.FromHarnessToBrainToolSummarizeResp import FromHarnessToBrainToolSummarizeResp
from .communication.FromHarnessToBrainToolSummarizeTaskReq import (
    FromHarnessToBrainToolSummarizeTaskReq,
)
from .communication.FromHarnessToBrainToolSummarizeTaskResp import (
    FromHarnessToBrainToolSummarizeTaskResp,
)
from .communication.FromHarnessToBrainToolVerifyReq import FromHarnessToBrainToolVerifyReq
from .communication.FromHarnessToBrainToolVerifyResp import FromHarnessToBrainToolVerifyResp
from .communication.FromHarnessToGameToolEvolveReq import FromHarnessToGameToolEvolveReq
from .communication.FromHarnessToGameToolExecuteReq import FromHarnessToGameToolExecuteReq
from .communication.FromHarnessToGameToolGetActionSpaceReq import (
    FromHarnessToGameToolGetActionSpaceReq,
)
from .communication.FromHarnessToGameToolGetActionSpaceResp import (
    FromHarnessToGameToolGetActionSpaceResp,
)
from .communication.FromHarnessToGameToolPerceiveOnceResp import (
    FromHarnessToGameToolPerceiveOnceResp,
)
from .communication.FromHarnessToGameToolResetReq import FromHarnessToGameToolResetReq
from .communication.FromHarnessToMemoryToolAppendObjectEventsReq import (
    FromHarnessToMemoryToolAppendObjectEventsReq,
)
from .communication.FromHarnessToMemoryToolQueryActMemoriesReq import (
    FromHarnessToMemoryToolQueryActMemoriesReq,
)
from .communication.FromHarnessToMemoryToolQueryActMemoriesResp import (
    FromHarnessToMemoryToolQueryActMemoriesResp,
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
from .communication.FromHarnessToMemoryToolQueryRecentActMemoriesReq import (
    FromHarnessToMemoryToolQueryRecentActMemoriesReq,
)
from .communication.FromHarnessToMemoryToolQueryRecentActMemoriesResp import (
    FromHarnessToMemoryToolQueryRecentActMemoriesResp,
)
from .communication.FromHarnessToMemoryToolQueryTaskMemoriesReq import (
    FromHarnessToMemoryToolQueryTaskMemoriesReq,
)
from .communication.FromHarnessToMemoryToolQueryTaskMemoriesResp import (
    FromHarnessToMemoryToolQueryTaskMemoriesResp,
)
from .communication.FromHarnessToMemoryToolRestoreMemoryReq import (
    FromHarnessToMemoryToolRestoreMemoryReq,
)
from .communication.FromHarnessToMemoryToolRestoreMemoryResp import (
    FromHarnessToMemoryToolRestoreMemoryResp,
)
from .communication.FromHarnessToMemoryToolSnapshotMemoryReq import (
    FromHarnessToMemoryToolSnapshotMemoryReq,
)
from .communication.FromHarnessToMemoryToolSnapshotMemoryResp import (
    FromHarnessToMemoryToolSnapshotMemoryResp,
)
from .communication.FromHarnessToMemoryToolStoreActMemoryReq import (
    FromHarnessToMemoryToolStoreActMemoryReq,
)
from .communication.FromHarnessToMemoryToolStoreEpisodeSummaryReq import (
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
)
from .communication.FromHarnessToMemoryToolStoreEpisodeSummaryResp import (
    FromHarnessToMemoryToolStoreEpisodeSummaryResp,
)
from .communication.FromHarnessToMemoryToolStoreKnowledgeReq import (
    FromHarnessToMemoryToolStoreKnowledgeReq,
)
from .communication.FromHarnessToMemoryToolStoreKnowledgeResp import (
    FromHarnessToMemoryToolStoreKnowledgeResp,
)
from .communication.FromHarnessToMemoryToolStoreTaskMemoryReq import (
    FromHarnessToMemoryToolStoreTaskMemoryReq,
)
from .communication.FromHarnessToReviewerAuditReq import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
)
from .communication.FromHarnessToReviewerInjectReq import FromHarnessToReviewerInjectReq
from .communication.FromHarnessToTraceToolAppendReq import FromHarnessToTraceToolAppendReq
from .communication.ModelCall import ModelCall, ModelCallLog
from .communication.RunResp import RunResp
from .domain import EntryStatus, GoalEntry, TraceEvent, TraceKind
