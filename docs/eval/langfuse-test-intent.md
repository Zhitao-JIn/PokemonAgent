# intent —— LangfuseTrace 测试与本机 smoke：证明实现可信，不改设计

> 流程位置：`langfuse-intent.md` → `langfuse-spec.md` → `langfuse-plan.md`（P0–P3 已落码）→
> **langfuse-test-intent.md**（本次改动）→ `langfuse-test-handoff.md`（执行依据）→ 测试落地
> 状态：**已生效**；本次改动 = 交接口令的意图化——只加测试与本机 smoke，不动实现设计
> 起草：2026-09-27
> 关联：`docs/eval/langfuse-{intent,spec,plan,test-handoff}.md`、
> `pokemon_agent/trace/{langfuse_trace,langfuse_support}.py`、`docs/spec/trace/{SPEC,API}.md`

---

## 一、一句话意图

在不启动真实 Harness、不连接任何远程服务的前提下，用离线自动化测试证明 `LangfuseTrace`
实现与 spec 相符，再用本机 self-hosted Langfuse 做一次独立 smoke 证明端到端链路可用——
**测试通过也不改变任何默认行为**。

## 二、为什么现在做

1. plan P0–P3 代码已落（`langfuse_trace.py` / `langfuse_support.py`），但**零测试**：
   `tests/test_langfuse_trace.py` 尚不存在，P1–P3 全部标着"未测试"。
2. Langfuse 路径 touches 封套编码、树形血缘、分页读回、恢复分支 fallback 等一串
   最终一致性行为，没有离线测试兜底，任何后续改动都在盲改。
3. 真机 P6 验证（三层装配）排在 Langfuse 之后；先把 trace 后端可选性钉稳，
   才不会在真机验证里混入两个未验证变量。

## 三、本次改动是什么（与不是什么）

**是**：
- 实现审阅：交接口 10 条事实逐条对照代码，缺陷先修（修要写 CHANGELOG）再测；
- 新增 `tests/test_langfuse_trace.py`（fake client / fake observations API，零联网），
  覆盖面以交接口第二阶段清单为准；
- 按需小幅更新 `tests/test_trace_tool.py`、`tests/test_build.py`；
- 跑定向测试 + 全量 pytest + ruff + trace 自包含检查，记录真实数字；
- 本机 self-hosted Langfuse smoke：独立脚本直构 `LangfuseTrace`，写一条
  `handoff-<后缀>` 测试 run，flush 后限时等待 API 可读，核对封套还原、
  branch 父子与 Dashboard 树。

**不是**：
- 不是设计评审重开——spec 已锁定的封套、确定性 trace_id、延迟血缘、最终一致性
  口径不在本次改动范围内重议；
- 不是接入切换——`TraceTool.build()` 默认 backend 保持 `local`，测试全绿也不改默认。

## 四、硬边界（与交接口一致，违反即返工）

1. **不起真实链路**：不启动游戏 Harness、`check_harness`、PyBoy、ROM、真实模型。
2. **只连本机**：只连 `LANGFUSE_BASE_URL` 指向的 localhost/本机容器 self-hosted
   Langfuse v4；Langfuse Cloud 及一切远程服务禁连。
3. **单元测试零联网**：一律注入 fake SDK client / API。
4. **密钥零暴露**：不记录、打印、回显或提交 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`。
5. **不动架构**：不加 LocalTrace 双写、不建 outbox、不改 checkpoint 状态来源、
   不把 Langfuse 设为默认 backend。
6. **不提交代码**：改动留工作区，是否 commit 由项目所有者另行决定。
7. **服务不可用不阻塞**：smoke 明确报"未执行"，自动化测试照常全部完成。

## 五、成功标准

1. 交接口第一阶段 10 条审阅事实全部"相符"或"已修复并有 CHANGELOG 条目"；
2. `tests/test_langfuse_trace.py` 覆盖交接口第二阶段全部条目，定向 + 全量 pytest、
   ruff check / format、trace 自包含检查全绿（已有失败须与基线区分、注明是否触及本次改动）；
3. smoke 有明确结论：执行了（附 run_id/trace_id、observation 数、visibility 延迟、
   不写 `tracelog/` 的证据）或未执行（附原因）；等待设总超时，不无限等待；
4. 汇报含：改动文件清单 + 理由、精确命令与数字、问题与未验边界、
   四条红线（未连 Cloud / 未起 ROM / 未跑 Harness / 未提交）逐条确认。

## 六、参考

- 交接口（执行依据，逐条照办）：`docs/eval/langfuse-test-handoff.md`
- 设计与计划：`docs/eval/langfuse-spec.md`、`docs/eval/langfuse-plan.md`（P4 待执行）
- 上位意图：`docs/eval/langfuse-intent.md`（本文件不推翻其任何原则，只细化测试阶段）
