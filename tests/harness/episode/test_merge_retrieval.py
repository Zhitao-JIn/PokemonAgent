"""`merge_retrieval` 的用法示范：**object 语义记忆折进观测的"动态字段"**。

这个文件钉一件事——"折进去"到底落在哪一格。0915 143903 那一局在真机上炸在这里：

    TypeError: 'Facts' object is not a mapping
    （`merge_retrieval.py:46`，`{**obs.facts, "known_objects": …}`）

`obs.facts` 是 `Facts`（Pydantic 模型、`extra="allow"`），**不是 `dict`**——那个
`{**…}` 是 `facts` 还是 `dict[str, str]` 的年代留下的写法。它一直没炸，只是因为
`if state.object_semantic_memory:` 这道门在那之前从没开过（前几局的目标都不涉及
可交互对象）；143903 的目标是"跟 NPC 说话"，object 记忆第一次非空，门一开就炸，
**整局 episode 直接 `run_error` 收场**。

以及它**该落在哪**：`known_objects` 走 `Facts` 的**动态字段**（`model_config` 是
`extra="allow"`，`Facts.exclude()` 就是为剥掉它而写的），不是具名字段。
所以正确写法是 `facts.model_copy(update={"known_objects": …})`——既不能进具名槽，
也不能 `model_dump()` 之后当关键字重新验证（那会 `ValidationError`）。

**用假 Runtime**：`merge_retrieval` 不调模型、不查库、不写账（见模块 docstring），
`runtime` 在这一格是签名上的占位。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.brain import Task
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.perceive.merge_retrieval import merge_retrieval
from pokemon_agent.world import Facts, Observation

OBJECT_MEMORY = "- 人 地图12 (16,13)：已互动 1 次、结果 无效果"


class _Runtime:
    """这一格用不上真 deps——给个占位，说明"没用到"比塞一堆假件更诚实。"""

    context: Any = None


def _state(object_memory: str) -> EpisodeRunState:
    return EpisodeRunState(
        run_id="r1",
        episode_id="r1-ep1",
        goal=Task(
            task_id="g1",
            goal="跟草丛里的 NPC 说话",
            success_criteria="画面出现 NPC 说的一句话",
            max_steps=20,
        ),
        ep_ctx=EpisodeContext(
            observation=Observation(
                step=3,
                status="你在野外。",
                facts=Facts(where="全局坐标 地图12 x=16 y=12", facing="south"),
            ),
            object_semantic_memory=object_memory,
        ),
    )


def test_object_memory_lands_in_the_dynamic_extra_not_in_named_fields() -> None:
    """有 object 记忆时它出现在 `facts.known_objects`，而具名字段一个不动。"""
    got = merge_retrieval(_state(OBJECT_MEMORY), _Runtime())

    facts = got["ep_ctx"].observation.facts

    assert facts.known_objects == OBJECT_MEMORY
    assert facts.model_extra == {"known_objects": OBJECT_MEMORY}
    assert facts.where == "全局坐标 地图12 x=16 y=12"
    assert facts.facing == "south"


def test_folded_key_is_strippable_so_it_never_lands_in_memory() -> None:
    """折进去的是"别处塞进来的检索结果"，写记忆前 `exclude()` 必须能剥掉它。"""
    facts = merge_retrieval(_state(OBJECT_MEMORY), _Runtime())["ep_ctx"].observation.facts

    clean = facts.exclude(frozenset({"known_objects"}))

    assert getattr(clean, "known_objects", None) is None
    assert not (clean.model_extra or {})
    assert clean.where == facts.where, "剥动态字段不该动具名字段"


def test_nothing_is_folded_when_object_memory_is_empty() -> None:
    """没查到时**这一帧原样返回**：不凭空塞一个空字段进 prompt。"""
    got = merge_retrieval(_state(""), _Runtime())

    assert got["ep_ctx"].observation == _state("").ep_ctx.observation
    assert not (got["ep_ctx"].observation.facts.model_extra or {})
