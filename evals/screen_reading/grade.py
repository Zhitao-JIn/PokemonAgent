"""逐项打分：精确匹配，只做空白与大小写无关的规整（`é` 等字符原样比）。"""

from __future__ import annotations

from .schemas import FIELDS, TAKEOVER_SCENES, ScreenAnswer, ScreenLabel


def _norm(text: str) -> str:
    """压空白、去首尾。大小写保留（游戏里大小写就是字面）。"""
    return " ".join(text.split())


def grade(answer: ScreenAnswer, label: ScreenLabel, *, with_scene: bool) -> dict[str, bool]:
    """每个字段对不对。

    `with_scene`：打不打界面种类（解码直出一列打，模型读后一列不打——种类是系统给的，不是模型读的）。
    标注是接管类界面时只打种类与是否在初态；`quantity` 只在标注有值时打分；v1 没标种类时不打种类。
    """
    scene_ok = {"scene": answer.scene == label.scene} if with_scene and label.scene else {}
    if label.scene in TAKEOVER_SCENES:
        start_ok = (
            {"at_start": answer.at_start == label.at_start} if label.at_start is not None else {}
        )
        return {**scene_ok, **start_ok}
    ok = {
        "overlay": answer.overlay == label.overlay,
        "dialog_text": _norm(answer.dialog_text) == _norm(label.dialog_text),
        "options": [_norm(o) for o in answer.options] == [_norm(o) for o in label.options],
        "cursor": _norm(answer.cursor) == _norm(label.cursor),
    }
    if label.quantity is not None:
        ok["quantity"] = answer.quantity == label.quantity
    ok = {**scene_ok, **ok}
    assert set(ok) <= set(FIELDS)
    return ok


__all__ = ["grade"]
