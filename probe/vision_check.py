"""探针之三：验证感知链路能不能真的把图片送到模型。

和前两个探针的区别：**这个走的是产品代码**（`pokemon_agent.providers.dashscope.QwenVision`），
不是另写一套 HTTP 调用。所以它通过 = 真实感知链路通过，而不是"另一条路能通"。

它回答三个问题：
  1. 图片有没有真的送达（靠 `ImageNotDelivered` 自动判定，不用你数 token）
  2. 模型读不读得出 160×144 的 GB 像素画面（看它抄出来的文字对不对）
  3. 一帧感知值多少钱（token 数 × 单价，这是简历上"单 episode 成本"的感知部分）

用法（PowerShell）：
    $env:DASHSCOPE_API_KEY = "sk-..."
    python probe/vision_check.py                                  # 自动挑 screenshots/ 第一张
    python probe/vision_check.py "screenshots/xxx.png"
    python probe/vision_check.py "screenshots/xxx.png" qwen3-vl-plus
"""

from __future__ import annotations

import pathlib
import sys

from pokemon_agent.errors import ImageNotDelivered
from pokemon_agent.providers.dashscope import QwenVision

# 元/百万 token（华北2，2026-08）。用来把 token 数换算成钱。
PRICES: dict[str, tuple[float, float]] = {
    "qwen3-vl-flash": (0.15, 1.5),
    "qwen3-vl-plus": (1.0, 10.0),
    "qwen-vl-plus": (1.0, 10.0),
}

PROMPT = (
    "这是一张 Game Boy 游戏截图。请做两件事：\n"
    "1. 用一句话说明画面里有什么。\n"
    "2. 原样抄出画面中出现的所有文字，一行一条，不要翻译、不要补全、不要猜。"
)


def check(model: str, image: pathlib.Path) -> bool:
    """跑一次感知。返回是否通过。"""
    print(f"── {model}")
    try:
        result = QwenVision(model=model).describe(image.read_bytes(), PROMPT)
    except ImageNotDelivered as e:
        print(f"   ❌ 图被静默丢弃：{e}")
        print("      → 这个模型/端点组合不可用。回答再合理也是幻觉，不要采信。")
        return False
    except Exception as e:  # noqa: BLE001  探针：任何失败都只需看清楚原因
        print(f"   ❌ {type(e).__name__}: {str(e)[:300]}")
        return False

    print(f"   ✅ 图片已送达   input={result.input_tokens} output={result.output_tokens}")

    if model in PRICES:
        p_in, p_out = PRICES[model]
        yuan = (result.input_tokens * p_in + result.output_tokens * p_out) / 1_000_000
        print(f"      单帧成本 ≈ {yuan:.6f} 元    → 1万步 ≈ {yuan * 10_000:.2f} 元")

    print("      ---- 模型读到的 ----")
    for line in result.text.strip().splitlines():
        if line.strip():
            print(f"      {line.strip()}")
    print("      --------------------")
    return True


def main() -> None:
    if len(sys.argv) > 1:
        image = pathlib.Path(sys.argv[1])
    else:
        shots = sorted(pathlib.Path("screenshots").glob("*.png"))
        if not shots:
            sys.exit("screenshots/ 下没有 png，先在 PyBoy 里按 O 截几张。")
        image = shots[0]

    if not image.is_file():
        sys.exit(f"找不到文件：{image}")

    models = [sys.argv[2]] if len(sys.argv) > 2 else ["qwen3-vl-flash", "qwen3-vl-plus"]

    print(f"图片: {image}  ({image.stat().st_size} 字节)\n")
    passed = [m for m in models if check(m, image)]
    print()

    if not passed:
        print("结论：没有一个模型收到图。感知链路当前不可用——")
        print("      别往上接 ScreenState，先解决送达问题（换端点 / 换模型 / 退回 CV 方案）。")
        sys.exit(1)

    print(f"结论：{len(passed)}/{len(models)} 通过 → {', '.join(passed)}")
    print("      对照画面核一下抄出来的文字：全对 = 熔断第一关过；")
    print("      读错或漏读 = 记下来，那正是熔断要量化的东西。")


if __name__ == "__main__":
    main()
