# PLAN —— `MemoryToolPort` 检索方法收敛（ROADMAP 24 的另一半）

> 状态：**设计稿**。0910 分层定案已拍板；"接口归位"与"撤 discard + 改名"均已实施
> 剩余待定点见 §8.2。
> 0910 二稿：补 §9 设计问答（`refresh_changed` 与 `search` 的边界、kind 是选择器不是条件）、
> §9.4 索引层一处真缺陷、§10 方案 C 与"复用边界"判据；待拍板点由 5 个增至 6 个。
> 0910 三稿：补 §11（`MemoryIndexPort` 是全仓唯一零消费者的 Port，与 A/B/C 选择强耦合），
> 待拍板点增至 8 个（点 7 是它的处置、点 8 是 §9.4 缺陷的开单方式）。
> 0910 四稿：**用户拍板分层定案（memory 通用 / tool 专用 / 裸字段无信封），方案 A、B 作废**；
> §8 改写为"决策记录 + 剩余待定"（唯一决策清单）；新增 §12（`index.json` 重建复活 forget
> 记录、`memory` 传递依赖整个 `schemas` 层，两条均为实测）。
> 0910 五稿：**接口归位已实施**——`MemoryIndexPort` 从 `interfaces/memory/` 搬进
> `memory/ports.py`，memory 包运行期自此零依赖 `interfaces/` / `schemas`（§12.2 那处
> 传递依赖一并修掉）；用户裁定 `forget_many` 撤除（"消失一律 = 移动归档"）。
> 0910 六稿：**§8.2 三处细节全部定案并实施**——`rank` 单列、`get`/`get_many` 保留
> （理由是 `filter()` 零读盘）、`delete_many` 撤除、接口不拆；`discard_episode_steps`
> 改走 `archive_many` 落 `retired-<ts>/`。契约从 11 个方法降到 **9 个**。
> 0910 七稿：**用户裁定"局结束不碰记忆"**——`discard_episode_steps` 整个撤除，§8.1 第 5 条
> 的连带落点作废（step 记忆按 `episode_id` 查询天然隔离，既不需要清场，也不需要第二个
> 归档时机）。**命名同时改定**：`MemoryIndexPort` → `MemoryStorePort`、
> `MemoryIndexStore` → `MemoryStore`，模块 `memory/index/index_store.py` → `memory/store.py`
> （`Index` 是 0908 三套存储并列时的限定词，0910 合并后对照物消失、名字停在旧出身里）。
> 本文件**六稿及之前的章节保留旧名**作为决策留痕，不逐处回改。
>
> **术语**：本文件里的"收敛"沿用 ROADMAP 24 的原词（第 801/812 行），指把 `MemoryToolPort`
> 上六个专用读方法收成 `filter` / `search` 两个通用方法——不是数学意义的收敛。
> 它拆开是两件事：**收**（方法个数 6 → 2）与 **散**（六个方法里叠的领域逻辑
> ——`step` 数值截断、`matches_scene` 场景通配、质量粗筛与加权重排——挪到哪里去）。
> 0910 分层定案后**两件事都不做**：tool 层保留六个专用方法（那本就是宝可梦适配器），
> 本轮只做"接口归位 + import 卫生"。
> 上游依据：`docs/ROADMAP.md` 第 24 条（0908 拍板）＋ 本文件的姐妹篇
> `PLAN_memory_trace_layout.md`（0910 已实施，那是"存储形状"那半边，本文件是
> **接口形状**这半边）。
> 存续前提：索引层的方法形状 0910 已是收敛后的形状（put/get/filter/search/rank/
> archive/delete）——本轮**只动契约的归属与 memory 包的 import 卫生**，不动方法形状。

---

## 1. 目标（24 条原话）

> memory 只对外提供两种能力——元数据过滤检索、语义相似度检索——不再为每种
> 检索维度各开一个专用方法。

现状问题（24 条）：`MemoryToolPort` 的六个读方法按各自消费方定制、形状互不
相同，**每加一种检索维度就要新开一个方法**，接口挪不给别的项目用。

---

## 2. 现状盘点：六个读方法各自的领域逻辑

| 方法 | 消费点 | 索引层调用 | 叠在上面的领域逻辑 |
|---|---|---|---|
| `query_episode_steps(episode_id)` | `retrieve_step_episode_memory`、`retrieve_verify_step_memory` | `filter({episode_id})` | payload → `StepMemory`；按 `step` 升序 |
| `query_recent_steps(episode_id, limit)` | `judge()` | 同上 | 同上 + 取尾部 `[-limit:]` |
| `query_object_events(map_id, before_step)` | `retrieve_object_semantic_memory` | `filter({map_id})` | payload → `ObjectFactEvent`；按 `step` 升序；`step < before_step` 数值收尾 |
| `query_object_events_at(place)` / `query(place)` | `retrieve_*`、`object_interactions.object_fact_events(..., memory)` | `filter({map_id, place})` | 同上（`query()` 是同一实现的第二个名字，供判定层当 reader 用） |
| `query_episode_summaries(scene, query, limit, run_id)` | `retrieve_global_episode_memory` | `filter({run_id})` + `rank()` | **场景通配匹配**（`EpisodeMemory.matches_scene`）→ **质量粗筛**（`EPISODE_CANDIDATE_CAP`）→ 混合检索 → **质量/成败加权重排** |
| `query_knowledge(query, limit)` | `retrieve_knowledge_semantic_memory`、`retrieve_verify_knowledge` | `refresh_changed()` + `search()` | 抽出 `text` 与 `metadata["source"]` 两个列表 |

写侧（`store_episode_step` / `append_object_events` / `store_episode_summary`）
与生命周期（`void_memory_after`；原 `discard_episode_steps` 已于七稿撤除）**不在本轮收敛范围**，
理由见 §7。

---

## 3. 实施前必须先澄清的一处歧义

24 条的影响面写了两句**彼此冲突**的话：

1. "`MemoryToolPort` 现有的这批专用方法要收敛成'过滤检索 + 语义检索'两个通用方法"；
2. "原来每个方法各自的查询逻辑（按局、按图、按窗口……）**下沉到 tool 层**用通用方法
   自己拼过滤条件字典实现"。

第 2 句在字面上不成立：`MemoryToolPort` **就是** tool 层的对外面——它是
`harness` 能看到的东西，逻辑没法"再往 tool 层下沉一层"。真正能选的是
**领域逻辑放在通用方法之上还是之下**，也就是下面两个方案。

（`AGENTS.md` 三·2 的"接口先行"要求把这个分叉摆出来定，而不是替调用方选。）

---

## 4. 方案 A（推荐）：Port 收敛为两种通用检索，领域逻辑搬到 harness 侧

### 4.1 新接口

```python
@runtime_checkable
class MemoryToolPort(Protocol):
    """harness 读写记忆的门面：**只有两种检索能力** + 记录取用 + 生命周期。"""

    # ---- 读写分离的两条通用检索（项目无关：只认 kind / 字段字典 / 一句话） ----
    def filter(self, req: FromHarnessToMemoryToolFilterReq) -> FromHarnessToMemoryToolFilterResp: ...
    def search(self, req: FromHarnessToMemoryToolSearchReq) -> FromHarnessToMemoryToolSearchResp: ...

    # ---- 写侧与生命周期：本轮形状不变 ----
    def store_episode_step(self, req: ...) -> None: ...
    def append_object_events(self, req: ...) -> None: ...
    def store_episode_summary(self, req: ...) -> ...: ...
    def void_memory_after(self, req: ...) -> ...: ...
```

新 schema（`schemas/harness/communication/`，命名按 PLAN_harness_decoupling §2）：

```python
class FromHarnessToMemoryToolFilterReq(BaseModel):
    kind: MemoryKind            # step_memory / object_memory / episode_memory / knowledge_memory
    conditions: dict[str, str] = {}   # AND-of-equalities，字段全对等，无主键

class FromHarnessToMemoryToolFilterResp(BaseModel):
    records: list[MemoryRecord]

class FromHarnessToMemoryToolSearchReq(BaseModel):
    kind: MemoryKind
    query: str
    limit: int
    conditions: dict[str, str] = {}   # 先等值圈候选，再在候选内做语义排序

class FromHarnessToMemoryToolSearchResp(BaseModel):
    records: list[MemoryRecord]
```

`MemoryRecord`（新，`schemas/memory/datastore/memory_record.py`）——**memory 侧
产出、harness 侧消费**，把现在 `MemoryIndexPort` 的裸元组
`(metadata, payload, text)` 升级成 Pydantic（**顺带补上铁律 4 的一处漏网**：

```python
class MemoryRecord(BaseModel):
    uuid: str
    metadata: dict[str, str]
    payload: dict
    text: str
```

### 4.2 领域逻辑的新住所

`harness` 侧新增一个模块（建议 `harness/memory_retrieval.py`，与既有的
`harness/memory_query_utils.py` 并列、职责互补）：

| 从 `MemoryTool` 搬出来的逻辑 | 新住所 |
|---|---|
| payload → `StepMemory` / `ObjectFactEvent` 的解析 | `memory_retrieval.py`（`to_step_memories(records)` 等） |
| 按 `step` 升序 / 取尾部 N 条 | 同上（`recent_steps(records, limit)`） |
| `step < before_step` / `step > keep_step` 数值收尾 | 同上（**这正是 24 条说的"tool 层的领域知识"——收敛后由调用方持有**） |
| `matches_scene` 通配匹配 + 质量粗筛 + 质量/成败加权重排 | `memory_retrieval.py`（`rank_episode_summaries(records, scene, query, limit)`） |
| `text` / `metadata["source"]` 抽取 | `memory_retrieval.py`（`knowledge_hits(records)`） |

`memory_query_utils.py` 保持原职责（拼 query 字符串），只是消费方多了一处。

### 4.3 调用点迁移表

| 现在 | 改后（harness 侧） |
|---|---|
| `query_episode_steps(ep)` | `filter(kind=STEP, {episode_id: ep})` → 解析 → 按 step 排序 |
| `query_recent_steps(ep, limit)` | 同上 → 取尾部 `limit` |
| `query_object_events(map_id, before_step=step)` | `filter(kind=OBJECT, {map_id})` → 解析 → `step < before_step` |
| `query_object_events_at(place)` / `query(place)` | `filter(kind=OBJECT, {map_id, place})` → 解析；**`object_interactions` 的 reader 依赖要改成"接收一个已查好的事件列表"或一个 `Callable[[PlaceInWorld], list[ObjectFactEvent]]`** |
| `query_episode_summaries(scene, query, limit, run_id)` | `filter(kind=EPISODE, {run_id})` → 场景匹配 → 粗筛 → `rank()`（**这一步需要 Port 再给一个 `rank(uuids, query, fuse_top_k)`，或让 `search` 支持"给定候选集"**） → 加权重排 |
| `query_knowledge(query, limit)` | `refresh_changed()` + `search(kind=KNOWLEDGE, query, limit)` → 抽 text/source |

> ⚠ 场景匹配那一行暴露了方案 A 的一个**真实成本**：`query_episode_summaries`
> 不是"filter 一下再 search 一下"能拼出来的——它是"先按 run_id 圈候选、
> 在候选内按场景/质量筛、再对**筛过的候选集**做混合检索、最后加权"。要把它
> 拆到 harness 侧，Port 必须额外暴露 `rank(uuids, query, fuse_top_k)`
> （即 `MemoryIndexPort.rank` 的同名能力），否则 harness 只能退化成"先 search
> 再在返回结果里过滤"，语义会变（召回集不同）。这是方案 A 里**唯一需要新增
> 的能力**，请在评审时明确认可或否决。

### 4.4 代价与收益

**收益**
- Port 上只剩两个检索方法，形状项目无关（换项目能直接挪），24 条的目标字面达成。
- `MemoryTool` 退化成"kind → 对应 `MemoryIndexStore`"的薄映射 + 写侧组装，
  领域语义全部住进 harness 侧一个新模块——**`memory/` + `tools/memory_tool.py`
  合起来变成可复用的"记忆子系统"**，正好服务 ROADMAP 25 的"memory 独立成块"。

**代价**
- harness 侧多一个模块，`object_interactions` 的 reader 依赖要改签名。
- "哪些 kind 需要过滤、按什么字段" 这类知识写在 harness 的检索节点里，
  不再有 tool 的方法名当路标——**可读性靠 `memory_retrieval.py` 的函数名撑**。
- `experiment/real_check/check_memory_roundtrip.py` 覆盖的五条路径要跟着改写
  （它是全方法自检）。

---

## 5. 方案 B：Port 两个通用方法带 `kind`，领域策略留在 tool 内部

```python
def filter(self, req: ...) -> ...   # req: {kind, conditions, sort_by?, limit?, before_step?}
def search(self, req: ...) -> ...   # req: {kind, query, limit, conditions}
```

`MemoryTool` 内部**按 `kind` 分派**到现有的领域逻辑（场景匹配、质量加权、
step 数值收尾全部原地保留），harness 只改调用形状。

**收益**：改动面最小，harness 的检索节点几乎不动，`object_interactions` 的
reader 用一个 `filter(kind=OBJECT, {map_id, place})` 包装即可。

**代价**：接口"形似通用、实为 kind 分派"——签名看不出 `kind=episode_memory`
会额外做场景通配和质量加权，`kind=object_memory` 会做数值收尾；这是**把
领域规则藏进 kind 的魔法**，跟 24 条"字段全对等、没有谁是主键"的精神相反。
而且 `MemoryTool` 仍然是宝可梦专用的，**换项目照样挪不走**——只解决了
"方法个数"，没解决"项目无关"。

---

## 6. 共同影响面（两个方案都要动）

| 文件 | 动作 |
|---|---|
| `interfaces/tools/memory_tool_port.py` | 读方法收敛（形态随方案） |
| `tools/memory_tool.py` | 删/改六个专用读方法 |
| `schemas/harness/communication/` | 删 10 个 `FromHarnessToMemoryToolQuery*.py`；新增 Filter/Search 两对 |
| `schemas/harness/__init__.py` | 导出同步 |
| `harness/episode_harness.py` | 六个检索节点 + `judge()` + `store_step_episode_memory` 记账 |
| `harness/object_interactions.py` | `query(place)` 依赖换形状 |
| `harness/memory_query_utils.py` | 可能升格为检索组装模块（方案 A） |
| `experiment/real_check/check_memory_roundtrip.py` | 五条路径改写 |
| `docs/spec/tools/SPEC.md`、`docs/spec/memory/SPEC.md`、`CLAUDE.md`、`AGENTS.md` 目录树 | 接口描述同步 |
| `CHANGELOG.md` | 一条（四段格式） |

---

## 7. 范围界定

**本轮不做**
1. **写侧不收敛**：`store_episode_step` / `append_object_events` /
   `store_episode_summary` 保持信封形状。24 条点名的只有查询方法；写侧要收敛
   成 `put(kind, metadata, payload, text)` 是另一件事（会牵动 8 个调用点 +
   两个 schema 家族），想做就单独开一轮。
2. **生命周期不收敛**：`void_memory_after` / `discard_episode_steps` 内部同样
   有"筛 + 数值比较 + 归档"的组合，但它们不是"检索维度"，且 `void` 的编排
   目前清楚地属于 `CheckpointTool`。若认可"Port 上只该有两种检索能力"的
   严格读法，这两个也该拆成 `filter` + `archive_many` 组合——**0910 已拍板：不动**
   （`forget_many` 已撤，"让记录消失"只剩 `archive_many` 一个语义，见 §8.1 第 5、6 条）。
3. **不拆 memory 成独立包**（24 条 §没定的地方第三条）：先在本仓库内把接口
   收敛掉；方案 A 落地后，包边界已经基本干净，拆包是后续的机械动作。
4. **`MemoryIndexPort` 改了位置、也减了两个方法**（撤 `forget_many` / `delete_many`，
   见 §8.1 第 5、6 条）——其余方法形状不变（索引层 0910 已是收敛形状）。

---

## 8. 决策记录与剩余待定

### 8.1 已决（0910 用户拍板）

1. **tool 层不收敛**：`MemoryToolPort` 保留现有六个专用读方法，不改成 `filter` / `search`。
   → **§4（方案 A）与 §5（方案 B）自此作废**；§10 的 A/B/C 讨论保留作决策留痕。
   → ROADMAP 24 中"tool 半边"的文字目标**放弃**，24 条的成果只落在索引层（0910 已达成）。
2. **memory 层做通用能力**：元数据检索 + 文本相似检索 + 存储。
   → `MemoryIndexPort` 定位为 **memory 层的对外契约**。它仍不作为 `MemoryTool` 的注入点
   （0908 那条"测试换隔离目录只动 `memory_root`"的拍板不变），而是这一层对外的能力声明
   ——见 §11.5 的五稿裁定。
3. **tool → memory 裸字段、不造信封**：**已是现状**，无需改动（`MemoryToolPort` docstring：
   "门面往里调各个 store 走裸参数、返回 store 自己的类型，那一跳不造信封"）。
   信封只存在于 harness ↔ tool 这一跳。
4. **接口归位（0910 已实施）**：`MemoryIndexPort` 从
   `interfaces/memory/memory_index_port.py` 搬进 **`memory/ports.py`**——契约随包走，
   拷 `memory/` 即得契约 + 实现 + 算法。同步清掉 import 卫生：`index_store.py` /
   `retrieval.py` 对 `EmbeddingProvider` / `RerankerProvider` 的依赖收进 `TYPE_CHECKING`
   （两处都只是类型注解，运行期不需要符号）。实测 `import pokemon_agent.memory` 后
   `pokemon_agent.interfaces` 不再被加载，传递拖入的 `schemas.*` 由 **103 → 0**（§12.2）。
5. **`forget_many` 撤除**（0910 用户裁定——"都只是移动归档"）：删掉"摘索引但文件原地留"
   这个第三种状态。它同时是 §12.1 那个复活漏洞的根源：`archive_many` 把文件 `os.replace`
   搬走所以不受影响，`forget_many` 只 `_unindex`，重建时文件还在目录里 → 复活。
   撤掉后"让记录消失"只剩一个语义——**移动归档**。
   → ~~连带 `discard_episode_steps` 改用 `archive_many`，落点 `memory/retired-<ts>/<kind>/`~~
   **（七稿作废）**：`discard_episode_steps` 整个撤除——"让记录消失"只剩
   `void_memory_after` 一个时机，没有"例行清理"这第二个动机（见 §8.2 第 2 条）。
6. **`delete_many` 撤除**（0910 用户裁定）：它与 `archive_many` 的差别只是"真删 vs 搬走"，
   而生产路径从不需要真删（"落盘了就不丢"）。测试若要真删，留在实现层即可，不必占契约位置。
7. **接口不拆**（0910 用户裁定）：`MemoryIndexPort` 保持单一 Protocol，不按"读/写/维护"
   拆成三块。
   → **后果**：它与 AGENTS.md 三·2「一个接口方法数量超过 6 个就该拆」直接冲突（现 9 个）。
     那条规则加例外（"只有跨层边界才强制"）还是认定 memory 不适用，**尚未拍板**——
     改规范要先讨论，故此条挂起。

### 8.2 结论（0910 六稿定案，七稿修正第 2 条）

1. **接口清单三处细节**：
   - `rank` **单列**，不并进 `search`。它是"对给定候选集重排"的底层原语，而 `search`
     反过来是它的封装（"filter 圈候选 + 截断"）——方向不能倒。合并还会让 `rank`
     失去它唯一的存在理由：调用方按自己的领域规则先筛、再进来排。
   - `get` / `get_many` **保留**。"让 `filter` / `search` 直接返记录"被否掉，理由是
     `filter()` 的**零读盘**：它只查内存倒排表、不打开任何记录文件，内容按 uuid 惰性取。
     直接返记录会让每次过滤都读 N 个文件 + 反序列化，把"索引落盘"换来的收益扔掉
     （见 `memory/SPEC.md` §3 第 2 条）。
   - `delete_many` 撤除（§8.1 第 6 条）。
2. ~~**`discard` 归档落点**：`memory/retired-<ts>/<kind>/`，与 void 的 `voided-<ts>/`
   并列而不合用~~ → **七稿作废：`discard_episode_steps` 整个撤除**。理由：step 记忆按
   `episode_id` 查询天然隔离（`query_episode_steps` / `query_recent_steps` 都带这个
   条件），局收尾不需要清场；顺带消掉"每局新建一个 `retired-<ts>/` 目录"的目录爆炸，
   索引重建的漏洞面也从两处收成一处。**已实施**（tool / Port / 信封 / harness 调用点 /
   真机脚本全链路清理）。
3. **裸元组返回是否升级成 `MemoryRecord`**（铁律 4）：**未做**，用户未拍板。现状
   `get_many()` 返回 `[(uuid, metadata, payload, text)]` 四元组。
4. **§9.4 那处缺陷**（`refresh_changed` 只刷向量、不重建 metadata 倒排表）：**未做**，
   倾向单独开一条。
5. **AGENTS.md 三·2 的例外**（见 §8.1 第 7 条）：**挂起待议**。

**本轮实施状态**：§8.1 第 4、5、6 条 + §8.2 第 2 条已落地并验证（改动文件 ruff 全绿、
真机 `check_memory_roundtrip` 五路径 PASS、另有"归档后重建不复活"专项实测）；
第 1 条是"确认现状、无需改"；第 3、4、5 条未做。

**七稿追加**：`discard_episode_steps` 撤除 + 两个类改名（`MemoryIndexPort` →
`MemoryStorePort`、`MemoryIndexStore` → `MemoryStore`，模块 `memory/store.py`）
均已落地；真机 `check_memory_roundtrip` 现为**七条路径**（新增 5b：归档后删
`index.json` 强制重建，被归档的记录不复活）。

---

## 9. 设计问答（0910 评审中提出）

### 9.1 `refresh_changed()` 为什么与 `search()` 分开

**它是"把外部对记录文件的修改同步进派生态"，不是检索本身。**

| | `search()` | `refresh_changed()` |
|---|---|---|
| 副作用 | 无（纯读） | 读盘 + 算 embedding + 重写 `index.json` / `vectors.jsonl` |
| 成本 | 一次混合检索 | O(N) 次 `stat`，命中变更还要重算向量（最贵的一步） |
| 对 4 类 kind | 都适用 | 只有 md 类有意义（json 类是运行期写穿产物，no-op） |
| 调用时机 | 每次要检索时 | 只在"外部可能改过文件"之后 |

折进 `search()` 的代价是双向的：一次纯读变成可能写盘、可能调外部模型，且每次语义检索都付一遍全目录 `stat`。**刷新是入口语义，不是检索语义。**

**现状的一处不对称（本次评审发现，建议一并处理）**：只有 `query_knowledge` 调了
`refresh_changed()`；`query_episode_summaries`（`episode_memory` **同样是 md 类**）没调。
根因是判据选错了——当前用 `_MD_KINDS`（**存储格式**）当刷新判据，真正的判据是
**记录是不是外部作者写的**：`knowledge_memory` 是运营手工播种/编辑的语料
（`memory/knowledge_memory/*.md`），`step_memory` / `object_memory` / `episode_memory`
都是运行期产物。"md 类"代表"会被人手改"只是个恰好成立的巧合。

更严的形态二选一：**(a)** 判据从"md 类"改成构造期开关（如
`MemoryIndexStore(..., watch_external_edits=True)`），哪些 kind 要盯由装配点声明；
**(b)** 同步时机收窄到进程入口——启动/恢复时调一次，之后由显式 re-sync 触发，
而不是每次检索前 `stat` 一遍全目录。

### 9.2 `filter` 为什么不"指定记忆种类"

**因为 kind 是"查哪个库"，不是"库里的哪个字段"——它是选择器，不是条件。**

- **索引层**：`MemoryIndexStore` **一个实例绑定一个 kind**（一个 kind = `memory/`
  下一个文件夹）。`filter(conditions)` 已被实例圈在该库内，再带 kind 是冗余；
  带上还会暗示存在"跨库一次查完"的能力——而存储布局恰恰没有这个能力。
- **工具层**：`FromHarnessToMemoryToolFilterReq` **有 kind**，但它是顶层字段
  （决定路由到四个 store 中的哪一个），不塞进 `conditions`。

不塞进 `conditions` 的理由是**类别错误**：条件字典的设计前提是 ROADMAP 24 那句
"任何字段都能做等值查询，地位完全对等、没有谁是主键、全部可选"。kind 一旦进去，
就是唯一必填、且唯一带特殊语义（不筛记录、只选库）的键——等于把主键从后门放回来。
方案 B 的毛病正是这个：把领域规则藏进 kind 的魔法。

要"跨库一次查完"的话，那是 fan-out（四库各查一次再归并），不是给 `filter` 加参数；
目前每个调用点都清楚自己要哪种记忆，没这个需求。

### 9.3 待拍板点的去向

本节原列的第 6（`refresh_changed` 归谁调）、7（`MemoryIndexPort` 处置）、8（§9.4 缺陷怎么开单）
三点，已在 0910 用户拍板后改由 **§8** 统一管理：点 6 随"tool 层不收敛"自然消解
（refresh 继续留在 tool 内部），点 7 定为"激活"（见 §8.1 第 2 条），点 8 并入 §8.2 点 4。
**§8 是唯一的决策清单，本节不再维护第二份。**

### 9.4 顺带发现：`refresh_changed()` 只刷向量，不刷 metadata 倒排表

核对这个问题时查了一处实现，确认是个**真缺陷**（0910 索引层遗留；本轮范围外，但记在这里）：

`MemoryIndexStore.refresh_changed()` 里 `_, _, text = self._read_record(record_id)`——
**metadata 被丢掉了**，接着只 `_put_vector()`。于是：

- 手改 `.md` 的**正文** → 向量重算，`search()` 生效 ✅
- 手改 frontmatter 的 **metadata**（比如改 `topic`）→ 倒排表**保持陈旧** ❌

**重启也修不好**：`_load_or_rebuild()` 的对账只比"文件集合 vs 索引 uuid 集合"——文件还是
那个文件、uuid 没变 → 对账通过 → 直接沿用陈旧的 `inverted`。

修法不是一行：倒排表只加不能改，得先 `_unindex(record_id)` 再 `_index_record(record_id, metadata)`。
另外 `MemoryIndexPort.refresh_changed()` 的 docstring 只承诺"重读正文、重算向量"，
而 `MemoryTool.query_knowledge()` 的 docstring 写的是"编辑 `.md` 不用重启就生效"——
**两处承诺不一致**，要么补实现、要么把后者的措辞收到"正文"。

**与本轮的关系**：metadata 是 `filter()` 的唯一输入，所以这条缺陷会直接影响收敛后
`filter(kind, conditions)` 的语义（用户以为改过的 metadata 能筛到，实际筛不到）。
建议**单独开一条**处理，不混进接口收敛这一轮。

---

## 10. 第三个方案与判据：复用边界决定搬不搬（0910 二稿补）

§4/§5 只摆了 A（领域逻辑搬出去）和 B（留在 tool 内），漏了把前提本身摆上台面。补上。

### 10.1 搬的到底是什么

搬的是**叠在检索之上的领域规则**，不是检索本身（filter/search/rank 一直住 `memory/`）：

- `EpisodeMemory.matches_scene()` 的场景通配匹配
- `EPISODE_CANDIDATE_CAP` 质量粗筛 + 质量/成功加权重排
- `step < before_step`、`step > keep_step` 的数值收尾
- payload → `StepMemory` / `ObjectFactEvent` 的解析与排序

### 10.2 唯一站得住的理由，以及它的漏洞

**理由**：ROADMAP 24 的目标不是"方法少一点"，而是"memory 子系统能挪给别的项目"
（ROADMAP 25 拆包）。要挪，交付出去的那个面就必须项目无关。现有两层候选边界：

| 边界 | 项目无关？ |
|---|---|
| `MemoryIndexPort` / `MemoryIndexStore` | ✅ 0910 收完后只认 metadata / payload / text |
| `MemoryToolPort` | ❌ 方法名就是检索维度（按局/按图/按格/按场景），实现里躺着 `matches_scene`、质量加权、`step` 数值比较 |

**漏洞**：复用单元本来就可以是 `memory/` 包，那 `MemoryToolPort` 就只是**本项目的适配器**——
适配器里放领域规则天经地义，一行都不用搬。

**判据（一句话）**：半年后把记忆子系统拷到别的项目，你拷的是 `memory/`，
还是 `memory/` + `tools/memory_tool.py`？前者 → B/C；后者 → A。

### 10.3 方案 A 的收益被高估了一处

A 落地后 `tools/memory_tool.py` 会变成薄映射，但宝可梦策略原样搬进
`harness/memory_retrieval.py`——别的项目复用时**这个策略模块照样要重写**。
所以 A 相对"现在直接拷 `memory/` 再自己写个适配器"的边际收益只剩"适配器已经写好了"。

A 真正的增量价值是**可测性**：策略变成 harness 侧纯函数
（`rank_episode_summaries(records, scene, query, limit)`），可以脱离 store 单测。这条不依赖复用目标。

A 另有一处不优雅：`query_episode_summaries` 拆到 harness 侧后，需要把索引层的
`rank(uuids, query, fuse_top_k)` 原语暴露到 tool 门面上——通用门面为一类记忆的排序需求
泄漏底层原语，气味不对。

### 10.4 方案 C（二稿新增）：承认分层，只做去重式轻收敛

把复用单元明确定在 `memory/` 包（`MemoryIndexPort`，0910 已项目无关），`MemoryToolPort`
定位为**本项目 harness 的记忆适配器**——24 条的"项目无关"只在索引层兑现。tool 层不做
"项目无关"的收敛，只做去重：

| 动作 | 说明 |
|---|---|
| `query_object_events_at(place)` / `query(place)` 合一 | 现在就是同一实现的两个名字（一个给检索节点、一个给判定层当 reader），只是消费方不同 |
| `query_episode_steps` / `query_recent_steps` 合一 | 后者只是前者的尾部切片（`[-limit:]`），把 `limit` 变成可选参数即可 |

**收益**：改动最小（两个方法消失，无新增模块、无 reader 改签名、无 Port 泄漏原语），
且**如实反映实际架构**——工具的读方法就是宝可梦检索策略，不假装自己通用。
**代价**：放弃"`MemoryToolPort` 可被别的项目直接复用"这个主张；24 条的文字目标只在索引层达成。

---

## 11. `MemoryIndexPort` 有没有必要留（0910 三稿补）

### 11.1 它是什么

`interfaces/memory/memory_index_port.py`，把 `MemoryIndexStore` 的能力声明成 Protocol：
写端（`put` / `forget_many` / `archive_many` / `delete_many`）、读端（`get` / `get_many` /
`filter` / `search` / `rank` / `count`）、维护（`refresh_changed`）——**11 个方法**。

### 11.2 现状：零代码消费者

全仓引用统计（排除 `interfaces/` 自身）：`TracePort` 23、`BrainToolPort` / `TraceToolPort` 15、
`MemoryToolPort` 14、`GameToolPort` 13……**`MemoryIndexPort` 3，而这 3 处全是 docstring**
（`index_store.py` 的模块 docstring与类 docstring、`memory/__init__.py` 的说明段）。
没有任何一行代码拿它当类型、当参数注解、当 `isinstance` 目标——它是 `interfaces/` 里唯一的孤儿。

同时它违反本项目自己的两条规则：

- AGENTS.md 三·2「一个接口方法数量超过 6 个就该拆」→ 它 11 个；
- 铁律 4「跨层传递的数据一律是 Pydantic，不用裸 dict」→ `get` / `get_many` 返回裸 tuple。

### 11.3 为什么它没长起来：0908 已经关掉了它的用武之地

`MemoryTool.__init__` 内部直接 `MemoryIndexStore(...)` 建四个实例——连构造函数注入都不走，
参数注解写的就是具体类；docstring 明说"测试换隔离目录只动 `memory_root`；不再需要为每类
记忆注入各自的 mock store"。**Port 唯一能兑现的价值（换实现 / 换替身）被 0908 的拍板主动
放弃了**，测试改用 `memory_root` 指 tmpdir。

于是它四缺：有接口、没消费者、没注入点、没替身。

### 11.4 与本轮的耦合（重要）

**只有方案 A 能让它活着**——A 里 `MemoryToolPort.filter/search` 的签名直接以它为基础，
还要把 `rank()` 暴露上去。

| 选 | `MemoryIndexPort` 的结局 |
|---|---|
| A | 有了消费者，契约名副其实 → 值得留，且应顺势按 6 方法上限拆成"读 / 写 / 维护"三块 |
| B | 仍是孤儿（`MemoryTool` 继续直接 new 具体类）→ 该删 |
| C | 同上 → 该删 |

### 11.5 处置：0910 五稿已决——三个选项都不选，走"归位"

**已决**：契约**随 memory 包走**——从 `interfaces/memory/memory_index_port.py` 搬到
`memory/ports.py`（§8.1 第 4 条，已实施）。

原三选项的共同前提是"留在 `interfaces/` 里想办法"，而分层定案后这个前提本身不成立：
`interfaces/` 的定位是本项目的跨层港口（brain ↔ harness ↔ world），memory 却是要能被
整体拷走的子系统；既然它是"memory 层的对外契约"，就该与实现同住一包。

**顺带收益**：这一搬同时消灭了唯一一处让 `memory` 传递依赖 `schemas` 的 import 路径
（§12.2），包边界从"声明上干净"变成"事实上干净"。

**未采纳原选项 2（激活为注入点）的理由**：那要让 `MemoryTool.__init__` 改接注入，
会推翻 0908"测试换隔离目录只动 `memory_root`"的拍板；而本次不需要它——契约作为
"这一层对外承诺什么能力"的声明已经成立，注入与否是另一件事。

下面三个原选项保留作决策留痕。

### 11.5a 原三选项

1. **删**：去掉 `interfaces/memory/` 与 `interfaces/__init__.py` 的导出，把契约说明并进
   `index_store.py` 的模块 docstring（那里本已很厚）。代价：要给 AGENTS.md 三·2 加例外——
   "只有跨层边界（brain↔harness↔world）才需要 Port，包内实现不强制"（**这条是改规范，得先讨论**）。
2. **激活**：`MemoryTool.__init__` 改成接四个 store（类型标 `MemoryIndexPort`），`build.py` 负责
   new。代价：推翻 0908 的拍板，回到"为每类记忆注入 store"的老样子。
3. **留作文档**：保留但明确它只是契约文档 + 换后端的预留缝。代价：靠纪律防漂移——而 §9.4
   那处 docstring 漂移正说明这个纪律维持不住。

---

## 12. 0910 补查：两条"索引是派生物"的漏洞 + 一处 import 卫生问题

### 12.1 删掉 `index.json` 能跑吗——能，但被 `forget` 的记录会复活

`index.json` 确是派生物：删掉后构造期对账（文件集合 vs 索引 uuid 集合）不一致 → 全量扫描重建。
**实测**（临时目录、两条记录、`text` 为空所以不碰 embedding）：

    put 两条 → forget 其一 → filter 命中 1 条                    ✅ 符合预期
    删除 step_memory/index.json → 新建实例（触发重建）
    → filter 命中 2 条，被 forget 的那条回来了                   ❌ 语义被破

**根因**：`forget_many` 只 `_unindex` **不删文件**（设计上"盘上保留作审计记录"），
而重建的输入是"目录里所有 `<uuid>.json`"。于是**重建不还原"曾经被 forget"这个状态**——
"索引是派生物、可自愈重建"这条承诺在这里只对了一半：它能重建出**内容**，重建不出**历史决策**。
`archive_many` 不受影响（`os.replace` 把文件搬走了，不在目录里）。

修法二选一：① `forget` 把文件挪进 `<kind>/forgotten/`（与 archive 同构，只是目标目录固定）；
② 记录文件里落 `forgotten: true` 标记，重建时跳过。倾向 ①（不改记录格式）。
**影响面**：~~`discard_episode_steps` 丢弃的单步记忆会复活~~ → **七稿已消解**：
`forget_many`（0910 撤除）与 `discard_episode_steps`（0910 撤除）双双消失后，
"让记录消失"只剩 `archive_many` 一条物理移动路径，重建不会再复活任何东西。
真机 `check_memory_roundtrip` 路径 5b 已把这条不变量固化成断言。

`vectors.jsonl` 删掉也能跑：代价是重新调 embedding（花钱花时间），`rank` 里惰性补算。

### 12.2 `memory/` 到底引用了什么（实测）

- **`schemas`：直接引用 0 行**（整个包 grep 不到 `schemas`）。
- **`interfaces`：2 处运行期 import**（`index/index_store.py:45`、`retrieval.py:24`），
  都只要 `EmbeddingProvider` / `RerankerProvider` 两个 Protocol。
- **但传递依赖把整个 `schemas` 拖了进来**：因为写的是 `from pokemon_agent.interfaces import ...`，
  这会执行 `interfaces/__init__.py`，而它 re-export 全部 16 个 Port，其中
  `brain/brain_port.py` 第 14 行就 `from pokemon_agent.schemas.brain import (...)`。
  实测 `import pokemon_agent.memory` 后 `sys.modules` 里有 **~100 个 `pokemon_agent.schemas.*`**
  （`schemas.brain.*`、`schemas.harness.communication.*` 的 40 多个信封、`schemas.trace`、
  `schemas.world`、`schemas.providers`）。

**声明上不碰、事实上拖进整层。** 若"memory 独立成块"（ROADMAP 25）是真目标，这是必修的
import 卫生：① 把 `from pokemon_agent.interfaces import X` 改成直连模块
（`from pokemon_agent.interfaces.providers.embedding_provider import EmbeddingProvider`）；
② 更彻底——把这两个 provider Protocol 收进 memory 包自己的 `ports.py`，让 memory 零外部依赖。

**0910 五稿已修**（走 ① 的严格版）：契约搬进 `memory/ports.py`（§8.1 第 4 条），
两个 provider Protocol 的依赖收进 `TYPE_CHECKING` —— 它们只出现在函数签名里，
`from __future__ import annotations` 已让注解延迟求值，运行期不需要符号。
实测 `import pokemon_agent.memory` 后 `pokemon_agent.interfaces` **零加载**、
`schemas.*` 由 **103 → 0**。

未走 ②（把 provider Protocol 抄进 memory 包）：同一契约会出现两份定义、必然漂移；
`TYPE_CHECKING` 已经拿到"运行期零依赖"的全部好处。**残余依赖只剩类型检查期**，
拷包到别的项目时只要提供的 embedder / reranker 结构上满足 Protocol 即可。
