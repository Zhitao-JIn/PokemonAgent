"""`EpisodeHarness` 与 `MemoryToolPort`（记忆）交互专用的工具函数。

**只放这一根依赖会用到的纯计算**——跟 `game_utils.py`/`brain_utils.py`
是同一个原则在 harness 各根依赖上各自的落地。这里全是纯函数：从
`ObservationFromWorld`/`StepMemory` 这些已经在契约内的对象拼出检索用的
query 字符串，交给调用方去调 `MemoryToolPort` 的查询方法——**不碰
`MemoryToolPort` 本身**，不属于数据结构转换（那是 `tools/memory_tool.py`
的活），纯粹是"编排已经在契约内的对象"。
"""

from __future__ import annotations

from pokemon_agent.schemas.memory import StepMemory
from pokemon_agent.schemas.world import ObservationFromWorld


def build_knowledge_query(obs: ObservationFromWorld, goal: str) -> str:
    """拼知识库检索 query：observation 特征 + goal，不只按 goal 检索。

    只按 goal（"走到镇长家"）时，战斗/菜单类先验（2×2 行动菜单、a 确认 b 取消）
    在 BM25 里匹配不上——agent 在战斗里全靠猜，犯过"down×3 当 RUN""用 b 当确认"
    这类错（knowledge 里都有，就是没被检索到）。
    """
    bits = [
        f"scene:{obs.facts.get('scene', '')}",
        f"overlay:{obs.facts.get('overlay', '')}",
        obs.status,
    ]
    if obs.place is not None:
        bits.append(f"map:{obs.place.map_id}")
    return " ".join(filter(None, bits + [f"目标：{goal}"]))


def build_verify_knowledge_query(entries: list[StepMemory], goal: str) -> str:
    """拼校验器的知识检索 query：整局 step 记忆的 scene/overlay/动作特征并集 + goal。

    跟 `build_knowledge_query` 同一个教训——只按 goal 检索时战斗/菜单类先验在
    BM25 里匹配不上。校验器手里没有单一 observation（它审的是整局），所以这里
    取整局 entries 的 before/after scene/overlay 加动作描述的并集，覆盖这一局
    实际经过的所有场景，而不是只覆盖终局那一帧。
    """
    scenes: set[str] = set()
    overlays: set[str] = set()
    actions: set[str] = set()
    for entry in entries:
        for obs in (entry.before, entry.after):
            if obs.facts.get("scene"):
                scenes.add(obs.facts["scene"])
            if obs.facts.get("overlay"):
                overlays.add(obs.facts["overlay"])
        actions.add(entry.action)
    bits = (
        [f"scene:{s}" for s in sorted(scenes)]
        + [f"overlay:{s}" for s in sorted(overlays)]
        + [f"action:{a}" for a in sorted(actions)]
    )
    return " ".join(bits + [f"目标：{goal}"])


def build_scene_key(obs: ObservationFromWorld) -> str | None:
    """拼跨局摘要检索用的场景键；`obs.place` 为 None 时没有场景可过滤，返回 None。"""
    if obs.place is None:
        return None
    return "|".join(
        filter(
            None,
            (
                f"map:{obs.place.map_id}",
                f"scene:{obs.facts.get('scene', '')}",
                f"overlay:{obs.facts.get('overlay', '')}",
            ),
        )
    )
