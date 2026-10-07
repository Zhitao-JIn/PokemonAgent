"""`ScreenText`：从模拟器内存（屏幕 tile 缓冲 + 战斗标志）确定性读出的屏幕文字。

`screen_text.read_screen_text` 的产出 schema。它让 RAM 档感知也能交出
对话、选项与光标——这几样原来只有视觉模型给得出。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScreenText(BaseModel):
    """一帧屏幕上的文字事实。读不出的项留空，不猜。"""

    dialog_text: str = Field(
        default="", description="底部对话框里的文字（续页标记已去掉）；图鉴条目页的说明文字也算"
    )
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
    option_details: list[str] = Field(
        default_factory=list,
        description="与 `options` 一一对应的附注：数量（`× 4`）、价格（`¥200`）；"
        "没有附注的项为空串",
    )
    covered: bool = Field(
        default=True,
        description="解码是否完整覆盖了这一帧的选单：光标框有左边界、切得出选项、框里的字都分进了"
        "某个选项。没有光标的帧恒为 True。只进 trace 做统计，不决定调不调视觉",
    )
    has_cursor: bool = Field(default=False, description="屏幕上有没有 `▶`（等待输入的光标）")
    quantity_box: bool = Field(default=False, description="屏幕上有没有数量框（`×01` 这种）")
    strict_dialog: bool = Field(
        default=False,
        description="严格的对话帧：底部对话框画着（空框也算，字可能还没打出来）、没有 `▶`、"
        "没有数量框、对话框外没有别的框",
    )
    screen: str = Field(
        default="",
        description="整屏逐行渲成的文字（`screen_text.render_screen`），与切好的字段互相校验",
    )

    def render_details(self) -> str:
        """有附注的选项渲染成 `选项 附注`，用 ` / ` 连接；一个附注都没有时为空串。"""
        pairs = zip(self.options, self.option_details, strict=False)
        return " / ".join(f"{option} {detail}" for option, detail in pairs if detail)

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
