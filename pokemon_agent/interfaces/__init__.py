"""interfaces 包：全部 Protocol（"港口"）与伴随的状态模型。

`brain → interfaces ← harness` 的依赖方向由这一层锚定：实现方（harness/world/
tools/providers/trace）实现这些 Protocol，消费方（brain/harness）只认它们。
依赖方向永远是 `实现 → interfaces ← 消费`，绝不反向，绝不横向。

**memory 的契约不在这里**：`MemoryStorePort` 随 `memory/` 包走
（`pokemon_agent/memory/ports.py`）——那是一个要求能被整体拷去别的项目复用的
子系统，它的接口与实现同住一包，不属于本项目的跨层港口。

本文件是统一出口：本层全部 Port 与状态模型从这里 re-export，
消费方只写 `from pokemon_agent.interfaces import X`，不深到子目录的模块文件。

**这个包正在被逐步淘汰**：`WorldPort` 已经搬到 `pokemon_agent/world/interface/
world_port.py`，`TracePort`（连同它的账目词表 `TraceKind`）已经搬到
`pokemon_agent/trace/interface/`——都跟着各自的实现同住一包，理由和取舍见
对应 CHANGELOG 条目。这次不再在这里保留 re-export：消费方直接
`from pokemon_agent.world import WorldPort` / `from pokemon_agent.trace import
TracePort`。本文件剩下的其余 Port 会按 trace → providers → brain → tools →
harness 的顺序逐个搬完，搬完最后一个后这个包整体删除。
"""

__all__ = [
    "BrainPort",
    "BrainToolPort",
    "CheckpointToolPort",
    "EmbeddingProvider",
    "EpisodeHarnessPort",
    "EpisodeRunState",
    "GameToolPort",
    "HarnessPort",
    "HumanReviewer",
    "JudgeProvider",
    "LLMProvider",
    "MAX_GOAL_RETRIES",
    "MAX_PLAN_PUSH",
    "MemoryToolPort",
    "PLAN_MAX_ATTEMPTS",
    "RerankerProvider",
    "ResumeEpisode",
    "RunState",
    "TraceToolPort",
    "VisionProvider",
]
from .brain.brain_port import BrainPort
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
from .providers.embedding_provider import EmbeddingProvider
from .providers.llm_provider import LLMProvider
from .providers.reranker_provider import RerankerProvider
from .providers.vision_provider import JudgeProvider, VisionProvider
from .tools.brain_tool_port import BrainToolPort
from .tools.checkpoint_tool_port import CheckpointToolPort
from .tools.game_tool_port import GameToolPort
from .tools.memory_tool_port import MemoryToolPort
from .tools.trace_tool_port import TraceToolPort
