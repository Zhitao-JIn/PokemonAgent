# 基础按键在所有场合开放（缺陷修复说明）

状态：用户已确认（2026-10-14）。前序：提交 `4d38f48`（所有场合开放方向键）。

## 根因
短目标评测第 8 例"选 FIGHT 打开招式列表"、第 10 例"打开宝可梦列表"要求在战斗行动菜单按 a 只打开列表；
脚本接管场合 a 关闭，`battle_fight` / `battle_switch` 会直接出招/换人，无法等价。目标与动作空间冲突。
用户的裁决：方向键、a 这类基础按键不该按场合关闭，应一律开放，脚本只是在其上的快捷方式。

## 决定
- 定义基础按键 `BASIC_KEYS = up, down, left, right, a, b`（放 `world/interface/domain/action_semantics.py`，与 `DIRECTION_KEYS` 同处；`DIRECTION_KEYS` 保留）。
- `compute_action_space`：所有场合、所有叠加层，`names` 都含后端支持的基础按键；脚本接管场合除基础按键外没有别的键；非接管场合在此之上仍按 `OVERLAY_ACTIONS` 追加 `start`（NONE 与 CHOICE）。
  结果：DIALOG 由 `a`（加 `4d38f48` 的方向键）变为方向键 + a + b；接管场合由"方向键"变为方向键 + a + b；start / select 规则不变（接管场合与 DIALOG 仍关闭，select 一直不在任何集合里）。
- 理由与代价：b 开放后模型可能手动退出菜单、a 可能误确认；但键的后果由下一帧证据判断，脚本本身也用 B 回初态，掩码只管"能不能按"，不替模型判断"该不该按"（与 `4d38f48` 同一原则）。
- 代码落点唯一：`pokemon_agent/world/action_space.py`（掩码唯一出处）；门面 `mcpclient/game_tools.py::_action_space` 只补文案，不改掩码。
- 文案：`button_help.md` 给接管场合与对话场合补 a / b 的按键说明（a 确认当前光标项或推进对话，可能执行选项；b 取消/返回；目标只要求打开列表或移动光标时，达到后停手）；`decide_action.md` "方向键在所有场合都可用"改为"方向键、a、b 在所有场合都可用"，保留"目标只要求移动光标/打开列表就不要执行选项"的约束；`decide_script.md` 的"你不直接按键"改为"选脚本时你不直接按键"；`button_help.md` 对话一节的措辞与新掩码保持一致。
- 文档：`docs/spec/world/SPEC.md`（2026-10-14 全场合方向键一节改为"基础按键"、`OVERLAY_ACTIONS` 说明、掩码说明、ActionSpace 行）、`docs/spec/tools/SPEC.md`、`CHANGELOG.md`（新编号 450）。
- 测试：`tests/` 下断言接管场合或 DIALOG 的 `names` / mask 的用例，期望改为新规则；新增：接管场合 a、b 为 True 且脚本仍在，start / select 为 False；DIALOG 含方向键 + a + b；NONE / CHOICE 含 start。

## 提交信息
`fix(world): 2026-10-14（450）—— 基础按键在所有场合开放`

## 停止条件
- 需要触及 `compute_action_space` 以外的掩码逻辑，或 `state_schema_hash` 变化。
- 任何测试失败（不设例外）。
- 无模型验证做不到：用模拟器在战斗行动菜单按 a 打开招式列表、按 b 退回、再调用脚本，确认三者都能执行；第 10 例的队伍列表同样。
- 需要真实模型调用才能验证。

## 非目标
不开放 start / select 到接管场合；不改脚本实现、解码器、数据集。
