# 工程经验文档索引

每篇 = 一次端到端问题的「分析 → 定位 → 解决 → 验证」。模板与规范见
[`docs/EXPERIENCE_DOCS.md`](../EXPERIENCE_DOCS.md)。

**没有登记索引的经验文档等于没写。** 新文档：放本目录 + 在下面表格加一行。

| 日期 | 主题 | 摘要 | 关联 Issue |
|---|---|---|---|
| 2026-08-31 | [审计/判定 43-77 秒：step 记忆渲染里 walk_map 占大头](2026-08-31-audit-77s-input-bloat.md) | 输入膨胀是长延迟第一嫌疑；渲染层排除不变字段（1300→356 字符，审计 77s→11.4s） | — |
| 2026-08-31 | [跨局摘要检索 KeyError：向量缓存与磁盘摘要生命周期不一致](2026-08-31-keyerror-cross-run-leak.md) | error 的 id 前缀不是当前 run = 跨 run 泄漏；派生索引跟随真相惰性重建 | — |
| 2026-09-01 | [搭测评框架：judge 机械复核从「引用过但已删除」到可运行 + 接 CI](2026-09-01-eval-framework-bootstrap.md) | 重建 audit_verdicts.py（19 条任务的机械复核规则）+ pyproject/CI 接入，本地无真实 knowledge_* 数据，改用经验文档里的误判场景做回归测试 | — |
| 2026-09-01 | [trace 该不该记 task_id：一次质疑一错一半对，外加一个真实的打包 bug](2026-09-01-trace-task-id-and-memory-carried.md) | task_id 缺失是刻意设计（读代码后自我纠正）；episode_memory 跨批次检索是真实风险，先补 memory_carried 做可观测；顺带修好 pip install -e 装不上的包发现 bug | — |
| 2026-09-13 | [brain 与 harness 脱钩、brain 独立成模块：全流程经验原则](2026-09-13-brain-decoupling-principles.md) | 模块划分判据是「能不能整个拷走」而非「谁在消费」；异常继承判据是「有没有跨过 tool 层」；同形不同约靠鸭子类型 + 副本字段核对；brain 对外依赖归零 | `AGENTS.md` 铁律 2 |
| 2026-09-13 | [trace 模块脱钩审计：按 P1～P7 清点「如何移出」](2026-09-13-trace-decoupling-audit.md) | trace 本体对外依赖已为 0（P1 零成本通过）——要移出的不是 trace，是 harness 里 8 个读点；`TraceEvent` 12 字段里 trace 只用 5 个 ⇒ 拆出 `Event`（Protocol 方案已实测可行）留 trace、`TraceEvent` 移出；P3 因 trace 项目无关而不适用；另发现 `store.py` 用 `__file__` 硬编码仓库根的真依赖 | `AGENTS.md` 铁律 2 |
| 2026-09-13 | [memory 模块按 brain 脱钩原则审计](2026-09-13-memory-decoupling-audit.md) | memory 对外依赖为 0，八条里七条直接通过；唯一待改是 `build.py` 的造型 import（建议加 `MemoryTool.build()`） | `AGENTS.md` 铁律 2 |
| 2026-09-13 | [world 模块脱钩审计：按 P1～P7 清点「如何移出」](2026-09-13-world-decoupling-audit.md) | world 是四模块里唯一出边不为零的一个：2 条出边（`pyboy_world.py:26` → `tools.prompts` 是**反向依赖真违规**，一行拿下 82 个传递模块；`errors.py:24` → `AgentError` 是 P3 主动保留的例外）；入边 22 条里 16 条非 tool（实现依赖只剩 `build.py`，是四模块唯一没做工厂的）；P4 不对称——world 的重试循环建在 harness 而非 tool 层，这也是它「该继承 `AgentError`」的根因 | `AGENTS.md` 铁律 2 |
