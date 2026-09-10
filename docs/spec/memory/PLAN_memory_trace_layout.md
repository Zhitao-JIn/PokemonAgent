# PLAN —— memory/trace 落盘布局重构：一条记录一个文件 + uuid 命名（2026-09-10 定稿）

> 状态：设计定稿，待实施。四点拍板 + uuid 命名规则均由用户 0910 确认。
> 上游依据：ROADMAP 24（记录标识 = 不带语义的 uuid；run_id/episode_id/step 等全部降级为
> 对等的 metadata 字段）；本方案是 24 条"存储形状"那半边的落地，**不含** MemoryToolPort
> 专用查询方法收敛那半边（见 §10 范围界定）。

---

## 1. 背景与目标

现状三类运行期产物落在包内（`pokemon_agent/memory/...`），trace 落在
`trace_data/<run_id>/episodes/<episode_id>.jsonl`（append + jsonl，"按局一个文件"）。
本次重构：

1. 四类运行期产物（StepMemory / ObjectMemory / EpisodeMemory / Knowledge）全部搬出包，
   挪到仓库根级 `memory/<run_id>/`，与 `checkpoints/<run_id>/`、`trace_data/<run_id>/`
   对齐成同一套"根级 + 按 run 分目录"约定。
2. 彻底放弃 append+jsonl，换成**一条记录一个文件**；truncate/void 从
   "读整份 jsonl → 过滤 → 临时文件重写 → rename"简化为对文件直接搬走/改写。
3. 文件名一律用 uuid，**不带任何语义**（无 run_id/episode_id/step/seq/event_id）。
   排序、过滤永远以解析文件内容得到的字段为准，文件名只给人肉眼看。

### 拍板记录（0910）

| # | 问题 | 决定 |
|---|---|---|
| 1 | 知识库要不要也挪进 run 目录 | 要。`memory/<run_id>/knowledge_memory/`，每 run 一份快照，共享源进 git（§4.4） |
| 2 | resume 作废的 Step/Object 文件删还是归档 | 归档到 `voided-<ts>/`，不 unlink——"落盘了就不丢"贯彻到废弃分支 |
| 3 | 废弃 trace 分支怎么处理 | 不搬走、不删，加 `valid` 字段原地打标；读端只过滤 `valid=false`，不需要"跳区间"逻辑 |
| 4 | 排序依据 | 以解析出的字段为准（step 按 `episode_id+step`、object 加 `seq`、trace 按 `event_id`） |
| 5 | 命名规则 | 全部 uuid，对齐 ROADMAP 24：记录标识不带语义，调用方不能也不需要从文件名反推任何字段 |
| 6 | 旧数据 | 不写迁移脚本，旧目录原地不动，新布局从空开始（开发期数据） |
| 7 | 截图归属与命名 | 截图绑定 trace 事件（不是 StepMemory），放 `trace_data/<run_id>/screenshot/`，文件名与对应事件共享 event_id，永远递增（§8） |
| 8 | 索引落盘 | **每个 memory 文件夹下保证一个倒排索引**——随记录写穿落盘为 `index.json`，派生物、可自愈重建（§5.1） |
| 9 | 截图 void | 取消截图归档——event_id 保证递增，resume 重跑不会撞名，废弃事件的截图原地保留，与 valid=false 的事件一起构成废弃分支的审计记录（§7/§8） |
| 10 | memory 是否按 run 分层 | **不分层**——run_id 只是元数据，四类产物全项目各一个文件夹（§2）；trace 仍按 run_id 分级不变 |

---

## 2. 最终目录布局

```
memory/                                # 全项目一份，不按 run 分层（拍板⑩）：run_id 是 metadata
├── step_memory/      <uuid>.json     # 一条 StepMemory 一个文件
│   └── index.json                    # 每个文件夹保证一份倒排索引（§5.1，拍板⑧）
├── object_memory/    <uuid>.json     # 一条 ObjectFactEvent 一个文件（同 step 多条靠 seq 字段）
│   └── index.json
├── episode_memory/   <uuid>.md      # 一局一个 md；跨 run 共池，run_id 过滤（ROADMAP 8）
│   ├── index.json
│   └── vectors.jsonl                 # 有 text 的文件夹自带向量 sidecar（§5.3）
├── knowledge_memory/ <uuid>.md      # 运营手写、进 git；不再有 run 快照（§4.4）
│   ├── index.json                    # 随源一起进 git
│   └── vectors.jsonl
└── voided-<ts>/                      # ②废弃归档：内部保留 step_memory/object_memory/
                                      #   episode_memory/ 分型子目录，文件原名照搬；
                                      #   归档文件不带索引——从检索世界消失；
                                      #   文件自带 run_id metadata，归档后仍可溯源
trace_data/<run_id>/                  # trace 仍按 run 分级（与 memory 的拍板⑩无关）
├── events/               <uuid>.json  # 一条 TraceEvent 一个文件（含 event_id + valid 字段）
└── screenshot/           <event_id>.png  # 人眼便利副本，与 trace 事件绑定（§8）：文件名 = 承载
                                          # frame_png 的那条事件的 event_id，永远递增、天然不撞
                                          # 名；不参与 void（拍板⑨）
```

不再存在的目录/文件：

- `pokemon_agent/memory/episode/memory/`（包内落盘点，整体退役）
- `pokemon_agent/memory/index/records/records.jsonl`（索引主体文件取消，§5.1）
- `trace_data/<run_id>/episodes/<episode_id>.jsonl`（按局 jsonl 取消）

---

## 3. 统一记录形状

四类产物在索引层是**同一种东西**，只有序列化形态不同：

```
Record := {
  uuid: str          # uuid4().hex，存储层生成，不带语义
  kind: str          # collection 名：step_memory / object_memory / episode_memory / knowledge_memory
  metadata: dict     # 全部过滤字段，字段间完全对等（episode_id / step / seq / map / scene / run_id ...）
  payload: dict      # 领域记录全文（StepMemory / ObjectFactEvent 的 model_dump）
  text: str          # 参与语义检索的文本；空串 = 这条记录语义检索不可见
}
```

序列化规则（由存储层按 kind 决定，调用方不感知）：

| kind | 文件 | metadata | text | payload |
|---|---|---|---|---|
| step_memory | `<uuid>.json` | 显式字段 | "" | `StepMemory.model_dump()` |
| object_memory | `<uuid>.json` | 显式字段（含 seq） | "" | `ObjectFactEvent.model_dump()` |
| episode_memory | `<uuid>.md` | JSON frontmatter | md 正文 | `{}` |
| knowledge_memory | `<uuid>.md` | JSON frontmatter | md 正文 | `{}` |

md 形态沿用 episode_store 现有约定："md 是唯一真相"——frontmatter 是检索要的
结构化元数据，正文给人看/给语义检索用；重启扫描目录解析 frontmatter 即可完整重建索引。

### 3.1 metadata 字段集：按 kind 各不相同，由 tool 层组装

上文示例里的三个字段只是片段。字段集**不是**索引层定的——ROADMAP 24 写入侧
对称：harness 把它知道的全部上下文递给 tool 层，tool 层组装字段集合，memory 只
机械存取、不理解任何字段含义。预期字段集（以 `memory_tool.py` 实际组装为准）：

| kind | 5 个代表字段（依据 = §3.2 消费方地图的实际调用） |
|---|---|
| step_memory | `run_id, episode_id, step, map, place` |
| object_memory | `run_id, episode_id, step, map, place`（`seq` 是同 step 多条的排序消歧字段，照存但不进检索字段） |
| episode_memory | `run_id, episode_id, scene, goal, success` |
| knowledge_memory | `scene, topic, tags, source, updated_at`（运营手写，共享源不挂 run_id） |

**5 个是代表不是上限**：其余字段照递照存、索引照建（ROADMAP 24 字段全对等）；
知识库当前纯语义检索无等值过滤，五个字段是给将来加过滤留的钩子。

- **run_id 必须进 metadata**（除 knowledge 共享源外）：目录分 run 管"文件放哪"
  （物理组织），记录内 run_id 管"这条记录是谁的"（逻辑归属自证，审计脚本单独
  捡起一个文件仍可溯源）。更硬的理由：episode_memory 摘要**本来就是跨 run
  检索的**（ROADMAP 8 的记忆污染观测、`query_episode_summaries` 的 run_id 过滤
  参数），记录不带 run_id，跨 run 过滤就断了。
- run_id 是普通过滤字段：跨 run 共池后，"查全池"与"只查本 run"的区别就是过滤
  字典里带不带 run_id，索引层无任何特判。
- 前置条件由 tool 层保证：该递的字段递全，缺字段是调用方 bug（同 ROADMAP 24
  "tool 层漏传该带的过滤字段是查询写错了"，memory 不兜底）。

### 3.2 检索消费方地图（谁在查、用什么查）

memory 检索的生产消费方全部集中在 `harness/episode_harness.py` 的检索节点、
`judge()` 与收尾链，另有 void 编排和 real_check 自检：

| 调用点 | 检索类型 | 用的字段/条件 |
|---|---|---|
| `judge()`（judge_success 取最近几步当证据） | 元数据：等值 + 区间 | `episode_id`；step 最近 N（tool 层数值收尾） |
| `retrieve_step_episode_memory`（decide→think 的本局记忆） | 元数据：等值 | `episode_id` |
| `retrieve_object_semantic_memory`（think 的 object 语义） | 元数据：等值 + 区间 | `map_id`；`step < before_step`（**跨局共有知识**，刻意不带 episode_id——ROADMAP 24 记录的既有取舍） |
| `retrieve_verify_step_memory`（收尾校验） | 元数据：等值 | `episode_id` |
| `retrieve_global_episode_memory`（跨局摘要） | **语义 + 元数据混合** | query=goal 做语义；`scene`、`run_id` 等值过滤 |
| `retrieve_knowledge_semantic_memory` | 纯语义 | query（observation 特征 + goal 拼，无等值条件） |
| `retrieve_verify_knowledge` | 纯语义 | query（verify entries + goal 拼，无等值条件） |
| `CheckpointTool.void_after()` 编排 | 元数据：等值 + 区间 | `episode_id`；`step > N-1`（N=恢复步）；该局摘要整条；future_episodes 整局 |
| `experiment/real_check/check_memory_roundtrip.py` | 自检（全方法） | — |

**观察**：元数据检索实际消费的字段恰好是 `run_id / episode_id / step / map /
scene` 五个——§3.1 每类 5 个代表字段的依据；语义检索里唯一带等值过滤的是
episode_summaries（scene + run_id），knowledge 目前纯语义。这佐证了 §10 的
范围界定：现有专用查询方法背后只有两种真实形状（等值筛选 + 语义召回），将来
收敛成 filter+search 两个通用方法时不需要任何新能力。

---

## 4. 四类产物的写入与生命周期

### 4.1 step_memory / object_memory（运行期产物，一局一批）

- 写入：harness → MemoryTool 组装 metadata（episode_id/step/map/...）→
  索引层生成 uuid、落一个 json 文件、进倒排索引。**写穿**（盘上永不落后于内存），
  落盘单文件改用"临时文件 + `os.replace`"原子写——jsonl 追加模式做不了的事，
  一条一文件之后顺手就能做。
- 局收尾：**不做任何记忆操作**（0910 晚些时候修正拍板②——`discard_episode_steps`
  整个撤除：step 记忆按 `episode_id` 查询天然隔离，没有清场的必要）。生命周期
  从"随局删除"变为"随 run 永久保留"。
- resume 作废：文件整体搬进 `voided-<ts>/`（§7）——**这是"记录退出检索"的唯一时机**。

### 4.2 episode_memory（跨局摘要）

- 蒸馏产出 → 一个 `<uuid>.md`；episode_id 从"文件名"降为 frontmatter 里的普通字段。
- 超限淘汰（`max_summaries`，按质量淘汰最差）：被淘汰的 md 同样**搬进
  `voided-<ts>/episode_memory/`** 而不是删除——与"落盘了就不丢"一致，淘汰是容量
  机制不是销毁机制。
- 跨 run 检索：episode_memory 的语义检索天然跨 run 可见与否由调用方的过滤条件决定
  （现在 `query_episode_summaries` 收 run_id 参数做过滤），索引层所有字段对等，
  不内置任何 run 隔离规则。

### 4.3 运行期写入的索引一致性

单进程写、单进程读，先落盘后进内存索引（沿用现有 put 顺序）。进程崩溃窗口 =
文件已落、索引未进——重启时索引从全量扫描重建，自愈，无需 WAL。

### 4.4 knowledge_memory（静态先验，共享一份，不再有 run 快照）

- **共享源即唯一副本** `memory/knowledge_memory/`：运营手写、进 git、`<uuid>.md`
  + `index.json`。uuid 由入库时机分配一次（本次迁移把包内
  `semantic/knowledge/*.md` 搬过去时一次性分配），之后运营改内容不改名。
- **run 快照取消**（拍板⑩去掉 run 层的直接后果）：这一局用过哪些知识，审计走
  trace 的 MEMORY_READ 事件——检索节点本来就逐次记账（refs/count），账比副本
  更细；不靠文件副本。
- 语义变化：源改动**即时生效**（原"下一个 run 生效"的快照隔离语义随之取消）——
  运营中途改知识库会影响进行中的 run，这是拍板⑩的已知代价。

---

## 5. MemoryStore 改造（元数据倒排索引 + 语义检索）

### 5.1 存储主体与每文件夹倒排索引（拍板⑧）

现状 put() 把整条记录追加写进 `records.jsonl`（先落盘后进索引，倒排索引是
不落盘的物化视图，重启 `_load_all()` 全量读回重建）。改造后：

- **records.jsonl 取消**。记录文件（§4 的 json/md）本身就是存储主体，落盘动作
  = 写那一个文件。
- **每个 memory 文件夹下保证一份倒排索引**：各 kind 目录内的 `index.json`
  （嵌套结构 `{field: {value: [uuid, ...]}}`），put / archive 时随记录写穿——
  先写记录文件（真相），再原子重写本文件夹的 `index.json`。knowledge 的
  `index.json` 随源一起进 git。
- **索引是派生物，可自愈**：真相永远是记录文件。启动时读 `index.json` 后做一次
  廉价对账（文件数 vs 索引 uuid 数、文件是否存在），不一致（崩溃窗口、手工动过
  目录、索引损坏）就地全量扫描该文件夹重建并重写索引。
- **启动不再全量解析记录文件**：filter 直接走 `index.json`；记录文件按 uuid
  **惰性读取**（`get()` 命中时、search 召回候选需要 text 时才读）——这正是索引
  落盘换来的收益：filter 查询零扫描。
- `voided-<ts>/` 不参与任何扫描与索引——归档即从检索世界消失，但文件仍在盘上
  可查（归档文件不带索引）。

**`index.json` 写法细则**：

- 盘上格式：嵌套 `{field: {value: [uuid, ...]}}`。metadata 值统一是字符串
  （ROADMAP 24：值怎么序列化由调用方决定），索引层不碰类型转换；内存表示沿用
  现状 `_inverted: dict[(field, value), set[str]]`，`index.json` 只是序列化形态，
  uuid 列表落盘前排序（同样内容写出同样字节，diff 友好）。
- 写路径（put）：生成 uuid → 写记录文件（tmp + `os.replace`，真相先落）→
  `_index_record` 进内存 → **全量重写**本文件夹 `index.json`（tmp + replace）。
  archive_many 对称：搬文件 → `_unindex_record` → 重写索引。
- 全量重写而非增量的理由：json 无法原地改，索引的更新单位是"字段桶"——一个
  `(field, value)` 桶 put 时会加、archive 时会删，append-only 表达不了收紧，要么
  compaction 要么全量重写；单文件夹千级记录、索引几百 KB，重写成本可忽略，且
  全量重写幂等、崩溃靠对账自愈，不需要 WAL。与现状 `delete_many` 重写整个
  records.jsonl 同一个既有取舍，触发频率从"删除时"变"每次写"。
- 顺序保证：先记录后索引，唯一崩溃窗口是"索引落后"——丢的只是索引条目，真相
  不丢；单进程崩溃即进程死，重启对账自愈，窗口实际不可见。

### 5.2 API（MemoryStorePort 同步调整）

```
put(kind, metadata, payload, text="") -> uuid      # kind 即子目录名（collection 概念，项目无关）
get(uuid) -> Record | None
filter(conditions: dict) -> list[uuid]             # 纯等值/成员匹配，取交集，字段全对等，无主键
search(query, limit, conditions=None) -> list[uuid] # 语义检索：先 filter 圈候选 → hybrid_retrieve
archive_many(uuids, dest_dir) -> int               # §7 void 用：文件搬进 dest_dir + 摘出内存索引
delete_many(uuids)                                 # 仅测试用；生产路径一律 archive_many
```

- `filter` 仍不支持大小比较（这层不认识"大于"）；step 区间语义（最近 N 步、
  before_step、void 的 step>N）由 tool 层先用 `episode_id` 等值筛小候选集、再做
  数值比较——ROADMAP 24 已定的分工，本次照抄。
- `search` 排序细节（BM25 bigram + embedding 余弦 + RRF + reranker 精排）对调用方
  不透明，只认一句话进、一串 uuid 出——`retrieval.py::hybrid_retrieve` 原样复用。
- **不设多文件夹模式**（拍板⑩后不再需要）：全项目各 kind 一个文件夹，
  episode_memory 天然跨 run 共池；`run_id` 就是普通过滤字段，要不要限定本 run
  由调用方决定（现有 `query_episode_summaries` 传 run_id 过滤，行为不变）。

### 5.3 向量缓存 sidecar

语义检索需要缓存好的向量（重算要调 embedding 模型，不能启动时现算），单独落：

- **每个有 text 的 kind 文件夹自带** `vectors.jsonl`（实际只有 episode_memory、
  knowledge_memory；step/object 的 text 恒空不需要），每行 `{uuid, vector}`，
  put 且 text 非空时追加。
- 启动重建：以索引/记录扫描结果为准，有 text 的 uuid 到 sidecar 里查向量；查不到
  的记录语义检索不可见（退化行为，与现状"text 为空不可见"同型），不阻塞启动。
- 归档（archive_many）后的向量行变成孤儿条目：不主动清理，启动重建以记录扫描
  结果为准天然过滤；sidecar 超 run 结束整文件随目录保留，无一致性风险。

### 5.4 退役的实现

`FileEpisodeMemoryStore` / `EventObjectStore` / `KnowledgeStore` 的**存储职责**全部
并入统一索引层后退役。退役前逐项核对消费方（命名洁癖原则）：

| 退役物 | 现有消费方 | 去向 |
|---|---|---|
| `FileEpisodeMemoryStore` | MemoryTool（step 读写 + 摘要读写） | MemoryTool 改调统一索引层 |
| `EventObjectStore` | MemoryTool（object 读写） | 同上 |
| `KnowledgeStore` | MemoryTool（query_knowledge） | 同上（查 run 快照目录） |
| `memory/retrieval.py::hybrid_retrieve` | 各 store + index_store | **保留**，被 search() 调用 |

---

## 6. Trace 侧设计

### 6.1 落盘：一条事件一个文件

- `trace_data/<run_id>/events/<uuid>.json`，内容 = `TraceEvent.model_dump_json()`，
  含 `event_id`（全局单调整数，replay 依赖，语义不变）与新增 `valid` 字段。
- 写入改原子写（tmp + `os.replace`）——jsonl 追加时代的"POSIX 单行写原子"论证
  作废，单文件写完即完整，崩溃最多少一个未 rename 的 tmp。
- 体积注意：`frame_png` base64 仍内嵌在事件 json 里，一条一个文件总字节不变，
  文件数变多；rotation/归档缺口（ROADMAP 工程基础设施表）依然存在，本方案不解决。

### 6.2 `valid` 字段（拍板③）

- `TraceEvent` 增加 `valid: bool = True`；`TRACE_SCHEMA_VERSION` 3 → 4
  （默认值字段向后兼容读 v3 文件，升版本是诚实留痕）。
- `void_after()` 不再碰 events/ 的文件搬移，改为：扫出 `event_id > cursor` 的事件
  文件，**原地改写 `valid=false`**（读 json → 置字段 → 原子写回）。一个都不搬、不删。
- 读端只需一道 `valid=false` 过滤，**不需要**学"跳过游标后到下一条 resume 前"的
  区间逻辑——标记在写端一次性做完，读端永远只见一条干净时间线。这是选 valid 字段
  而不是"读端跳区间"的根本原因：半吊子风险（把从未发生的分支当历史重放）在
  数据形状上不可能出现，而不是靠每个读端都记得防。

### 6.3 resume 事件

恢复管线在 void 完成后经 `trace.append()` 写一条：

```
type = LIFECYCLE, payload.kind = "resume",
payload = {run_id, episode_id, step, cursor}
```

游标的语义从"截断点"变为"有效/废弃分界"。被放弃分支的事件全部还在盘上
（valid=false），审计上"这局曾经跑到哪、放弃了什么"可完整回放。

### 6.4 `LocalTrace` 改动

| 项 | 现在 | 改后 |
|---|---|---|
| `_next_id` | 构造参数 `resume_after_event_id + 1` | **扫盘 `max(event_id) + 1`**——废弃分支事件还占着 id，不能从游标续；构造参数保留仅作前置断言（盘上 max ≥ cursor，否则说明 void 没做完，就地爆炸） |
| `_episode_is_complete` | 读该局 jsonl 找 episode_end | 扫 events 找该 episode_id 的 lifecycle/episode_end（resume 时本来就扫盘，顺路建内存集合） |
| `_save_event` | jsonl 追加 | 单文件原子写 |
| `read_disk_events` | 各局 jsonl 合并排序 | 扫 events/*.json → 过滤 valid=false → 按 event_id 排序 |

### 6.5 读端改动清单

| 消费方 | 改动 |
|---|---|
| `RunDataCenter.rebuild()` | 数据源换 events/ 目录；只收 valid=true |
| `tools/trace_render.py` | 同上 |
| `experiment/real_check/check_trace.py` | 同上 |
| SSE 实时推送 | 写端只 append 有效事件，天然不用改；断线补发按 event_id 续，同样不受影响 |

---

## 7. void / resume 编排（checkpoint_tool + memory_tool 分工）

`CheckpointTool.void_after()` 重写为四步，归档先行的原则不变：

1. **trace 打标**：扫 events/，`event_id > cursor` 的文件原地写 `valid=false`。
2. **圈定 memory 作废集合**（走 MemoryTool，不直接碰文件）：目标局
   `filter(episode_id=eid)` → tool 层数值比较筛 `step > N-1`（N=恢复步；
   checkpoint N 是"第 N 步开局"，拍它时完成的只有 step 0..N-1）；future_episodes
   （只出现在游标后事件里的局，集合来自步骤 1 的扫描）整局全收。该局的
   `episode_memory` 也整条作废、**不按 step 筛**——摘要是局收尾的产物，而收尾
   发生在本局最后一个 checkpoint **之后**且没有自己的 checkpoint，所以任何恢复点
   都把那次收尾圈进废弃窗口（0910 实测：末步恢复的废弃窗口里就有一条
   `write_episode`；排除本类会让重跑落下同 `episode_id` 的第二份摘要）。
   `knowledge` 不进（全局先验、不属任何一局）。
3. **memory 归档**：`index.archive_many(uuids, memory/voided-<ts>/)`——
   文件按 kind 分子目录搬入 + 摘出索引（内存与受影响文件夹的 `index.json`
   同步重写）。文件自带 run_id metadata，归档后仍可溯源。
4. **checkpoint 归档**：现状逻辑不变（step 目录整体搬）。

**截图不参与 void**（拍板⑨）：event_id 永远递增，resume 重跑只会产生新的
event_id、新的截图，与旧截图零撞名——旧截图原地保留，与 valid=false 的事件
一起构成废弃分支的审计记录。

分层不破：checkpoint_tool 只做编排，memory 文件的圈定与搬运都在 memory 层完成
（它自己知道 uuid → 路径），trace 文件直接操作维持现状模式（checkpoint_tool 本就
持有 trace_dir、不持有 LocalTrace 实例）。

---

## 8. 截图：绑定 trace 事件，不绑定 StepMemory（0910 用户纠正）

截图是"某条感知事件 carrying 的原始画面"的人眼便利副本，归属 **trace 事件**，
与 StepMemory 无直接关系：

- 目录 `trace_data/<run_id>/screenshot/`（单数，与旧 `screenshots/` 区分），
  文件名 = **`<event_id>.png`**——承载 `frame_png` 的那条 TraceEvent 自己的
  event_id。event_id 全 run 单调递增，天然不撞名，`_save_screenshot` 的撞名
  `(n)` 后缀逻辑连根删除。
- 引用关系：谁要看这一帧，**引用 event_id**，按"event json 里的 event_id →
  `screenshot/<event_id>.png`"定位。StepMemory 若需挂帧（judge/verify 拼多模态
  请求），payload 里存 `before_frame_event_id` / `after_frame_event_id`
  （引用从"拼公式算文件名"变"记事件号"）。
- `screenshot_step` 参数删除——它存在的原因是旧公式按 step 命名而感知时序与
  step 号错位（look_after_action 存的是"下一步"开局画面）；event_id 命名下
  png 跟着事件走，错位语义由事件自身的 step 字段表达，文件名不再需要第二个
  step 号。
- `read_screenshot(run_id, filename)` 签名不变（filename = `<event_id>.png`）。
- **截图不参与 void**：event_id 永远递增 → resume 重跑只产生新 id 新图，零撞名，
  无需搬移；废弃事件的截图原地保留（§7），与 valid=false 的事件同属废弃分支
  的审计记录。旧的"截图必须归档防撞名"理由（`_void_screenshots`）随之消失。

---

## 9. 装配与依赖方向

- `build.py` 装配四个索引层实例（step/object/episode/knowledge 各一，指向
  `memory/` 下对应文件夹，knowledge 指共享源），harness/tool 全走注入，不读
  全局配置——依赖注入铁律不变。run 启动不需要任何 memory 侧装配动作（无 run
  目录、无快照拷贝，索引层构造即完成对账）。
- 依赖方向不变：`brain → interfaces ← harness/tools`；memory 层只认
  "uuid + metadata 字典 + payload"，不理解任何字段含义（AGENTS.md 四的分层原则，
  ROADMAP 24 的字段对等原则）。

## 10. 范围界定

- **本次做**：存储形状（uuid 一条一文件）、目录迁移、trace valid/resume、
  void/resume 编排重写、读端切换、MemoryToolPort **对外签名不变**（调用方零改动，
  只有实现换底）。
- **本次不做**：ROADMAP 24 的另一半——MemoryToolPort 专用查询方法
  （query_episode_steps / query_object_events / query_episode_summaries...）收敛成
  filter+search 两个通用方法。那是接口层重构，影响 brain/harness 调用方，单独开一轮；
  本方案落地的"uuid + metadata + payload"存储形状正是它的地基。
- **不做旧数据迁移**（拍板⑥）：包内旧落盘、旧 jsonl 原地不动，新代码不读。

## 11. 改动文件清单

| 文件 | 动作 |
|---|---|
| `memory/store.py`（原 `memory/index/index_store.py`） | 重写为统一记录存储 + 每文件夹 index.json 倒排索引 + 向量 sidecar + archive_many |
| `interfaces/` 对应 Port | put 加 kind 参数、archive_many 入口 |
| `memory/episode/episode_store.py`、`memory/semantic/semantic_store.py` | 退役删除（消费方核对见 §5.4） |
| `tools/memory_tool.py` | 读写改调统一索引层；void_memory_after 改"圈 uuid + 归档"；discard 后于 0910（13）整体撤除 |
| `tools/checkpoint_tool.py` | void_after 按七节重写 |
| `schemas/trace/domain/trace_kind.py`（TraceEvent 所在） | + valid 字段，TRACE_SCHEMA_VERSION → 4 |
| `trace/store.py` | §6.4 全表 |
| `harness/run_data_center.py`、`tools/trace_render.py`、`experiment/real_check/*` | 数据源 + valid 过滤 |
| 装配管线（run 启动处） | 无 memory 侧动作了（无 run 目录、无快照）——此行删除 |
| `CLAUDE.md` | 目录结构、trace 约定章节 |
| `CHANGELOG.md` | 本次重构条目（改了什么/为什么/取舍/影响面） |

## 12. 实施顺序

1. schemas（TraceEvent.valid + 版本号）→ 2. 索引层重写 → 3. MemoryTool 切换 →
4. trace/store.py → 5. checkpoint_tool.void_after → 6. 读端四件套 →
7. 知识库源迁移（uuid 分配 + index.json）→ 8. 退役物删除（先核对消费方）→
9. CLAUDE.md + CHANGELOG。

一次性做完再合并汇报，不改一半中断（跨文件结构性改动的既定约定）。
