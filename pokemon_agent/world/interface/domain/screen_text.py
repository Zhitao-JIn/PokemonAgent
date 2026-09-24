"""`ScreenText`：从模拟器内存（屏幕 tile 缓冲 + 战斗标志）确定性读出的屏幕文字。

`screen_text.read_screen_text` 的产出 schema。它让 RAM 档感知也能交出
对话、选项与光标——这几样原来只有视觉模型给得出。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScreenText(BaseModel):
    """一帧屏幕上的文字事实。读不出的项留空，不猜。"""

    dialog_text: str = Field(default="", description="底部对话框里的文字（续页标记已去掉）")
    options: list[str] = Field(default_factory=list, description="光标所在框里的选项，按屏幕顺序")
    cursor: str = Field(default="", description="光标（▶）指着的那一项；没有光标为空")
    option_grid: list[list[str]] = Field(
        default_factory=list,
        description="选项按屏幕排布分行：外层是行（自上而下），内层是该行从左到右的选项。"
        "竖排菜单每行一项；战斗菜单是 2×2",
    )
    cursor_cell: tuple[int, int] | None = Field(
        default=None, description="光标在 `option_grid` 里的 (行, 列)，从 0 起；没有光标为 None"
    )

    def render_layout(self) -> str:
        """把排布渲染成给决策读的一段：几行几列、光标在哪、方向键怎么走，再逐行列出选项。"""
        if not self.option_grid or self.cursor_cell is None:
            return ""
        rows, cols = len(self.option_grid), max(len(row) for row in self.option_grid)
        r, c = self.cursor_cell
        if cols == 1:
            head = f"竖排 {rows} 项，光标在第 {r + 1} 项；上/下 移动光标"
        elif rows == 1:
            head = f"横排 {cols} 项，光标在第 {c + 1} 项；左/右 移动光标"
        else:
            head = (
                f"{rows} 行 × {cols} 列，光标在第 {r + 1} 行第 {c + 1} 列；上/下 换行，左/右 换列"
            )
        lines = [
            "  ".join(
                ("▶" if (i, j) == self.cursor_cell else " ") + item for j, item in enumerate(row)
            )
            for i, row in enumerate(self.option_grid)
        ]
        return head + "\n" + "\n".join(lines)

    in_battle: bool = Field(default=False, description="战斗标志（wIsInBattle 非 0）")


__all__ = ["ScreenText"]
