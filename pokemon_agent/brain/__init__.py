"""brain 包：纯决策层。无状态——每一步的全部输入来自参数，全部记忆来自工具调用。

- `interface/`：这个子系统的港口（`BrainPort`）+ 它内嵌的数据形状
  （`Action`/`EpisodeSummary`/`Goal`/`Reflection`/`RunPlan`/
  `StepVerifyVerdict`/`Task`，以及每个方法的结果袋），跟"怎么决策"的实现
  物理分开。**选型纯数据 `BrainLlmConfig` 也住这里**（0913 深夜九从
  `build_llm_providers.py` 搬来）——它是零重依赖的 dataclass，住在工厂模块里
  会让"只想声明用什么型号"的调用方连带进口厂商实现
- `brain.py`：`BrainPort` 的唯一实现（`Brain`）
- `build_llm_providers.py`：**厂商接线工厂**——`build_llm_providers()`
  （从 config 造四个 provider）。`Brain` 的四个 provider 各配哪家厂商、
  `temperature` 常量、哪个位置必须是豆包型号名，是 brain 自己的接线知识，
  因此装配点（`build.py`）只递 config，不 import 具体 provider 类
- `providers.py`：**厂商实现本体**（`QwenProvider`/`ArkProvider`/
  `DeepSeekProvider` + 两个基类 + 图像网格工具）。0913 从顶层
  `pokemon_agent/providers/openai_compatible.py` 搬来——它服务的正是
  `build_llm_providers()` 造的这四个 provider，"谁消费归谁"。
  **`pokemon_agent/providers/` 这个包自此不存在。**
- `errors.py`：brain 的内部词汇（`ParseFailure`/`IllegalAction`/`OutputTruncated`/
  `ToolTimeout` + `AttemptFailed` 家族 + `ImageNotDelivered`），**自成一根
  `BrainError(Exception)`**——brain 要能被整体拷走，词汇得跟着走，且不能欠外面
  一个基类。这些异常全被 `BrainTool._attempt_loop` 接住、翻译成 `MaxRetriesExceeded`
  才上抛，**走不到 harness 的捕获点**，所以不必继承 `AgentError`
- `schemas/`：brain 自己的补全信封（`LlmCompleteReq/Resp` + `VisionDescribeReq/Resp`）。
  0913 深夜十一从顶层 `pokemon_agent/schemas/providers/` 搬来——provider 已全搬进
  brain，这四封信就是**brain 的内部协议**，留在外面等于 brain 拷走后欠一个外部文件。
  **world 有一份自己的副本**（`world/interface/domain/vision_describe.py`，只复制
  `VisionDescribe*` 两封），两份必须保持同构，靠"同一份原始定义复制 + 字段名核对"守。

**brain 的外部依赖**（0913 深夜十一审计）：**`pokemon_agent.*` 依赖为零**——
全部外部 import 只剩标准库（`collections`/`dataclasses`/`importlib`/`io`/`json`/
`math`/`os`/`pathlib`/`time`/`typing`/`urllib`/`base64`）与第三方库
（`pydantic`/`PIL`）。**横向依赖也为零。** 这就是"brain 可作为第三方整体拷走"
的字面含义：拷走 `pokemon_agent/brain/`，不欠任何同项目文件。

本文件是统一出口：消费方只写 `from pokemon_agent.brain import X`，不深到
模块文件。

**数据形状 + `BrainLlmConfig` 立即加载，`Brain`/`BrainPort`/`build_llm_providers`
懒加载。** 原因跟 `world/__init__.py` 对 `WorldPort` 的处理一模一样：
`brain.py`（`Brain` 的实现）要 `from pokemon_agent.schemas.brain import
(ChooseOnceReq, ...)`，而 `schemas/brain/communication/*.py` 里这些协议的字段
又要从 `brain.interface` 拿回 `Goal`/`Action` 等数据形状——如果
这里在包初始化时就把 `Brain`/`BrainPort` 也一并导入，`schemas.brain` 跟
这个包之间就会形成真正的循环导入。`build_llm_providers` 懒加载则是为了
不让"只想拿 `BrainLlmConfig`"的调用方背上厂商实现面。
`__getattr__` 把这些名字改成按需导入，
`from pokemon_agent.brain import X` 用起来和之前一模一样，只是不再是包
初始化时就全量加载。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .interface import (
    Action,
    ActionSegment,
    BrainLlmConfig,
    ChooseResult,
    EpisodeSummary,
    Goal,
    JudgeResult,
    ModelCall,
    PlanResult,
    Reflection,
    RunPlan,
    StepVerifyVerdict,
    SummarizeResult,
    Task,
    VerifyResult,
)

if TYPE_CHECKING:
    from .brain import Brain
    from .build_llm_providers import build_llm_providers
    from .interface import BrainPort

__all__ = [
    "Action",
    "ActionSegment",
    "Brain",
    "BrainLlmConfig",
    "BrainPort",
    "ChooseResult",
    "EpisodeSummary",
    "Goal",
    "JudgeResult",
    "ModelCall",
    "PlanResult",
    "Reflection",
    "RunPlan",
    "StepVerifyVerdict",
    "SummarizeResult",
    "Task",
    "VerifyResult",
    "build_llm_providers",
]

_LAZY: dict[str, tuple[str, str]] = {
    "Brain": (".brain", "Brain"),
    "BrainPort": (".interface", "BrainPort"),
    # `build_llm_providers` 懒加载：它所在的模块顶部 `from .providers import ...`
    # 会拉进整个厂商实现面（含 `PIL`）。`BrainLlmConfig` 是纯数据、已在上面的
    # 立即导入面里，所以"只想声明这次用什么型号"的调用方（`build.py`）
    # 不会因为 import 本包就背上网关客户端。
    "build_llm_providers": (".build_llm_providers", "build_llm_providers"),
}


def __getattr__(name: str) -> object:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
