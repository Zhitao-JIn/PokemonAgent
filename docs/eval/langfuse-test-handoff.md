# LangfuseTrace 测试交接

> 状态：交给测试执行者；实现见 `pokemon_agent/trace/langfuse_trace.py` 与 `pokemon_agent/trace/langfuse_support.py`
> 设计依据：[`langfuse-spec.md`](./langfuse-spec.md)、[`langfuse-plan.md`](./langfuse-plan.md)

## 交接任务

请在现有实现基础上完成 LangfuseTrace 的自动化测试和本机 self-hosted smoke。先检查工作区和相关实现，不要重置或覆盖用户已有改动。测试结束后汇报真实命令、通过/失败数量、失败摘要、是否连接本机服务以及改动文件；不要提交代码，除非项目所有者另行要求。

## 重要边界

- **禁止启动真实游戏 Harness、`check_harness`、PyBoy、ROM 或真实模型。** 本交接只测 trace adapter、tool/backend 装配与独立 Langfuse 服务 smoke。
- 只连接配置为 `LANGFUSE_BASE_URL` 的本机自托管 Langfuse。不得连接 Langfuse Cloud 或其他远程服务。
- 自动化单元测试不得联网；使用注入的 fake SDK client/API。
- 不记录、打印或提交 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`。诊断中不得回显环境变量。
- 不添加 LocalTrace 双写、不建立 outbox、不改变 checkpoint 状态来源。
- 不把 Langfuse backend 改成默认值；默认仍是 `local`。
- 若本机服务或凭据不可用，明确报告 smoke 未执行，继续完成全部 fake-client 自动化测试。

## 第一阶段：实现审阅

检查以下事实是否与实现相符；发现缺陷先修复并写 CHANGELOG，再跑测试：

1. `TracePort` 两个实现 `LocalTrace` / `LangfuseTrace` 和装饰器 `LiveFeedTrace` 均有 `append`、`read_events`、`flush`、`shutdown`。
2. `TraceTool.build()` 默认仍构造 LocalTrace；显式 `backend="langfuse"` 时使用 LangfuseTrace；未知 backend 报错；Langfuse 模式不会写出本地 trace JSON。
3. `build_real(trace_backend=...)` 将 backend 选择传给 TraceTool 工厂。
4. `LangfuseTrace` 不 import `pokemon_agent` 其他模块，不把 checkpoint 查询当作恢复状态前置条件。
5. 写入事件封套的 `uuid/kind/type/ts/meta/content` 可无损解码；返回 ID 是本地事件 UUID，而非 Langfuse observation ID。
6. 检查树形语义：run root → branch → episode → task → step → 操作 observations；`model_call` 为 generation；错误事件符合预定 Langfuse 类型/级别。
7. 检查 task/episode/run 边界账与各层 scope 节点的关系，防止 scope 节点被覆盖成普通事件或操作账误挂父节点。
8. 检查恢复分支：根据同一 run 的 checkpoint_id 找到 checkpoint_save observation 并建子 branch；保存账暂不可见时走 run root fallback 并保留 lineage_pending。调用延迟补建时，不应假称已有 Langfuse observations 已被重新挂接。
9. 检查观察查询 API 的字段选择、时段边界、分页 cursor 终止、响应字段形状与错误传播。
10. 核对 `docs/eval/langfuse-spec.md` 和 `docs/spec/trace/{SPEC,API}.md` 是否准确描述代码，尤其是延迟血缘、meta 字段和 `TracePort` 生命周期方法。

注意：实现使用 `event_meta` 等 Langfuse observation metadata 和 output 封套。按照已锁定的 `langfuse>=4.7,<5` 官方 SDK 实际类型验证 API 参数；不要凭 v3/v4 旧 API 名称推测。

## 第二阶段：新增离线自动化测试

新增 `tests/trace/langfuse/test_langfuse_trace.py`，通过注入 fake client 和 fake observations API 测试，不要求服务或密钥。所有新测试遵守仓库 `AGENTS.md` 的 Arrange / Act / Assert 结构、完整类型注解和命名规范。

至少覆盖：

- LangfuseTrace 结构满足 TracePort；确定性 trace ID、run_id/branch 盖章、拒绝调用方自带保留键。
- 普通事件封套写入及 read decode roundtrip；Unicode、嵌套对象、空值、布尔值和 metadata/content 类型保真。
- append 返回本地 UUID，不返回 SDK observation ID；事件时间排序 `(ts, uuid)`。
- `model_call` generation 类型、模型名/token usage 提取；错误账类型与 ERROR level/status。
- 显式 trace_context、parent_span_id；run/branch/episode/task/step scope 的真实父子 ID 与同 step 多账复用。
- `read_events` 精确 AND meta 过滤、未知 observation 跳过、查询错误传播、无结果返回空列表。
- API 多页 cursor；无 cursor、重复 cursor、空 data、到达尾页等退出场景；`trace_id` / 时间边界始终传入。
- 同 run checkpoint save/restore 的 branch 父节点；缺少父 checkpoint 时 fallback；lookup API 抛错时恢复账仍按设计处理；后续 reconcile 的行为、元数据和返回数。
- SDK flush/shutdown 委托；`run_end` / `run_error` 触发 flush；调用 flush/shutdown 的失败按契约记录或传播。
- `TraceTool.build()` local 默认兼容、Langfuse 显式选择、未知 backend、Langfuse 与 trace_root 冲突、缺失环境配置时报清晰错误。
- LocalTrace 现有行为继续工作；TracePort 生命周期新方法为空操作。
- Langfuse client 初始化只在选择该 backend 后发生；默认 local 不要求 Langfuse 配置/连接。

必要时更新 `tests/direct/trace/test_trace_tool.py`、`tests/assembly/test_build.py`；不要为了测试触发模型或 ROM。

## 第三阶段：运行自动化验证

按顺序运行并记录实际输出：

```powershell
pytest tests/trace/langfuse/test_langfuse_trace.py tests/direct/trace/test_trace_tool.py tests/assembly/test_build.py
pytest
ruff check .
ruff format --check .
python scripts/check_trace_self_contained.py
```

若项目环境/工具不存在，不要擅自换全局环境安装；报告缺少什么及可执行的部分。若全量已有失败，比较本次改动前基线或检查失败是否触及本次改动，并明确区分。

## 第四阶段：本机 self-hosted smoke（仅服务，不启动 Harness）

执行前确认 `LANGFUSE_BASE_URL` 是 localhost/127.0.0.1/本机容器服务地址，Langfuse self-hosted v4 正在运行，并且当前 shell 已安全配置公私钥。不要输出密钥。

用独立的小脚本或 Python REPL 直接构造 `LangfuseTrace(run_id="handoff-<随机后缀>")`，不调用 `build_real()`，不导入/构造 PyBoy、BrainTool 或真实模型。写入至少这些数据：

1. `run_start`；
2. `episode_start`、`task_start`；
3. 同一 task/step 的两个不同操作事件；
4. 一条 `model_call` generation（只用 synthetic input/output 和安全的假 token 数）；
5. `checkpoint_save` 与关联 `checkpoint_restore`（新 branch）；
6. `run_end`，执行 `flush()`，按有限退避等待 Observations API 可读，最后 `shutdown()`。

检查：

- `read_events()` 能还原本地封套，筛选 `run_id` / `branch` / `task_id` 正确，顺序按 `(ts, uuid)`；
- Dashboard/API 的同一 run trace 有预期 observation 数与 span/generation 类型；
- 普通链路与恢复 branch 的 parent observation ID 符合规格，checkpoint_restore 后续事件属于新 branch；
- 没有事件写入本地 `tracelog/` JSON（执行前后对比专用临时目录或显式确认不创建）；
- SDK flush 后查询延迟可以接受，记录实际等待时间。不要无限等待；设定总超时（例如 60 秒），到期报告 eventual consistency 尚未验证。

Smoke 写入的是一条独立测试 run；记录生成的 run_id/trace_id 和 Langfuse UI 链接即可，不要分享密钥或生产 run 数据。

## 完成标准与汇报

交接完成时提供：

1. 修改文件清单及每项改动理由；
2. 定向测试、全量 pytest、ruff、自包含检查的命令和精确结果；
3. 本机 smoke 是否执行，Langfuse server 版本、写入/读取结果、可见性延迟和 Dashboard 检查结果；
4. 遇到的问题、修复及尚未验证的边界；
5. 确认未连接 Cloud、未启动 ROM/PyBoy/真实模型、未运行真实 Harness、未提交代码。

不要因测试通过就把 Langfuse 设为默认 backend。是否切换默认后端需要项目所有者另行决定。
