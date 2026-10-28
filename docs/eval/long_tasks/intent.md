# intent —— 长期任务：跨 run 的记忆起点

> 流程位置：**intent.md**（待确认）→ spec → plan → 落码
> 关联：`docs/eval/mid_tasks/intent.md`（三档定义与 M1、M4）、`docs/eval/task_boundary/intent.md`、ROADMAP F13、B15、B16
> 状态：待确认。依赖：B16（逐键观察、摘要的 `index` 与 `facts`）合并；中期核实（V1、V3）的结果。

## 一、一句话意图

做两条"必须靠过往 run 的记忆才能完成"的长期任务：第二个 run 的起点带着由第一个 run 产生的、冻结的 run 记忆，考的是 agent 能不能读过往 run 的索引、取出其中的关键信息并用上。

## 二、为什么

1. 短期考一个 episode 内的 choose 与 task 记忆，中期考一个 run 内跨 episode 的记忆；"过往 run 索引"这条读取路径（`_read_run_index`、`RunMemory.index`）至今没有任何样本考到，因为现有存档的记忆都是空的。
2. 长期档的定义是"几个 run，只冻结 run goal"，但没有"带着非空记忆起跑"的起点就没法造。

## 三、做什么

1. **起点的造法（决定）**：用 oracle 跑第一个 run，让生产的记忆流水线（摘要器）照常产出这个 run 的记忆，**生成一次、人工审、冻结**。冻结物 = 第一个 run 结束时的 `.state` 加一份可被评测入口当作初始记忆根载入的记忆快照（`TaskMemory` / `EpisodeMemory` / `RunMemory` 文件）。第二个 run 才是被测对象。
   - 不选"用上一个 agent run 的真实输出当起点"：它混进了第一个 run 的成败与随机性，第二个 run 失败时分不清是记忆没用上还是记忆本来就不好。
   - 不选"手写记忆"：不真实，测不到摘要器产出的索引形状与关键词。
2. **两条任务**：
   - **L1 `long_parcel_deliver_from_memory`**：run 1（oracle）= M1 的第一个 episode（进店领包裹，停在店内）；run 2 目标：「把店员托你送的东西送到该收的人手里。」起点背包里有包裹（RAM 可见），但收件人与地点只在 run 1 的记忆里（`index.keys` 应含 PROF. OAK、PALLET TOWN）。判据沿用 M1 的 `parcel_delivered`。
   - **L2 `long_customers_hint_buy`**：run 1（oracle）= M4 的第一个 episode（问两位顾客，停在店内）；run 2 目标：「去宝可梦中心把队伍治好，然后回商店买 1 件其中一位顾客提到过、店里又确实在卖的东西。」顾客台词只在 run 1 的记忆里。判据沿用 M4 的 `customer_hint_purchase`。
3. 每条任务设三个读取设置做消融：(a) 过往 run 索引读取开；(b) 关闭"过往 run 索引"；(c) 关闭知识库。(b) 与 (a) 的差就是跨 run 记忆的贡献；M4 一类知识库里可能直接写了答案，所以 (c) 要看。
4. 指标：任务成败（`pass_at_k`）、`agent_steps / oracle_steps`、run 2 里是否读取并引用了 run 1 索引里的关键词（读取与使用分开记）。检索指标（Recall@k、MRR）等有了检索真值再报。

## 四、不做

- 不做三个以上的 run；不做 run 之间的长时间间隔或遗忘；不测记忆写入质量本身（那是摘要节点的量表）。
- 不用上一轮 agent 的真实输出当起点；不手写记忆。
- 不改现有 20 条短期样本与 M1–M5。

## 五、待确认与待查

1. 评测入口现在**能不能以"初始记忆根"启动 run**：只在 `evals/agent_short_goal_run/dataset/build/injured_start.py` 里看到相关用法，需要读一遍 `solver/runner` 与 `writable_memory.py`，确认记忆根如何指定、冻结的记忆文件如何校验（hash）；不能就要补一个最小入口，写进 spec。
2. 冻结记忆的摘要由哪个模型产出：需要一次真实模型调用（生成一次，不进 pytest，人工审后冻结）；用评测默认的摘要模型还是单独指定，由你定。
3. oracle 跑 run 1 的轨迹要能被记忆流水线消化（要产生合法的 trace 与 `ActMemory`）：是让 oracle 走完整的 harness 图（用脚本化的假大脑替代 choose），还是把 oracle 的按键序列回灌成 trace，两者工作量不同，等 B16 合并后实测。

## 六、成功的样子

- 两条任务的 run 2 起点可加载，冻结记忆的 hash 可核；oracle 的 run 2 在带记忆设置下通过判据。
- 关闭过往 run 索引后，同一批 agent 的成功率显著下降，或者至少 run 2 引用 run 1 关键词的比例下降，证明任务确实在考跨 run 记忆。

## 评测入口调查结果（2026-10-28）：第二个 run 能不能带着第一个 run 的记忆起跑

**现状：不能，但缺口小。** 读 `evals/common/eval_services.py`、`evals/agent_short_goal_run/solver/solver.py`、`solver/runner/one.py`、`evals/common/overlay.py` 与 `harness/run/perceive/read_plan_context.py`：

- 每条样本启动一套**独立**的 memory 服务，根目录是 `tempfile.mkdtemp` 临时目录，里面只放从仓库 `memory/knowledge_memory` 复制来的知识 Markdown；样本结束整个目录 `rmtree`。所以第二个 run 起跑时 memory 里除知识外是空的，第一个 run 的记忆也没有被导出。
- 好消息：规划层读"别的 run 的记忆"这条路本来就在（`_read_run_index` 读到的 run 记忆里滤掉 `run_id == 本 run` 的，其余都作为 run 索引），所以只要第二个 run 的 memory 根里放着第一个 run 的记忆文件，现有读取逻辑不用改。
- 需要补的三处小改动（留给长期数据集的 spec）：
  1. `eval_services` 增加可选的 `memory_seed`（一个目录，起服务前把它的内容复制进临时根的 `memory/`，做法同 `_prepare_knowledge`），每条样本仍然隔离，结束仍然清理；
  2. 数据集样本新增可选字段 `initial_memory`（相对路径加 sha256，仅长期档允许），加载时核对哈希，`solver` 把它传给 `eval_services`；
  3. 生成种子需要把第一个 run 的 memory 根在清理前导出：`eval_services` 增加可选的"退出前导出 memory 根到指定目录"。

## 设计原则（用户确认）：不靠"中途藏起记忆"制造需要

长期任务里，第二个 run 需要记忆，必须来自**游戏状态里本来就没有、只在上一个 run 里出现过的信息**（例如包裹的收件人只在托付对话里说过一次，之后画面、内存、背包里都没有），而不是我们把本来看得见的东西（知识库条目、地图连接）临时关掉。因此：

- L1 保留包裹交付（第二个 run 起点在"已拿到包裹"之后，背包里有包裹，收件人只存在于第一个 run 的记忆里）；知识库在第二个 run 里**照常开着**。
- 记忆开 / 关对照是评测运行设置里的消融（同一份数据集跑两遍），不是任务设计的一部分；任务本身不含"被藏起来的东西"。
- 因此包裹交付的前置实验仍然需要：从 `knowledge_dialogue_advance` 起，核实托付对话逐句、包裹进背包的时刻与事件位、交付的时序与台词、第二个 run 的起点存档怎么产生（把托付对话按完后用游戏自己的状态保存，不改内存）。
