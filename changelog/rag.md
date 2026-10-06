# RAG 变更志

> 主题账：memory 检索层（RAG）的每一次变更，按**错误 case → 归因 → 更改方案 → 结果**
> 四段记录。主 CHANGELOG.md 保持编号总账，这里是检索专题的完整叙事——每条目标：
> 拿出来就是一段可以直接写进博客或简历的"发现问题 → 定位 → 修"故事。
>
> 背景基线（2026-09-28 工业差距评估）：骨架为 BM25(字符 bigram) + bge-small-zh(512维)
> + RRF(k=60) + bge-reranker-base 四段流水线，契约清晰；短板集中在**观测盲区、
> sidecar 膨胀、精排无截断、零评估集**四项。17 维 rubric 见用户级 skill `module-gap-audit`
> 的 `references/rubric-rag.md`。

---

## RAG-1（2026-09-28，主账 324）—— 检索分段计时：耗时随返回值出，2~9s 黑盒开口说话

**错误 case**：真机 run 的 `query_knowledge` 单次耗时 2~9 秒波动（对照：全链路 LLM 调用均值
0.99~3.24s），每步决策圈都被拖慢；但 trace 里只有一笔总账（`started_at/ended_at`），
回答不了"时间花在哪"——是 embedding 慢、BM25 慢还是交叉编码器慢，全靠猜。

**归因**：① 检索五段（候选准备/BM25/向量余弦/RRF融合/精排）全部发生在 memory 模块内部，
harness 只看得到整段墙钟——**观测粒度断层**。② 主嫌疑是 `rerank` 段：`fuse_top_k =
max(limit*3, 10) = 15` 条候选**无低分截断**全量过 bge-reranker-base 交叉编码器
（CPU ONNX 逐对推理，候选正文越长越慢）——与 2~9s 的波动区间吻合，但在打点证实前
只是推断（工业界对照：腾讯云千万级知识库改造案例正是靠"精排截断 Top120"把 P99
从 720ms 压到 395ms）。③ 顺带盘出 sidecar 病理性膨胀：`knowledge_memory/vectors.jsonl`
**697 行只对 12 条记录（7.7MB）**，见 RAG-2。

**更改方案**：分段耗时**并入检索返回值**，不走旁路回调——对齐模型 provider 的先例：
`complete()` 的返回除了正文还带 token 用量，检索的返回除了命中还带各段耗时。
三层逐级透传：`hybrid_retrieve → (结果, timings)` → `MemoryStorePort.search/rank →
(uuids/命中, timings)`（Port 契约同步改形状，timings 五段
`prepare/bm25/vector/rrf/rerank`，五段之和 ≈ 调用时长）→ `QueryKnowledgeResp.timings`
→ `read_knowledge` 账 content 的 `timings` 键（可选键，判据侧出现即核形状；
排序不受影响——`ended_at` 仍是唯一排序依据）。原 `t0/t1` 总账保留，
与五段之和做对账。

**结果**：代码层完成，ruff 净、定向绿（memory_store / merge_retrieval / trace_render /
trace_tool；test_node_io 首跑 4 挂经排查为**既有非确定性 flaky**——同环境两次 run_fake
一次账流非法一次全绿，根因在 trace 排序同刻由随机 uuid 决胜，与本次改动无关，详见
当日日志；复跑 41 条全绿，随后 325 从根上根除该 flaky）。**真机数字待回填**：下一局
真机 run 的 `read_knowledge` 账将带出第一份分段分布，用于证实/证伪 rerank 主因假设，
并给 RAG-3（精排截断）提供改动前基线。

**聚合侧定案（0928 用户拍板）**：分段耗时的**聚合不做自研面板——直接靠 langfuse**
（`read_knowledge` 本就是 retriever 型 span，output 封套里 content.timings 可查可聚）。
AI 侧只需保证账在 content 里记：已补端到端契约测试
`test_query_knowledge_returns_per_stage_timings`（memory_store）钉住
"query_knowledge 返回必带五段 timings"——账没了或断了段，测试当场炸。

---

## RAG-2（2026-09-28，归因完成，修复待定向）—— vectors.jsonl 697 行对 12 条：sidecar 为什么越用越胖

**错误 case**：`memory/knowledge_memory/vectors.jsonl` 7.7MB、697 行，而知识库只有
12 条记录——每条记录被重复 embed 约 58 次，且每次知识检索前还要为这份垃圾付 IO。

**归因**（两个来源，一个主凶一个帮凶）：① **主凶：惰性加载被短路**——`rank()` 里
`vectors = self._vectors or {}`：首次语义检索时 `_vectors` 还是 `None`（sidecar 是
惰性加载的），`None or {}` 给出**空 dict**，等于宣告"全部候选没有缓存向量"→ 12 条
全部现算 embed + 逐条 append 进 sidecar。**每次进程重启后的首次检索都白算一轮、
追加 12 行**（697 ≈ 58 次启动 × 12 行）。② 帮凶：`refresh_changed()` 以 mtime 判
"文件被编辑过"，而 knowledge md 被 git 跟踪——git checkout/pull 重写工作区文件
（mtime 变、内容一字不变），下次检索前整库重算。

**更改方案**：① 一行修复——`self._vectors or {}` 改 `self._load_vectors()`
（真正触发惰性加载）；② 判据从 mtime 升级为"mtime 预筛 + 内容 sha256 复核"
（hash 随 index.json 持久化，与 `_mtimes` 同构）；③ 一次性压实 sidecar
（按 uuid 去重重写，697 → 12 行，派生物可重建、零风险）。

**结果**：①②③ **全部落地（CHANGELOG 324 + 328）**——324 修主凶（惰性加载短路），
328 治帮凶（hash 判变更）并压实存量（697 行 7.7MB → 12 行 133KB）。三条行为测试
钉住：同内容重写不重算（embed 计数不变）、真编辑必重算、corpus 跨实例持久化。
主账 328。

---

## 待办（按优先级，做完挪进上面成条）

- **RAG-3 精排截断**：`fuse_top_k=15` 全量过 cross-encoder、无低分跳过——等 RAG-1
  的分段账证实占比后再动，用评估集守住召回（改动前基线 = RAG-1 数字）。
- **检索金标集**：20~50 条 query → 应命中 uuid，报 recall@5 / MRR——当前检索侧
  零评估，任何调参都是盲调。
- ~~RAG-2 三件套~~：**已全部落地**（324 + 328，见上）。
- **BM25 持久化**（328 连带）：分词 corpus 随 index.json 走 + 索引本体按语料指纹缓存——查询路径不再重分词全库（原维度 11/12 的差距，已消）。
- **向量打分 numpy 化 + sidecar 自动压实**（329，主账）：rubric 维度 02 的提前量（numpy 扁平精确索引，十万条毫秒级，换 HNSW 只动一处）与维度 03 的自动压实（阈值 max(64, ×4)）——详见 CHANGELOG 329。

- 远期（规模到了再做）：ANN 索引、查询改写、BM25 索引持久化。
