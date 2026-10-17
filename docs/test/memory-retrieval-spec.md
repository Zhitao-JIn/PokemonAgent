# spec —— `tests/memory/retrieval/`：检索纯函数的单元测试

> 依据：`docs/test/memory-test-intent.md` 第五节；源码 `pokemon_agent/memory/retrieval.py`（194 行）。
> 检查点：CP5（编号 500，派发时登记）。替身：`tests/_doubles/memory.py`（本检查点新建）。

## 一、决定表

| 编号 | 决定 | 理由与代价 |
|---|---|---|
| D1 | 直接 import 纯函数，不经任何 store 或 capability | 包文档明确允许；这是 retrieval 唯一可以就地 import 私有性之外的入口，代价是测试与函数签名绑定 |
| D2 | 替身只用 `DeterministicEmbedder`（计数）与 `OverlapReranker`（分数 = 共有 bigram 数） | 足够断言"谁排第一"，不依赖模型；代价是不测排序质量（那是评测） |
| D3 | 零向量 embedder 单独用手写小类，不混进 `DeterministicEmbedder` | 零向量语义（norm=0 得 0 分）要单独钉住 |
| D4 | `prebuilt` 参数只测**输出等价**，不 spy 是否重建 | 不碰私有成员，符合 intent 第四节第 2 条 |
| D5 | 前置条件用 `pytest.raises(AssertionError)` 钉住 | 与 intent 第四节第 3 条一致 |

## 二、已知观察（不写成预期测试，记入遗留）

- **K1**：`hybrid_retrieve(fuse_top_k=0)` 的 `AssertionError` 来自 reranker 的入参断言（候选为空），不是 `hybrid_retrieve` 自身的前置条件。`hybrid_retrieve` 的 docstring 未声明 `fuse_top_k > 0`。处理：不测这一条，记遗留（文档缺口）。
- **K2**：`bm25_rank` / `build_bm25` 的边界（单字符、重复文档）只在探针里看过行为，不写成契约测试。

## 三、用例清单（每条一句话命名）

**tokenize**
1. `test_tokenize_splits_text_into_character_bigrams`：`"甲乙丙"` → `["甲乙", "乙丙"]`。
2. `test_tokenize_drops_whitespace_before_bigramming`：`" a b "` → `["ab"]`。
3. `test_tokenize_returns_single_char_for_one_char_input`：`"a"` → `["a"]`（探针已确认）。
4. `test_tokenize_returns_empty_list_for_empty_input`：`""` → `[]`（探针已确认）。

**build_bm25 / build_bm25_from_corpus / bm25_rank**
5. `test_build_bm25_rejects_empty_documents`：空列表触发断言。
6. `test_build_bm25_from_corpus_rejects_empty_corpus`：空语料触发断言。
7. `test_bm25_rank_puts_document_sharing_query_bigrams_first`：三条文档中唯一共享查询 bigram 的排第一。
8. `test_bm25_rank_returns_indices_covering_every_document`：返回下标集合 = `range(len(documents))`，无重复、无遗漏。
9. `test_bm25_rank_with_prebuilt_index_matches_fresh_build`：`prebuilt` 与现建的结果相同。
10. `test_bm25_rank_rejects_empty_documents`：空列表触发断言。

**embedding_rank**
11. `test_embedding_rank_orders_documents_by_cosine_similarity`：与 query 向量夹角最小的排第一。
12. `test_embedding_rank_scores_zero_vector_document_as_zero`：零向量候选排在正相似度候选之后。
13. `test_embedding_rank_embeds_documents_only_when_vectors_not_supplied`：传入 `document_vectors` 时 embedder 只收到 query（计数 = 1）。
14. `test_embedding_rank_embeds_query_and_documents_when_vectors_not_supplied`：不传时计数 = 1 + 文档数（探针可核）。
15. `test_embedding_rank_rejects_mismatched_document_vectors`：长度不等触发断言（探针已确认）。
16. `test_embedding_rank_rejects_empty_documents`：空列表触发断言。

**reciprocal_rank_fusion**
17. `test_rrf_sums_reciprocal_ranks_across_rankings`：同一下标在两路都排第一，分数 = 2/(60+1)。
18. `test_rrf_omits_documents_absent_from_every_ranking`：返回 dict 的键只含出现过的下标。
19. `test_rrf_returns_empty_dict_for_no_rankings`：`[]` → `{}`（探针已确认）。
20. `test_rrf_uses_k_of_60_by_default`：默认 k 下第一名分数 = 1/61。

**hybrid_retrieve**
21. `test_hybrid_returns_fuse_top_k_results_sorted_by_rerank_score`：长度 = `min(fuse_top_k, n)`，按 rerank 分降序。
22. `test_hybrid_returns_all_documents_when_fuse_top_k_exceeds_count`：`fuse_top_k` 大于文档数时长度 = 文档数。
23. `test_hybrid_reports_four_timing_stages`：timings 键恰为 `bm25`、`vector`、`rrf`、`rerank`，值为非负浮点。
24. `test_hybrid_feeds_reranker_only_the_fused_candidates`：reranker 收到的候选数 = `fuse_top_k`（用记录调用的替身）。
25. `test_hybrid_with_prebuilt_bm25_matches_fresh_build`：结果相同（D4）。
26. `test_hybrid_rejects_empty_documents`：空列表触发断言。

## 四、替身清单（`tests/_doubles/memory.py`）

- `DeterministicEmbedder`：`embed(texts)` 按 bigram 哈希进固定维度（16）；记录 `calls` 累计条数。
- `OverlapReranker`：`rerank(query, docs)` 分数 = query 与文档共有 bigram 数；入参为空时断言（与真实 provider 一致）。
- 零向量 embedder：仅在 `test_retrieval_*` 文件内手写，不进共用替身。

## 五、迁移清单

本目录无迁入用例（retrieval 纯函数此前只有 `test_memory_store.py` 里的零向量一例，属于 store 的 numpy 用例，迁入 `retrieval/` 时由 CP6 处理：`test_embedding_rank_scores_zero_vector_document_as_zero` 对应原用例）。

## 六、验证

- 默认 pytest：`tests/memory/retrieval/` 全部通过，耗时计入 memory 目录 3 秒预算。
- 破坏验证：临时把 `reciprocal_rank_fusion` 的分母改成 `k + rank - 1`，用例 17、20 应失败；还原后 `git diff` 生产目录为空。
- 不调真实模型，不联网。

## 七、停止条件

- 任一用例需要 spy 私有成员（`_inverted` 等）才能写 → 停，汇报。
- K1 之外发现 `hybrid_retrieve` 的其他失败位置 → 停，汇报（不自行加断言）。
- 文件名与现有测试重名 → 停，汇报。

## 八、非目标

- 不测排序质量（评测）；不测 `hybrid_retrieve` 在 store 里的用法（store spec）；不测真实 fastembed 推理。
