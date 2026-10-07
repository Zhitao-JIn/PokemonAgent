# 帧真值标注交接（1007）

给接手标注的 AI。目标：给 `evals/data/frames/` 的 1045 帧补 decode 的独立真值，写进
`evals/data/frames/truth.jsonl`。试点 49 帧已标完并按用户裁决改过，见该文件 `note="pilot_1007"` 的行。

## 1. 标什么、不标什么

- **RAM 就是真值**。只标"RAM 里读不出、要靠解码规则才得出"的字段：
  - `scene_truth`：`scene`（TaskScene 词表）与 `at_start`（只接管场合填 true/false，常规场合填 null）。
  - `screen_truth`：`overlay`、`dialog_text`、`options`、`cursor`、`quantity_box` 里**定义明确**的那几个，
    拿不准的字段整个不写（scorer 只比较写了的键）。
- 判据是 RAM 的屏幕缓冲（WRAM 0xC3A0 起 20×18 tile）。截图只作辅助：capture 帧（`c-xxxx`）的截图
  与 RAM **不同刻**（对话逐字打出时截图落后、光标被擦掉的那一刻等），两者不一致一律以 RAM 为准。
  probe / takeover / terrain 帧是同刻采集。
- **不能**拿被测解码器的输出（帧里的 `label` 预标、`decode_frame` 的结果）当答案抄。先盲标，再跑 decode 对分歧。

## 2. 用户已裁决的规则（1007）

| 情形 | 结论 |
|---|---|
| 整屏 tile 全是空格 0x7F（开场白屏、战斗白闪） | `transition` |
| 地图边上露出黑边（tile 0x00 成片，房间外/地图外） | 不是过场，按所在场合（walk / shop…） |
| 只有一个空的底部对话框（字还没打出来） | `scene=dialog`（店里仍是 `shop`），`overlay=dialog`，`dialog_text=""` |
| 图鉴条目页的说明文字 | 算对话：进 `dialog_text`，`overlay=dialog`；场合仍是 `pokemon_info`（战斗中捕获后弹出的仍是 `battle`） |
| 空招式位 `-`、图鉴未见条目 `----------` | 算选项，按屏幕顺序放进 `options` |
| 命名键盘的结束键 | 记作 `ED`；框外 `lower case` 不算选项 |
| 命名键盘、队伍列表（naming / party / faint_switch）的光标与选项 | 屏幕解码读不出、由接管脚本自己读，**不标** `cursor` / `options`；场合、`at_start`、对话框文字照标。其余场合解码读得出的光标、选项照标 |
| 战斗中打开的能力页（EXP POINTS 那页） | `battle` |
| 光标被擦掉的帧 | 只标场合 |
| 屏上只有数量框、没有 `▶` 时的 `overlay` | `choice`：要用方向键调数量，DIALOG 的掩码只给 `a`；叠加层只决定掩码 |

`at_start` 的定义见 `pokemon_agent/world/scene.py::at_start`：本场合主菜单画着、有实心 `▶`、屏上没有空心 `▷`。

## 3. 写法

一行一帧，字段见 `evals/data/frames/schemas.py::FrameTruth`：

```json
{"sample_id": "c-0773", "labeler": "<你的标识>", "reviewed": false, "note": "<批次>",
 "scene_truth": {"scene": "battle", "at_start": null},
 "screen_truth": {"overlay": "dialog", "dialog_text": "BUG CATCHER sent out"}}
```

- `dialog_text`：对话框各行用一个空格连接，续页标记 `▼` 去掉，按 RAM 里已经打出的字（可能是半句）。
- `reviewed` 一律 `false`，由用户审后改 `true`；默认评分只读已审的行。
- 同一 `sample_id` 只能一行；帧文件里已有的同组真值（probe 的 `label_checked`、takeover / terrain 帧）不要重复标该组。

## 4. 流程

1. 按场合分层抽批（每批 50 帧左右），把 RAM 屏幕缓冲用 `pokemon_agent/world/screen_text.py::CHARMAP` 渲成文字逐帧看；需要时看截图。
2. 写进 `truth.jsonl`。
3. 跑分歧报告（不入库）：

```python
from evals.core.frames import load_frames
from evals.data.frames.truth import load_truth
from evals.tasks.decode.solver import decode_frame
from evals.tasks.decode.scorer import truth_for, compare_group
T = load_truth(include_unreviewed=True)
for f in load_frames(include_unreviewed=True):
    if f.sample_id not in T:
        continue
    run = decode_frame(f)
    for g in ("scene", "screen"):
        s = compare_group(getattr(run, g), truth_for(f, g))
        if s.value == "I":
            print(f.sample_id, g, s.explanation)
```

4. 分歧逐条复核 RAM：自己标错就改标注；确属解码器问题或规则没覆盖的情形，列给用户裁决，**不要**为了消分歧改解码器或改标注迁就。
5. 每批写一条 CHANGELOG（改了什么 / 为什么 / 取舍 / 影响面）。

## 5. 已知解码缺口（标注照实标，分歧留着）

- 图鉴列表（`start_menu` 下的 CONTENTS 页，光标在框外左侧）：解码给不出 `cursor` / `options`（试点 c-0423）。
- 队伍列表、选项页的旧 probe 人工标注（`p-field_party_list`、`p-battle_party_*`、`p-battle_use_on_which`、
  `p-option_screen`）与解码不一致，属于接管场合或待定，不在本轮处理。

## 6. 约束

不提交、不推送（等用户点头）；git 只读且带 `GIT_OPTIONAL_LOCKS=0`；不调真实模型；不动 ROADMAP 与冻结文档；
写新测试前先问；不碰用户存档 `assets/rom.ram`、`assets/rom.state`。
