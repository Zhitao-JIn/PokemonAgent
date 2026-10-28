# 评测数据集清单（agent_short_goal_run）

> 位置：`evals/agent_short_goal_run/dataset/`。现行版本只有三个；退役的旧版本（`v1`、`v2`、`v20261021_corrected`、`v20261021_current_state`、`v20261021_merged_583`、`v20261021_retest4`）已由 686 整理并删除，内容保存在 git tag `archive/eval-datasets-before-tidy-20261028`（取回：`git show <tag>:<路径>` 或 `git checkout <tag> -- <路径>`）。
> 默认运行版本由 `evals/config.json` 的 `version` 指定（整理后为 `v20261028_short_frozen`）；`loader` 的三个函数不再有默认版本，必须显式传。
> 三档的性质、冻结与分层的关系、规划器条件的用法见 `docs/eval/tiers.md`（以它为准）；长期任务的设计见 `docs/eval/long_tasks/intent.md`。

## 一、现行版本

| 版本 | 档位 | 样本数 | 作用 | 来源与构建 |
|---|---|---:|---|---|
| `v20261021_retest5` | 无 tier 字段（旧格式） | 20 | 短期的"自由拆解"对照：task 表由 decomposer 自己拆，不冻结；也是下面两个版本的父版本 | 历史版本，不再改；构建脚本以它为父版本 |
| `v20261028_short_frozen` | `short` | 20（21 个 task，只有 `knowledge_shop_interaction` 有两个） | 短期正式数据集：每条样本冻结一张 task 表，两个冻结开关全开 | `dataset/build/short_frozen.py` 加 `short_frozen_tasks.json`，由 retest5 生成，只改 `dataset_version`、新增 `tier` 与 `goals`；存档与 retest5 逐字节相同；设计见 `docs/eval/short_frozen/` |
| `v20261028_mid` | `mid` | 5 | 中期数据集：每条样本冻结 episode 目标表（3、3、2、3、2 个 episode） | `dataset/build/mid_dataset.py`、`mid_starts.py`、`mid_goals.json`；设计见 `docs/eval/mid_tasks/intent.md` 与 `docs/eval/mid_dataset/spec.md` |

## 二、中期五条样本

| 样本 | run 目标（摘要） | 起点 | 判据 `check_id` | episode 数 | 预算 `max_steps` |
|---|---|---|---|---:|---:|
| `mid_walk_to_pallet` | 走到真新镇，再走进大木研究所 | `knowledge_pokemon_center_enter`（原样） | `walk_to_pallet` | 3 | 300 |
| `mid_heal_buy_return` | 治好队伍、买 2 个精灵球、回到起点 | `m2_bulbasaur_half_hp`（首只 HP 25→12） | `heal_buy_return` | 3 | 250 |
| `mid_catch_then_heal` | 抓住眼前的野生宝可梦，再把全队治满 | `m3_bulbasaur_half_hp_battle`（队伍与战斗缓存与 HUD 都是 12/25） | `catch_then_heal` | 2 | 190 |
| `mid_customers_hint_buy` | 先问两位顾客，治疗，再买被提到且在售的东西 | `knowledge_shop_interaction`（原样） | `customer_hint_purchase` | 3 | 330 |
| `mid_cure_poison_budget` | 不进中心，用别的办法解毒，花费不超过 150 | `m5_pidgey_poisoned`（第二只状态字节 PSN） | `cure_poison_budget` | 2 | 230 |

- **oracle 步数**（确定性参考解，"一个决策一步"）：旧等待下记入 `revision.json`：M1 22（无遇敌 6、最大 98）、M2 83、M3 61、M4 108、M5 76；新判稳（680、681）下复核：M1 最小 6、中位 14、最大 22，M2 79，M3 56，M4 104（自适应路线），M5 75。**预算按旧值保留**（3×oracle 取整，留给 agent 探索与战斗的余量），不随复核降低。
- oracle 脚本目前在 `experiment/mid_verify/`（不入库）；入库化另排。
- M1 的路线知识在知识库里新增的一条 `map_connections`（只写方向与地标，不写坐标与按键）；评测时可单独开关这一条做消融。

## 三、已知局限与读结果的方式

1. **M3 抓捕受随机数影响**：游戏随机数每帧滚动，球扔出的时刻决定成败；模拟器确定，所以同一空转帧数的重复结果完全相同，**不是独立样本**。判据只看结果（队伍多一只、之后在中心治满、对手没被打倒、终局不在战斗或起名界面），不受影响；但同一个 agent 不同次运行的通过率会有波动，看 `pass_at_k`，不要看单次。起点有 4 个球，允许重投；"扔了几个球"单列报告，不与决策好坏混读。具体哪些空转帧下成功没有规律，不写进说明。
2. **M1 遇敌次数随节奏变化**：1 号道路有草丛，遇敌率旧 60%、新 80%，同样不是独立样本；遇敌次数与战斗内决策数单列报告，不与移动步数混读。`agent_steps / oracle_steps` 对 M1 不可与其他任务直接比较。
3. **M4 移动顾客的位置取决于时间线**：加载时在 `(5,7)`，走几步后可能在 `(5,6)`；oracle 必须自适应（每步先读 NPC 坐标）；对 agent 无影响（它每步都能看到）。台词两句固定：`This shop sells many ANTIDOTEs.`（线索）与 `No! POTIONs are all sold out.`（干扰）。
4. **知识库混杂**：`shop_purchase` 原子里直接写了 M4 的两句台词，知识库开着时 agent 可能不靠记忆就猜出该买 ANTIDOTE；要看记忆的作用必须读"知识库关闭"那一批。
5. **起点的包裹事件**：这批存档里 `D74E=0x03` 的都已过了包裹那一幕，进商店不会触发托付；M4 的起点已核实。包裹交付任务并入长期任务 L1（起点用 `knowledge_dialogue_advance`，`D74E=0x00`）。
6. **等待参数的前提**：以上步数都在统一判稳规则下取得（默认 24 帧、战斗类 180 帧、治疗 360 帧，预算 900、1200、1200，见 `docs/world_settle/spec.md`）；规则再改，需要复核战斗与治疗段。
7. **旧格式冻结数据**：`evals/dataset/` 下的旧格式数据（`brain_calls`、`brain_annotations` 等）仍在，对应 72 个带 `D33:` 标记的跳过测试，等用新框架重新生成数据后恢复（ROADMAP B16）。

## 四、起点存档校验

每个样本的 `start.source_sha256` 是起点文件的 sha256；`loader.check` 会核对文件存在与哈希；评测运行时再由 `PREFLIGHT_CHECK_IDS` 里的起点预检（`dataset/build/preconditions.py`）在真实世界里验一次。派生存档的改动（地址、改前改后、屏幕图块）记在 `v20261028_mid/revision.json`。
