# 测评指标与判据规范（Eval Metrics & Rubric）

> v0.6 —— 2026-09-02。对应路线图 P3（`docs/EXPERIENCE_DOCS.md` 第六节）、
> 可观测第 1 条（`docs/ROADMAP.md` #1，v1 实现规格见第十节）。
> v0.6 变更：全项目可观测/审计扫描的两条直接产出——① `tests/test_step_audit.py`
> 引用的 `Brain.audit_steps`/`step_audit.py` 早已被 `verify_steps`/`step_verify.py`
> 取代，测试没跟着改名、import 直接 `ModuleNotFoundError`，已删除（死代码，
> 不是这次新增的回归）；② `eval_report.py` 补上"审计器失效率统计"——
> `Source.VERIFY` 枚举注释里"算得出校验器自己的失效率"这句期望，之前只是把
> `verdicts` 结构化落了 trace（`trace_utils.verify_call`），从没有代码解析它；
> 现在 `SourceMetrics` 新增 `verify_total`/`verify_unreliable`/
> `verify_unreliable_rate`/`verify_parse_errors`，报表里对应链路会多一行
> "审计失效率"明细。详见 10.4a。对应 `docs/ROADMAP.md` P2"可审计"从
> 📋 未开始 推进到 🚧 进行中（judge/verify 人工标定样本仍未做）。
> v0.5 变更：**用户决定不需要机械复核这条线**（不清楚 `audit_verdicts.py`
> 在做什么、明确表示可以删）——`evaluation/audit_verdicts.py` 与
> `evaluation/tests/test_audit_verdicts.py` 已删除（git 历史可查）；本文件
> 里依赖它的部分（五节 rubric、三·1 的 judge/复核对照四个字段、六节草案的
> "成功率（judge vs 复核）"一栏、七节步骤 1、九节的 CI 遗留项）标记**已移除**，
> 不是"待实现"。success rate 现在只剩 `judge_success_rate` 一个数字，
> 可信度问题（0827 假阳率 13.9% 的实证）仍然存在但**没有替代方案**，留作
> 开放问题，不假装已解决。
> v0.4 变更：`evaluation/eval_report.py` 落地（`read_run_events` +
> `aggregate_events` + CLI），第十节标记实现现状，第七节步骤 2 划勾。
> v0.3 变更：0902 拍板可观测 v1（跨 run 每链路 token/延迟聚合报表）；
> 延迟口径从"payload.latency_ms"修订为 Δt 归本事件（见三·2 修订与第十节 10.3）；
> 补"边界"一节——judge 归 harness，不是测评（防术语再混淆）。
> 依赖 trace 作为唯一数据源（`docs/spec/DATAFLOW.md`）。
>
> **目录约定**：测评相关的新文件全部放在 `evaluation/`（本文件所在目录），
> 不散进 `docs/spec/`、`probe/`、`pokemon_agent/experiment/`——历史上
> `probe/audit_verdicts.py` 就散在包外单独一个目录，这次统一收拢。
> `evaluation/` 是一个**独立于 `pokemon_agent` 包的子系统**：它的代码只解析
> trace JSONL 的字面结构，不 `import pokemon_agent`，好处是它的测试不需要装
> `agent-permission`/`fastembed` 这类重依赖，CI 里可以单独、快速地跑。
> `evaluation/` 自己的测试放 `evaluation/tests/`（`pyproject.toml` 的
> `testpaths` 已经加了这一条），不塞进项目根的 `tests/`——那里是
> `pokemon_agent` 包各模块的测试，`evaluation/` 是平行的另一个子系统，
> 混进去会让"测试属于哪个子系统"这件事又要靠人记。

## 边界：judge 是 harness 的一部分，不是测评

（0902 拍板。目的：防"judge 算不算测评"再起混淆，为文档/讨论用词定调。）

- **judge（`EpisodeHarness` 图的终止判定节点）归 harness**：它输出的
  `done`/`success` 消费方是**控制流**（收尾 `verify_steps → summarize` 还是继续
  循环）；把它拆掉，agent 不会停、永远不会成功收尾——运行时内部机制。术语上用
  "终止判定器 / 达成判定器"，不叫"测评"。
- **LLM-as-Judge 是技术形态名，不是层名**：harness 内部的 judge 与测评侧未来的
  外部评分器都可能用"模型按判据给结论"这一形态——归哪层看**消费方**，不看形态。
- **本文件（测评）是事后外部视角**：报表消费 `trace_data`，拆掉它 agent 照跑
  不误。judge 写的 `EPISODE_END.success` 只是测评审视的**被测数据**，不是
  测评的成员。（曾经有一个纯规则机械复核工具 `evaluation/audit_verdicts.py`
  给这句话提供具体实现，0902 已按用户决定删除——见五节。）
- **内部自评不可信这件事本身没有变**：judge 是 agent 自己，会给自己发奖状
  （实证假阳率 13.9%，见 `0827-false-positive-analysis.md`）——但"脱离 harness
  用纯规则复核"这条解法 0902 已经被撤回，当前**没有**替代的外部核验手段，
  `judge_success_rate` 的可信度问题是留着的开放问题，不是解决了。
- 一句话判据：**问"谁消费它的输出；拆掉它 agent 行为变不变"**——变了是 harness
  组件，不变才是测评/可观测。

## 一、目的

把"测评"从"跑几局看感觉"变成"四个可复现的数字"：success rate、cost per run、
无效步占比、每链路 token。四个数字都必须能从 `experiment_results/` +
`trace_data/` 离线重算，不依赖跑批时的终端输出。

**前提立场**：`0827-false-positive-analysis.md` 已经证明 `task_stats` 里的
`success` 字段不可信（judge 记的 115/124，机械复核后 102/124，13.9% 假阳率，
且误判集中在 5/19 条任务，不是均匀噪声）。所以本规范把 success rate 拆成
两个数字，而不是一个。

## 二、数据来源（唯一真相）

所有指标只从两处算，不引入第三份记账：

- `trace_data/<run_id>/*.jsonl`——逐事件流，`EventType.MODEL_CALL` 给 token/延迟，
  `EventType.ACT`/`STEP_MEMORY_WRITE` 给动作与画面前后对比，`EPISODE_END` 给
  `success`/`steps`/`reason`（这是 **judge 记的**，不是机械复核的）。
- `experiment_results/task_stats/<chain_id>.json`——`run_all_tasks.py` 已经在
  维护的按任务累积表，本规范只加字段，不改结构。

`Source` 枚举（`schemas/datastore/__init__.py`）已经把每条 `MODEL_CALL` 标了
`perception` / `decision` / `judge` / `memory` / `harness` 五条链路，
按链路聚合直接 `groupby(Source)`，不需要新的分类逻辑。

## 三、四个指标

### 1. success rate —— 曾拆成两个数字，机械复核那一半 0902 已移除

**已移除（0902，用户决定）**：`judge_success_rate` / `verified_success_rate` /
`false_positive_rate` / `false_negative_rate` / `unverifiable_rate` 这一组
本来靠 `evaluation/audit_verdicts.py`（纯规则机械复核）算，该文件与它的
测试已删除（用户表示不清楚这个工具在做什么、不需要）。**现状**：success
rate 只剩 `judge_success_rate`（`EPISODE_END.success`，judge 自己的结论）
一个数字可报，`0827-false-positive-analysis.md` 记录过的假阳率 13.9% 这个
可信度问题**没有被解决，只是失去了这一版核验手段**——如果以后要重新引入
外部核验，需要重新设计，不是恢复删掉的文件（那一版是不是"对的"方式本身
就是这次被撤回的原因，见开头版本说明）。

**批次内记忆污染的诊断（跟机械复核无关，保留）**：`EPISODE_START` 现在带
`memory_carried`（开局时跨局摘要池大小，`memory.episode_summary_count`）。
同一批次里同一条任务的多次 repeat，如果这个数字持续走高，说明 `success
rate` 不能被当成 N 次独立同分布试验的平均值来读——后面的 repeat 读到了
前面 repeat 蒸馏出的经验。`evaluation/eval_report.py`（已实现，见第十节）
目前的 run 汇总表把每个 run 的结果分行列出，还没有把 `memory_carried` 这个
数字并排显示——这是它跟这段诊断需求之间还没接上的地方。要不要在批次测评时
隔离记忆还没有结论，见 `docs/EXPERIENCE_DOCS.md` 六·1 节。

### 2. cost per run

按 run 汇总 `MODEL_CALL.payload` 的 `input_tokens` + `output_tokens`，
以及延迟的中位数/p90（长尾在哪条链路一目了然，
`0827-knowledge-baseline.md` 已经示范过这张表的形状）。

**0902 修订（延迟口径）**：v0.2 写的 `payload.latency_ms` 字段**不存在**——
`ModelCall.payload` 是 `dict[str,str]`（`schemas/domain/model_call.py`），真实
事件样本里没有该键。拍板：**不新增字段**，延迟一律按第十节 10.3 的
"Δt 归本事件"口径用事件 `ts` 差近似——归因不准是 trace 不够密，根治方向是
补事件边界，不是给事件塞元数据。

不做美元换算——模型定价会变，token 数才是稳定的比较基准；需要换算时在报表
末尾按当前价目单单独算一行，不进入原始记录。

### 3. 无效步占比（invalid step ratio）

**定义**（机械、不依赖模型判断）：一个 step 记为"无效"当且仅当

```
(action.describe(), after.stall_key()) == (上一步的 action.describe(), 上一步的 stall_key())
```

即 `episode_harness.remember()` 里已经在算的停摆键**完全复用**——不新造一套判据。
区别在于：现有的 `STALL_LIMIT=5` 只用来触发强制终止，中途 1-4 次的原地重复
目前**不落表**；本指标把每一步都记，不等到连续 5 次才算。

```
无效步占比 = 该 run 内“无效步”计数 / 该 run 总步数
```

聚合到任务级/批次级时按 run 加权平均（长 run 的无效步不该被短 run 稀释）。

**已知局限（不是这次要解决的，见 `docs/EXPERIENCE_DOCS.md` 六·1 节）**：这个
定义只能抓住"连续动作 + 画面机械状态完全相同"这一种最狭窄的无效，且
`STALL_LIMIT=5` 在短任务（`max_steps=15`）里几乎形同虚设——很多局在真正
触发停摆判定前就已经因为步数用尽结束了。这个指标现在算出来的数字是
**真实无效步占比的下界，不是准确值**，报数字时要带上这句话。

**边界**：episode 第一步没有"上一步"，不计入分母也不计入分子。

### 4. 每链路 token

`MODEL_CALL` 按 `Source` 分组求和/求中位数，输出一张表（链路 × {调用次数、
input token 占比、output token 占比、延迟中位数、延迟 p90}），
`0827-knowledge-baseline.md` 第七节的表就是这个指标当前的手工版本，
本次做成可重跑的脚本。**延迟口径见第十节 10.3（Δt 归本事件）**；v1 报表
另并失败/重试/降级计数（10.4 的指标集合），失败类型不混进 token 聚合。

## 四、判据设计 rubric（给写新任务的人看）

不新写一份——`pokemon_agent/experiment/tasks.py` 头部的九条规则 +
自查清单已经是这份 rubric，本规范只追加两条来自假阳性分析、九条里没覆盖的：

10. **不写"数量类"以外的过程状态叠加判据**——两个终局共享同一组可观测量时
    （如"买成"和"取消购买"都回到商品列表），必须加否定项排除另一个终局
    （见 `shop_cancel_purchase` 案例，`0827-false-positive-analysis.md` 第四节 B 类）。
11. ~~写完新任务先跑一次机械复核（见五）~~ **这条已经没有对应工具**——
    机械复核 0902 已移除（见五节），"判据要能在单帧上机械核对"这条自查
    标准本身依然成立、继续遵守，只是没有代码能自动帮你核对了，全靠写
    判据时自己按前十条过一遍。

## 五、judge 机械复核 rubric —— **已移除（2026-09-02）**

历史上存在过两次：最早是 `probe/audit_verdicts.py`（`70f4c4c` 删掉），
2026-09-01 在 `evaluation/audit_verdicts.py` 重建过一版（19 条任务规则 +
32 个回归测试）。**2026-09-02 用户明确表示不清楚这个工具在做什么、可以
删掉，已删除**（连同 `evaluation/tests/test_audit_verdicts.py`）。

下面这份 rubric 保留在文档里**只是历史记录**（说明"如果以后要重新做这件事，
上一版是怎么设计的"），不代表当前有对应代码，本节标题以下的 5 条规则不再
维护、不再是"待实现"：

1. 只认 `facts` 字段的字面值和 `dialog_text` 的字面文本——不重新调用任何模型，
   不"理解"画面，只做字符串/数值比对；核对不了返回"无法核对"，不猜。
2. 不是第二个判定器——用一个模型去检查另一个模型只是把信任转移一次；
   复核工具本身必须是纯规则代码，零 LLM 调用。
3. `success_criteria`（人写的中文描述）没有结构化形式，复核脚本要手动把
   每条翻译成检查代码——这是唯一需要人工维护的部分。
4. 输出逐 run 的 `verified_success: bool | None`（`None` = 无法核对）+
   一句机器可读依据。
5. 挂进批次流程：`run_all_tasks.py` 跑完自动复核一次，汇总表同时打印
   `judge_success_rate` 和 `verified_success_rate`。

**如果以后要重新引入外部核验**，先想清楚"这次为什么被撤回"（用户不理解
它在做什么，说明它的输出/存在感对用户不透明），而不是原样复原这份代码。

## 六、报表输出形态（草案，已被实际实现取代——见下方"跟实现的出入"）

一次批次跑完，产出 `experiment_results/eval_reports/<batch_id>.md`，最初设想的结构：

```
# 批次 <batch_id> 测评报告

## 成功率（judge vs 复核）
task_id | judge成功率 | 复核成功率 | 假阳 | 假阴 | 无法核对

## 成本（按 run）
task_id | 中位token | p90延迟 | 单run成本区间

## 无效步占比
task_id | 无效步占比 | 总步数

## 每链路 token
链路 | 调用次数 | input占比 | output占比 | 延迟中位数 | p90
```

**跟实现的出入（0902）**：`evaluation/eval_report.py` 实际落地的是第十节 v1
范围——按 `Source` 聚合的一张表（调用次数/成功/失败/重试/token/降级/错误/
延迟分位数）+ 一张 run 汇总表（episode 数/成败/token/时长），**没有**这里
草案里的"成功率（judge vs 复核）"一栏（机械复核已移除，见五节）和"无效步
占比"一栏（不在第十节 v1 范围，见七·2）。渲染选了 Markdown 表，没做 JSON。
本节剩下的字段设想（按 task_id 分组、成本区间）留作以后要不要做的参考，
不代表当前实现的形状——要看实际输出格式，以 `evaluation/eval_report.py`
的 `render_markdown` 为准。

## 七、实现顺序

1. ~~`evaluation/audit_verdicts.py`——19 条任务的机械复核规则~~ 2026-09-01
   实现过、**2026-09-02 已移除**（用户表示不清楚这个工具在做什么、明确
   同意删除，连同它的 32 个回归测试）。原计划里的"遗留"验证步骤（拿真实
   `knowledge_*` 批次数据核对规则）因此不再需要——见五节。
2. ~~`evaluation/eval_report.py`——读 `task_stats` + `trace_data`，
   产出六节的报表~~ **已完成**（2026-09-02）。实现的是第十节定的 v1 范围：
   `read_run_events`（跨文件按 `event_id` 归并、残行跳过）+ `aggregate_events`
   （按 `Source` 聚合 token/失败/重试/降级 + 10.3 的 Δt 延迟口径 + run 级
   episode 数/成败/时长）+ CLI（`--prefix`/`--run` 两种选组方式，输出
   `experiment_results/eval_reports/<label>.md`）。14 条单测覆盖
   `evaluation/tests/test_eval_report.py`（Δt 不跨 run 泄漏、`attempt` 重试
   计数、token 解析失败计入 `malformed`、`error` vs `PermissionSkipped` 降级
   分类、`--prefix` 精确匹配不做子串模糊匹配等），另用本地真实 `trace_data/`
   跑过一次冒烟验证。**没做**：六节草案里"无效步占比"（三·3 定义的那个指标）
   本来就不在第十节 v1 范围内，`eval_report.py` 目前只覆盖 token/延迟/失败/
   降级 + 成功率，没做无效步占比的报表列——这是下一轮如果要接的话需要单独
   排期的部分，不是这次漏做。
3. `run_all_tasks.py` 收尾处接入报表生成——**还没做**（原计划里的"接入
   复核"随五节移除一起取消，现在只剩接入 `eval_report.py` 这一半）；
4. 已补 `docs/experiences/2026-09-01-eval-framework-bootstrap.md`，
   记录这次"搭测评 + CI"本身的分析→定位→解决→验证。

## 九、CI/CD

`.github/workflows/ci.yml`：`push`/`pull_request` 到 `main` 时跑
`ruff check` + `ruff format --check`（lint job）与 `pytest`（test job，
Python 3.11/3.12 矩阵）。`evaluation/` 的测试不需要项目主依赖，天然适合
在 CI 里独立快速验证；`pokemon_agent` 包的测试套件本来就"不许连网、不许调
真实模型"（`CLAUDE.md` 第十节），跑在 CI 里不需要任何密钥或网络白名单之外
的东西。**这次没做的**：覆盖率门槛、发布流水线（这是个原型项目，还没有
"发布"的概念）。（原计划里"把 `evaluation/audit_verdicts.py` 接进 CI 跑真实
批次"随五节移除一起取消，不再是待办。）

## 八、本规范不做的事

- 不重新设计判据格式（仍是自然语言 `success_criteria` + 人工翻译成复核代码）——
  结构化判据是更大的改动，等这版跑稳再评估要不要做。
- 不引入美元成本——见三·2。
- 不覆盖 P0/P1/P2 未完成的部分（run 级重试、权限降级告警等），
  测评框架只消费已有数据，不新增护栏。

## 十、可观测 v1 实现规格（0902 拍板；ROADMAP 第 1 条）

0902 讨论定稿：可观测先落地为**跨 run 的每链路（Source）token/延迟聚合报表**，
观测台 UI 第二拍。三个拍板：a) 按 `Source` 聚合（`Source` 全集八个，含 0902 拆分
的 `VERIFY`，`schemas/datastore/__init__.py`）；b) **延迟不加字段**，用事件 `ts`
差近似（10.3）；c) 指标含失败/重试/降级计数（10.4），不只 token/延迟。

本节的代码全部落在 `evaluation/`，遵守本文件头部的目录约定：**只解析 trace
JSONL 字面结构，不 `import pokemon_agent`**。

**实现现状（0902）**：`read_run_events`（10.2）、`aggregate_events`（10.4）、
`eval_report.py` CLI（10.5）全部已实现，见 `evaluation/eval_report.py`；
测试见 `evaluation/tests/test_eval_report.py`（10.6 定的两类测试都有：
Δt 口径的人工可算断言、`read_run_events` 的跨文件归并与残行跳过）。
`run_all_tasks.py` 收尾接入（第七节步骤 3）、观测台 `GET /runs/{id}/metrics`
（10.7 边界，第二拍）还没做。

### 10.1 数据源事实（读侧的地基）

- 落盘布局：`trace_data/<run_id>/episodes/<episode_id>.jsonl`（`trace/store.py` 按
  `episode_id` 分文件追加写）；run 级事件的 `episode_id` 恰好等于 `run_id`，所以
  run 级文件（如 `run-xxx.jsonl`）与局级文件（`run-xxx-epN.jsonl`）在同一目录。
- `event_id`：由每 run 一个 `LocalTrace` 分配，**run 内全局单调连续**、跨文件；
  **跨 run 必然从 0 重复** → 批量读必须先按 `run_id` 分组，组内按 `event_id`
  排序。run 内跨文件"归并"实际就是 **sort by event_id**（id 唯一、无并列，
  不需要多路归并）。
- 事件是扁平信封：`event_id / run_id / episode_id / step / type / phase / source /
  payload / ts / schema_version`（`TraceEvent`，v2）。`ts` 是 float 秒。
- `MODEL_CALL.payload`：`input_tokens` / `output_tokens` / `attempt`（"1" 起步，
  每次重试 +1）/ `ok`（"True"/"False"）/ `raw` 等字符串。
- **失败类型不在 MODEL_CALL 里**：`trace_utils.model_call` 对失败调用额外补一条
  `ERROR`（payload `{kind: error_kind, reason, attempt}`）——账单与失败模式分开。
- **权限降级也是 `ERROR`**：`trace_utils.permission_skipped` → `EventType.ERROR` +
  `payload.kind == "PermissionSkipped"`（另有 `permission`/`function`/`fallback`）。
  真错误与降级同 type、靠 `payload.kind` 区分。

### 10.2 读侧：`read_run_events(run_id) -> list[Event]`

扫 `trace_data/<run_id>/episodes/*.jsonl`，逐行解析、**按 `event_id` 升序排**返回。

契约（进 docstring）：
- 前置：`run_id` 非空。
- 后置：返回事件 `event_id` 严格升序；解析失败的残行（被杀进程留下的半行）跳过，
  不中断（`store.py` 的 `_episode_is_complete` 已有跳过残行的先例）。
- 事件解析用 evaluation 内部的轻量结构（字面字段），不 import 包内 `TraceEvent`。

### 10.3 延迟口径契约（Δt 归本事件）

```
对有序事件流 e_0, e_1, …：Δt_i = ts(e_i) − ts(e_{i−1})   （i ≥ 1）
Δt_i 归给 e_i 的 (source, type)。
Source.X 的链路延迟 = X 下所有 type==MODEL_CALL 事件的 Δt 分布（中位/p90/max）。
```

为什么成立：`MODEL_CALL` 事件在**调用完成后**才写，所以它的 Δt ≈ "调用前本地
准备 + 调用本体"；`MEMORY_READ` 的 Δt = 检索耗时，归 `MEMORY`，不会污染相邻
模型链路（真实样本：judge call 与下一条 decision call 之间隔 42s 的 memory_read，
Δt 口径下那 42s 归 MEMORY，judge 只算到它自己那段）。`attempt>1` 时每次尝试是
独立 MODEL_CALL、独立 Δt。

已知误差（v1 接受，报数时心里有数）：step 边界前的小段空闲（evolve 等待等）
可能算进前一个 MODEL_CALL；归因仍不准的段 = **trace 不够密**，根治方向是补
事件边界（如检索起止），不是加字段。

### 10.4 聚合核心：`aggregate_events(events) -> RunMetrics`

吃事件序列（跨 run 调用方把多个 run 的 events 直接 concat——每个 run 内部已
有序，聚合只做计数与分布，不依赖 run 间相对顺序），产出按 `Source` 的指标：

| 指标 | 来源 |
|---|---|
| `calls` / `ok` / `failed` | MODEL_CALL 计数 / `payload.ok=="True"` / `=="False"` |
| `retries` | `Σ max(0, int(payload.attempt)−1)`（attempt 缺失按 0） |
| `tokens_in` / `tokens_out` | `Σ int(payload.input_tokens/output_tokens)`（解析失败计入 `malformed`） |
| `error_kinds` | `type==error && kind!="PermissionSkipped"` 的 ERROR 按 `payload.kind` 分组 |
| `degraded` | `type==error && kind=="PermissionSkipped"`，按 `payload.permission` 分组 |
| `latency` | 10.3 Δt 口径：p50 / p90 / max |

run 级汇总（同一函数或报表层）：episode 数（EPISODE_START 计数）、success/fail
（EPISODE_END.success）、总 token、run 时长（RUN_START → RUN_END 的 ts 差）。

#### 10.4a 审计失效率（`Source.VERIFY`，0902 第二轮补充）

只对 `source == "verify"` 有意义：`trace_utils.verify_call` 把 `StepVerifyVerdict`
列表结构化落进 `MODEL_CALL.payload["verdicts"]`（JSON 字符串），这里解析它：

| 指标 | 来源 |
|---|---|
| `verify_total` | `Σ len(json.loads(payload.verdicts))` |
| `verify_unreliable` | `Σ` 判定里 `reliable == False` 的条数 |
| `verify_unreliable_rate` | `verify_unreliable / verify_total`（`verify_total==0` 时为 `None`） |
| `verify_parse_errors` | `verdicts` 字段存在但不是合法 JSON / 不是列表——跟 `malformed`
  （token 字段）是并列的另一种"记了账但读不出细节" |

没有 `verdicts` 字段的普通 model_call（decision/perception/judge 等）不受影响，
`verify_total` 恒为 0。这不是新的数据源——`verdicts` 一直在 trace 里，只是之前
`eval_report.py` 把 `Source.VERIFY` 当成普通链路参与 token/延迟聚合，从没解析
过这个字段本身。

### 10.5 报表 CLI：`evaluation/eval_report.py`

- 选组：`--prefix <base_run_id>`（实验批：`MMdd-HHMMSS-xxxxxx`，repeat 时
  `-rN` 同 base，`pokemon_agent/experiment/run_experiment.py`）｜`--run id1,id2`
  （API 手动 run：`run-YYYYMMDD-…` 没有 base，靠显式清单）。对比的真实维度是
  "代码版本"（`experiment_results/<run_id>/manifest.json` 的 git commit），
  v1 先不做跨版本 diff，只把一批跑成一页。
- 输出：第六节草案的每链路表扩展列（calls | ok | failed | retries | tokens_in |
  tokens_out | 降级 | p50 | p90 | max）+ run 级汇总行。Markdown 表落
  `experiment_results/eval_reports/<prefix>.md`，终端同步打。
- 跨 run concat 后再聚合（10.4），同一批各 run 的同一链路合成一份分布。

### 10.6 实现顺序与验证

1. `read_run_events`（读侧）
2. `aggregate_events`（聚合核心）
3. `eval_report.py`（CLI + 输出）

测试（`evaluation/tests/`，不连网、不 import pokemon_agent）：合成事件序列喂
`aggregate_events`，Δt 口径人工可算（构造已知 ts 差断言 p50/p90）；`read_run_events`
用样例 fixture 验证跨文件 event_id 归并与残行跳过；10.4a 的三段测试覆盖
可信/不可信混合判定、`verdicts` 解析失败计入 `verify_parse_errors`、没有
`verdicts` 字段的普通链路不受影响（`evaluation/tests/test_eval_report.py`，
17 个用例全过）。

### 10.7 本 v1 不做（边界）

- 权限配置完整性校验、降级**主动**告警——ROADMAP 第 2 条的另两块，另行讨论；
- `duration` 字段（10.3 拍板）；
- 美元换算（三·2）。

**观测台实时数字/UI 已完成（0902 当晚）**，不再是边界之外的事——`pokemon_agent/
api.py` 新增 `GET /runs/{id}/metrics`，直接复用这里的 `aggregate_events`，喂的
是内存事件表（`handle.trace.events()`），run 没跑完也能看。当时预告的两个方案
"挪核心进包"或"API 侧包一层"都没用上，走了第三条更省事的路：**惰性 import**——
`from evaluation.eval_report import aggregate_events` 放进端点函数体内，不放
`api.py` 模块顶部，这样 `evaluation/` 缺失只影响这一个端点，不影响
`pokemon_agent.api` 本体的可导入性，绕开了"包内 import 破坏装包"这个顾虑。
详见 `docs/ROADMAP.md` 第 2 条。
