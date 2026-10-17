# intent —— memory 模块单元测试：新建覆盖 + 迁入散落的 memory 行为测试

> 状态：**已确认**（2026-10-17，用户回复「全按推荐」，O2/O3 另经追问后确认改实现）。
> 范围：只做单元测试。模块 = `pokemon_agent/memory/`（含 `recall.py` 的 `MemoryCapability`）。
> 关联：`docs/test/brain-test-intent.md`（brain 模块的做法，本文沿用）；AGENTS.md 第三节第 4、5 条。

## 一、一句话意图

把 `pokemon_agent/memory/` 当作**可整体拷走的第三方库**来测：只经它的公开面说话——`LocalMemoryStore`（`MemoryStorePort` 的实现）、`MemoryCapability`（`recall` / `memorize` / `snapshot` / `restore`）、`retrieval` 的纯函数、两个 provider 协议及本地实现的构造契约——用一对**确定性假 embedder / reranker** 钉住每个方法的后置条件与每类失败。同时把散在 `mcpclient/`、`mcp_servers/` 里、实质在测 memory 行为的用例迁进来。

## 二、为什么现在做

1. **brain-scope 的地基**：CP1 给 memory 加了 run 这一级，之后不再改这个包；现在钉稳，后面的 L0/L1 读记忆才有依据。
2. **现有 memory 测试名不副实**：`tests/memory/test_memory_store.py` 444 行 19 个用例，一半以上经 `memory_server_context`（真 FastMCP + 内存传输）绕一圈；store 的 `put/get/filter/delete/count` 反而没有直接测试。
3. **核心契约没人守**：`filter` 的交集语义与空条件；`put/get/get_many` 在 json / md 两形态下的往返；`delete_many` 与 `count`；索引自愈；`search` 的 `conditions` / `limit` / 候选为空；`rank` 的前置条件与 `fuse_top_k`；`memorize` 各 kind 的落族与断言；`recall` 的分族路由、摘要自然序、`limit` 截断、非法 payload 静默跳过；`retrieval` 的 `tokenize` / `bm25_rank` / `reciprocal_rank_fusion` / `hybrid_retrieve`。
4. **「测试是用法示范」**：读者应能看完测试就会用这个包，而不是先去看懂 MCP 夹具。

## 三、是什么 / 不是什么

**是**：
- 按源码文件镜像的四个目录（见第五节），每个目录若干「一句话命名」的用例；
- 共用替身 `tests/_doubles/memory.py`：`DeterministicEmbedder`（按字符 bigram 哈希进固定维度，记录收到的文本条数）与 `OverlapReranker`（分数 = 与 query 共有 bigram 数）。现有 `_doubles/memory_server.py` 的零向量假件**保留**给 MCP 夹具用；
- 迁移：memory 行为的测试改成直接调 `LocalMemoryStore` / `MemoryCapability`，不再绕 MCP。

**不是**：
- 不测 MCP 传输与管理面（`--enable-admin`、归档大小上限、sha256 校验、并发 restore 互斥、客户端 `MemoryMcpTool`）——那是 `mcp_servers/` 与 `mcpclient/` 的契约，原地保留；
- 不测真实 fastembed 推理（要下载模型、慢、非确定）；本地 provider 只测构造不加载、空入参 assert、`config()` 自报；
- 不测排序质量（那是评测）；不测 harness / brain 如何使用 memory；
- **O1–O3 的修复在本轮内完成**（见第六节），但修复本身不是测试的目标，修复后再测。

## 四、硬边界

1. 零联网、零真实模型、零模拟器；落盘一律 `tmp_path`，缺省根的用例用 `monkeypatch.chdir(tmp_path)`。
2. 不测私有成员：不碰 `_inverted` / `_uuids` / `_vectors` 等；需要观察内部副作用的（如「有没有重算向量」）只经**注入的假 embedder 的调用计数**和**盘上文件**这两条公开通道。唯一例外是 `retrieval.py` 的纯函数（包文档明确写了可就地 import）。
3. 文档化的前置条件用 `pytest.raises(AssertionError)` 钉住，与现有 `snapshot` 用例一致。
4. 一个用例只钉一件事，函数名是一句话；Arrange / Act / Assert 三段空行分开；不用 `MagicMock`，假件是手写小类。
5. 速度：整个 memory 测试目录默认 pytest 下**不超过 3 秒**；不加 `slow`；不 sleep；需要「mtime 变了」就 `os.utime`。
6. 测试文件名全仓唯一：统一前缀 `test_retrieval_*` / `test_store_*` / `test_capability_*` / `test_local_providers_*`。

## 五、目录与迁移（概要；精确到用例的清单在各目录 spec）

新结构（镜像 `pokemon_agent/memory/`）：

| 目录 | 对应源码 | 钉什么 |
|---|---|---|
| `tests/memory/retrieval/` | `retrieval.py` | `tokenize`、`bm25_rank` / `build_bm25*`、`embedding_rank`（含零向量）、`reciprocal_rank_fusion`、`hybrid_retrieve`（`fuse_top_k` 截断、降序、四段 timings） |
| `tests/memory/store/` | `store.py` | `put/get/get_many/filter/delete_many/count`（json 与 md 两形态）；索引自愈；`search` / `rank`；`refresh_changed`；向量 sidecar；`snapshot` / `restore`；缺省根与显式根；`kind` 校验 |
| `tests/memory/capability/` | `recall.py` | `memorize` 各族落族与断言；`recall` 路由、摘要自然序、`limit`、非法 payload；`snapshot` / `restore`（不安全条目、缓存清空）；缺省根 |
| `tests/memory/providers/` | `embedding_provider.py` `reranker_provider.py` `fastembed_*.py` `ports.py` | 协议的 `isinstance` 判定（`runtime_checkable`）与本地实现的不加载契约 |

迁移原则：**断言对象是 memory 自己的行为 → 迁入并改写成直调；断言对象是传输 / 信封 / 管理面 → 原地保留。**

| 现有文件 | 处理 |
|---|---|
| `tests/memory/test_memory_store.py`（19 个） | **整个文件拆开迁入**并删除原文件：落盘根用例 → `store/` 与 `capability/`；快照 / 恢复 → 改直调 store 与 capability；timings、`refresh_changed`、语料持久化、numpy 零向量、sidecar 压实 → `store/` 与 `retrieval/` |
| `tests/mcpclient/memory_tool/test_episode_summary_order.py` | **迁入** `capability/`（摘要自然序，改直调） |
| `tests/mcpclient/memory_tool/test_object_recall_content.py` | **拆**：object 内容往返的 memory 侧断言迁入 `capability/`；「条目满足 MCP 端口模型」的断言原地保留 |
| `tests/mcpclient/memory_tool/test_memory_admin_validation.py` | **原地保留**（传输 / 管理面）；「不安全条目整包拒绝」的能力层断言随 `test_memory_store.py` 迁入 `capability/` |
| `tests/mcpclient/memory_tool/test_memory_mcp_only.py` | 原地保留（客户端装配） |
| `tests/mcp_servers/test_mcp_memory_e2e.py` | 原地保留（服务端注册与双路径对齐）；能力层的 kind 分发与 hint 过滤由 `capability/` 直测 |
| `tests/evals/common/test_memory_server.py`、`tests/evals/memory_store_recall/test_run_memory_mcp.py` | 原地保留（评测侧） |
| `tests/harness/**` 里读写记忆的用例 | 原地保留（harness 模块的事，另案） |
| brain-scope CP1 新增的 `tests/memory/test_memory_index_lines.py`、`test_run_memory_family.py`（在 `feature/brain-scope`，尚未合入主线） | **等 brain-scope 合入后**作为最后一个检查点迁入新结构并补 run 族；本轮不碰 |

## 六、缺陷处理（已确认）

逐行读码得到、并经源码核实（2026-10-17）的五条：

1. **O1 `refresh_changed` 的内容 hash 不跨进程**：`_hashes` 文档说「随 `index.json` 持久化」，但 `_save_index` 不写、`_load_or_rebuild` 不读。重启后 git 重写文件（mtime 变、内容不变）会整库白算向量。**处理：单独立检查点修**（让 hash 随索引持久化），加回归测试，写 CHANGELOG。
2. **O2 `get` 在文件被外部删除、索引未对账时返回 `({}, {}, "")` 而非 `None`**（已核实：`store.py` 第 254–260 行与第 516–526 行）。契约写「不存在返回 None」。**处理：改实现**——缺失时返回 `None`，加回归测试。
3. **O3 `search(limit<=0)` 无前置条件检查**（已核实：`store.py` 第 286–298 行无 assert，接口 `ports.py` 第 94 行要求 `limit > 0`）。`limit=0` 静默返回空，`limit=-1` 静默返回去掉最后一个的结果。**处理：改实现**——入口补 `assert limit > 0`，加回归测试。
4. **O4 `recall` 的 knowledge 条目 `score` 恒为 `None`**，但 `_recall_knowledge` 的 docstring 写「score = 相关性」。**处理：只改注释**，与行为对齐。
5. **O5 `LocalMemoryStore.__init__` 里属性文档字符串错位**（`_corpus` 的说明排在 `_vector_rows` 之后，成了游离字符串）。**处理：只改注释位置**。

修复检查点的顺序：O1、O2、O3 各一个检查点（先修、再补回归测试、再写 CHANGELOG）；O4、O5 合并为一个纯注释检查点。这些检查点排在测试迁移之前。

## 七、已确认的问题

1. 范围含 `recall.py`。
2. 迁移原则：断言 memory 行为的迁入、改为直调；断言传输 / 信封 / 管理面的原地保留；`test_memory_store.py` 整个拆掉。
3. 本地 provider 只测不需要模型的契约。
4. 基于 `main`（`5964222`）做；brain-scope CP1 的两个 memory 测试等它合入后再迁。
5. 缺陷按第六节处理（O1–O3 改实现先修，O4–O5 只改注释）。
6. 文档化的前置条件用 `pytest.raises(AssertionError)` 钉住。

## 八、成功的样子

- `tests/memory/` 下四个目录、约 60–80 个用例，默认 pytest 下 3 秒内；
- 读完它就知道 `LocalMemoryStore` / `MemoryCapability` 怎么用、每个方法承诺什么、失败时抛什么；
- `tests/memory/test_memory_store.py` 与 mcpclient 下被迁走的用例不再存在；用例总数只增不减（迁移前后集合对得上，新增是新覆盖）；
- O1–O5 各有去向：O1–O3 已修并有回归测试，O4–O5 已改注释，没有一条被钉成「当前错误行为」。
