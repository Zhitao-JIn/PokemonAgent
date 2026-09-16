"""world 的内部失败：感知链路读不出画面。

**它们自成一根 `WorldError`，不继承顶层的 `AgentError`**（0913 夜定案）——
判据是 P3 那句「**这条异常有没有跨过 tool 层这座桥**」：

    world 抛 PerceptionAttemptFailed ──► GameTools.perceive_with_retry 捕获、重试
                                     ──► 耗尽抛 MaxRetriesExceeded ──► harness 的 except AgentError

重试循环 0913 从 harness 节点搬回了 tool 层（对齐 `BrainTool._attempt_loop`），
于是 world 的词汇**在桥上就被翻译掉了**，走不到 `RunHarness.dispatch` 的
捕获点——继承 `AgentError` 就成了纯仪式，而仪式有实价：**world 拷走后还得带上
`pokemon_agent/errors.py` 才能跑**，P1「能不能整个拷走」当场不成立。
**brain 的情况与此完全同构**（`BrainError` 自成一根），两边现在同一规格。

**为什么这些异常住在 `world/` 而不是顶层 `errors.py`**（0913 定案）：
它们是 **world 的内部词汇**——`PerceptionAttemptFailed` 是感知链路的
"这一次没读出来"。world 是要能**被整体拷走复用**的模块（跟 `memory/`/`brain/`
同一规格），它的词汇得跟着它走。

**`ImageNotDelivered` 不在这里**（虽然它也是"图的事"）：它由
`brain/providers.py::describe()` 抛出，而 `describe()` 是 brain 与 world
**共用的实现**——既然抛出者归 brain（0913 深夜十一"谁抛的归谁"），它就住在
`brain/errors.py`（**不再是顶层 `errors.py`**，那份旧叙述已过时）。
world 自己**不认识它**——`PyBoyWorld.perceive_once` 就地
`except Exception` 把它收编成自己的 `PerceptionAttemptFailed`。
"""

from __future__ import annotations


class WorldError(Exception):
    """world 的内部失败根。**不继承 `AgentError`**。

    理由见模块 docstring：world 的异常在 `GameTools.perceive_with_retry` 里就被
    翻译成 tool 层的 `MaxRetriesExceeded`，**走不到 harness 的捕获点**。
    判据同 brain 的 `BrainError`——继承与否反映的是"这条异常有没有跨过
    tool 层这座桥"，不是含糊的"共同祖先"。
    """


class PerceptionAttemptFailed(WorldError):
    """一次感知尝试失败（视觉模型输出解析不出 `ScreenState`）。

    **世界侧的同类模式**（不在 brain 的 `AttemptFailed` 家族里——那个家族是
    brain 的六条链路，这是 `world` 的唯一链路）。账随异常带出来：
    "要不要再问一次"由调用方（`GameTools.perceive_with_retry`）决定，
    重试预算与升级态都在那一层。

    与 brain 的 `AttemptFailed` 家族**刻意不合并**：两者都属于不同模块的契约面，
    合并会让 `world` 与 `brain` 共享一个异常类，等于两者之间多一条隐式耦合。
    """

    def __init__(self, call: dict[str, str | list[str]]) -> None:
        """记下这次失败的账单（普通 dict，字段同 brain 的 `ModelCall.payload`，
        值可为标量字符串或字符串列表——如感知账里的 `images`）。"""
        super().__init__(f"perception attempt failed: {call.get('raw', '')[:200]!r}")
        self.call = call


__all__ = ["PerceptionAttemptFailed", "WorldError"]
