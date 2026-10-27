# intent —— 脚本内对话文字进账

> 流程位置：**intent.md**（待确认）→ spec → plan → 落码
> 关联：`docs/eval/mid_tasks/intent.md`（M1、M4 依赖本项）、`docs/eval_freeze/intent.md`（独立，不冲突）
> 状态：已确认（2026-10-27，用户答复：ActMemory 新增独立字段；对话不截断；不改等待逻辑）。

## 一、一句话意图

脚本执行过程中收到的对话文字，完整进入 `act_call` 账和 ActMemory，agent 与评分都能读到。

## 二、为什么

1. 现状：脚本每按一键都会把新出现的对话行收进 `DialogCache`（`pokemon_agent/world/scripts/dialog_cache.py`），但脚本结束后只剩"结局码加一行摘要"：`pokemon_agent/harness/task/script_report.py` 的 `result_line` 只取 `data.summary` 或 `data.reason`，`act_call` 账只有 `script`、`args`、`ok`、`code`、`events`，ActMemory 只有脚本前后各一帧。
2. 后果：一口气按完的对话（领包裹、长对话）中间的文字全部丢失，包裹事件是进店自动触发的过场，不是按键打在物体上，`events[]` 里也没有它。收件人 PROF. OAK 与 PALLET TOWN 这条证据因此可能从账里消失，M1、M4 的判据与记忆测试都会漏判。
3. 已核实的现场：`eval_results/full_eval_20261020_01/.../knowledge_wild_encounter/trace` 的脚本 `act_call` 只有上述几个字段。

## 三、做什么

1. 所有脚本的终态报告统一带一个顶层 `dialog`：本次调用累计的对话增量行，按出现顺序；脚本本身不改。
2. harness 把 `dialog` 完整写进 `act_call` 账的新字段，同时写进 ActMemory 的新字段，不截断。
3. 渲染进 prompt 时，ActMemory 的对话字段按行完整列出（新的 prompt 片段版本，旧版本不改）；token 增长靠 prompt 缓存承担，上线后看实测。
4. 对话增量按脚本调用去重（同一次调用内重复的行只记一次；跨调用不去重）。
5. 不改等待逻辑：每次按键仍按现有稳定检测读一次。

## 四、不做

- 不改按键后的等待与稳定检测，不逐帧读、不加 `▼` 检测；不截图。
- 不截断对话；不改 `events[]` 与对象记忆的写入规则；不改按键模式的行为。
- 不改机械判据本身；`customer_hint_purchase`、`parcel_delivered` 等需要读新字段的判据，在 mid 样本构建时另案加。

## 五、已定

- 对话在 ActMemory 里是新增独立字段，不拼进 `result`（用户已确认）。
- 去重沿用 `DialogCache` 现有行为：同一次调用内同一行只记一次（同一句话停在屏幕上跨好几次按键，不会重复记）。

## 六、影响面与风险

- 影响面：`pokemon_agent/world/scripts/engine.py`（`finish`）、脚本终态报告的契约、`pokemon_agent/harness/task/act/act.py`、`ActMemory` 记忆模式（`pokemon_agent/schemas/memory/datastore/act_memory.py`）、trace 的 `act_call` 字段、prompt 的 `memory_records` 片段（新版本）、对应测试。
- 风险：读侧（评分器、reviewer、trace 回放、记忆蒸馏）对 `act_call` 与 ActMemory 的字段假设；旧记忆文件缺新字段时按默认值读，不写兼容逻辑。

## 七、成功的样子

- 对一段多行对话跑一次 `advance_dialog`，`act_call.dialog` 恰好等于屏幕上依次出现的行；对应 ActMemory 含同样的行。
- 按键路径、对象记忆事件、等待时长与改动前一致。
- 领包裹那段进店对话，在账里能读到完整台词。
