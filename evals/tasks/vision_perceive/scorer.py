"""视觉五字段对人工标注；缺标注记 NOANSWER，不进入分母。"""

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.core.judged import judged_accuracy, judged_count
from evals.core.snapshot import SnapshotMemory, snapshot_of
from evals.data.screen_reading.schemas import ScreenLabel, ScreenSample
from pokemon_agent.world import Facts
from pokemon_agent.world.ram import OVERWORLD_TILESET, W_CUR_MAP_TILESET

from .schemas import SCORE_KEYS, FieldVerdict, PerceiveRun, PerceiveRunRecord

S = Facts.Scene
SCENE_TRUTH: dict[str, Facts.Scene] = {
    "battle": S.BATTLE,
    "battle_menu": S.BATTLE,
    "faint_switch": S.BATTLE,
    "shop_items": S.SHOP,
    "shop": S.INDOOR,
    "start_menu": S.MENU,
    "bag": S.MENU,
    "party": S.MENU,
    "pokemon_info": S.MENU,
    "naming": S.NAMING,
    "transition": S.TRANSITION,
}
"""task 层场合 → episode 层场景；`walk` / `dialog` 另按 tileset 定，不在表里的不判。"""
ON_MAP = ("walk", "dialog")
NA = FieldVerdict(value="N")


def judge_facts(sample: ScreenSample, run: PerceiveRun) -> dict[str, FieldVerdict]:
    """逐列判一帧（列见 `SCORE_KEYS`）。

    尝试失败（解析不出）时：这一帧可判的视觉列一律判负、内存列记 N、`parsed` 判负。
    """
    memory = snapshot_of(sample)[1] if sample.wram else None
    label = sample.label
    is_dialog = label.overlay == "dialog"
    has_options = label.overlay == "choice" and bool(label.options)
    has_cursor = label.overlay == "choice" and bool(label.cursor)
    if run.facts is None:
        failed = FieldVerdict(value="I", got=run.failure)
        judgeable = {
            "scene": _scene_truth(label, memory) is not None,
            "overlay": True,
            "dialog_text": is_dialog,
            "options": has_options,
            "cursor": has_cursor,
            "ram_fields": False,
            "parsed": True,
        }
        return {key: failed if judgeable[key] else NA for key in SCORE_KEYS}
    facts = run.facts
    return {
        "scene": _judge_scene(facts, label, memory),
        "overlay": _same(facts.overlay, label.overlay),
        "dialog_text": _when(is_dialog, _flat(facts.dialog_text), _flat(label.dialog_text)),
        "options": _when(has_options, _flats(facts.options), _flats(label.options)),
        "cursor": _when(has_cursor, _flat(facts.cursor or ""), _flat(label.cursor)),
        "parsed": FieldVerdict(value="C"),
    }


def _judge_scene(facts: Facts, label: ScreenLabel, memory: SnapshotMemory | None) -> FieldVerdict:
    """场景：标注换成 `Facts.Scene` 再比；换不过去记 N。"""
    want = _scene_truth(label, memory)
    return NA if want is None else _same(facts.scene, want)


def _scene_truth(label: ScreenLabel, memory: SnapshotMemory | None) -> Facts.Scene | None:
    """标注场合 → episode 层场景；走路 / 对话按 tileset 分野外与室内；换不过去为 None。"""
    if label.scene in ON_MAP:
        if memory is None:
            return None
        return S.FIELD if memory[W_CUR_MAP_TILESET] == OVERWORLD_TILESET else S.INDOOR
    return SCENE_TRUTH.get(label.scene)


def _same(got: object, want: object) -> FieldVerdict:
    """相等即 C。"""
    return FieldVerdict(value="C" if got == want else "I", got=str(got), want=str(want))


def _when(applicable: bool, got: object, want: object) -> FieldVerdict:
    """这一帧该项可判才比，否则 N。"""
    return _same(got, want) if applicable else NA


def _flats(texts: list[str]) -> list[str]:
    """逐项 `_flat`。"""
    return [_flat(t) for t in texts]


def _flat(text: str) -> str:
    """只规整空白（换行 / 连续空格）——与旧读屏测评同一口径。"""
    return " ".join(text.split())


@scorer(metrics={key: [judged_accuracy(), judged_count()] for key in SCORE_KEYS})
def perceive_scorer() -> Scorer:
    """把 `judge_facts` 的逐列判定翻成 inspect Score（每列一个 C / I / N）。"""

    async def score(state: TaskState, target: Target) -> Score:
        del target  # 真值在样本的标注与快照里
        run = store_as(PerceiveRunRecord).run
        assert run is not None, "solver 没有写 PerceiveRun"
        sample = ScreenSample.model_validate(state.metadata["sample"])
        verdicts = judge_facts(sample, run)
        wrong = [f"{k}: {v.got!r} ≠ {v.want!r}" for k, v in verdicts.items() if v.value == "I"]
        return Score(
            value={k: v.value for k, v in verdicts.items()},
            answer=str(run.facts.overlay) if run.facts else "failed",
            explanation="；".join(wrong) or "可判各项全对",
            metadata={
                "verdicts": {k: v.model_dump() for k, v in verdicts.items()},
                "raw": run.raw,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
            },
        )

    return score


__all__ = ["SCENE_TRUTH", "judge_facts", "perceive_scorer"]
