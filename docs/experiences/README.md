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
