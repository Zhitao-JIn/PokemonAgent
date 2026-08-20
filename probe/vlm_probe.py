"""熔断：VLM 在 160×144 的 GB 像素画面上到底读不读得出来。

对每张帧调 `QwenVision` + `perceive_screen` prompt，解析成 `ScreenState`，
和真值比，输出三项准确率。走的是**产品代码**（`providers/` + `prompts/` + `schemas/`），
所以通过 = 真实感知链路通过。

## 三项判据（熔断只看第一项）

| 判据 | 门槛 | 不过怎么办 |
|---|---|---|
| **界面类型分类**（scene + overlay 都对） | ≥ 90% | **真熔断**，感知方案要改 |
| 对话框文字 | 关键信息不丢 | 降级：交给 CV 插件 OCR |
| 数值字段 | ≥ 80% | 降级：数值全交 CV，VLM 只做分类和文本 |

只有第一项是熔断，另外两项不过是降级不是停工。

## 真值从哪来

`probe/labels.json`。**它是 AI 标的初稿，必须人工核过才能拿来报数字**——
否则「我和被测模型都读错」的帧会被记成正确，系统性抬高分数。
所以跑完会列出**分歧清单**：只有那些帧的真值影响分数，核它们就够。

    python -m probe.vlm_probe                      # 默认 qwen3-vl-flash
    python -m probe.vlm_probe qwen3-vl-plus
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

from pokemon_agent.errors import ImageNotDelivered
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.providers.dashscope import QwenVision
from pokemon_agent.schemas.core import ScreenState

LABELS = pathlib.Path("probe/labels.json")
SHOTS = pathlib.Path("screenshots")
OUT = pathlib.Path("probe/results")


def parse(text: str) -> ScreenState | None:
    """把模型输出解析成 ScreenState。容忍 ```json 包裹，其余不兜底。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1].removeprefix("json").strip()
    try:
        return ScreenState.model_validate_json(t)
    except Exception:  # noqa: BLE001  解析失败本身就是一项要统计的结果
        return None


def norm(s: str) -> str:
    """文本比对前的归一化。

    实测两类假阴性，都不是模型读错：
    - 游戏里的 `é` 是特殊字形，我标成 `POKeMON`、模型给 `POKEMON`
    - 空格与标点在低分辨率下本就不可靠

    比对不归一化，量出来的是「我的标注习惯和模型的输出习惯像不像」，
    不是「它读对没读对」。
    """
    t = s.lower()
    for a, b in (("é", "e"), ("è", "e"), ("!", ""), ("?", ""), (".", ""), (",", "")):
        t = t.replace(a, b)
    return "".join(t.split())


def digits(s: str) -> str:
    """只留数字与斜杠，用来比 HP 这类值，忽略空格与全半角差异。"""
    return "".join(c for c in s if c.isdigit() or c == "/")


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3-vl-flash"

    if not LABELS.is_file():
        sys.exit(f"没有真值文件 {LABELS}。先生成标注。")
    truth = json.loads(LABELS.read_text(encoding="utf-8"))

    vision = QwenVision(model=model)
    prompt = load_prompt("perceive_screen")
    print(f"模型 {model} | prompt {prompt.sha} | {len(truth)} 帧\n")

    rows, disagree = [], []
    n_parse_ok = n_scene = n_overlay = n_both = 0
    n_dialog_total = n_dialog_ok = n_field_total = n_field_ok = 0
    tok_in = tok_out = 0
    t0 = time.time()

    for i, (name, want) in enumerate(sorted(truth.items()), 1):
        path = SHOTS / name
        if not path.is_file():
            print(f"  [{i:>2}] 缺文件 {name}")
            continue

        try:
            r = vision.describe(path.read_bytes(), prompt.text)
        except ImageNotDelivered as e:
            sys.exit(f"图被静默丢弃，全部结果不可信：{e}")

        tok_in += r.input_tokens
        tok_out += r.output_tokens
        got = parse(r.text)

        if got is None:
            print(f"  [{i:>2}] {name[-12:]}  解析失败")
            rows.append({"frame": name, "parse_ok": False, "raw": r.text})
            continue

        n_parse_ok += 1
        ok_scene = got.scene.value == want["scene"]
        ok_overlay = got.overlay.value == want["overlay"]
        n_scene += ok_scene
        n_overlay += ok_overlay
        n_both += ok_scene and ok_overlay

        if want.get("dialog_text"):
            n_dialog_total += 1
            n_dialog_ok += norm(want["dialog_text"]) in norm(got.dialog_text)

        for k, v in (want.get("fields") or {}).items():
            n_field_total += 1
            mine = got.fields.get(k, "")
            hit = digits(mine) == digits(v) if digits(v) else norm(mine) == norm(v)
            n_field_ok += hit

        both = ok_scene and ok_overlay
        want_pair = f"{want['scene']}/{want['overlay']}"
        got_pair = f"{got.scene.value}/{got.overlay.value}"
        tail = "" if both else f"   真值 {want_pair}"
        print(f"  [{i:>2}] {name[-12:]}  {'✓' if both else '✗'} {got_pair}{tail}")

        if not both:
            disagree.append((name, want_pair, got_pair))
        rows.append({"frame": name, "parse_ok": True, "got": got.model_dump(mode="json"),
                     "want": want, "in": r.input_tokens, "out": r.output_tokens})

    n = len(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{model}-{prompt.sha}.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 58)
    print(f"解析成功      {n_parse_ok}/{n}")
    print(f"scene 正确    {n_scene}/{n}")
    print(f"overlay 正确  {n_overlay}/{n}")
    print(f"**两者都对**  {n_both}/{n}  = {100 * n_both / max(n, 1):.1f}%   （门槛 90%）")
    if n_dialog_total:
        print(f"对话框文字    {n_dialog_ok}/{n_dialog_total}")
    if n_field_total:
        pct = 100 * n_field_ok / n_field_total
        print(f"字段值        {n_field_ok}/{n_field_total} = {pct:.1f}%   （门槛 80%）")
    print(f"\ntoken  in={tok_in} out={tok_out}   耗时 {time.time() - t0:.0f}s")
    print(f"明细     {out_path}")

    if disagree:
        print(f"\n=== 分歧清单（{len(disagree)} 张，只有这些的真值影响分数）===")
        for name, want, got in disagree:
            print(f"  {name}\n      真值 {want}   模型 {got}")
        print("\n核这些就够，外加随机抽几张一致的——防「两个都错但记成对」。")


if __name__ == "__main__":
    main()
