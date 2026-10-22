# 记忆后端选型调研：图 + 实体 + 时序 + 向量 + 元数据

> 调研日期：2026-10-20（star/许可/pushed 均为当日 GitHub API 实测）
> 需求：权威第三方库，原生同时具备 ① 属性图 ② 实体抽取/解析 ③ 时序 ④ 向量语义检索 ⑤ 多字段元数据过滤（且过滤发生在 top-k 截断之前）
> 证据等级：A = 读源码/API 文档；B = 官方文档；C = 第三方文章/仓库（已在文中区分，不混算）
> 本文**未运行任何候选库**，是静态调研；结论里"待实测"的项不得当作已验证。

## 0. 一句话结论

**没有单一权威库五项全原生具备。** 按"五项命中度"排序，最接近的是 **Cognee**（4 项原生 + 1 项半原生），其次是 **Hindsight**（图/实体/向量/时间四路检索齐全，但元数据维度是 tags 而非任意 key/value）。Graphiti 时序最强但元数据与正文向量双缺（见 `STATIC_EVIDENCE.md`）。**"任意 key/value 元数据下推过滤"是所有框架层共同的短板**，只有下沉到底层数据库（Neo4j vector index + Cypher WHERE / Postgres + pgvector + SQL WHERE / LanceDB prefilter）才拿得到。

## 1. 能力矩阵

| 库（团队） | stars | 许可 | ① 图 | ② 实体 | ③ 时序 | ④ 向量 | ⑤ 元数据过滤 | 免 Docker |
|---|---:|---|---|---|---|---|---|---|
| **Cognee**（topoteretes） | 32,586 | Apache-2.0 | ✅ | ✅ | ⚠️ | ✅ | ⚠️ | **✅ 默认嵌入式** |
| **Hindsight**（vectorize-io） | 51,948 | MIT | ✅ | ✅ | ⚠️ | ✅ | ❌（tags 替补） | ✅ pg0 嵌入 |
| **Graphiti**（getzep） | 32,083 | Apache-2.0 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **neo4j-agent-memory**（Neo4j Labs） | 589 | Apache-2.0 | ✅ | ✅ | ⚠️ | ✅ | ⚠️ | ❌ |
| **Mem0**（mem0ai） | 67,523 | Apache-2.0 | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ |
| **LangMem / LangGraph BaseStore** | 1,715 | MIT | ❌ | — | ❌ | ✅ | ✅ | ✅ |

（"图"= 实体为节点、关系为边、可遍历的属性图；"免 Docker"= 是否存在嵌入式默认后端）

## 2. Cognee —— 五项命中度最高

**证据（A 级，读 main 分支源码）**

- **统一存储**：`DataPoint` 是 Pydantic 模型，字段 `id / created_at / updated_at / version / topological_rank / metadata / type / belongs_to_set`；**同一个 `id` 同时落在图库（关系）、向量库（语义）、关系库（版本/溯源）三层**。这正是"正文 + 向量 + 元数据统一存储"。
- **④ 向量**：`metadata.index_fields` 决定**哪些字段被嵌入**；每个被索引字段生成独立的 `Class_field` 向量集合 → 想嵌正文就嵌正文，是原生可控的（Graphiti 缺的正是这个）。
- **① 图 + ② 实体**：`add_data_points()` 把 Pydantic 对象直接变成图节点与边（`author: Author`、`Edge(weight=0.8)`、`list[Chapter]`），**不需要 LLM 抽取**；文本走 `add() → cognify()` 由 LLM 抽取。有 `Entity` / `EntityType` / `Triplet` 内置类型。
- **③ 时序**：`SearchType.TEMPORAL` → `TemporalHybridRetriever`（`cognee/modules/retrieval/temporal_hybrid_retriever.py`，SDK-828），有 `Timestamp` 一等节点、`get_timestamps_in_range`、`get_temporal_anchors`（Ladybug/Neo4j/Postgres 上是原生查询）、`tightness_rank`（"1965-03-18" 排在只写 "1965" 的前面）。
  **但**：docstring 明写 "similarity barely sees dates, so the rows a window names are mostly outside the fetched set"，做法是先取候选、把时间锚定的候选 `prioritize` 前移、再 `finalize` 切 top_k → **时序是 rerank/前移，不是硬过滤**，也不是 `valid_at/invalid_at` 失效模型。
- **⑤ 元数据过滤**：`node_set=["projectA","finance"]` → cognify 后成为图里的一等 `NodeSet` 节点 + `belongs_to_set` 边，检索用 `node_name` + `node_name_filter_operator` 限定子集 → **多维标签、图侧过滤**（比 Graphiti 的一维 `group_id` 强一档）。自定义标量属性（外部 ID/标签）能否在检索侧下推过滤：**待实测**。
- **免 Docker**：`ladybug`（图）+ `lancedb`（向量）+ `aiosqlite`（关系）都是**核心依赖**而非 extras；`neo4j` / `postgres` 才是可选 extras。→ 默认嵌入式，本机直接可跑。

**缺口**：时序是"排序/前移"而非硬过滤与失效模型；任意 kv 元数据过滤未证实。

## 3. Hindsight —— 检索最强，元数据维度是 tags

**证据（B 级，读官方文档 `hindsight.vectorize.io/developer/api/recall` + README）**

- `retain` 用 LLM 抽取 facts / temporal data / entities / relationships，规范化成 canonical entities、**time series**、索引与 metadata。
- `recall` 跑**四路并行**：semantic 向量 + BM25 关键词 + **graph（entity/temporal/causal links）** + **temporal（time range filtering）**，再 fusion + rerank。
- **时间字段**是 `occurred_start` / `occurred_end`（事件时间，LLM 抽取）与 `mentioned_at`（入库时间）——双时间语义，但**不是** `valid_at/invalid_at`。
- `temporal_window` 官方明写：**"This ranks, it does not filter."** 窗口外的记忆仍然返回。
- `bank` 隔离：官方称 "Isolation is strict: no cross-bank leakage"；有 `types`（world/experience/observation）、`tags` / `tags_match`（any/any_strict/all/all_strict/exact）/ `tag_groups`（复合布尔 + fuzzy resolve）——**这是它真正的过滤维度，服务端作用域过滤**。
- **⑤ 元数据**：README 第 387 行称 "custom metadata … can be filtered when retrieving"，但 **recall API 文档的参数表里没有 metadata 参数**，`metadata` 只作为**返回字段**出现（"The key-value string pairs attached when the fact was retained"）→ 按 metadata 过滤只能在拿到响应后自己做。**README 与 API 文档口径不一致，以 API 文档为准。**
- 部署：Docker / 裸机 pip / **Embedded DB (pg0)**；有 Python embedded（no server required）；内置 MCP（每 bank 一个 endpoint）。

**缺口**：metadata 只能后置过滤；时间窗口只排名不过滤。

## 4. 其余候选的定位

| 库 | 定位与硬证据 |
|---|---|
| **Graphiti** | 时序（双时态失效边、逆序写入）仍是全场最强；但原生不支持正文向量、元数据不落盘也不过滤、隔离只有 `group_id` 一维。详见 `eval_results/.../STATIC_EVIDENCE.md`。 |
| **neo4j-agent-memory** | Neo4j Labs（**明示"not officially supported，无 SLA"**）。三层记忆（short-term 消息 / long-term 实体+preferences+facts / reasoning traces）、本体驱动 GLiNER2.5 抽取与实体解析、语义 + 图检索、Bolt 下可写自定义 Cypher（→ 过滤可下推）。**但官方自己警告**：`user_identifier` "does not automatically filter entity, preference or trace searches"，`search_preferences` 是语义检索且**不自动限定用户** —— 与 Graphiti 同一个"过滤在截断之后"的坑。偏好有 `supersede_preference`（取代）机制，非双时态关系失效。 |
| **Mem0** | 67.5k stars 最大，但据第三方引用其 v3 迁移指南："Graph memory is removed from the open-source SDK"，已转为平台功能 → ① 图这一项在开源侧不成立。 |
| **LangMem / LangGraph BaseStore** | `search(namespacePrefix, filter={...}, query=...)`：namespace 元组前缀 + **多字段元数据过滤** + 可选向量索引且能指定 `index.fields`（正文向量）——④⑤ 原生，但**无图、无时序**。与 Graphiti/Cognee 恰好互补。 |
| **Letta**（25,205 / Apache-2.0） | 未深查；已知强项是 agent runtime 与 archival memory（向量），图与时序未见主张。 |

## 5. 横向判断：为什么"元数据下推"谁都没做

框架层的检索都是"先按相似度取候选（`2*limit` / top_k×N）→ 再 fusion/rerank → 最后截断"。下推过滤只有两类做法：

1. **把身份维度压进分区键**（Graphiti `group_id`、Hindsight `bank`、Cognee `dataset`/`node_set`）——能下推，但维度有限或需编码；
2. **自己写查询**（Neo4j Cypher `WHERE` + vector index、Postgres SQL `WHERE` + pgvector、LanceDB prefilter）——完全可控，代价是绕开框架的检索层。

带"任意 key/value 且过滤先于截断"的开箱能力，目前只在本轮看到的**平台侧**（Zep 的 `MetadataFilterGroup` / `episode_metadata_filters` + metadata projection）成立，开源侧要靠自己写。

## 6. 对项目的直接含义

| 项目诉求 | 最佳匹配 |
|---|---|
| 原始记忆"正文 + 向量 + 元数据"统一存储 | **Cognee**（同一 `id` 跨图/向量/关系三库，`index_fields` 决定嵌什么） |
| 多重记忆靠元数据区分 | **Cognee 的 NodeSet 多维标签** / Hindsight 的 `types` + `tags` |
| 时序实体关系图 | 硬时序（失效边）仍只有 **Graphiti**；Cognee 是时间锚点 rerank，Hindsight 是事件时间 + 排名 |
| 复用现有 MCP 边界 | Cognee / Hindsight / Graphiti 都有官方 MCP；但**过滤参数都得自己封**，官方面都不暴露业务身份维度 |
| 免 Docker 验证 | **Cognee（默认嵌入式）** 与 Hindsight（pg0）都可；Graphiti / neo4j-agent-memory 需要图库服务 |

## 7. 建议的下一步（按成本从低到高）

1. **不改 spec 的 40 条 fixture，换后端重跑**：`experiment/memory_graph_probe/` 的 `ProbeStorePort` 已经把后端抽象出来了，加一个 `backends/cognee.py` 即可复用同一套 oracle。Cognee 默认嵌入式 → **不需要 Docker**，可在本机直接跑完 P1–P6。
2. **优先实测 Cognee 的三个未知项**：`node_set` 过滤发生在截断前还是后；自定义标量属性能否参与检索过滤；`TEMPORAL` 检索在 40 条时序 fixture 上的实际排序。
3. **若必须硬时序失效**（旧事实被新事实取代且可回溯），保留 Graphiti 只做时序旁路，或直接在自建层用 `valid_from/valid_to` 两列实现——比引入第二个图栈便宜。
4. **别急着组合 LangMem + Graphiti**：LangMem 底座（BaseStore）与 Cognee 在④⑤上重叠，与 Graphiti 在①③上互补；先定主存储，再谈组合。
