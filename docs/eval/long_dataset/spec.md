# spec —— 长期数据集 v20261028_long（开放探索，两个 run）

> 流程位置：intent（`docs/eval/long_tasks/intent.md`，2026-10-28 重写）→ **spec** → plan → 落码。分层与冻结的口径以 `docs/eval/tiers.md` 为准。
> 前置实验：`experiment/long_verify/`（不入库）：冷启动卧室存档（5 次重复哈希一致 `95b2cabd5b83d7d6922f4504f6602bd4d121de146b34c1a59db13c8a8a977158`）、完整路线 334 个 oracle 步、文字线索普查。
> 编号：688（基础设施）、689（数据集与判据）、690（冻结记忆种子）。直接在主仓库 main 工作区做（不开 worktree、不开分支），执行方不提交，设计侧验收后提交。**删除目录或文件由用户做，执行方不删。**
> 与 checkpointer 的关系：本 spec **不使用** memory 服务的 `snapshot_memory`/`restore_memory` 管理接口（它们属于恢复体系，可能被移除），一律用文件复制；harness 只在启动时按 `.state` 恢复世界，没有中途恢复。

## 一、目标

第三层长期样本：开局在新游戏卧室，目标"离开真新镇"；评测第二个 run，全新启动，memory 根里放着冻结的第一个 run 的记忆；另有一个"不带种子"的消融设置。第一、二、四层只是同一起点加不同的目标与判据，本期不建。

## 二、决定表

| 编号 | 决定 |
|---|---|
| D1 | 数据集版本 `v20261028_long`，目录 `evals/agent_short_goal_run/dataset/v20261028_long/`，构建脚本 `dataset/build/long_dataset.py`；已存在则报错，不覆盖。输出确定，重复生成 `samples.jsonl` 的 sha256 不变 |
| D2 | 一条样本：`sample_id=long_leave_pallet_town`，`tier="long"`，`granularity="run"`，`goals=[]`（long 档目标表由规划器建）。run 目标逐字：「离开真新镇，一路向北走到镇外。」判据文（给 agent 内部 judge）逐字：「人已走出真新镇，来到北边的下一个区域，并且队伍里已经有一只自己的宝可梦。」`max_steps=720`（3×oracle 238 取整）。`check_id="leave_pallet_town"`，`k_metric="pass_at_k"`。`category`、`behavior`、`rubric`、`red_lines`、`split` 沿用 `dataset/build/mid_dataset.py` 的写法；`behavior` 写："从卧室下楼出门，往北走会被大木拦住带去研究所，选一只宝可梦，与对手对战，然后出镇往北。" |
| D3 | 起点：新游戏卧室存档 `states/new_game_bedroom.state`，**由 ROM 冷启动按固定按键序列生成**，不是手工保存。新增 `dataset/build/long_start.py` 与数据文件 `dataset/build/long_start_keys.json`（按键序列，来自 `experiment/long_verify/long_preflight.py` 与 `long_preflight.json`，移植为数据）。脚本用 `assets/rom` 起独立 PyBoy（`window="null"`），在进程内连续生成两次比较 sha256，应等于 `95b2cabd…`（不等就停下汇报），保存到新版本目录的 `states/`。`revision.json` 记按键序列的 sha256、存档 sha256、起点读数（map 38 `(3,6)`、队伍与背包为空、钱 3000、`D74E=0x00`） |
| D4 | 起点预检：`PREFLIGHT_CHECK_IDS` 加 `leave_pallet_town`；预检只读 `RamReadout` 与 `TaskObservation`：map 38、行走场景、不在战斗、队伍为空、背包为空、钱 3000 |
| D5 | 样本新增两个可选字段（默认值使现有 25 条样本与全部数据集一个字节都不变）：`initial_memory: InitialMemory \| None = None`（`path`：版本目录内相对目录；`manifest_sha256`：该目录里 `MANIFEST.json` 的字节哈希），`knowledge_exclude_topics: list[str] = []`。`validate_tiers`：`initial_memory` 只允许 `tier="long"`。`loader.check`：`initial_memory` 的目录必须存在，`MANIFEST.json` 哈希匹配，其中列出的每个文件哈希匹配、目录里没有清单之外的文件、不含 `knowledge_memory`；`knowledge_exclude_topics` 里每个主题必须真实存在于仓库 `memory/knowledge_memory/*.md` 的 frontmatter `metadata.topic`，否则 `DatasetError` |
| D6 | `evals/common/eval_services.py` 新增三个可选参数（旧调用方不变）：`memory_seed: Path \| None`——起 memory 服务**之前**把种子目录复制进临时根的 `memory/`（拒绝覆盖已有文件、拒绝逃出根目录的路径、拒绝种子里有 `knowledge_memory`）；`knowledge_exclude_topics`——复制知识 Markdown 时跳过 frontmatter `metadata.topic` 在集合里的原子；`export_memory_to: Path \| None`——退出清理前把临时根的 `memory/` 复制到该目录，排除 `knowledge_memory` 与缓存文件（`index.json`、`vectors.jsonl`），目标已存在则拒绝。三者都只用文件复制 |
| D7 | `solver/solver.py` 按样本 id 与版本取到样本，把 `initial_memory`（解析为版本目录下的绝对路径）、`knowledge_exclude_topics` 传给 `eval_services`。两个评测运行设置（`evals/config.json` 的顶层键，默认关）：`ignore_initial_memory`（为真则不复制种子，样本数据不变，这就是"不带种子"的消融设置）与 `export_memory_dir`（给定则起服务时传 `export_memory_to=<dir>/<sample_id>#e<epoch>`，生成种子用） |
| D8 | 知识：新增一条只讲方法、不给地图事实的原子，主题 `explore_and_read`，源文件 `explore_and_read.md`，机制与 `map_connections` 相同（先 `git grep -n "map_connections.md"` 看现有原子怎么生成），正文逐字见第六节；长期样本写 `knowledge_exclude_topics=["map_connections"]`，所以长期运行里没有路线知识，中期样本不写，行为不变 |
| D9 | 机械判据 `leave_pallet_town`（放 `scorer/rules/long.py`，登记并配正反例）：起点帧 `map_id != 38` → unjudgeable；取带内存读数的帧：首个队伍人数 ≥ 1 的帧 i_p；存在帧 i_m（i_m > i_p）`map_id == 12` → pass；失败分类：从未拿到宝可梦 / 拿到了但没到地图 12 / 先到地图 12 再有宝可梦（理论上不会发生，如实记）。不要求终局不在战斗（到达地图 12 之后可能遇敌）。`reason` 里附里程碑首次出现的帧序号：地图 37、0、40、38 之后的 0、队伍≥1、12。判据只读账本与内存，不读规划器或分解器的输出（tiers.md 第四节） |
| D10 | oracle 数据记在 `revision.json`（文档用途）：总 238 步到地图 12，各里程碑累计步数（下楼 10、室外 24、大木拦路 74、选宝可梦界面 104、选好 131、对战开始 160、对战结束 207、出研究所 220、进地图 12 238），来源 `experiment/long_verify/route.json` |
| D11 | 冻结记忆种子（690）：见第五节。689 完成时样本**没有** `initial_memory`；690 冻结后才加 |
| D12 | 测试全部用合成数据：字段校验、`MANIFEST.json` 哈希核对的正反例、`eval_services` 三个参数（用临时目录与假知识文件，不起真服务）、规则 `leave_pallet_town` 的正反例与失败分支、预检的正反例；真实核对只在生成后做一次，不写成常驻测试 |

## 三、688（基础设施，不含数据集）

范围：D5、D6、D7 的代码与测试；不新建数据集版本、不加知识原子。验收：全量 pytest（先取基线，预期 `tests=2961`，以实测为准）`failures=0`、`errors=0`、`skipped=72`；守卫四条 `[ OK ]`；ruff 三项；两种 `git diff --stat` 逐行一致；`CHANGELOG.md` 顶部新增 688 条目。**必须核实的一点**：种子目录复制进临时根后，memory 服务读取"别的 run 的记忆"的路径（`harness/run/perceive/read_plan_context.py::_read_run_index` 所用的读取）能看到种子里的 run 记忆；做一个合成核对（假种子目录加真的 memory 服务进程，或最接近的可行方式），说明服务是否需要重建索引、在哪里触发；若需要，在 `eval_services` 里解决，不改 `pokemon_agent/`。允许范围：`evals/agent_short_goal_run/dataset/{schemas.py,loader.py}`、`evals/common/eval_services.py`、`evals/agent_short_goal_run/solver/solver.py`、`evals/config.json`（只加两个顶层键，默认值使行为不变）、测试、`CHANGELOG.md`。不改 `pokemon_agent/`、`docs/`。

## 四、689（数据集、起点、判据、知识）

范围：D1 到 D4、D8 到 D10、D12。验收：`loader.load("v20261028_long")` 得 1 条，`loader.check` 与 `validate_tiers` 通过，起点预检通过（构建脚本里用同一个 `validate_start` 对起点验一次）；重复构建 `samples.jsonl` 与 `revision.json` 的 sha256 不变；卧室存档 sha256 等于 `95b2cabd…`；现有 25 条样本与四个旧版本的所有文件哈希与整理前一致；`explore_and_read` 原子正文逐字等于第六节，且 `loader.check` 里的主题校验通过；规则登记后 `test_evals_checks.py` 的"每条规则有正反例"与"数据集 check_id 都已登记"两个约束通过。允许启动模拟器（只用于生成与核对起点）；不调用真实模型。允许范围：`dataset/build/{long_dataset.py,long_start.py,long_start_keys.json,preconditions.py}`、`dataset/v20261028_long/`、`scorer/rules/{long.py,__init__.py}`、`memory/knowledge_memory/` 下新增的一条原子及源文件、测试、`CHANGELOG.md`。

## 五、690（冻结记忆种子，需要真实模型，设计侧与用户共同执行）

1. 配置：一份评测运行配置，`models` 的 `text_model`、`judge_model`、`summary_model`、`plan_model` 四个角色都用 **deepseek4.1flash**（完整标识字符串以用户给的为准，API 密钥走环境变量，不入库）；`export_memory_dir` 指向 `experiment/long_seed/attempt_<n>/`；`ignore_initial_memory` 关；样本是 689 的 `long_leave_pallet_town`（没有 `initial_memory`）。
2. 最多跑 5 次（attempt 1 到 5）。**成功标准事先写死**：机械判据 `leave_pallet_town` 判 pass；取**第一次** pass 的那次冻结；5 次全部留档（每次的判据结果、`oracle_steps` 比、实际决策数、耗时、费用或 token、run id、记忆目录），**不事后挑选**；5 次都失败则停下汇报，不冻结。
3. 人工审（设计侧与用户）清单：记忆目录里有 run 记忆且带索引（headline 与 keys）、episode 记忆；不含知识原子、不含缓存文件；索引里能看到这次探索得到的关键信息（研究所在哪、被大木拦住、选宝可梦、对战、出镇往北）——**有就有，没有就是真实情况，不补写、不改写**；没有泄露评测答案；总大小合理（建议小于 1 MiB，超出则列出）。
4. 冻结：复制到 `v20261028_long/memory_seed/leave_pallet_town_v1/`，写 `MANIFEST.json`（文件相对路径与 sha256 的有序列表），样本加 `initial_memory`（`path`、`manifest_sha256`），`revision.json` 记 `seed_selection`（尝试次数、各次结果、选中的 attempt、选中理由=第一次 pass、模型标识、配置哈希、日期）。冻结后样本哈希变化只允许发生在 `initial_memory` 字段。
5. 验证：带种子跑 oracle 路线不是目的，目的是确认第二个 run 能读到种子：跑一个最短的第二个 run（可以是同一个模型），在 trace 里核对规划层读取了 run 索引且内容含种子里的 run 记忆。

6. **费用护栏（用户 2026-10-29 定：每 20 元人民币停一次）**：**直接用 DeepSeek 官方的余额接口算人民币**：`GET https://api.deepseek.com/user/balance`（请求头 `Authorization: Bearer <DEEPSEEK_API_KEY>`），返回 `balance_infos[]`，其中 `currency="CNY"` 项的 `total_balance`（字符串，含赠金与充值余额）就是账户当前可用余额，**花费 = 尝试开始时的余额 − 当前余额**，不需要价格表也不需要汇率（已用官方文档核对过：端点、字段、币种取值 CNY 或 USD）。注意两点：①它量的是**整个账户**的消耗，不只是本次尝试，所以尝试期间不要有别的东西在用同一个 DeepSeek 账户（评测只用 DeepSeek 一个提供方，别的 session 用的是 Anthropic，不冲突；`reviewer` 的 AI 席也用 DeepSeek，尝试期间别启动它），这样量出来偏高不偏低，对护栏是安全的；②余额更新可能有短暂延迟，所以监视脚本按固定间隔（建议 20 秒）轮询，且**取读到的最小余额**作为当前余额（余额只降不升，除非充值）。**做法**：新增费用监视脚本（放 `scripts/`，只读，不改被测系统；密钥只从环境变量或 `.env` 读，**不打印、不写入任何日志与报告**），每次尝试单独起一个进程；脚本记录开始余额，轮询时算累计花费，达到 **20 元**就**终止该次尝试**（记为"费用封顶"，计入 5 次里），因为不做中途恢复，终止即作废。**每次尝试结束（无论成败）都停下**，向用户报告：本次花费、累计花费、该次判据结果、剩余次数，**等用户确认再开始下一次**；累计每超过 20 元的整数倍也同样停下确认。报告里同时给 trace 里的原始 token 数，并用 `scripts/probe_models.py` 的 `PRICES` 与 `estimate` 算一份估算费用（美元）作**对账与后备**：余额接口不可用或返回币种不是 CNY 时，脚本退回估算（用保守价格，汇率由用户确认，默认暂按 1 美元 = 7.2 元占位），并在报告里明确标注"费用来自估算，不是余额"。`PRICES` 与 `estimate` 抽成共享模块，`probe_models.py` 改为导入（行为不变，现有测试照过）。费用监视与共享模块由 690 之前的任务 696 完成，690 本身不写代码。

## 六、`explore_and_read` 知识正文（逐字；只写实验里确实读到的东西）

```
## 探索时怎么找线索

- 走到路牌或告示牌的正前方，面向它按 `a`，读出上面的地名；每到一个新地图，先看有没有路牌和门。
- 家里的电视和遇到的每个 NPC 都可以面向它按 `a` 对话，把对话里出现的人名、地名、该去哪里记下来。
- 被人拦住、被叫去某个地方时，对话里说的就是下一步该做什么。
- 在地图边缘继续朝一个方向走，会进入相邻的区域；记住自己是从哪个方向进来的。
- 走不通时先看有没有别的门或出口，再换方向，不要在同一处反复撞墙。
```

## 七、不做

不建长期其他三层；不做图内恢复；不用 memory 服务的 snapshot/restore 管理接口；不手写记忆；不改现有 25 条样本与四个旧版本；`pokemon_agent/` 不动。里程碑步数曲线、无效步数等指标的 scorer 另排（第三层先只有成败判据）。
