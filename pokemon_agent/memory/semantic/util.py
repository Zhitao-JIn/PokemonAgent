"""纯函数：算坐标、解析当帧地标。**不碰任何存储状态**——这是它们和
`memory/semantic/object_store.py`（有状态的 `_objects` 字典）的唯一区别，
也是拆成单独文件的理由：纯函数可以脱离"有没有建过档"单独测试和复用，
将来别的语义记忆类别要用同样的"查一圈"逻辑时，不需要牵连任何存储实现。
"""

from __future__ import annotations

from pokemon_agent.schemas.observation import FACING_STEP, Landmark, Observation, Place


def surrounding_cells(place: Place) -> list[Place]:
    """`place` **脚下这格 + 四个相邻格**，一共 5 格。

    这是一次方向键按下去唯一可能影响到的范围——按键要么改变自己脚下这格
    的状态（踩在门上朝外按），要么作用在某个相邻格上（从旁边推）。
    `FACING_STEP` 只有四个朝向，穷尽，不需要再单独判断"往哪边扩展"。

    叫 `surrounding_cells` 不叫 `ring`：这五格是"十"字形（含中心），
    不是环——严格意义上的"一圈"应该排除中心，而中心（脚下）恰恰是
    最容易被漏掉、也最要紧的一格（人物精灵盖住它，当帧 `landmarks` 报不出来）。
    名字里不该带一个会让人以为"脚下不算"的词。

    给出脚下这格加四邻，一共五格。
    """
    return [place] + [
        Place(map_id=place.map_id, x=place.x + dx, y=place.y + dy)
        for dx, dy in FACING_STEP.values()
    ]


def parse_landmarks(obs: Observation) -> list[Landmark]:
    """把 `obs.facts["landmarks"]` 那一行读回结构化的 `Landmark` 列表。

    **只在这里解析一次**，而且解析的是我们自己刚渲染出去的格式
    （`门 x=13 y=5; 人 x=2 y=7`）。真正干净的做法是让 `Observation` 直接带
    结构化的 landmarks，但那要给跨层契约再加一个字段，而目前只有语义记忆
    这一个消费方——等第二个消费方出现再提上去。

    把 facts 里的地标那一行读回结构化列表。
    """
    if obs.place is None:
        return []
    out: list[Landmark] = []
    for item in obs.facts.get("landmarks", "").split("; "):
        parts = item.split()
        if len(parts) != 3 or not parts[1].startswith("x=") or not parts[2].startswith("y="):
            continue
        out.append(Landmark(
            kind=parts[0],
            place=Place(map_id=obs.place.map_id,
                        x=int(parts[1][2:]), y=int(parts[2][2:])),
        ))
    return out


def kind_in_frame(obs: Observation, place: Place, interactive: tuple[str, ...]) -> str | None:
    """**只看当帧**：`place` 这一格在这一帧的 `landmarks` 里是什么。认不出来返回 `None`。

    这是 `kind_at`（在 `object_store.py` 里，档案兜底那一半）拆出来的**当帧那一半**——
    拆开是因为这一半是无状态的纯查询，档案那一半要碰 `_objects`，两者的
    可信来源也不同：这一半答的是"这一帧确实看见了"，另一半答的是
    "我以前见过那里有什么"（当帧看不见时补上，比如人物精灵盖住了脚下的门）。

    看这一格在这一帧里是什么类型。
    """
    for mark in parse_landmarks(obs):
        if mark.place.key == place.key and mark.kind in interactive:
            return mark.kind
    return None
