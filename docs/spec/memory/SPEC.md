# `pokemon_agent/memory/` 技术规格

覆盖文件：`memory/ports.py`（对外契约）、`memory/store.py`（唯一实现）、
`memory/retrieval.py`（混合检索纯函数），以及 `memory/__init__.py`（统一出口）。

> **0910 重写说明**：本文件此前 465 行描述的是 `memory/semantic/`、
> `interfaces/memory/*store.py` 那套"按记忆类型各拆一个 store"的实现。那套实现在
> 0910 重构中整体退役——存储职责并入 `store.py`（一条记录一个文件 + 每文件夹倒排索引），
> 领域对象的组装（`StepMemory` / `EpisodeMemory` / `ObjectFactEvent` 的解析与渲染）
> 上移到 tool 层。旧内容不再逐节保留，本文档改为"当前形状"的短规格。
> 详细记录见两份 PLAN：[`PLAN_memory_trace_layout.md`](PLAN_memory_trace_layout.md)
> （落盘布局与索引自愈）、[`PLAN_memory_query_convergence.md`](PLAN_memory_query_convergence.md)
> （对外契约的形状与归位决策）。

---

## 1. 定位：一个可以整体拷走的记忆子系统

按**检索单元**而不是记忆种类组织，只认三个形状：`metadata`（字段→值，过滤检索用）、
`payload`（调用方自己的结构，原样存取、不解析）、`text`（给语义检索用的文本）。

**它不理解游戏。** 字段叫什么、值是什么、payload 装的是什么，对本包完全不透明——
"发生了什么、影响了谁"这类语义判定由 harness 完成后以数据形式交给它
（AGENTS.md 四·分层原则）。这条边界正是它可复用的前提：换一个项目，只要给出的
`metadata` / `text` 自洽，`ports.py` + `store.py` + `retrieval.py` 一行不用改。

这也是 0910 把契约从 `interfaces/memory/memory_index_port.py` 搬进 `ports.py` 的原因：
`interfaces/` 是本项目的跨层港口（brain ↔ harness ↔ world），而 memory 是要能被整体
拷走的子系统——契约与实现同住一包，拷走即得。搬完 `memory/` 运行期对
`interfaces/` / `schemas/` **零依赖**（只有类型检查期引用两个 provider Protocol）。

---

## 2. 三个文件

### 2.1 `ports.py` —— 对外契约

`MemoryStorePort`（Protocol，`runtime_checkable`）：写入 + 点查 + 过滤检索 +
语义检索 + 归档，共 9 个方法。

| 类别 | 方法 |
|---|---|
| 写 | `put(metadata, payload, text) -> uuid` |
| 点查 | `get(uuid)` / `get_many(uuids)` |
| 过滤检索 | `filter(conditions) -> [uuid]` |
| 语义检索 | `search(query, limit, conditions?) -> [uuid]`、`rank(uuids, query, fuse_top_k) -> [(uuid, score)]` |
| 归档 | `archive_many(uuids, dest_dir) -> int` |
| 维护 | `count()` / `refresh_changed()` |

**每个方法的完整契约（这个方法承诺什么 / 什么情况下会失败 / 调用方要保证什么）
写在 `ports.py` 的 docstring 里，本文件不复制一份。**

### 2.2 `store.py` —— 统一记录存储

`MemoryStore`：`MemoryStorePort` 的默认（也是唯一）实现。

一个实例绑定一个 kind（= `memory/` 下的一个子文件夹）。四类记忆四个文件夹、
四个实例：`step_memory` / `object_memory` 是 json 类（整文件一个 JSON），
`episode_memory` / `knowledge_memory` 是 md 类（JSON frontmatter + 正文）。

**落盘布局**：

    memory/<kind>/
    ├── <uuid>.json        # json 类记录：{"uuid","metadata","payload","text"}
    ├── <uuid>.md          # md 类记录：JSON frontmatter + 正文（= text）
    ├── index.json         # 倒排索引（派生物、写穿、可自愈重建）
    └── vectors.jsonl      # 语义检索的向量缓存 sidecar

**全项目不按 run 分层**：`run_id` 是 metadata 里的普通过滤字段，跟 `map` / `scene`
完全对等，这一层不做任何特判。

### 2.3 `retrieval.py` —— 混合检索纯函数

BM25 bigram + embedding 余弦 + RRF 融合 + reranker 精排。**只认字符串，不认任何
记忆类型**——所以它住包根而不是某个 kind 目录：跨局摘要与知识库共用这一份逻辑。
纯函数（向量与精排分数由调用方算好传进来），可以脱离 provider 单测。

---

## 3. 读代码前先记住的四条契约

1. **索引是派生物**：`index.json` / `vectors.jsonl` 都可以删，删了会从记录文件重建
   （代价是重算向量——花钱花时间）。但**重建能还原内容，还原不了历史决策**——
   所以"退出检索"这件事必须伴随文件移动（见第 3 条）。
2. **`filter()` 零读盘**：它只查内存里的倒排表，不打开任何记录文件。这是"索引落盘"
   换来的收益——所以 `filter()` 只返回 uuid，内容要用 `get()` / `get_many()` 按 uuid
   惰性取。这个两步不是冗余，是这条契约的形状。
3. **"让记录消失"只有归档一个语义、也只在一个时机发生**：`archive_many()` 把文件
   `os.replace` 搬走 + 摘出索引，不 unlink。当前唯一调用方是 `void_memory_after`
   （checkpoint 恢复，搬进 `voided-<ts>/`）。**局正常收尾不碰记忆**——step 记忆按
   `episode_id` 查询天然隔离，没有清场的必要，所以也没有"例行清理"这第二个归档
   动机。**没有"摘索引但文件原地留"的中间态**——那个状态在索引重建时无法还原，
   会让被丢弃的记录复活（0910 实测确认，遂撤掉 `forget_many` 与
   `discard_episode_steps`）。
4. **过滤检索只支持等值 / 成员匹配**（AND-of-equalities 取交集），不支持大小比较。
   数值区间（"step 小于 N"）是调用方的领域知识：先用等值条件把候选筛小，
   再对候选集里的字段做数值比较。

---

## 4. 与 `schemas/` 的关系：为什么领域对象不住在这个包里

`StepMemory` / `EpisodeMemory` / `ObjectFactEvent` 定义在 `schemas/memory/`、
`schemas/world/`，不在 `memory/` 包内部——因为它们要出现在**跨层契约**里
（harness 递给 tool、tool 递回 harness），而 `memory/` 只认
`metadata` / `payload` / `text` 三个泛型形状。

本包对领域对象一无所知：解析与渲染都在 tool 层（`tools/memory_tool.py`），
连"哪些记录已作废"这种判断也是 tool 先 `filter()` 出 uuid、再按 `step` 数值筛，
最后交给本包搬走。
