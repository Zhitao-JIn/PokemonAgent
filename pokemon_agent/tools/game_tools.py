"""GameTools —— 把「世界的能力」翻译成「Harness 操作世界的手」。**全项目只有这一个。**

**这个类现在只碰 `WorldPort`，不碰任何记忆。** 早先它还持有一份 `ObjectMemory`
的引用，`perceive()` 顺手把语义记忆拼进 `facts["known_objects"]`——那条耦合
这次拆掉了：`known_objects` 现在由 `Harness._observe()` 在拿到这个类的
`perceive()` 结果之后，另外调 `MemoryToolPort.known_here()` 拼上去。
`GameTools` 因此没有任何字段指向记忆，`memory/` 包整个是它看不见的东西——
这是 `GameToolPort`/`MemoryToolPort` 拆成两个协议在这个类上的直接体现。

它以前叫 `Harness`，改名是因为那个名字盖住了两件不同的事：
"怎么碰环境"（这里）和"一局怎么跑"（`harness/harness.py`）。
合在一个类里的时候，`perceive()` 同时是"看一眼"和"新的一步"，
于是需要按步去重来调和两种身份——而那个去重制造了步号回退和判定重复计费。

拆开之后这个类**没有任何跨步骤状态**，只有"上一次给出的动作空间"，
这是为 `execute()` 的前置条件服务的。它不写 trace、不认识 LLM、不知道 episode 是谁。

## 掩码规则

从 `facts["overlay"]` 查 `OVERLAY_ACTIONS`。
**掩码是策略，所以在这一层；`overlay` 是感知的产物，所以由 world 交出来。**
两边通过 `Observation.facts` 这个公开字段衔接，谁也不认识谁的内部。

`overlay` 在熔断里 23/23 全对，是整条感知链里最可靠的一维——把动作空间挂在它上面
是刻意的：分类错一次的代价是大脑看到一组不该有的动作，比字段读错严重得多。

## 感知归 world，这一层只是转发

用户定的分工：**感知是"tool 调用 world"**。VisionProvider 留在 `PyBoyWorld` 里，
理由是 `Observation` 是跨层契约，谁产出谁负责完整性；而且"一帧只感知一次"的
缓存依赖它在 world 内部。这一层只把 `observe()` 转出来。
"""

from __future__ import annotations

from pokemon_agent.interfaces.world import WorldPort
from pokemon_agent.prompts.game_hints import BUTTON_HELP, MAP_HINT, REPEAT_HINT
from pokemon_agent.schemas.action import Action, ActionSpace, ToolResult
from pokemon_agent.schemas.observation import (
    OVERLAY_ACTIONS,
    Overlay,
    PerceptionResult,
)
from pokemon_agent.schemas.task import Task

# `BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT` 的组装逻辑在
# `pokemon_agent/prompts/game_hints.py`——这里只是消费方。


class GameTools:
    """`GameToolPort` 的唯一实现。持有 world，**不持有记忆**。"""

    def __init__(self, world: WorldPort) -> None:
        self._world = world
        self._last_space: tuple[ActionSpace, str] | None = None
        """上一次交出去的动作空间，**连同它是给哪一帧算的**。

        它回答两个问题，缺一不可：`execute()` 里那个动作确实来自最近一次
        `get_action_space()`（不是幻觉出来的名字），以及那次动作空间**没有过期**——
        画面换过之后再拿旧清单放行，就是在一个已经变了的世界里按一个
        按当时语境选的键。所以把帧哈希一起存下来，让"这份清单过期了"
        变成一条能当场炸掉的契约。
        """

    # ---- GameToolPort ----

    def reset(self, task: Task) -> PerceptionResult:
        """开新一局。"""
        self._last_space = None
        return self._world.reset(task)

    @property
    def last_frame_sha(self) -> str:
        return self._world.last_frame_sha

    def perceive(self) -> PerceptionResult:
        """看一眼当前画面。world 自己按帧缓存，所以一帧之内调多少次都只花一次感知的钱。

        `result.calls` 直接是 `world.observe()` 交出来的那份，原样转发——
        这一层不做任何记账相关的事，只是把 world 的返回值传上去。
        """
        return self._world.observe()

    def inspect(self, focus: str) -> PerceptionResult:
        """对同一帧再问一次感知。转发给 world —— 换的是 prompt，不是画面。"""
        assert focus.strip(), "inspect() got an empty focus"
        return self._world.inspect(focus)

    def get_action_space(self) -> ActionSpace:
        """掩码发生在这里，**只看 overlay**。

        后置条件：names 非空。走投无路也必须给至少一个动作——
            空动作空间是这一层的 bug，不能推给大脑处理。
        """
        # calls 在这里丢弃是安全的：调用方（Harness._space）总是紧跟在
        # `_observe()` 之后同一步内调用这个方法，画面没变过，这次 observe()
        # 必然命中缓存、calls 必然是空列表——真正的账已经在 `_observe()` 里记过了。
        obs = self._world.observe().observation
        overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
        names = [a for a in OVERLAY_ACTIONS[overlay] if a in self._world.all_actions()]

        assert names, f"action space must never be empty (overlay={overlay})"
        # `intents` 留空（默认只有 press）—— 由 Harness 覆写。
        # 能不能拆子目标取决于目标栈有多深，工具层不知道也不该知道。
        space = ActionSpace(
            names=names,
            descriptions=dict(BUTTON_HELP[overlay]),
            note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
        )
        # 连同帧哈希一起记：掩码是**按这一帧的 overlay 算的**，换帧就作废。
        self._last_space = (space, self._world.last_frame_sha)
        return space

    def execute(self, action: Action) -> ToolResult:
        """执行动作，推进世界。

        前置条件：调用方必须先调用过 `get_action_space()`，且 action 来自那次结果。
        后置条件：`result.observation` 非空。
        """
        assert self._last_space is not None, "execute() before get_action_space()"
        space, frame = self._last_space
        assert space.contains(action.name), (
            f"execute() got {action.name!r} outside {space.names}"
        )
        # **掩码必须是给当前这一帧算的。** 只查名字是不够的：`a` 在野外、对话框、
        # 选择框里都可用，名字对得上不代表语境对得上。画面换过之后再拿旧清单放行，
        # 就是在一个已经变了的世界里按一个按当时语境选的键。
        assert frame == self._world.last_frame_sha, (
            "execute() got an action space computed for an older frame "
            f"({frame} != {self._world.last_frame_sha}) — call get_action_space() again"
        )

        result = self._world.step(action)
        self._last_space = None      # 世界推进了，上次的空间失效

        assert result.observation is not None, "world.step() must return the new observation"
        return result
