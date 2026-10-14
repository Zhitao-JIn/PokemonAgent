"""`format_form` 的用法示范：多行值不转义、嵌套缩进、空字段不渲染。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from pokemon_agent.harness.review_render import format_form


class _Phase(Enum):
    MOVE = "move"


class _Step(BaseModel):
    """miniature 版 `Task`：多行 goal + 枚举 + 可选空字段，够撑起每条渲染规则。"""

    task_id: str
    goal: str = Field(description="多行散文")
    phase: _Phase = _Phase.MOVE
    note: str = ""


class _Plan(BaseModel):
    """miniature 版 `Decomposition`：模型列表 + 顶层标量。"""

    why: str
    steps: list[_Step]
    max_steps: int = 8


def test_format_form_keeps_real_newlines_and_indents_nesting() -> None:
    form = _Plan(
        why="先走到草地",
        steps=[_Step(task_id="t1", goal="向北走一步\n判据：y 变小", phase=_Phase.MOVE)],
    )

    text = format_form(form)

    # 多行值原样保留，没有字面 \n；续行对齐到值那一列（缩进 4 + "goal: " 6 格 = 10 格）。
    assert "\\n" not in text
    assert "goal: 向北走一步\n          判据：y 变小" in text
    # 嵌套列表带序号缩进，枚举渲染成成员值而不是 `Enum.MEMBER`。
    assert "steps:\n  [1]\n    task_id: t1" in text
    assert "phase: move" in text
    # 空可选字段不打出来。
    assert "note" not in text


def test_format_form_falls_back_to_str_for_non_models() -> None:
    assert format_form("随手一句话") == "随手一句话"
