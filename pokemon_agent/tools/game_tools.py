"""`GameToolPort` 的实现：Harness 和世界之间那层薄壳。**不碰任何记忆。**

薄到几乎只是转发，但有两件事只在这里做：

- **动作掩码。** `get_action_space()` 按当前 overlay（有没有对话框、菜单、选择框）
  给出此刻能按的键。掩码**只看 overlay**，不看目标、不看历史——它回答的是
  "这一帧按下去有意义吗"，不是"这一步该按什么"。
- **前置检查。** `execute()` 断言动作确实来自最近一次给出的动作空间。
  大脑幻觉出不存在的键要在这里就地爆炸，而不是变成一个语义不明的模拟器错误。

掩码是**按这一帧算的，换帧就作废**，所以和帧哈希一起存。

方法上挂着权限装饰器，所以除各自写明的失败外都可能抛权限异常。
"""

from __future__ import annotations

from agent_permission import require_permission

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
        """接好世界，备好动作空间的帧内缓存。"""
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

    @require_permission("execute:game:reset")
    @require_permission("execute:llm:perception")
    def reset(self, task: Task) -> PerceptionResult:
        """开新一局。

        开新一局，返回第一帧观测。
        """
        self._last_space = None
        return self._world.reset(task)

    @require_permission("execute:game:save_state")
    def save_state(self, path: str) -> None:
        """把当前世界状态存成一个文件。"""
        self._world.save_state(path)

    @require_permission("read:game:perceive")
    @require_permission("execute:llm:perception")
    def perceive(self) -> PerceptionResult:
        """看一眼当前画面。world 自己按帧缓存，所以一帧之内调多少次都只花一次感知的钱。

        `result.calls` 直接是 `world.observe()` 交出来的那份，原样转发——
        这一层不做任何记账相关的事，只是把 world 的返回值传上去。

        看一眼当前画面，一帧之内只花一次感知的钱。
        """
        return self._world.observe()

    @require_permission("read:game:action_space")
    def get_action_space(self) -> ActionSpace:
        """掩码发生在这里，**只看 overlay**。

        后置条件：names 非空。走投无路也必须给至少一个动作——
            空动作空间是这一层的 bug，不能推给大脑处理。

        按当前 overlay 给出此刻能按的键。
        """
        # calls 在这里丢弃是安全的：调用方（Harness._space）总是紧跟在
        # `_observe()` 之后同一步内调用这个方法，画面没变过，这次 observe()
        # 必然命中缓存、calls 必然是空列表——真正的账已经在 `_observe()` 里记过了。
        obs = self._world.observe().observation
        overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
        names = [a for a in OVERLAY_ACTIONS[overlay] if a in self._world.all_actions()]

        assert names, f"action space must never be empty (overlay={overlay})"
        space = ActionSpace(
            names=names,
            descriptions=dict(BUTTON_HELP[overlay]),
            note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
        )
        # 连同帧哈希一起记：掩码是**按这一帧的 overlay 算的**，换帧就作废。
        self._last_space = (space, self._world.last_frame_sha)
        return space

    @require_permission("execute:game:press")
    @require_permission("execute:llm:perception")
    def execute(self, action: Action) -> ToolResult:
        """执行动作，推进世界。

        前置条件：调用方必须先调用过 `get_action_space()`，且 action 来自那次结果。
        后置条件：`result.observation` 非空。

        校验动作合法后按下去，推进世界。
        """
        assert self._last_space is not None, "execute() before get_action_space()"
        space, frame = self._last_space
        for segment in action.segments():
            assert space.contains(segment.name), (
                f"execute() got {segment.name!r} outside {space.names}"
            )
        if action.sequence:
            assert len(action.sequence) == 1 or all(
                segment.name in {"up", "down", "left", "right"} for segment in action.sequence
            ), (
                "multi-step action sequence may contain only directional keys"
            )
        # **掩码必须是给当前这一帧算的。** 只查名字是不够的：`a` 在野外、对话框、
        # 选择框里都可用，名字对得上不代表语境对得上。画面换过之后再拿旧清单放行，
        # 就是在一个已经变了的世界里按一个按当时语境选的键。
        assert frame == self._world.last_frame_sha, (
            "execute() got an action space computed for an older frame "
            f"({frame} != {self._world.last_frame_sha}) — call get_action_space() again"
        )

        # **整条链交给 world 一次执行完。** 这里不再自己展开。
        #
        # 展开过两版，两版都是错的：一次一按（`step(times=1)`）让 `up×4` 变成
        # **四次视觉调用**（实测一步 17k input token、6.6 秒）；一段一次
        # （`step(times=4)`）好一些，但 `up×4 -> down×2` 仍是两次。
        # 感知是每步花钱的那一项，而多段链按规则只能是移动键——中间那几帧
        # 没有任何会被用到的信息。一次决策就该是一次感知。
        #
        # 连按次数也不再经过 `args["times"]` 这条字符串通道：`world` 直接读
        # `action.segments()`，次数在 `ActionSegment.times`（1-8）解析期就校验过了。
        result = self._world.step(action)
        self._last_space = None      # 世界推进了，上次的空间失效

        assert result.observation is not None, "world.step() must return the new observation"
        return result
