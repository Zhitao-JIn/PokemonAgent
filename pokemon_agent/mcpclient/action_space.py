"""动作掩码的 prompt 文案适配，供进程内与 MCP 门面共用。"""

from __future__ import annotations

from pokemon_agent.direct.prompts import BUTTON_HELP, MAP_HINT, REPEAT_HINT
from pokemon_agent.world import ActionSpace, Facts, TaskObservation
from pokemon_agent.world.action_space import compute_action_space


def with_prompt_text(space: ActionSpace, obs: TaskObservation) -> ActionSpace:
    """补按键说明、连按用法与地图规则，不改 names / mask / entries。

    调用方保证 space 对应 obs；空 names 原样返回，其余返回带文案的副本。
    文案只取既有常量，按 overlay 与 covered_by_script 选择，不使用每帧数据。
    """
    if not space.names:
        return space
    overlay = obs.facts.overlay or Facts.Overlay.NONE
    return space.model_copy(
        update={
            "descriptions": {
                name: BUTTON_HELP[overlay].get(name, BUTTON_HELP[Facts.Overlay.NONE].get(name, ""))
                for name in space.names
            },
            "note": REPEAT_HINT,
            "map_note": "" if obs.covered_by_script else MAP_HINT,
        }
    )


def action_space_for(obs: TaskObservation, all_actions: list[str]) -> ActionSpace:
    """计算掩码后补文案；调用方提供本帧观测与后端支持的全部按键。

    掩码计算失败时原样抛出契约错误；成功时保留 world 产出的全部能力条目。
    """
    return with_prompt_text(compute_action_space(obs, all_actions), obs)
