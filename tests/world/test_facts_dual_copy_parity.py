"""`Facts` 有两份副本，这份测试钉住它们**不许漂**。

## 为什么有两份

`world.interface.domain.facts.Facts` 是**真身**（世界子系统对外承诺的观测形状）；
`schemas.memory.datastore.act_memory.ActMemory.Observation.Facts` 是**快照版**
（记忆只存"当时看到的样子"，不依赖 world 的行为——铁律 2 的模块零依赖）。
两份类刻意互不引用，靠 `brain.brain.reflect()` 在构造 `ActMemory` 之前
把真身 `model_dump(mode="json")` 拍平后验证过去。

## 为什么要测

这份重复的**唯一正当性**是：两边渲染出**一模一样的文本**。
大脑要把"当前观测"和"记忆里的旧快照"逐行对照，同一个字段在两份里必须
出现在同一个相对位置、写同样的标签。任何一边偷偷改了字段名、顺序、
标签、或者对齐算法，对照就从"看哪一行变了"退化成"两份文本对不上"——
而这件事**不会报错**，只会让模型读到两个不同的世界。

字段集/顺序/渲染的漂移是静默的，所以在这里钉死。
"""

from __future__ import annotations

from pokemon_agent.schemas.memory.datastore.act_memory import ActMemory
from pokemon_agent.world import Observation
from pokemon_agent.world.interface.domain.facts import Facts

RealFacts = Facts
SnapFacts = ActMemory.Observation.Facts


def _real(scene, overlay, extra: dict[str, str]) -> Observation:
    """造一份真身观测：主要字段全给上，动态字段由 `extra` 注入。"""
    facts = RealFacts(
        scene=scene,
        overlay=overlay,
        where="地图12 x=16 y=13",
        facing="south",
        neighbors="北 G 南 N 西 N 东 G",
        landmarks=[
            RealFacts.Landmark(kind="人", map_id=12, x=15, y=13),
            RealFacts.Landmark(kind="招牌", map_id=12, x=12, y=9),
        ],
        dialog_text="你好，旅行者！" if overlay is RealFacts.Overlay.DIALOG else "",
        options=["是", "否"] if overlay is RealFacts.Overlay.CHOICE else [],
        cursor="是" if overlay is RealFacts.Overlay.CHOICE else None,
        walk_map="y=12 ....GGGG#.\ny=13 ##NGGG#.",
        map_id=12,
    )
    for key, value in extra.items():
        setattr(facts, key, value)
    return Observation(
        step=7, place=None, status="你在野外。", facts=facts, done=False, perceived=True
    )


def _to_snapshot(obs: Observation) -> ActMemory.Observation:
    """就是 `reflect()` 走的那条路：`model_dump(mode="json")` 再验证过去。"""
    return ActMemory.Observation.model_validate(obs.model_dump(mode="json"))


def _cases() -> list[tuple[str, Observation]]:
    return [
        (
            "野外+动态字段",
            _real(
                RealFacts.Scene.FIELD,
                RealFacts.Overlay.NONE,
                {"my_hp": "12/20", "foe_name": "小拉达"},
            ),
        ),
        (
            "对话中",
            _real(
                RealFacts.Scene.FIELD, RealFacts.Overlay.DIALOG, {"my_name": "RED", "my_level": "5"}
            ),
        ),
        (
            "选择框",
            _real(
                RealFacts.Scene.BATTLE,
                RealFacts.Overlay.CHOICE,
                {"my_hp": "3/20", "z_last": "没见过的字段"},
            ),
        ),
        ("空事实", _real(RealFacts.Scene.FIELD, RealFacts.Overlay.NONE, {})),
    ]


def test_dual_copy_declares_the_same_fields_in_the_same_order() -> None:
    """除旧记忆保留的 overview 外，字段名与顺序相同——顺序决定渲染行序。

    `scene`/`overlay` 的注解**允许**不同（真身是 Enum，快照是 str）：快照不需要
    枚举行为，只存文本值；这条差异是刻意的，所以这里只比字段名。
    """
    assert "overview" not in RealFacts.model_fields
    assert "overview" in SnapFacts.model_fields
    real_fields = [name for name in RealFacts.model_fields]
    snap_fields = [name for name in SnapFacts.model_fields if name != "overview"]

    assert snap_fields == real_fields, (
        "两份 Facts 的字段漂了——真身与快照渲染出的文本会不再可比：\n"
        f"  真身有而快照没有：{sorted(set(real_fields) - set(snap_fields))}\n"
        f"  快照有而真身没有：{sorted(set(snap_fields) - set(real_fields))}\n"
        f"  顺序不同：{real_fields} vs {snap_fields}"
    )


def test_snapshot_renders_byte_identical_text_to_the_real_one() -> None:
    """同一份观测过完 `reflect()` 那条转换路，两边渲染出的文本必须一字不差。"""
    for name, real in _cases():
        snapshot = _to_snapshot(real)

        assert snapshot.render() == real.render(), (
            f"用例「{name}」两边渲染不一致——大脑读到的当前观测与记忆里的旧快照"
            "会对不上，而对照失败是静默的：\n"
            f"--- 真身 ---\n{real.render()}\n"
            f"--- 快照 ---\n{snapshot.render()}"
        )


def test_dynamic_fields_survive_the_round_trip() -> None:
    """视觉模型自由给的字段（`extra="allow"`）必须原样穿过转换，不能掉。"""
    real = _real(
        RealFacts.Scene.FIELD, RealFacts.Overlay.NONE, {"my_hp": "12/20", "z_last": "没见过的字段"}
    )
    snapshot = _to_snapshot(real)

    assert snapshot.facts.model_extra == {"my_hp": "12/20", "z_last": "没见过的字段"}
    assert "my_hp" in snapshot.render(), "动态字段掉了——大脑会以为这一帧没有它"
    assert "没见过的字段" in snapshot.render(), "没见过的动态字段也该原样留着"


def test_snapshot_render_used_by_judge_drops_only_walk_map() -> None:
    """`judge` 看到的那份（`_render_obs`）只抹 `walk_map`，其余字段一个不少。

    抹它是因为它占一条记忆的 ~800 字符且同图内几乎不变；但"四邻"要给出来，
    否则撞墙判断没依据。这条测的是**抹的范围**——多抹一个字段，判定器就瞎一块。
    """
    real = _real(RealFacts.Scene.FIELD, RealFacts.Overlay.DIALOG, {"my_hp": "12/20"})
    text = ActMemory._render_obs(_to_snapshot(real))

    assert "walk_map" not in text
    assert "四邻" in text, "四邻是撞墙判断的唯一依据，不能一起抹掉"
    assert "对话" in text and "你好，旅行者！" in text, "对话框文本必须留着"
    assert "my_hp" in text, "动态字段必须留着"
    assert "地标" in text and "人 x=15 y=13" in text, "地标是坐标推理的依据"
