# spec —— `tests/memory/providers/`：provider 协议与本地实现的契约测试（不加载模型）

> 依据：intent 第三、五节；源码 `pokemon_agent/memory/embedding_provider.py`、`reranker_provider.py`、`fastembed_text.py`、`fastembed_reranker.py`、`ports.py`（174 行）。
> 检查点：CP8（编号 503，派发时登记）。
> 探针依据（2026-10-17，沙箱实跑，沙箱未装 fastembed）：`LocalEmbeddingProvider` / `LocalRerankerProvider` 构造成功；`isinstance` 对两个协议均为真；`embed([])`、`embed([''])`、`rerank('', [...])`、`rerank('q', [])` 均触发 `AssertionError`；`config()` 返回 `{'model': …, 'runtime': 'fastembed'}`。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 不加载模型：通过 `sys.modules["fastembed"] = None` 让导入失败，证明构造与断言前置不触发导入 | 公开行为（不碰私有 `_model`）；代价是依赖 `sys.modules` 的替换语义 |
| D2 | `isinstance` 用 `runtime_checkable` 协议判定 | 协议结构检查，不需要显式继承 |
| D3 | 前置条件用 `pytest.raises(AssertionError)` | 与 intent 第四节第 3 条一致；断言在导入模型之前触发，所以不需要模型 |
| D4 | 不测真实推理、不测向量维度、不测分数质量 | intent 第三节 |

## 二、用例清单（每条一句话命名）

**协议判定**
1. `test_local_embedding_provider_satisfies_embedding_port`：`isinstance(LocalEmbeddingProvider(), EmbeddingProviderPort)` 为真。
2. `test_local_reranker_provider_satisfies_reranker_port`：同上，`RerankerProviderPort`。
3. `test_local_memory_store_satisfies_memory_store_port`：`isinstance(LocalMemoryStore(...), MemoryStorePort)` 为真（需先确认 `MemoryStorePort` 是 `runtime_checkable`；执行方第一步探针，若不是，改为"不声明 runtime_checkable"的用例或删去，并汇报）。

**构造不加载模型**
4. `test_local_embedding_provider_construction_does_not_import_fastembed`：`sys.modules["fastembed"] = None` 下构造成功。
5. `test_local_reranker_provider_construction_does_not_import_fastembed`：同上，reranker 子模块。

**前置条件（在导入之前断言）**
6. `test_embed_rejects_empty_text_list`。
7. `test_embed_rejects_empty_string_in_texts`。
8. `test_rerank_rejects_empty_query`。
9. `test_rerank_rejects_empty_documents`。

**config 自报**
10. `test_embedding_config_reports_default_model_and_runtime`：默认模型名 `BAAI/bge-small-zh-v1.5`，runtime `fastembed`。
11. `test_reranker_config_reports_default_model_and_runtime`：默认 `BAAI/bge-reranker-base`。
12. `test_config_reports_custom_model_name_passed_to_constructor`。

## 三、已知观察

- 无。协议与实现的对应关系与探针一致。

## 四、迁移清单

本目录无迁入用例。`tests/memory/test_memory_store.py` 中与 provider 相关的用例（若存在）在 CP6 读源码时判定归属；本 spec 不预设。

## 五、验证

- 默认 pytest：`tests/memory/providers/` 通过，耗时计入 memory 目录预算。
- 沙箱与用户本机均无需 fastembed 安装（用例不得依赖它）。
- 破坏验证：临时把 `embed` 的 `assert texts` 去掉，用例 6 应失败；还原后生产目录 `git diff` 为空。

## 六、停止条件

- 用例 4、5 因 fastembed 在导入路径上其它位置被触发（例如包级 `__init__` 顶层导入）→ 停，汇报，不改生产代码。
- 用例 3 的 `MemoryStorePort` 不是 `runtime_checkable` → 按第二节第 3 条处理并汇报。

## 七、非目标

- 不测真实模型下载、推理、维度；不测 `fastembed` 的 API 形状；不测评测质量。
