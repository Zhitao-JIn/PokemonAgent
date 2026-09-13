# PLAN_wikiskill_reproduction —— 复现 WikiSkill 的三层机制

> 目标：**忠实复现 WikiSkill（Google Research, arXiv 2608.27454）的三层架构与四步进化循环**，
> 把它落在本项目现有的 trace / memory 骨架上，新增 skill 层。
> 本文是设计规划，不是变更日志；动代码前先读这里，动完代码按 AGENTS.md 追加 `CHANGELOG.md`。
> 状态：**草案，待拍板**。

---

## 〇、先说清楚"复现"是什么意思

WikiSkill 是一个**技能进化框架**，不是一个记忆库。复现它 ≠ 把它的文件格式抄过来，
而是把它的**机制**跑通并观察它是否成立。因此本文的验收标准是：

1. 论文里的三层（raw / wiki / skill）在本项目里**物理上分得开**；
2. 论文里的四步循环（执行 → 归纳 → 提案 → 门控）能**跑起来**，每步都有 trace；
3. 论文声称的两个性质能被本项目的数据**检验**：Wiki 永不回滚、Skill 可回滚。

**明确不属于本次复现范围的**：论文里针对通用 agent 的那套 `SKILL.md` 文件协议细节
（`PURPOSE.md`、页面级单元测试、最小权限护栏）。这些是为"技能是任意代码模块"设计的，
本项目的动作空间是固定的按键集，照抄会变成空架子。**要复现的是机制，不是文件格式。**

---

## 一、三层与现有模块的映射

| WikiSkill 层 | 论文定义 | 本项目落点 | 现状 |
|---|---|---|---|
| **Raw Layer** | 不可变执行轨迹 + 成败标签 | `trace_data/<run_id>/events/*.json` | ✅ 已达标 |
| **Wiki Layer** | 结构化知识条目（失败模式/有效策略 + 战绩） | `memory/` 扩一个 kind | 🚧 需扩 |
| **Skill Layer** | 可回滚的程序性指令 | 新增 `skills/` + harness 节点 | 📋 全新增 |

### 1.1 Raw 层：trace 已经天然满足，一行不用改

论文要求 Raw 层**不可变、可回放、作为唯一证据源**。对照 `trace/store.py`：

- `events/<run_id>-<event_id:012d>.json`，一条事件一个文件，`_atomic_write_text` 原子写；
- `event_id` 严格单调，`_next_id` 从盘上算而非从游标算；
- **废弃不打删除、原地打 `valid=false`**（`void_after`）——这正是"不可变"的正确实现：
  历史留在原处，只是被标记。

**唯一需要新增的**不是存储，是一个**只读的索引视图**：把一次 run 的轨迹编译成
"一次任务执行"的记录（任务描述 + 轨迹 + 成败标签），供 Wiki Maintainer 消费。

> **设计决定 D1**：Raw 层**不加任何新存储**。新增一个纯函数
> `wikiskill/raw.py::compile_trace_to_run_record(run_id) -> RunRecord`，
> 从现有 trace 读盘并组装。理由：Raw 层已经完备，再加一层只是重复 AGENTS.md 铁律 6 的保证。
> 它住在 `harness/`（编排层），**不进 `memory/`**——memory 不该理解"任务"这个概念。

### 1.2 Wiki 层：不是新建，是给 memory 扩一种内容形态

这是最容易搞错的一层。**Wiki 层不等于 `memory/`**，它是 `memory/` 里的一种 kind。

现有四类 kind 的性质对照：

| kind | 一条 = | 是否跨运行 | 是否带战绩 |
|---|---|---|---|
| `step_memory` | 一步 | ❌ 局内 | ❌ |
| `object_memory` | 一格上的一个事件 | ❌ 局内 | ❌ |
| `episode_memory` | 一整局蒸馏 | ⚠️ 局级 | ❌（有 quality_score，但不是战绩） |
| `knowledge_memory` | 一条手写先验 | ✅ 全局 | ❌ |
| **`wiki_memory`（新增）** | **一个失败模式 / 一条有效策略** | ✅ **跨运行归纳** | ✅ **必需** |

**关键差异（也是 WikiSkill 最值钱的设计）**：`episode_memory` 是"这一局发生了什么的总结"，
一次运行产生一条；`wiki_memory` 是"跨多次运行归纳出的模式"，**一条 wiki 条目对应 N 次运行的证据**。

> **设计决定 D2**：新增 kind `wiki_memory`，作为 `memory/store.py` 的第五个 kind。
> **不改 `MemoryStorePort`** —— `put/get/filter/search/rank` 这套接口完全够用，
> wiki 层需要的"战绩"通过 `metadata` 传（见 §1.2.1）。这验证了 AGENTS.md 里
> "Port 收裸字段"这条设计的正确性：**新增一种记忆类型不需要动接口**。

#### 1.2.1 战绩字段怎么过 `dict[str, str]` 的窄门

`MemoryStorePort.put` 的 `metadata` 是 `dict[str, str]`，且 `filter` 只支持等值匹配。
WikiSkill 的战绩是**统计量**（成功次数/失败次数），这看起来是个冲突。**其实不是**——

按 `ports.py` 已经写好的分工："数值型的大小比较由调用方自己先用等值条件把候选集筛到足够小，
再对候选集里的字段做数值比较"。所以：

- **metadata 只放等值可查的分类字段**：`domain`（战斗/导航/对话）、`topic`、
  `status`（`active` / `deprecated` / `voided`）、`evidence_count`（字符串化的整数，
  等值查"被引用次数恰好是 N"没意义，但它作为**排序键**有用）。
- **战绩结构进 `payload`**：`payload` 是 `dict`，可以装任意结构，检索不碰。

新增 schema（`schemas/memory/datastore/wiki_memory.py`）：

```python
class WikiEvidence(BaseModel):
    """一条证据：某次运行的一次观察，支撑或推翻这条 wiki 条目。"""
    run_id: str
    episode_id: str
    step: int
    outcome: Literal["support", "refute"]  # 支持 / 推翻
    note: str = ""                          # 具体发生了什么

class WikiMemory(BaseModel):
    """一条 wiki 知识条目：跨多次运行归纳出的一个模式。

    与 EpisodeMemory 的本质差异：那条是"一局的自述"，这条是"N 局归纳出的结论"。
    """
    domain: str                              # 领域（战斗/导航/对话/…）
    topic: str                               # 主题，同 domain 下唯一标识
    pattern: str                             # 归纳出的模式（正文，md 主内容）
    claim: str                               # 一句话结论：这类情况该怎么做
    root_cause: str = ""                     # 论文的根因分析
    evidence: list[WikiEvidence] = []        # ★ 战绩：这条结论基于哪些证据
    revision: int = 1                        # 第几版（被新证据改写时 +1）
    superseded_by: str | None = None         # 被哪条新条目取代（指向 uuid）

    @property
    def support_count(self) -> int: ...      # 战绩：支持次数
    @property
    def refute_count(self) -> int: ...       # 战绩：推翻次数
    @property
    def track_record(self) -> str: ...       # 渲染成 "3 支持 / 1 推翻"
```

> **设计决定 D3**：**战绩只算不改**。`evidence` 是 append-only 列表，战绩由它派生
> （`support_count` 是 property 而非存储字段）。理由：论文要求"被新证据推翻的结论会被
> 改写，而不是无限追加"——改写的是 `claim`/`pattern`（`revision` +1），
> 而 `evidence` 永远保留。这正是"Wiki 永不回滚"的落地形态：**结论可改，证据不删**。

### 1.3 Skill 层：唯一真正的新增，且它不属于 memory

这一层必须新建，且必须**放在 harness 层**，原因：

- 它要进 prompt 影响动作 → 属于编排；
- 它要能回滚 → 需要版本与门控 → 属于编排；
- 它是 `SKILL.md` 式的**程序性指令**，不是"发生了什么"的客观记录。

放进 `memory/` 会直接违反 AGENTS.md 四的分层原则第 1 条
（"memory 只保管 harness 交给它的数据结构与索引、按键原样读写"）。

**新建独立模块 `pokemon_agent/skills/`**（与 brain/memory/trace/world 平级）：

```
pokemon_agent/skills/
├── __init__.py          统一出口
├── ports.py             SkillStorePort（对外唯一 Port）
├── store.py             落盘实现：一条技能一个文件夹 + active 指针
├── domain.py            本模块方言：Skill / SkillVersion / SkillPatch
└── interface/
    └── skill_port.py    （若需拆分对外契约）
```

落盘布局（对齐论文的 `skills/` 目录形态）：

```
skills/
├── <skill_name>/
│   ├── active.json          # 当前生效版本的指针 + 元信息
│   ├── versions/
│   │   ├── v1.md            # 每版正文：指令 + 适用条件
│   │   ├── v2.md
│   │   └── v3.md
│   └── impact.jsonl         # 每次提案的结果（接受/拒绝 + 原因）——论文的 skill-impact
└── _index.json              # 技能清单（派生物、可自愈重建，同 memory 的 index.json）
```

> **设计决定 D4**：`skills/` 是**独立模块**，不是 `memory/` 的子目录。
> 对外只暴露 `SkillStorePort`，契约收裸字段，不认识本项目 `*Req` 信封——
> 与 brain/memory/trace 同一套待遇。调用它只发生在 `tools/skill_tool.py`。
> 这样 `skills/` 也能整体拷走复用。

---

## 二、四步进化循环怎么落到 harness

论文的四步：**Inference Agent → Wiki Maintainer → Skill Proposer → Gating**。

**关键约束（论文实测的反直觉结论）**：Inference Agent 执行时**不能读 wiki**，
否则技能质量反降（63.7% → 60.9%）。所以四步是**两个时间尺度**：

- **步 1（执行）**：跑一局，是**在线**的，已经有了（`episode` 子图）；
- **步 2/3/4（归纳→提案→门控）**：是**离线**的批处理，跑在 N 局之后。

**这一点至关重要，也是最容易做错的地方。** 如果按"每局收尾都进化一次"来做，
就同时犯了两个错：(a) 违反了 Inference Agent 不读 wiki 的隔离要求，
(b) 每局改技能 = 归因污染（见 §四）。

> **设计决定 D5**：**新增一张独立的进化图 `EvolutionGraph`**，跑在 `run` 图之外、
> 由 `run` 正常收尾后触发（或手工触发）。它**不是** episode 子图里的节点。

### 2.1 进化图的节点设计

新建 `pokemon_agent/harness/evolution/`：

```
harness/evolution/
├── __init__.py
├── evolution_graph.py       图装配（对齐 run_graph/episode_graph 的风格）
├── evolution_state.py       EvolutionState（图状态载体）
├── evolution_entry.py       图外侧门
└── nodes/
    ├── collect_raw.py          步 1'：从 N 个已完成的 run 收集 Raw 记录
    ├── maintain_wiki.py        步 2：Wiki Maintainer —— 归纳失败模式/有效策略
    ├── propose_skill.py        步 3：Skill Proposer —— 读 wiki 提技能补丁
    ├── gate_skill.py           步 4：Gating —— 在验证集上测，接受或回滚
    └── close_evolution.py      写 impact 日志、收尾
```

拓扑（**线性四步，不循环**——循环由多次调用进化图表达）：

```
collect_raw → maintain_wiki → propose_skill → gate_skill → close_evolution → END
```

**为什么不做成环形**：对齐 AGENTS.md 五"循环用 StateGraph 承载，不手写 while 循环"
的精神，但环形的图在 LangGraph 里表达会增加复杂度，而"多轮进化"本来就是
"多跑几次进化图"，用外层调度表达更清晰。**先做线性，够用。**

### 2.2 四个节点各自干什么

#### `collect_raw` —— 步 1'

```python
def collect_raw(state: EvolutionState, runtime: Runtime[EvolutionDeps]) -> dict:
    """把指定的一批 run 的 trace 编译成 RunRecord 列表（Raw 层的读视图）。

    前置条件：state.run_ids 非空。
    后置条件：返回 {"run_records": [...]}，每条含任务描述、轨迹摘要、成败标签。
    """
```

**忠实复现的要点**：论文的 Raw 层每条记录含 **二元测试反馈**（成功/失败）。
本项目的成败标签 `EpisodeMemory.success` 已经有了，直接从 trace 的
`lifecycle/episode_end` 事件读。

#### `maintain_wiki` —— 步 2（论文的核心）

```python
def maintain_wiki(state: EvolutionState, runtime: Runtime[EvolutionDeps]) -> dict:
    """Wiki Maintainer：读 N 份 RunRecord，归纳出模式，写入/改写 wiki 条目。

    **它只归纳，不改技能**（论文的角色边界，必须守住）。
    产出分两类：
      - 新的失败模式 / 有效策略 → 新增 wiki 条目；
      - 推翻已有条目的证据 → 改写该条目的 claim，revision+1，evidence 追加 refute。
    """
```

这是一次 LLM 调用，走 `BrainTool` 同一套重试循环（`BRAIN_MAX_ATTEMPTS`）。
**Brain 不能持有状态**，所以这个"归纳"动作要以 `BrainTool` 上的一个新方法暴露
（`BrainTool.induce_wiki` 或类似），prompt 住在 `tools/prompts/`。

> **设计决定 D6**：归纳的 prompt 模板与组装函数住 `tools/prompts/maintain_wiki.py`，
> 与现有 `verify_and_summarize.py` / `decide.md` 同级。理由：AGENTS.md 六
> "prompt 是规则，入参是素材"——归纳规则的写法属于 prompt，不该硬编码进 harness 节点。

#### `propose_skill` —— 步 3

```python
def propose_skill(state: EvolutionState, runtime: Runtime[EvolutionDeps]) -> dict:
    """Skill Proposer：读 wiki 条目 + impact 历史，提出一次只改一个目标的技能补丁。

    论文的约束：**一次只改一个目标**（one objective per proposal）。
    产出一个 SkillPatch，不直接落盘——落盘由 gate_skill 决定。
    """
```

**它读 wiki，但 Inference Agent 不读**——这个不对称是论文的要点，注释里要写清。

#### `gate_skill` —— 步 4（门控）

```python
def gate_skill(state: EvolutionState, runtime: Runtime[EvolutionDeps]) -> dict:
    """Gating：在验证集上跑候选技能，严格优于才接受，否则回滚并记录原因。

    后置条件：Skill 层要么多一个版本、要么原地不动；
              **无论哪种结果，impact.jsonl 都追加一条记录**（论文要求：
              被拒绝的提案其失败原因也是资产）。
    """
```

**与 checkpoint 的接法（关键）**：这里复用现有机制——
候选技能不达标时，回滚 = 把 `active.json` 指针指回上一版。
不需要新的存储机制，不需要搬文件（版本都在 `versions/` 里躺着）。

---

## 三、四步循环里的三条数据流

```
                 ┌──────────────────────────────────────────┐
                 │  在线（每局一次，已有）                     │
   episode 子图 ──→ trace_data/<run_id>/events/*.json         │
                 └──────────────────────────────────────────┘
                                  │  只读，不反向
                                  ▼
                 ┌──────────────────────────────────────────┐
                 │  collect_raw：编译成 RunRecord            │
                 └──────────────────────────────────────────┘
                                  ▼
   ┌───────────────────────────────────────────────────────┐
   │  maintain_wiki：归纳 → 写 memory/wiki_memory/          │
   │     新证据 → 新增条目 / 改写 claim + revision+1        │
   └───────────────────────────────────────────────────────┘
                                  ▼
   ┌───────────────────────────────────────────────────────┐
   │  propose_skill：读 wiki + impact → 产出 SkillPatch     │
   └───────────────────────────────────────────────────────┘
                                  ▼
   ┌───────────────────────────────────────────────────────┐
   │  gate_skill：验证集测 → 接受（新版本）/ 拒绝（回滚）    │
   │     两种结果都写 skills/<name>/impact.jsonl            │
   └───────────────────────────────────────────────────────┘
```

**三条铁律在这条链上的落地**：

- 铁律 2（模块隔离）：`skills/` 不认识 `memory/` 的东西，两者只在 `tools/` 交换；
- 铁律 6（每步产 trace）：进化图的每个节点都要产 trace 事件——
  需要给 `EventType` 加新的事件 kind（见 §五）；
- 分层原则（memory 不做语义判定）：归纳这件事发生在 **harness 节点里的 LLM 调用**，
  memory 只负责把归纳结果按键存下来。

---

## 四、⚠️ 归因污染：这是复现前必须想清楚的事

**这一节是本文最重要的部分。**

本项目在验证"结构化 episodic 记忆 + 状态表在线归并 + MC 信用分配"的价值。
WikiSkill 的 skill 层会**自动改规则**——这是个会自己进化的干预项。

如果同时打开"记忆机制"和"WikiSkill 自动进化"，后面看到
"用了记忆比不用强"，**无法回答是记忆结构的功劳还是自动进化的功劳**。

> **设计决定 D7**：**WikiSkill 的自动进化默认关闭，按实验开关打开。**
> - `config.py` 加 `WIKISKILL_AUTO_EVOLVE = False`（默认关）；
> - 关闭时：`maintain_wiki` 与 `propose_skill` 仍可手工/批量触发，
>   但**产出的 wiki 与 skill 只记账、不生效**（`active` 指针不动）；
> - 打开时才是完整的四步循环。
>
> **对应论文的 ablation**：论文发现"让 Inference Agent 读 wiki 会掉分"，
> 我们这里加一条自己的 ablation——**"自动进化 vs 固定 wiki"的对照**。
> 这恰好是论文没做、而本项目有条件做的实验。

**另外一条必须记住的**：论文的 `gating` 需要**验证集**。
本项目的 `experiment/tasks.py` 已经有任务定义与 `experiment_states/` 钉死存档，
**这就是天然的验证集来源**——但需要一次划分（哪些任务当训练、哪些当验证），
且这个划分一旦定了就不能随实验变（否则门控失去意义）。

> **待定 T1**：训练/验证任务集怎么划分。这是 WikiSkill 能否跑通的前提，
> 但涉及实验设计，需要用户拍板。

---

## 五、需要新增的东西清单

### 5.1 schemas

| 文件 | 内容 |
|---|---|
| `schemas/memory/datastore/wiki_memory.py` | `WikiEvidence` / `WikiMemory`（§1.2.1） |
| `schemas/harness/evolution.py` 或复用现有信封包 | `EvolutionRunReq/Resp`、节点间信封 |
| `schemas/skills/`（新包） | `Skill` / `SkillVersion` / `SkillPatch` / `SkillImpact` |

**命名对齐 AGENTS.md 十二**：信封 `From[模块A]To[模块B][函数名][Req/Resp]`；
模块对外接口模型用裸名。

### 5.2 trace 事件类型

`EventType` 现有 7 类（0903 收敛原则：type 与生产者正交、数量极小）。
进化图的动作**归入现有类型**，不新增 type：

- `maintain_wiki` / `propose_skill` 的 LLM 调用 → `model_call` + `llm_outcome`（`payload.kind = "wiki_induce"` / `"skill_proposal"`）；
- 写 wiki / 写 skill → `memory_io`（`payload.kind = "write_wiki"`）/ 新增 skill 的 io kind；
- 门控结果 → `lifecycle`（`payload.kind = "evolution_gate"`）。

> **设计决定 D8**：**严格遵守 0903 收敛原则，不新增 `EventType` 枚举值。**
> 新语义全部降级为 `payload.kind`。理由：进化循环是新的 source，但
> "LLM 调用/写记忆/生命周期"这些**种类**没有变——新增 type 会让 check 脚本
> 的相位表失去一致性。

### 5.3 harness

| 新增 | 说明 |
|---|---|
| `harness/evolution/` | 进化图（§2.1） |
| `tools/skill_tool.py` | `SkillStorePort` 的门面，跨模块转换住这里 |
| `tools/prompts/maintain_wiki.py`、`propose_skill.py` | 归纳与提案的 prompt |
| `wikiskill/raw.py`（或 `harness/` 下） | Raw 层只读编译视图（D1） |

### 5.4 独立模块

| 新增 | 说明 |
|---|---|
| `pokemon_agent/skills/` | Skill 层的完整模块（D4） |

### 5.5 build.py

装配点加：进化图依赖、`SkillStore` 实例、`SkillTool`。
**仍然只有一个装配点**（AGENTS.md 三.3）。

---

## 六、实施顺序（建议，每步可独立验证）

**按"能早看到数据"排，不按"架构漂亮"排。**

| 步 | 做什么 | 验收 |
|---|---|---|
| **E0** | 写 `wiki_memory` schema + 手工写 3 条 wiki 条目落进 `memory/wiki_memory/` | `filter`/`search` 能查到，与现有 kind 无差异 |
| **E1** | `collect_raw` 纯函数：从 trace 编 RunRecord（**纯读，无 LLM**） | 给定 run_id 能还原出任务+轨迹+成败 |
| **E2** | `maintain_wiki` 节点 + prompt，**手工触发**（不开自动） | 跑一次，产出 wiki 条目，trace 有账 |
| **E3** | `skills/` 模块 + `SkillStorePort` + store 落盘 | 手工建一个技能，能读能回滚 |
| **E4** | `propose_skill` + `gate_skill` | 一次完整提案 → 门控 → 接受/回滚，impact 有记录 |
| **E5** | 接进 `run` 收尾（受 `WIKISKILL_AUTO_EVOLVE` 控制） | 默认关闭时行为与今天完全一致 |
| **E6** | 对照实验：自动进化 vs 固定 wiki | **这一步才回答"值不值"** |

**E0–E2 是纯收益**（提升现有检索质量，不碰架构），**E3 之后才动架构**。
建议 E0 先做，一周内能看到 wiki 条目对决策的实际影响。

---

## 七、待拍板清单

| 编号 | 问题 | 为什么需要用户拍板 |
|---|---|---|
| **T1** | 训练/验证任务集怎么划分 | 涉及实验设计，且划分定了不能改 |
| **T2** | `WIKISKILL_AUTO_EVOLVE` 默认关闭能否接受 | 直接影响归因能力（§四） |
| **T3** | 进化图是独立图还是 episode 收尾的一个节点 | 独立性更高但改动更大 |
| **T4** | `brain` 是否加 `induce_wiki` 方法（还是 harness 直接调 provider） | 涉及 brain 的 Port 契约边界 |
| **T5** | checkpoint 恢复时，"作废分支贡献的证据"怎么处理 | 见我上一轮对话的分析——论文没有答案，需自定 |
| **T6** | 是否保留论文的"一次只改一个目标"约束 | 忠实复现 vs 实用主义的取舍 |

---

## 八、与既有设计的一致性核对

| AGENTS.md 条款 | 本规划是否违反 | 说明 |
|---|---|---|
| 铁律 1（brain 无状态） | ✅ 不违反 | `induce_wiki` 每次全从参数来 |
| 铁律 2（模块隔离） | ✅ 不违反 | `skills/` 独立模块，跨模块只在 `tools/` |
| 铁律 3（Port 收裸字段） | ✅ 不违反 | `SkillStorePort` 收裸字段 |
| 铁律 6（每步产 trace） | ✅ 遵守 | 进化图每节点产 trace（D8） |
| 分层原则 1（memory 不做语义判定） | ✅ 不违反 | 归纳在 harness 节点，memory 只存 |
| 分层原则 2（只经 tool 交换） | ✅ 不违反 | `tools/skill_tool.py` 是唯一桥 |
| 五（LangGraph 承载循环） | ✅ 遵守 | `EvolutionGraph` 用 StateGraph |
| 十一（不做机制二/三） | ⚠️ **部分冲突** | 见下 |

### ⚠️ 关于第十一节"这个阶段明确不做"

AGENTS.md 十一写着：**"状态表在线归并（机制一）、MC 回填（机制三）、
skill library（机制二）、沙箱。别提前做。"**

WikiSkill 的 skill 层**与机制二（skill library）高度重叠**。这个规划等于把机制二提前做了。

**这不是我该替你决定的事。** 两条路：

1. **把它当作机制二的前身/变体**——先做一版能跑的，机制二正式做时再收敛；
2. **把它当作独立实验**——不动机制二的定位，WikiSkill 复现是"另一个东西"。

建议按 (1) 走，并在文档里注明"WikiSkill 复现 = 机制二的首次落地尝试"，
这样 AGENTS.md 十一不必改，只是那条"不做"的边界被**主动、有记录地**越过了。

> **待定 T7**：机制二与 WikiSkill 复现的定位关系，需要拍板。

---

## 九、一句话总结

**Raw 层你已经有了（trace），Wiki 层只需给 memory 加一个 kind，真正要新建的只有 skill 层
——而 skill 层是编排概念，必须住 harness，不能塞进 memory。**

复现的成败不在于代码量，在于**能不能守住论文那两个反直觉的约束**：
Wiki 永不回滚、Inference Agent 不读 wiki。守住这两条，复现才有意义。
