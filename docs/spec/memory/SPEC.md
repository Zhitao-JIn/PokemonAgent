# memory —— 模块规格

> 最后更新：2026-09-16 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> Port 契约签名见同目录 `PORTS.md`（那份讲契约，这份讲全貌）

## 一、职责与边界

memory 的能力只有三块：**按 uuid 落盘记录**、**维护倒排索引**、**在给定候选集上做混合检索排序**
（`store.py` 按方法粒度拆成写入 / 点查 / 过滤检索 / 语义检索 / 删除 / 快照六件事）。

- 不做语义判定。"这一键是对门说话还是换图"由 harness 判定
  （`harness/episode/store/store_object_semantic_memory/rules.py`），摘要蒸馏由 brain 做
  （`tools/brain_tool.py::BrainTool.summarize()`），成没成由 harness 盖章——memory 只保管交进来的
  数据结构与索引，按键原样读写（`AGENTS.md` 四·分层原则 1）。
- 字段叫什么、值怎么序列化、`payload` 里装什么，对本层**完全不透明**：
  `LocalMemoryStore.put(metadata, payload, text)` 只认 `dict[str, str]` + `dict` + `str` 裸字段；
  包内不 import `world` / `brain` / `harness` / `schemas` / `tools`（`TYPE_CHECKING` 也没有外部的）。
  因此四类记录的具体形状**不在本包**，住 `pokemon_agent/schemas/memory/datastore/`（见第五节）。

## 二、目录结构

```
pokemon_agent/memory/
├── __init__.py            统一出口：6 个名字 re-export（0916 收窄），消费方不深到子模块文件
├── ports.py               MemoryStorePort（9 方法）
├── store.py               LocalMemoryStore：MemoryStorePort 的默认实现
├── retrieval.py           混合检索纯函数（5 个 + RRF_K）
├── embedding_provider.py  EmbeddingProviderPort 协议
├── reranker_provider.py   RerankerProviderPort 协议
├── fastembed_text.py      LocalEmbeddingProvider：EmbeddingProviderPort 的本地实现
└── fastembed_reranker.py  LocalRerankerProvider：RerankerProviderPort 的本地实现
```

消费方一律 `from pokemon_agent.memory import X`，`__all__` 的 6 个名字见 `PORTS.md`，
逐名字用途见 [`API.md`](./API.md) 第一节。

## 三、存储布局

一个 kind = `memory/` 下一个子文件夹 = 一个 `LocalMemoryStore` 实例。`MemoryTool.__init__`
（`tools/memory_tool.py`）一次造四个：`step_memory` / `object_memory` / `episode_memory` / `knowledge_memory`。

```
memory/<kind>/
├── <uuid>.json     # json 类记录（step_memory / object_memory）
├── <uuid>.md       # md 类记录（episode_memory / knowledge_memory）
├── index.json      # 倒排索引（派生物：写穿 + 可自愈重建）
└── vectors.jsonl   # 向量 sidecar（派生物：append-only）
```

- kind 白名单是模块级 `_KINDS`（md 类子集 `_MD_KINDS`），构造期 `assert kind in _KINDS`，传错即炸；
  `root` 缺省为**进程启动目录**下的 `memory/`（`Path.cwd()`，0916 起——不再从 `__file__`
  推仓库根）。`MemoryTool` 收**一个 `memory_root`**（父目录），四族**一视同仁**地住在
  它下面各自的 `<kind>/` 子文件夹里——"哪一族住哪"不是一个需要逐个指定的问题
  （0916 中途一度拆成 `step_root` / `object_root` / `episode_root` / `knowledge_root`
  四个独立开关，同日回退）。

**记录文件（真相层）**

- json 类：整文件一个对象 `{"uuid", "metadata", "payload", "text"}`。
- md 类：`---\n<JSON frontmatter：uuid/metadata/payload>\n---\n<text>\n`，正文即 `text`，
  读回走 `_parse_frontmatter` / `_parse_body`；一律经 `_atomic_write_text` 落盘（临时文件 + `os.replace`）。

**index.json（派生物，不是第二真相）**

- 结构 `{"kind", "count", "inverted", "mtimes"}`；`inverted` 为 `field → value → [uuid, ...]`，
  `mtimes` 为 `uuid → 记录文件 mtime`（`refresh_changed` 用）。
- **全量重写**而非增量：put / delete_many / 重建之后各重写一次，排序后写出以保证同内容同字节。
- 启动走 `_load_or_rebuild`：读索引 → 廉价对账（文件夹里 `*.json`/`*.md` 的 stem 集合 vs 索引 uuid 集合）
  → 不一致或 JSON 损坏就地全量扫描重建并重写。自愈，不需要 WAL。对账通过时**不读任何记录文件**：
  `filter` 走内存态 `_inverted`，`get` / `get_many` / `rank` 按 uuid 惰性读盘。
- 内存态只有四格：`_inverted` / `_uuids` / `_vectors` / `_mtimes`，记录正文不进内存。

**vectors.jsonl（sidecar）**

- 一行一个 `{"uuid", "vector"}`；`_load_vectors` 惰性加载（首次语义检索才读盘），`_put_vector`
  追加写，重复行以最后一行为准，崩溃残行跳过。
- `put` 时只对 md 类算并缓存向量（`if text and self._is_md`）；json 类当前 `text=""`，不写。
  与记录文件的关系是**可丢弃可重建**——缺失时 `rank` 现算并补写。

**手工源 vs 派生物**

- 手工源是 `<uuid>.md`：knowledge 的先验（人手写）、运营直接改的 episode 摘要。改完不重启进程也生效，
  靠 `refresh_changed()` 比 mtime 后重读整条（正文重算向量 + frontmatter metadata 重进倒排）；json 类
  是运行期写穿产物，该方法直接 no-op。
- `<uuid>.json`（写入口只有 `put`）、`index.json`、`vectors.jsonl` 都是派生物，删掉只损失算力或触发重建。

## 四、检索算法

三段流水线，实现全在 `retrieval.py`：纯函数、只认字符串、不碰库也不碰模型（向量与精排分数由调用方算好传进来）。**这五个函数不在包出口上**（0916 收窄：全仓零仓外消费方，`LocalMemoryStore.search` / `rank` 已覆盖全部需求；单测就地 `from pokemon_agent.memory.retrieval import …`）。
BM25 认得死词（技能名、地名），向量认得改写，cross-encoder 读得懂"答不答得上"但太贵，所以只对前几条跑。

| 阶段 | 函数 | 做什么 |
|---|---|---|
| 分词 | `tokenize(text) -> list[str]` | 去空白后取**字符 bigram**（不足 2 字返回单字） |
| 关键词 | `bm25_rank(query, documents) -> list[int]` | `BM25Okapi.get_scores` 打分，返回**降序下标** |
| 向量 | `embedding_rank(query, documents, embedder, document_vectors=None) -> list[int]` | 余弦打分（内部 `_cosine`），返回降序下标；传了 `document_vectors` 就不重复 embed 候选 |
| 融合 | `reciprocal_rank_fusion(rankings, k=RRF_K) -> dict[int, float]` | 只含至少一路出现过的下标，`1/(k+rank)` 累加 |
| 完整 | `hybrid_retrieve(query, documents, embedder, reranker, fuse_top_k=10, document_vectors=None) -> list[tuple[int, float]]` | BM25 + 向量各自排名 → RRF 取前 `fuse_top_k` → reranker 精排，返回 `(原始下标, reranker 分数)` 降序，长度 `min(fuse_top_k, len(documents))` |

可调参数（都在本层）：

- `RRF_K = 60`——平滑常数，文献经验值，不需要针对本项目调。RRF 只看排名不看绝对分，
  BM25（无上界）与余弦（[-1,1]）因此**不需要归一化**就能融合。
- `fuse_top_k`——进 reranker 的候选数，是精排成本的唯一旋钮：`LocalMemoryStore.search` 取
  `fuse_top_k=max(limit * 3, 10)`，再截前 `limit` 个；`rank` 由调用方直给。分词固定字符 bigram，无参数。

`LocalMemoryStore` 这一侧的实际入口：

- `rank(uuids, query, fuse_top_k)`：跳过不在索引里的 uuid 与原 `text` 为空的记录（语义检索看不见它），
  正文从盘上读、向量从 sidecar 取（缺了现算并补写），交给 `hybrid_retrieve` 后把下标映回 uuid。
- `search(query, limit, conditions)`：先 `filter` 圈候选，再走 `rank`，返回 uuid 列表。
- `filter(conditions)`：倒排取交集的 **AND-of-equalities**，空 dict 返回全部 uuid，不支持 OR / 大小比较。

## 五、数据形状

四类记录的形状住 `pokemon_agent/schemas/memory/datastore/`（`schemas/memory/__init__.py` 统一出口）；
memory 只把它们当 `metadata` / `payload` / `text` 三块收发，字段含义由 tool 层与组装方负责。

| kind | 记录类 | 一条 = 什么 | 格式 |
|---|---|---|---|
| `step_memory` | `StepMemory` | 一步：`before` / `rationale` / `action` / `after`（各含 `Observation` 快照） | json |
| `episode_memory` | `EpisodeMemory` | 一整局：来源章 + 本局可信 step 记忆的蒸馏正文 | md |
| `object_memory` | `ObjectFactEvent` | 一次按键对一格的交互事件 | json |
| `knowledge_memory` | `KnowledgeRecord` | 一条和坐标无关的世界知识 | md |

- `StepMemory`：`before` / `after` 都是 `StepMemory.Observation`（内部类，非 `world.Observation`），
  含 `step` / `place`（`map_id,x,y`）/ `status` / `facts`（`Facts` 快照，`extra="allow"`）/
  `done` / `perceived`；另有 `rationale: list[str]`、`action: str`、`step`、`episode_id`、`run_id`、
  `before_frame` / `after_frame`（base64 PNG 字符串，可为 `None`）。落盘 `text=""`，
  所以它**不参与语义检索**，只按 `episode_id` 等值筛 + 调用方按 `step` 数值排。
- `EpisodeMemory`：来源章 `episode_id` / `run_id` / `goal` / `success` / `steps`（harness 从 run state 盖的），
  派生正文 `summary` / `reusable_patterns` / `critical_decisions` / `failure_points` / `quality_score` /
  `quality_rationale` / `applicable_scenes` / `tags` / `markdown`。落盘时 `payload` 是
  `model_dump(exclude={"markdown"})`，`markdown` 当 `text` 写进正文并参与语义检索。
- `ObjectFactEvent`：`Annotated[ObjectDialogEvent | ObjectWarpEvent | ObjectStillEvent, Field(discriminator="outcome")]`。
  公共字段 `ObjectFactEventBase`：`episode_id` / `step` / `run_id` / `actor_place` / `place` / `object_kind` / `button`；
  `Place.key` 是 `f"{map_id}:{x}:{y}"`。子类按 `outcome` 判别：`dialog` 带 `text`、`warp` 带 `map_id`、
  `still` 无额外载荷。落盘 `text=""`，不参与语义检索。
- `KnowledgeRecord`：`topic` / `text` / `source` / `run_id` / `episode_id`；`text` 即记录正文与检索对象，
  `topic` / `source` 进 metadata 供过滤。手工先验与 run 产出的知识落盘形态一致。

**派生物与源记录的关系**：`step_memory` 是源记录（一局的事实轨迹，按 `episode_id` 天然隔离）；
`episode_memory` 的正文是本局通过校验的 step 记忆的蒸馏视图，**可重建、可丢弃**，
成没成一律读来源章而不从正文反推（`AGENTS.md` 铁律 3）。`object_memory` 是 harness 判定后
事件流的原样落盘，本层不折叠不派生；`knowledge_memory` 与坐标解耦，`run_id` / `episode_id`
只是来源不是身份。

## 六、provider 与选型

两个协议是 memory **要求调用方注入**的东西（`LocalMemoryStore.__init__` 收实例，不自己 new）：

| 协议 | 文件 | 唯一方法 |
|---|---|---|
| `EmbeddingProviderPort` | `embedding_provider.py` | `embed(texts: list[str]) -> list[list[float]]` |
| `RerankerProviderPort` | `reranker_provider.py` | `rerank(query: str, documents: list[str]) -> list[float]` |

两个本地实现与协议同住本包：

- `LocalEmbeddingProvider(model_name="BAAI/bge-small-zh-v1.5")`——中文优化小模型，`fastembed` 的 `TextEmbedding`；
  模型**首次 `embed()` 才加载**（懒加载），另有 `config() -> dict[str, str]` 自报模型与运行时。
- `LocalRerankerProvider(model_name="BAAI/bge-reranker-base")`——`fastembed` 的
  `TextCrossEncoder`，同样懒加载，同样有 `config()`。

依赖：`rank-bm25>=0.2`（`retrieval.py` 顶部 import，做 BM25 那一段）与 `fastembed>=0.8`（ONNX runtime，
不需要 torch；import 在函数内，首次用某模型时从 HuggingFace Hub 下一次，之后离线复用）。选本地而非远程
API：检索发生在 episode 内的 retrieve 节点里（`harness/episode/retrieve/`），远程意味着每步多一次网络往返。

## 七、依赖边界

**出边（memory 依赖谁）**：近似为零——包内互相 import，加标准库
（`json` / `os` / `pathlib` / `uuid` / `math` / `enum` / `typing`）；唯二第三方是 `rank_bm25`（`retrieval.py`
顶部）与 `fastembed`（两个实现文件内懒 import）；对 `pokemon_agent` 其余部分**零 import**——`store.py` 只
`from pokemon_agent.memory.retrieval import hybrid_retrieve`，两个 TYPE_CHECKING 块指向的是本包自己的协议。

**入边（谁依赖 memory）**：

- `tools/memory_tool.py` 是唯一调用方：模块顶部 `from pokemon_agent.memory import EmbeddingProviderPort, LocalMemoryStore, RerankerProviderPort`
  造四个 store；`MemoryTool.build()` 内 `from pokemon_agent.memory import LocalRerankerProvider, LocalEmbeddingProvider`
  造两个 provider（接线知识收在 tool 层，装配点不越过）。`build.py` 对 memory **零 import**，
  只调 `MemoryTool.build(...)` 递裸字段。
- `harness/**`、`brain/**`、`schemas/**`、`world/**` 均不 import memory 包；`schemas.memory` 的四个形状由
  `tools/memory_tool.py` 构造与解析。核对脚本 `experiment/real_check/check_memory.py`、`check_memory_roundtrip.py` 走 `MemoryTool.build()`。

## 八、当前状态与已知缺口

- **无独立测试**：`tests/` 下没有任何文件 import `pokemon_agent.memory`。`retrieval.py` 的五个纯函数
  （不碰库、不碰模型）本可脱 provider 单测，这份覆盖目前不存在；检索链路的验证靠真机 run 与
  `experiment/real_check/check_memory*.py`。
- **索引全量重写**：单文件夹千级记录、索引几百 KB 时可忽略，但没有针对更大规模做过测量，也没有增量路径。
- **无并发保护**：index.json 由内存态全量重写，代码里没有文件锁或并发检测——两个进程同时写同一 kind 文件夹，后写的会用自己那份索引覆盖前者的。当前用法是单进程。
- **vectors.jsonl 只加不减**：`delete_many` 与 `_unindex` 都不动 sidecar，被删记录的向量行留在
  文件里（`_load_vectors` 读时按活着的 uuid 过滤，无功能性影响，只是体积随历史累积）。
- **`MemoryStorePort` 11 个方法 > 6**：靠"写入/删除/快照"与"点查/检索"两层职责划界，暂未拆，
  见 `PORTS.md` 的边界核对表。另外 `import pokemon_agent.memory` 会连带拉起 `rank_bm25`（`retrieval.py` 顶部 import），
  纯 Python 小包，代价可忽略。
