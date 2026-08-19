"""图像预处理插件 —— 送进视觉模型之前，先把图片改一改。

## 为什么是插件而不是写死在 provider 里

预处理和**问什么问题**是一对：问"north 是什么"时叠网格毫无意义，问"第 3 行第 4 列
那格能不能走"时网格是必需的。这一对将来还要一起换好几轮。

做成注入式的插件，换预处理不用碰 `QwenVision`，也不用碰 world；
而且它**进 manifest**（见 `config()`），所以任何一批数字都说得清是在哪种预处理下跑的。
这一点比代码整洁重要得多：预处理换了没记，前后两批准确率就没法比。

## 契约

    ImageFilter(png_bytes) -> png_bytes

进出都是 PNG 字节。**不是 PIL 对象**——那会让 provider 和 world 都被迫依赖 Pillow，
而它们本来只是在传一张图。多解码编码几次的开销（一张 160×144 的图，亚毫秒）
换掉一个跨三层的依赖，划算。
"""

from __future__ import annotations

import io
from typing import Protocol, runtime_checkable

from PIL import Image, ImageDraw, ImageFont

GB_SCREEN = (160, 144)
"""Game Boy 的屏幕尺寸。写在这里是给断言用的，不是给缩放用的。"""

METATILE = 16
"""宝可梦野外地图的格子边长（像素）。

Game Boy 的硬件 tile 是 8×8，但**红版野外地图的一格是 2×2 个硬件 tile**，
也就是 16×16。走一步 = 移动一格 = 画面平移 16 像素。
网格要对齐的是这个尺度，不是 8。
"""


@runtime_checkable
class ImageFilter(Protocol):
    """一次图像预处理。

    实现方必须满足：
    - **幂等于自身之外**：同样的输入永远给同样的输出（不许有随机、不许有时间）。
      感知链路的 temperature 已经钉死在 0，预处理再引入随机就前功尽弃。
    - `config()` 必须完整到"照着它能复现这次处理"，且不含任何密钥。
    """

    def __call__(self, png: bytes) -> bytes:
        """处理一张 PNG，返回一张 PNG。"""
        ...

    def config(self) -> dict[str, str]:
        """自报参数，进 run manifest。"""
        ...


class GridOverlay:
    """在画面上叠 16×16 的网格，并在**画面之外**的白边上标出行列号。

    ## 为什么标签放在边框外而不是画面里

    不放大的前提下（用户的决定：游戏像素保持 1:1），画面内没有任何地方能放下
    可辨认的数字——一个字符最少要 6×11 像素，而一格才 16×16，数字会盖掉半格内容，
    等于用一个假信息换一个标签。

    加白边不动游戏像素一个点：**它不是放大，是加画框。**

    ## 为什么网格线是半透明的

    1 像素的实线会吃掉每格 1/16 的宽度，而障碍物（栅栏、断崖边缘）恰恰是靠
    那几个边缘像素辨认的。按 `alpha` 和底下的像素混合，线看得见，底下的内容也还在。

    alpha 是可调的，因为"线要多显眼"这件事只能靠实测定——它会进 manifest。

    ## 关于 origin

    地图滚动时，格子边界不一定落在屏幕原点上。`origin` 是网格相对屏幕左上角的偏移。
    **默认 (0, 0) 是个假设，不是事实**——要拿真实截图验证过才能当结论。
    验不过就把它做成从画面测出来的量，而不是常数。
    """

    def __init__(
        self,
        *,
        cell: int = METATILE,
        origin: tuple[int, int] = (0, 0),
        color: tuple[int, int, int] = (255, 0, 0),
        alpha: float = 0.45,
        margin: int = 14,
        labels: bool = True,
    ) -> None:
        """
        前置条件：cell > 0；0 <= alpha <= 1；labels 为真时 margin >= 12
            （小于这个数字放不下一个两位数，标签会被裁掉——那属于"画了但没用"）。
        """
        assert cell > 0, f"cell must be > 0, got {cell}"
        assert 0.0 <= alpha <= 1.0, f"alpha out of range: {alpha}"
        assert 0 <= origin[0] < cell and 0 <= origin[1] < cell, (
            f"origin must be inside one cell, got {origin} with cell={cell}"
        )
        assert not labels or margin >= 12, (
            f"margin={margin} is too small for a two-digit label; "
            "either raise it or set labels=False"
        )

        self._cell = cell
        self._origin = origin
        self._color = color
        self._alpha = alpha
        self._margin = margin if labels else 0
        self._labels = labels

    def __call__(self, png: bytes) -> bytes:
        """叠网格。

        前置条件：png 非空且能被解码。
        后置条件：输出尺寸 = 原尺寸 + margin（左和上各一条），**游戏像素本身不缩放**。
        """
        assert png, "GridOverlay got an empty image"

        src = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = src.size
        m = self._margin

        canvas = Image.new("RGB", (w + m, h + m), (255, 255, 255))
        canvas.paste(src, (m, m))

        ox, oy = self._origin
        xs = list(range(ox, w + 1, self._cell))
        ys = list(range(oy, h + 1, self._cell))

        # 线色铺满一整层，再用一张只在线上开口的蒙版把它按 alpha 混进去。
        # 不直接用半透明画笔逐条画：那样交叉点会被混合两次、明显更深，
        # 模型看到的就成了一张有规律暗点的图——纯属我们自己造的干扰。
        lines = Image.new("RGB", canvas.size, self._color)
        mask = _line_mask(canvas.size, xs, ys, m, w, h, self._alpha)
        canvas = Image.composite(lines, canvas, mask)

        if self._labels:
            self._draw_labels(canvas, xs, ys, m)

        out = io.BytesIO()
        canvas.save(out, format="PNG")
        return out.getvalue()

    def _draw_labels(self, canvas: Image.Image, xs: list[int], ys: list[int], m: int) -> None:
        """列号写在上边框，行号写在左边框。都是 0 起——和 prompt 里的说法必须一致。"""
        pen = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        for col, x in enumerate(xs[:-1]):
            pen.text((m + x + 3, 1), str(col), fill=(0, 0, 0), font=font)
        for row, y in enumerate(ys[:-1]):
            pen.text((1, m + y + 3), str(row), fill=(0, 0, 0), font=font)

    def config(self) -> dict[str, str]:
        """进 manifest。**网格参数变了，感知准确率就不可比**，所以一个都不能少。"""
        return {
            "filter": "grid_overlay",
            "cell": str(self._cell),
            "origin": f"{self._origin[0]},{self._origin[1]}",
            "color": ",".join(str(c) for c in self._color),
            "alpha": str(self._alpha),
            "margin": str(self._margin),
            "labels": str(self._labels),
        }


def _line_mask(
    size: tuple[int, int], xs: list[int], ys: list[int],
    m: int, w: int, h: int, alpha: float,
) -> Image.Image:
    """只在网格线所在的像素上开 alpha，其余位置完全不动。

    单独抽出来是因为这是**唯一会改动游戏像素的地方**，值得能被单独看、单独测。
    """
    mask = Image.new("L", size, 0)
    pen = ImageDraw.Draw(mask)
    level = int(round(alpha * 255))
    for x in xs:
        pen.line([(m + x, m), (m + x, m + h - 1)], fill=level, width=1)
    for y in ys:
        pen.line([(m, m + y), (m + w - 1, m + y)], fill=level, width=1)
    return mask


def apply_all(png: bytes, filters: tuple[ImageFilter, ...]) -> bytes:
    """按顺序跑完一串过滤器。空串原样返回。

    顺序是有意义的（先叠网格再画标记 ≠ 反过来），所以是 tuple 不是 set。
    """
    for f in filters:
        png = f(png)
        assert png, f"{type(f).__name__} returned an empty image"
    return png
