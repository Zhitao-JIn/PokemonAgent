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
    Observation,
    Overlay,
    PerceptionResult,
)
from pokemon_agent.schemas.task import Task

# `BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT` 的组装逻辑在
# `pokemon_agent/prompts/game_hints.py`——这里只是消费方。


def _mask(obs: Observation, all_actions: list[str]) -> ActionSpace:
    """按这份观测的 overlay 算动作空间。**纯函数，不碰 world。**

    后置条件：`names` 非空。走投无路也必须给至少一个动作——
        空动作空间是这一层的 bug，不能推给大脑处理。

    `get_action_space()` 和 `execute()` 共用它，而**不是让后者去调前者**：
    那会在一次权限守卫调用里再触发一次守卫，审计流里多一条没有意义的记录。
    掩码本身不是一个需要授权的动作，需要授权的是"向外交出动作空间"。
    """
    overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
    names = [a for a in OVERLAY_ACTIONS[overlay] if a in all_actions]

    assert names, f"action space must never be empty (overlay={overlay})"
    return ActionSpace(
        names=names,
        descriptions=dict(BUTTON_HELP[overlay]),
        note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
    )


class GameTools:
    """`GameToolPort` 的唯一实现。持有 world，**不持有记忆**。"""

    def __init__(self, world: WorldPort) -> None:
        """接好世界。**本对象没有状态。**

        这里曾经有一个 `_last_space`（上次交出去的动作空间 + 当时的帧哈希），
        用来在 `execute()` 里验动作合法、并判断那份掩码有没有过期。
        现在两件事都由参数回答：`execute(action, obs)` 收下"这个动作是按哪份观测
        选的"，就地用同一个纯函数重算一遍掩码去校验——攒起来再回头取，就得额外
        发明一个办法判断攒的那份还新不新，而调用方本来就知道答案。
        """
        self._world = world

    # ---- GameToolPort ----

    @require_permission("execute:game:reset")
    @require_permission("execute:llm:perception")
    def reset(self, task: Task) -> PerceptionResult:
        """开新一局。

        开新一局，返回第一帧观测。
        """
        return self._world.reset(task)

    @require_permission("execute:game:save_state")
    def save_state(self, path: str) -> None:
        """把当前世界状态存成一个文件。"""
        self._world.save_state(path)

    @require_permission("read:game:action_space")
    def get_action_space(self, obs: Observation) -> ActionSpace:
        """掩码发生在这里，**只看 obs 里的 overlay**。

        前置条件：`obs` 是调用方当下正在依据的那份观测。
        后置条件：names 非空。走投无路也必须给至少一个动作——
            空动作空间是这一层的 bug，不能推给大脑处理。

        **这是一个纯函数，不碰 world。** 它曾经自己去 `world.observe()` 取一份
        观测，只为了读 `facts["overlay"]` 这一个字段——那一次感知完全是多余的，
        当年靠帧缓存挡住才没花钱。掩码的依据应该由调用方交出来：它按哪份观测
        做的决策，就该拿哪份观测算动作空间。这样"用过期的掩码"在结构上不可能发生，
        不需要运行时比对帧哈希去发现。

        按这份观测的 overlay 给出能按的键。
        """
        return _mask(obs, self._world.all_actions())

    @require_permission("execute:game:press")
    @require_permission("execute:llm:perception")
    def execute(self, action: Action, obs: Observation) -> ToolResult:
        """执行动作，推进世界。

        前置条件：`obs` 是这个动作**据以选出**的那份观测。
        后置条件：`result.observation` 非空。

        **依据由调用方交出来，不由本对象攒着。** 这里曾经有一个 `_last_space`
        实例变量，存着上次算的动作空间和当时的帧哈希，执行时比对帧哈希来防止
        "拿过期的掩码去按键"。攒起来再回头取，就得额外发明一个办法去判断攒的
        那份还新不新——而调用方本来就知道自己按的是哪份观测，让它说出来即可。

        校验动作合法后按下去，推进世界。
        """
        space = _mask(obs, self._world.all_actions())
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

        assert result.observation is not None, "world.step() must return the new observation"
        return result
