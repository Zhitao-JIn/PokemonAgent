"""动作命中与合法性的纯函数；只消费冻结 matcher 与 world 给出的掩码。"""

from evals.dataset.brain_choose import ActionMatcher
from pokemon_agent.brain.interface import Action
from pokemon_agent.world import ActionSpace


def matches(action: Action, acceptable: list[ActionMatcher]) -> bool:
    """脚本按参数子集匹配；按键链每段都须命中且不超次数，空动作不命中。"""
    if action.script is not None:
        return any(
            matcher.script == action.script.name
            and (
                matcher.args is None
                or all(
                    key in action.script.args and action.script.args[key] == value
                    for key, value in matcher.args.items()
                )
            )
            for matcher in acceptable
        )
    return bool(action.sequence) and all(
        any(
            matcher.key == segment.name
            and (matcher.max_times is None or segment.times <= matcher.max_times)
            for matcher in acceptable
        )
        for segment in action.sequence
    )


def is_legal(action: Action, space: ActionSpace) -> bool:
    """每个动作名必须在原始 mask 中 enabled；不重算、不补全或放宽掩码。"""
    if action.script is not None:
        return space.enabled(action.script.name)
    return bool(action.sequence) and all(space.enabled(segment.name) for segment in action.sequence)
