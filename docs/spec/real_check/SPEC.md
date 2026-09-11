# real_check —— 真实链路核对规格（六个维度）

> 位置：`experiment/real_check/`。一个维度一个文件，`python -m`
> 独立进程运行，互不依赖对方的执行逻辑（只共享 `common.py` 的纯函数与路径）。
>
> **核心目的**：验证 `RunHarness` 接真实 Brain / agent_permission / PyBoy 跑通全链路。
> 这类 bug（例如权限运行时初始化顺序）只有接真实依赖才会现形，Mock 驱动的测试测不出来。
> 每个维度有独立的通过/失败判定。

## 运行方式

```bash
# 维度 1：驱动真实链路跑一局（生产者，生成全部产物）——重负载
python -m experiment.real_check.check_harness

# 维度 5：完整跑一局 + 从中段存档恢复续跑（两次真实 PyBoy + 模型）——最重
python -m experiment.real_check.check_restore

# 维度 2/3/4：只读产物做核对（消费者，秒级，不起模拟器/模型）
python -m experiment.real_check.check_trace
python -m experiment.real_check.check_checkpoint
python -m experiment.real_check.check_memory

# 维度 6：MemoryTool 真实读写回环（fastembed 本地推理，无外部 key 依赖）
python -m experiment.real_check.check_memory_roundtrip
```

环境变量：维度 1/5 需要 `ARK_API_KEY` 与 `DASHSCOPE_API_KEY`。

## 产物定位

维度 1/5 跑完会把 `(run_id, episode_id)` 写进 `trace_data/.last_realcheck.json`。
维度 2/3/4 通过 `common.resolve_run()` 定位产物：**优先读指针；指针缺失/失效时
回退扫描** `trace_data/` 下最新的 `restorecheck-*` / `realcheck-*` 目录，取其中
最近修改且非空的 episode 级 jsonl。会话重启会丢后台进程和指针文件，产物还在——
回退扫描保证核对不依赖"上一个脚本恰好跑完了最后一行"。

## 六个维度

### 维度 1 —— `check_harness.py`：跑得完

唯一真正"从零驱动"的脚本。`build_real()` 装配 PyBoy + 真实 Brain +
agent_permission + 四路真模型（perception/judge 走 DashScope Qwen，verify/plan
走火山方舟豆包），从 `assets/rom.state` 存档跑一个 3 步短目标
（`GOAL = "向北走一步看看反应"`）。

**通过判定**：整张图 `begin → plan → dispatch → ... → run_end` 跑到底不崩，
返回 `RunOutcomeResp` 且 `steps ≥ 1`、`reason` 非空。
打印分 6 个 `[n/6]` 阶段标记，硬崩溃时看停在哪个标记就能归因到
build_real（装配）/ harness.run（图 + 模型调用）/ world.stop（收尾）。

### 维度 2 —— `check_trace.py`：记账落盘对不对

读 `trace_data/<run_id>/episodes/` 下的 run 级（`<run_id>.jsonl`）与 episode 级
（`<run_id>-epN.jsonl`）两个文件。两个文件交叉分配 event_id，**必须按 event_id
全局排序后判断**，不能按文件读取顺序。

**通过判定**：① 排序后 event_id 严格连续（无缺号、无重号）；
② `payload.kind` 同时出现 `run_start / run_end / episode_start / episode_end`；
③ 至少一条 `type=model_call`（证明真的调了模型，不是空跑）。

### 维度 3 —— `check_checkpoint.py`：存档配对

读 `checkpoints/step/<episode_id>/` 下的 step 存档——每份由一对 `<step>.state`
（模拟器世界快照）+ `<step>.json`（**EpisodeRunState dump ＋ 当时的 RunState
dump ＋ 游标**，提交点）构成。0909 起没有独立的 `run.json`：run 级状态（目标栈/
结算）跟 episode 级状态打包进同一份 `<step>.json`（同一局内 RunState 不变，
只在局间被 `dispatch`/`reflect` 改动），resume 只需读一份文件就能同时重建
两层状态——原先 `resume_run()` 靠"猜 step=0 该读哪个文件"读 run 锚点，
只要这一局跑过 step0 就会被自己的 step0 存档抢先命中，run.json 永远读不到，
这是实测踩出来的真实 bug（详见 `PLAN_checkpoint.md` v5 变更），不是这次顺手
优化。

**通过判定**：state 与 json 的文件名（不含后缀）集合完全一致；json 里能读出
非空的 `run_state_dump` 且其 `run_id` 与当前 run 一致。不成对 = 存档写坏了，
`CheckpointTool.load()` 恢复时会直接拒绝。

### 维度 4 —— `check_memory.py`：记忆落盘自洽

查 `pokemon_agent/memory/episode/memory/steps-<episode_id>.jsonl`（StepMemory）
与 `pokemon_agent/memory/semantic/object_events/ep-<episode_id>.jsonl`
（ObjectMemory）。

**通过判定**：两个文件**不存在是正常的**（episode 成功收尾后 StepMemory 被
蒸馏链 `discard_episode_steps` 清空；3 步任务大概率不触发物体交互）；
但存在就不能是空文件——空文件是"写了一半/清了一半"的中间态。

### 维度 5 —— `check_restore.py`：真实跨进程存档恢复

维度 1-4 全部只查"落盘产物长什么样"（写路径的静态检查），维度 5 补上
**读回路径的真实执行**：

- **阶段 A**：`build_real` 完整跑一个 3 步 run，生成 trace / checkpoint / 记忆产物；
- **阶段 B**：模拟"崩溃后重启"——读**要恢复到的那一步自己的 checkpoint**
  （`step/<eid>/<N>.json`，0909 起 run.json 已合并进来，见维度 3）拿事件游标，
  带 `resume_cursor` 重新 `build_real`（新进程语义：trace 从游标 +1 续写），调
  `resume_run(run_id, episode_id, step)` 走
  `CheckpointTool.load → void_after（废弃时间线归档截断）→ 世界快照回载
  （load_state_bytes）→ 状态重建 → 进图续跑`。

**通过判定**（五条独立）：① 阶段 B 返回 `RunOutcomeResp`；② trace 里出现
`checkpoint_restore` 事件且 restored 三元组（episode_id, step）对得上；
③ 恢复后**有效**事件（valid=true）按 event_id 全局排序仍严格连续——主前缀
[0..cursor] 连续、游标之后从某个 >cursor 的号起连续，中间的缺号正是被废弃的
分支（盘上还在、只是 valid=false）；④ `checkpoints/voided-*/` 归档目录真实生成；
⑤ 记忆侧跟着一起作废：`(episode_id, step)` 至多一条 step 记忆；该局恢复前的
**跨局摘要**必须已被归档（恢复前后 uuid 无交集）且恢复后该局至多一条摘要；
`memory/voided-*/` 确有新增。

`--step N` 指定恢复到该局第几步开局（不给则取最后一个存档步，即原先的唯一口径）。
末步恢复**也会**归档该局的跨局摘要——局收尾（verify → `write_episode`）发生在最后
一个 checkpoint 之后、且自己没有 checkpoint，任何恢复点都会把那次收尾圈进废弃
窗口；`--step 1`（中间步）才可能额外压到 step 记忆的归档路径，前提是阶段 A 在
恢复步真的执行过动作（目标一步即达成时压不到，此时判定 5 的第一条是真空过）。
跑完把 last-run 指针指向恢复后的时间线，维度 2/3/4 可直接复核恢复后的产物。

### 维度 6 —— `check_memory_roundtrip.py`：MemoryTool 真实读写回环

维度 4 只查"记忆文件落盘了没有"，维度 6 把 MemoryTool **每条读写路径**在真实
实现下过一遍：真实 `MemoryStore`（注入临时 `memory_root`，不污染真实记忆库，
跑完清理）、
真实 fastembed ONNX（embedding + reranker）、真实权限运行时（`@initialize`，
方法上的 `@require_permission` 全部生效）。

**通过判定**（五条独立）：
1. episodic 写读回环：存 3 条单步记忆 → 升序读回、最近 N 条读回；
2. object 写读回环：追加 3 条交互事件 → 按地图升序全量读回、按格过滤读回、空格返回空；
3. 知识库混合检索：真实知识库（`memory/semantic/knowledge/*.md`，BM25 + 向量 +
   reranker）命中合理条目（实测"野外遇敌"查询命中 `wild_encounters.md` 排第一）；
4. 跨局摘要写入 + 混合检索 + **run_id 隔离**：自造摘要落盘后检索命中它，
   且换一个 run_id 查不到（失败局蒸馏的"已验证"经验跨 run 污染决策是真实风险）；
5. 截断（checkpoint 恢复的记忆侧）：`void_memory_after(eid, 2)` 后 step>2 的
   单步记忆与交互事件、**以及该局的跨局摘要**（摘要不按 step 筛，整条走）全部
   消失，返回计数精确（含 `episode_memories`）；再删 `index.json` 强制重建，
   被归档的记录不得复活。

## 已验证状态（2026-09-09 凌晨）

| 维度 | 状态 | 结果 |
|---|---|---|
| 1 harness | ✅ 跑过 | 真实链路跑通 3+ 步，出 RunOutcomeResp（0908 两次 + 0909 一次） |
| 2 trace | ⏸ 待跑 | 依赖一次完整 run 的产物（0909 的 run 被会话重启截断，无 run_end） |
| 3 checkpoint | ⏸ 待跑 | 同上；0908 的产物曾被清空，需重新生成 |
| 4 memory | ⏸ 待跑 | 同上 |
| 5 restore | ⏸ 半程 | 阶段 A 未跑完（进程随会话重启被杀，非硬件断电）；需重跑 |
| 6 memory_roundtrip | ✅ 全过 | 五条路径全绿，临时目录已清理 |

## 已知事项与风险

1. **硬件断电风险**：0908 两次真实链路运行都在 `Brain.judge` 带图调用时触发
   Kernel-Power 41（BugcheckCode=0，非蓝屏硬断电）。该机为七彩虹 MEOW R16
   游戏本（非虚拟机），Event 41 历史频繁，怀疑过热保护/供电问题。维度 1/5
   是全链路负载最高的场景，**跑之前做好心理与数据准备**。
2. **`max_steps` 疑似未硬性封顶**：0909 的 restore 阶段 A 中，3 步任务实际跑到
   step 9 仍未终止（ep2 存了 step 0-9 的存档）。`recursion_limit` 公式
   `(max_steps - step) * 17 + 20` 按理应在 step≈4 截断，实际没有——
   值得查一下 judge 兜底/步数计数的语义。
3. **会话重启会杀后台跑批**：后台进程跟随会话生命周期，重启后产物保留但
   指针丢失（维度 2/3/4 的 `resolve_run` 回退扫描即为此设计）。
4. **pytest 版本**：`tests/test_real_integration.py` 是同一规格的 pytest 形态，
   因 pytest 进程曾伴随系统重启事件被弃用（原因未查明，不排除巧合），
   独立脚本形态是当前主用形态。
