# plan —— 删除视觉感知档

> 流程位置：intent → spec → **plan（本文）** → PR → production
> 关联：`remove-vision-intent.md`、`remove-vision-spec.md`（做什么、为什么）；本文只管**谁、何时、过什么关、出事怎么退**。
> 状态：v1.1（2026-10-16）：S0–S4 已完成并提交；S3/S4 的范围调整与哈希链见文末“2026-10-16 执行记录”；待执行：S5、对比跑、合入

---

## 一、角色

| 角色 | 负责 |
|---|---|
| 用户 | P0 提交（或授权执行模型提交）；S0 与 S5 的 `agent_short_goal_run` 及其费用确认；`state_schema_hash` 变化后重建 agent 存档；最终合入 |
| 执行模型 | P0 的测试与提交（用户授权时）；S1–S5 的全部代码、测试、文档改动与提交 |
| 我（设计侧） | 每步提交后核对 diff 与 spec 的一致性；裁决停止条件；对比报告的解读 |

## 二、顺序与依赖

```
P0 提交 442 ──► S0 基线 ──► S1 切换取帧 ──► S2 删调用链 ──► S3 删 world 视觉档 ──► S4 接线/配置/评测 ──► S5 测试文档 ──► 对比跑 ──► 合入
```

- 严格串行。S2 依赖 S1（sense 不再调 `perceive_with_retry` 才能删它），S3 依赖 S2（world 的 `perceive_once` 没有调用方才能删），S4 依赖 S3（`vision` 参数没有消费者才能去掉）。
- P0 必须先完成：本项与 442 改同一批文件（`mcpclient/game_tools.py`）。
- S0 的基线跑可与 P0 并行准备，但必须在 P0 提交后的 HEAD 上跑，否则基线不干净。

## 三、各步关卡（过不了不进下一步）

| 步 | 进入条件 | 完成关卡 | 我的核对点 |
|---|---|---|---|
| P0 | 无 | pytest 全绿、ruff 两项通过、`git status` 干净、代码与文档两个提交 | 提交范围未混入无关文件、行尾未整文件翻转 |
| S0 | P0 完成 | 基线目录名与 `state_schema_hash` 记录在案 | 基线确实在 442 之后的 HEAD |
| S1 | S0 完成 | 新增 4 类测试通过（TaskObservation 产出、无盲帧提示、场景键重查、序列化往返不丢 `scene`）；全量绿 | prompt 渲染无 None/空块；`_blind` 的处理是否合理 |
| S2 | S1 提交 | 全量绿；`grep perceive_with_retry` 只剩注释 | MCP tool 列表少一项，其余 tool 签名未变 |
| S3 | S2 提交 | 全量绿；spec 验证第 2 条的 grep 仅剩允许项；（v1.3）`evals/episode_vision_read` 随本步删除、评测列表为五项；`state_schema_hash` 变为 `4f1cac6fcc7216d5` 且同提交重打 v1 存档 | `world/`、`mcp_servers/` 下无 prompt 文件、无 `brain` import；`world.state` sha256 逐项不变 |
| S4 | S3 提交 | 全量绿；`config.json` 无 `vision_model`；`--vision-model` 参数消失；旧 manifest 仍能加载 | 判定器仍走 `judge_model`，brain 的 `describe()` 通道完好；存档未被改动 |
| S5 | S4 提交 | 全量绿；旧账读取验证通过；文档改写与历史标注就位；CHANGELOG 新条目 | 历史文档只加了文件头，正文未改 |
| 对比跑 | S5 提交 | 用户确认费用后跑完；基线与新结果并排表 | 调用数、耗时、通过率、失败样本 |

## 四、回退

- 每步一个提交，**回退即 `git revert` 该步提交**（不重写历史）。
- S1 是唯一改变行为的一步，也是对比跑里最可能暴露质量问题的一步。若对比跑显著变差：
  1. 不回滚 S2–S5（它们是纯删除，与质量无关）；
  2. 我们读失败样本的 sense 帧渲染，判断是缺信息还是 prompt 问题；
  3. 缺信息 → 另开"补解码器"任务；prompt 问题 → 另开 prompt 调整任务；都不在本项内。
- 若要整体放弃：按 S5→S1 倒序 revert。因 S3、S4 删了文件，倒序 revert 时必须从最近的一个开始，不要跳步。

## 五、时间估计（执行侧，不含用户跑模型的等待）

| 步 | 估计 |
|---|---|
| P0 | 0.5 小时 |
| S1 | 2–3 小时（含类型标注与序列化测试） |
| S2 | 1 小时 |
| S3 | 1–2 小时 |
| S4 | 1–2 小时 |
| S5 | 2 小时（文档量大，但多为加文件头） |

合计约一个工作日，另加两次 `agent_short_goal_run` 的运行时间。

## 六、PR

- 若走 PR：六个提交（P0 两个 + S1–S5）保持原样，不 squash，便于逐步 revert。
- PR 描述包含：删除清单（来自 spec 第二节）、`state_schema_hash` 前后值、对比跑并排表、旧账读取验证结果、剩余 grep 项及其理由。
- 合入条件：全量绿；对比跑通过率不显著低于基线（"显著"的线在对比表出来后由你和我一起定，不预设数字）；你确认。

## 七、遗留（合入后另案）

- `Facts.scene` 在内存档下只有战斗/空，应与 `TaskObservation.scene` 统一。
- 解码覆盖盘点：从对比跑的失败样本里找信息缺口。
- 是否给 run/episode 的观测渲染补一行"场合"。
- MCP memory 的 snapshot / restore 缺口已由 `docs/mcp/memory-admin-spec.md` 解决（服务端需 --enable-admin，付费端到端验收待用户执行）；视觉删除的基线与对比跑仍使用同一套配置，不因本项自动切换模式。
- Windows 上 Inspect 评分阶段会按 GBK 读自带的 UTF-8 YAML 元数据（`UnicodeDecodeError`）；`PYTHONIOENCODING` 无效，需在启动进程的环境里设 `PYTHONUTF8=1`。基线与对比跑都按此设置，且不写进 `.env` 或仓库。

## 2026-10-14 基线口径变更（S0 重跑前）

- 提交 `bcd4cc9`（`RUN_MAX_EPISODES` 50→3、评测 timeout 600）与 `4d38f48`（所有场合开放方向键）发生在 spec 与 S1 之间；旧的 `c2ded1d` 基线作废。
- 前置检查发现数据集第 8、10 例要求在战斗菜单按 a 打开列表，而脚本接管场合 a 关闭。裁决（用户确认）：**基础按键（方向键、a、b）在所有场合开放**（见 `docs/world/basic-keys-all-scenes.md`，提交编号 450）；基线改在该提交之后的 HEAD 上跑**全部 10 例**，不裁样本。
- 遗留（另案）：`RUN_MAX_EPISODES=3` 是全局生产常量，长任务前须重估；脚本接管帧新增 overlay/光标/整屏文字的显示变化；`brain_choose` 评测的可接受集合须按"所有场合有方向键、a、b"复核。

## 2026-10-14 基线再次作废：预算先行

- 在 `d40aedb` 上的基线只有前 5 例正常收尾，第六例（商店）因预算各层未连起来在 600 秒被强杀、无 `run_end`；该基线不成立。
- 先做 `docs/budget/run-budget-spec.md`（B1–B5），再在冻结的工作区上用同一预算档重建 10 例基线；视觉删除的 S1 继续暂停。
- 基线重建前须冻结共享工作区：其他会话不得在基线运行期间提交（HEAD 在 `d40aedb` 之后已被他人提交 451/452/文档改动，虽未触及生产代码，仍偏离"固定 HEAD"）。每个样本启动时记录 HEAD。
- 遗留（另案）：第五例模型评分器缺历史证据；商店柜台"可互动但不可通行"的规划误判；请求生命周期事件（需与用户商定 trace 落点）。

## 2026-10-14 预算改动使 `state_schema_hash` 变化

- 预算 B3 把累计动作、拆解轮次放进状态，`state_schema_hash` 由 `570c830a9cf52445` 变为新值（见预算 spec D13），评测存档随之重打（B3b）。
- 视觉删除的“哈希不得变化”停止条件改为：**相对重打后的新哈希不得变化**。基线记录的哈希以预算合入后的值为准。

## 2026-10-14 预算已合入，基线在独立 worktree 上重建

- 预算 B1–B5 已快进合入 `codex/unify-script-execution`，HEAD 为 `19307a1`（提交 455–458 与规格 v1.3 修正）。`state_schema_hash` 为 `40e2cd635256744f`，20 份 v1 存档已重打。
- 视觉删除在新 worktree `D:\Users\GummiGu\PycharmProjects\Pokemon_Agent-vision`、新分支 `perceive/remove-vision` 上做，起点固定为 `19307a1`；worktree 的 HEAD 不随其他会话的提交移动，这就是基线的"冻结"。
- S0 基线在该 worktree 的 `19307a1` 上用 `evals/config.json` 的预算档跑前十个 val 样本（`wall_clock_s=600`、`max_episodes=3`、`max_total_actions=60`，其余取共用层默认），结果目录 `eval_results/remove_vision_baseline_19307a1/`。评测 task 启动时自己写 `baseline_context.json`（预算文件路径与 sha256、模型、样本、超时），环境与 HEAD 等补充信息另存 `baseline_env.json`，不要手改前者。
- 基线通过判据（先于任何分数）：10 个样本都有 `run_end`；无样本触发 600 秒硬终止；第一个样本的评分阶段通过后才放行其余。分数只记录，不作验收判据。

## 2026-10-16 执行记录：S0–S4 完成，S3/S4 范围调整

- 已提交（分支 `perceive/remove-vision`）：`31ad913`（文档）、`188f9db`（459，第十例机械判据）、`113c3f6`（S1，取帧换成内存观测，重打存档）、`733900c`（S2，删调用链）、`256253f`（spec v1.3）、`e31ec2c`（S3）、`a54e636`（S4）。
- **S3 范围调整**：`evals/episode_vision_read/` 实际 import 了 S3 要删的 world 视觉模块（`world.prompts`、`world.visual_perception`、`VisionProvider`、`PerceptionAttemptFailed`），原顺序（S4 才删评测）无法同时满足“删除前无他处引用”与“全量测试通过”，是设计侧漏看了依赖。裁决：评测的删除、注册表六变五、`dataset/frames/build/cli.py` 与 `snapshot.py` 的引用、对应测试提前到 S3；S4 只剩 `vision_model` 接线与配置。
- **`state_schema_hash` 链**：`570c830a9cf52445`（预算前）→ `40e2cd635256744f`（预算 B3）→ `d30940d71e1612aa`（S1 中间态）→ `b143f3ee76954378`（S1）→ **`4f1cac6fcc7216d5`（S3，删 `Facts.overview`）**。每次变化都随提交重打 20 份 v1 存档，`world.state` sha256 全程不变。S5 起不得再变。
- 删除后仍保留（只为读旧账、旧记忆）：`TraceKind.SENSE_CALL` 及其解析/渲染映射；`ActMemory.Observation` 的 `perceived` 字段与 `Facts.overview` 字段及渲染；20 份旧 manifest 里的 `"vision"` 键（历史元数据，不重打）。
- S4 之后 MCP world server 为 44 个 tool（S2 起比 45 少 `perceive_once`）。pytest 为 801 passed、2 skipped（S2 的 852 减去被删视觉评测测试的 51 项）。
- CHANGELOG 编号：分支内按分支自己 HEAD 取号（459 之后为 460）；与主线其他分支合并时由设计侧统一重编号。
- 合入时：先把主工作区里未提交的 `docs/perceive/remove-vision-plan.md` 复原到 HEAD（本文已在分支内提交），再做快进合并；合并在用户的 Windows 本机执行。
