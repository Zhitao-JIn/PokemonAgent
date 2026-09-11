"""interfaces 包：全部 Protocol（"港口"）与伴随的状态模型。

`brain → interfaces ← harness` 的依赖方向由这一层锚定：实现方（harness/world/
tools/providers/trace）实现这些 Protocol，消费方（brain/harness）只认它们。
依赖方向永远是 `实现 → interfaces ← 消费`，绝不反向，绝不横向。

**memory 的契约不在这里**：`MemoryStorePort` 随 `memory/` 包走
（`pokemon_agent/memory/ports.py`）——那是一个要求能被整体拷去别的项目复用的
子系统，它的接口与实现同住一包，不属于本项目的跨层港口。

本文件是统一出口：本层全部 Port 与状态模型从这里 re-export，
消费方只写 `from pokemon_agent.interfaces import X`，不深到子目录的模块文件。

**这个包正在被逐步淘汰**：`WorldPort`→`pokemon_agent/world/interface/`、
`TracePort`+`TraceKind`→`pokemon_agent/trace/interface/`、
`LLMProvider`/`VisionProvider`/`JudgeProvider`/`EmbeddingProvider`/
`RerankerProvider`+`ModelCall`→`pokemon_agent/providers/interface/`、
`BrainPort`+六个数据形状→`pokemon_agent/brain/interface/`、
`BrainToolPort`/`CheckpointToolPort`/`GameToolPort`/`MemoryToolPort`/
`TraceToolPort`→`pokemon_agent/tools/ports.py` 已经搬完，都跟着各自的实现
同住一包，理由和取舍见对应 CHANGELOG 条目。这次不再在这里保留 re-export：
消费方直接 `from pokemon_agent.brain import BrainPort` /
`from pokemon_agent.tools import BrainToolPort` 这样各自认模块。本文件
剩下的其余 Port（`harness/` 子目录）搬完后这个包整体删除。
"""

__all__ = [
    "EpisodeHarnessPort",
    "EpisodeRunState",
    "HarnessPort",
    "HumanReviewer",
    "MAX_GOAL_RETRIES",
    "MAX_PLAN_PUSH",
    "PLAN_MAX_ATTEMPTS",
    "ResumeEpisode",
    "RunState",
]
from .harness.episode_harness_port import EpisodeHarnessPort, EpisodeRunState
from .harness.harness_port import (
    MAX_GOAL_RETRIES,
    MAX_PLAN_PUSH,
    PLAN_MAX_ATTEMPTS,
    HarnessPort,
    ResumeEpisode,
    RunState,
)
from .harness.human_reviewer import HumanReviewer
