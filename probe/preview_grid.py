"""把网格叠到一张截图上存出来，**先用眼睛看，再花钱调模型**。

    python -m probe.preview_grid screenshot/frame_003.png
    python -m probe.preview_grid screenshot/frame_003.png --alpha 0.3 --origin 8,0

存到同目录下的 `*_grid.png`。

存在的理由很实在：网格参数（格子大小、原点偏移、线的深浅）是**看得出来对不对**的，
而拿模型准确率去反推这些参数，一轮就是几十次调用和十几分钟。眼睛零成本。

要确认的三件事，按重要性排：

1. **格子边界压在地图格子的接缝上吗？** 压不上就说明 `origin` 猜错了，
   或者滚动时边界会动——那样网格非但没用，还会把每个格子切成四份。
2. **线会不会盖掉关键像素？** 栅栏、断崖边缘是靠几个边缘像素辨认的，
   线太实会连人带证据一起盖掉。调 `--alpha`。
3. **边框上的行列号看得清吗？** 看不清就是白加了 14 像素。
"""

from __future__ import annotations

import pathlib
import sys

from pokemon_agent.vision.preprocess import GridOverlay


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    src = pathlib.Path(argv[0])
    if not src.is_file():
        print(f"找不到文件：{src}")
        return 1

    kw: dict[str, object] = {}
    rest = argv[1:]
    for flag, value in zip(rest[::2], rest[1::2], strict=False):
        key = flag.lstrip("-")
        if key == "alpha":
            kw["alpha"] = float(value)
        elif key == "cell":
            kw["cell"] = int(value)
        elif key == "margin":
            kw["margin"] = int(value)
        elif key == "origin":
            x, _, y = value.partition(",")
            kw["origin"] = (int(x), int(y))
        else:
            print(f"未知参数 {flag}")
            return 2

    overlay = GridOverlay(**kw)  # type: ignore[arg-type]
    out = src.with_name(f"{src.stem}_grid.png")
    out.write_bytes(overlay(src.read_bytes()))

    print(f"写出 {out}")
    print("参数：" + "  ".join(f"{k}={v}" for k, v in overlay.config().items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
