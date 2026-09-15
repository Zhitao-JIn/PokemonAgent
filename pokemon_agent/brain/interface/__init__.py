"""brain/interface 包统一出口：大脑的港口（`BrainPort`）+ 它内嵌的数据形状
（`Action`/`EpisodeSummary`/`Goal`/`Reflection`/`RunPlan`/`StepVerifyVerdict`/
`Task`，以及每个方法的结果袋 `ChooseResult`/`JudgeResult`/`PlanResult`/
`SummarizeResult`/`VerifyResult`）+ 选型纯数据（`BrainLlmConfig`）。

`BrainPort` 原来放在顶层 `pokemon_agent/interfaces/brain/`；六个数据形状原来
分别放在 `schemas/brain/domain/` 下——都跟着"协议物理挨着它自己的实现/数据
形状"这条原则搬到了这里。

**`BrainLlmConfig` 0913 深夜九从 `build_llm_providers.py` 搬来**：它是零重依赖的
纯数据（四个型号名 + `max_tokens`），而留在工厂模块时，任何只想要它的调用方
（`build.py` 造一份选型表）都要连着进口那个模块顶部的
`from .providers import ArkProvider, QwenProvider`——实测连带拉进 25 个 brain
模块 + `PIL`。搬到这里后 `from pokemon_agent.brain import BrainLlmConfig`
只走到本层，厂商实现一个都不碰。"温度分层"是常量，留在工厂里。

**这几个数据形状 + `BrainLlmConfig` 立即加载，`BrainPort` 懒加载**：跟
`world/interface` 的 `WorldPort`/`Facts` 同一个道理——`brain_port.py` 要
`import pokemon_agent.schemas.brain`（拿 `ChooseOnceReq` 等通信协议），而
`schemas/brain/communication/*.py` 里这些通信协议的字段又要从这里拿回
`Goal`/`Action` 等数据形状。两条依赖在初始化顺序上正面
相撞：`schemas.brain` 聚合 `__init__` 走到某个 communication 文件那一行时，
如果这里连 `BrainPort` 一起立即导入，就会在 `schemas.brain` 自己还没跑完的
时候被回头要 `ChooseOnceReq` 之类还没绑定的名字，直接炸成
`ImportError: cannot import name ... from partially initialized module`。
数据形状本身零依赖，可以放心立即导入；`BrainPort` 推迟到
真的有人访问 `.BrainPort` 时才导入，两头都不用再对导入顺序小心翼翼。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .domain import (
    Action,
    ActionSegment,
    ChooseResult,
    EpisodeSummary,
    ExtractResult,
    Goal,
    JudgeResult,
    KnowledgeItem,
    LearnedKnowledge,
    ModelCall,
    PlanResult,
    Reflection,
    RunPlan,
    StepVerifyVerdict,
    SummarizeResult,
    Task,
    VerifyResult,
)
from .llm_config import BrainLlmConfig
from .llm_provider import JudgeProvider, LLMProvider

if TYPE_CHECKING:
    from .brain_port import BrainPort

__all__ = [
    "Action",
    "ActionSegment",
    "BrainLlmConfig",
    "BrainPort",
    "ChooseResult",
    "EpisodeSummary",
    "ExtractResult",
    "Goal",
    "JudgeProvider",
    "JudgeResult",
    "KnowledgeItem",
    "LLMProvider",
    "LearnedKnowledge",
    "ModelCall",
    "PlanResult",
    "Reflection",
    "RunPlan",
    "StepVerifyVerdict",
    "SummarizeResult",
    "Task",
    "VerifyResult",
]


def __getattr__(name: str) -> object:
    if name == "BrainPort":
        from .brain_port import BrainPort as _BrainPort

        globals()["BrainPort"] = _BrainPort
        return _BrainPort
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
