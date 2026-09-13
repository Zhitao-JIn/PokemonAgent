"""world 的内部失败：感知链路读不出画面。

**为什么这些异常住在 `world/` 而不是顶层 `errors.py`**（0913 定案）：
它们是 **world 的内部词汇**——`PerceptionAttemptFailed` 是感知链路的"这次没读出来"，
`PerceptionFailure` 是重试耗尽后的升级态。world 是要能**被整体拷走复用**的模块
（跟 `memory/`/`brain/` 同一规格），它的词汇得跟着它走。

**`ImageNotDelivered` 不在这里**（虽然它也是"图的事"）：它由
`brain/providers.py::describe()` 抛出（那个文件 0913 从顶层
`providers/openai_compatible.py` 搬进 brain），而 `describe()` 是 brain 与
world **共用的实现**——两个模块的契约（`world/interface/vision_provider.py` 与
`brain/interface/llm_provider.py`）都声明"图片未送达时必须抛它"。既然它横跨两个
模块、且由共享实现抛出，就**留在顶层 `errors.py`**（跟 `AgentError` 同理）。
**而且留下更必要了**：world 若从 `brain.errors` 拿它，就是一条
`world → brain` 的横向依赖；从 `pokemon_agent.errors` 拿，两个模块谁都不欠谁。

跟 `AgentError` 的关系：这些异常**仍继承顶层的 `AgentError`**——
"单局异常不崩掉整个 run"这条 run 级策略靠的正是这个共同祖先。
**子类在这里、根在顶层**，两边各取所需。
"""

from __future__ import annotations

from pokemon_agent.errors import AgentError


class PerceptionAttemptFailed(AgentError):
    """一次感知尝试失败（视觉模型输出解析不出 `ScreenState`）。

    **世界侧的同类模式**（不在 brain 的 `AttemptFailed` 家族里——那个家族是
    brain 的六条链路，这是 `world` 的唯一链路）。账随异常带出来：
    `PerceptionFailure` 是重试预算耗尽后的升级态，这里只是"问一次没读出来"。

    与 brain 的 `AttemptFailed` 家族**刻意不合并**：两者都属于不同模块的契约面，
    合并会让 `world` 与 `brain` 共享一个异常类，等于两者之间多一条隐式耦合。
    """

    def __init__(self, call: dict[str, str]) -> None:
        """记下这次失败的账单（普通 dict，字段同 brain 的 `ModelCall.payload`）。"""
        super().__init__(f"perception attempt failed: {call.get('raw', '')[:200]!r}")
        self.call = call


class PerceptionFailure(AgentError):
    """反复调用视觉模型仍拿不到能解析的 `ScreenState`。

    和 brain 的 `ParseFailure` 分开：那是**大脑**的输出格式问题（改 prompt 或上约束解码），
    这是**感知层**的（换模型、改预处理、或者这一帧本来就没法读）。
    在 replay 里它们指向完全不同的修法，合并就丢了诊断信息。

    与 `ImageNotDelivered` 也分开：那是图没送到（网关问题），
    这是图送到了但读不出结构（能力问题）。
    """

    def __init__(self, attempts: int, last_reason: str) -> None:
        """记下试了几次、最后一次为什么失败。"""
        super().__init__(f"perception failed after {attempts} attempts: {last_reason}")
        self.attempts = attempts
        self.last_reason = last_reason


__all__ = ["PerceptionAttemptFailed", "PerceptionFailure"]
