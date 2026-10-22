# intent —— trace 模块单元测试：按公开面重组、补缺口、迁入散落的 trace 行为测试

> 状态：**已确认**（2026-10-21，用户回复「其他都可以」，并指定 Langfuse 部分放到 trace 线最后一个阶段）。
> 范围：只做单元测试。本轮模块 = `pokemon_agent/trace/` 中 **除 Langfuse 外** 的部分（`LocalTrace`、`seq`、`Event`/`TracePort` 协议、`EventType`）。**Langfuse（`langfuse_trace.py`、`langfuse_support.py`、`tests/trace/langfuse/`）整体放到 trace 线最后一个阶段，本轮不碰、不起 Langfuse 相关测试。**
> 关联：`docs/test/memory-test-intent.md`、`docs/test/mcp-servers-test-intent.md`（同一套做法）；AGENTS.md 第三节第 4、5 条、第九节。

## 一、一句话意图

把 `pokemon_agent/trace/` 当作**可整体拷走的第三方库**来测：只经它的公开面说话——`TracePort`（`append` / `read_events` / `flush` / `shutdown`）的本地实现 `LocalTrace`、`Event` 协议、`next_seq()`、`new_event_uuid()`、`EventType`——用 `tmp_path` 钉住每个方法的后置条件、排序与筛选语义、残文件容忍和包边界。`LangfuseTrace` 是 `TracePort` 的第二个实现，**留到最后一个阶段**再按同一份契约补测；本轮把契约测试写成「换一个实现就能复用」的形状即可。同时把混在 `tests/trace/test_trace_store.py`、`tests/direct/trace/test_trace_seq.py` 里**实质在测 trace 本身**的用例迁出 `TraceTool`（项目门面）的壳，直接对着 `LocalTrace` 测。

## 二、为什么现在做

1. **现有测试文件名不副实**：`tests/trace/test_trace_store.py`（385 行、16 例）几乎每个用例都经 `TraceTool` + `FromHarnessToTraceToolAppendReq` 绕一圈。其中一半（`meta` 缺键被拒、`run_id` 不许调用方传、`count` 已废、`build` 工厂转发 `trace_root`）测的是 **direct 层门面**的契约，不是 trace 模块；另一半（一事件一文件、八字段、交集筛选）是 trace 的契约，却要先看懂门面的信封才读得懂。
2. **`LocalTrace` 没有被直接测过**：构造器、`new_event_uuid`、`flush` / `shutdown`、`append` 的 `started_at` / `ended_at` 缺省补值、非 ASCII 与嵌套 content 的往返、残文件与旧格式文件被跳过、`.tmp` 文件被忽略——这些全靠门面测试顺带碰到，或者根本没有。
3. **`next_seq` 与排序决胜**：`(ended_at, seq)` 的决胜键是 0928 事故（流序断言概率性炸）的修复，现在只有 `tests/direct/trace/test_trace_seq.py` 一个经 `TraceTool` 的用例守着，`next_seq` 本身的线程安全与严格递增没有直接测试。
4. **文档与代码已有漂移**：`store.py` 模块 docstring 写「七个字段」和 `(ts, uuid)`，`_Event` docstring 写「六个字段」，`tests/trace/test_trace_store.py` 顶部写「七字段」；实际封套是 **八个字段**（含 `seq`），排序键是 `(ended_at, seq)`。契约测试应当把正确的那一份钉死，旧说法留在注释里会误导读者。
5. **包边界没有机械守卫**：模块 docstring 反复强调「对 `pokemon_agent` 其余部分零 import」，但 `scripts/check_trace_self_contained.py` 不在 pytest 里，没人跑就没人知道。

## 三、是什么 / 不是什么

**是**：
- 按源码文件镜像的目录（见第五节），每个文件若干「一句话命名」的用例；
- 一个**契约文件**，用一个 `trace_factory` 夹具产出实现，本轮夹具只提供 `LocalTrace`，断言一组 `TracePort` 契约：返回本地 uuid、`(ended_at, seq)` 升序、`meta` 交集匹配且缺键不匹配、空 `meta` 等于不过滤、无匹配返回空列表、`isinstance(…, TracePort)`、`flush` / `shutdown` 可安全调用。Langfuse 阶段只需往夹具里加一个参数；
- 迁移：trace 行为的用例改成直接调 `LocalTrace`，不再经 `TraceTool`。

**不是**：
- 不测 `TraceTool`、`direct/trace/render.py`、`parse` 等 **direct 层门面**（`tests/direct/trace/` 其余文件原地保留，归 direct 模块那一轮）；
- **不碰 Langfuse**：`langfuse_trace.py`、`langfuse_support.py`、`tests/trace/langfuse/`、`tests/_fake_langfuse.py` 本轮一概不改不移；经 `TraceTool` 同时参数化两个后端的 `tests/direct/trace/test_trace_seq.py` 也**原样保留**（本轮另在 `tests/trace/` 写只针对 `LocalTrace` 的 seq 用例）；
- 不测 trace 事件的 `kind` / `type` 取值域（那是声明方的事，trace 不认识）；
- 不测排序质量以外的性能；不追覆盖率。

## 四、硬边界

1. 零联网、零真实模型、零模拟器；落盘一律 `tmp_path`，缺省根的用例用 `monkeypatch.chdir(tmp_path)`。
2. 不测私有成员（`_scan_events`、`_dir`、`_Event` 等）。可观察通道只有：公开返回值、`tmp_path` 下的文件、假 client 的调用记录。例外：`store.py` 的纯函数 `new_event_uuid`（模块 `__all__` 已导出）。
3. 文档化的前置条件用 `pytest.raises(AssertionError)` 钉住；**预期内的运行期情况**（残文件、旧格式文件）用返回值断言，不用 assert。
4. 一个用例只钉一件事，函数名是一句话；Arrange / Act / Assert 三段空行分开；不用 `MagicMock`，假件是手写小类。
5. 速度：整个 `tests/trace/` 默认 pytest 下 **≤ 3 秒**；不加 `slow`；不 sleep；需要「同刻」就直接传相同的 `ended_at`，需要「跨毫秒」就 monkeypatch `time.time`。
6. 测试文件名全仓唯一。
7. Langfuse 相关文件与共享夹具 `_fake_langfuse.py` 本轮不动。

## 五、目录与迁移（草案，spec 阶段逐文件核对）

```
tests/trace/
├── test_trace_port_contract.py          TracePort 契约，实现由夹具提供；本轮只有 LocalTrace（新建）
├── local/
│   ├── test_local_trace_append.py       一事件一文件、文件名=uuid、八字段不多不少、meta/content 为 JSON 字符串、
│   │                                    started_at/ended_at 缺省补值、非 ASCII 与嵌套往返、不可序列化 content 的行为（见第六节 T3）
│   ├── test_local_trace_read.py         交集匹配、缺键不匹配、空 meta、排序 (ended_at, seq)、同刻按 append 序、
│   │                                    残文件 / 旧格式 / .tmp 被跳过、读不动 meta 的文件不匹配任何条件、同根多 run 平铺
│   ├── test_local_trace_root.py         缺省根=启动目录下 tracelog/、str 与 Path 都收、根目录自动创建、flush/shutdown 空操作
│   └── test_new_event_uuid.py           v7 布局、跨毫秒字典序即时间序、同毫秒不撞名
├── test_trace_seq.py                    next_seq 严格递增、多线程下唯一；两个 LocalTrace 实例同刻账按进程 append 序决胜（新建，不经 TraceTool）
├── test_trace_event_protocol.py         `_Event` 满足 `Event` 协议的八字段对齐（机械守卫「三份定义靠人工同步」那一条）
├── test_trace_package_boundary.py       AST 扫描 pokemon_agent/trace/**：对 pokemon_agent.* 的 import 为零（新建，替代手跑脚本）
└── langfuse/                            本轮不动，留到最后阶段（test_langfuse_trace / test_langfuse_preflight / test_langfuse_seed）
```

**迁移表**：

| 现有用例 | 去向 |
|---|---|
| `test_trace_store.py` 的一事件一文件、八字段、JSON 字符串、交集筛选 / AND / 缺键不匹配 / 两个 run 平铺、uuid 即文件名、缺省根 | 改写成直接调 `LocalTrace`，迁入 `local/`；旧文件对应用例删除 |
| `test_trace_store.py` 的 `meta` 缺键被拒、空 source 被拒、调用方传 `run_id` 被拒、`count` 已废、`call` kind 与失败尝试独立成账、`build` 工厂转发 `trace_root` | **留在 direct 层**（`TraceTool` 门面契约）：本轮只把它们从 `tests/trace/` 移到 `tests/direct/trace/test_trace_tool_contract.py`，断言不改 |
| `tests/direct/trace/test_trace_seq.py` | 原样保留（同时参数化 local 与 langfuse，随 Langfuse 阶段再处理）；本轮在 `tests/trace/test_trace_seq.py` 另写 LocalTrace 版 |
| `tests/trace/langfuse/*`、`tests/_fake_langfuse.py` | 不动 |

## 六、缺陷与漂移嫌疑（读码得到，写 spec 时**不要钉成预期**；让执行方第一步用最小脚本复现并汇报，再由用户裁决）

- **T1** `LocalTrace._scan_events` 用 `except Exception: continue` 吞掉所有解析错误。意图是容忍残文件 / 旧格式，但 AGENTS.md 第八节写明「不许 `except Exception: pass`」，且会同时吞掉权限错误、磁盘 IO 错误等**预期外**的异常。是否收窄到 `pydantic.ValidationError` / `json.JSONDecodeError` / `UnicodeDecodeError` 待裁决。
- **T2** 文档漂移：`store.py` 模块 docstring（七字段、`(ts, uuid)`）、`datastore/event.py` 的 `_Event` docstring（六字段、`(ts, uuid)`）、`datastore/trace_event.py` 无关；`tests/trace/test_trace_store.py` 顶部（七字段）。AGENTS.md / CLAUDE.md 第九节表格也写「六个字段、`ts`」。属于只改注释 / 文档的修正。
- **T3** `append` 对不可 JSON 化的 `content`（如 `set`、自定义对象）的行为未在契约里说明：`json.dumps` 会抛 `TypeError`，且此时 uuid 已生成但文件未写——是否应在 docstring 里写明「失败时不落盘」。需要先复现确认没有留下半个文件。
- **T4** `append` 不校验 `started_at <= ended_at`。契约没要求，但 `read_events` 按 `ended_at` 排序、下游算延迟用差值，反向区间会得到负时长。是否加 precondition assert 待裁决（若加，属于调用方契约，不是输入校验）。
- **T5** `LocalTrace.append` 接受缺 `run_id` / `branch` 的 `meta`，而 `TracePort.append` 的前置条件写「需要它们的实现就地 assert」，`LangfuseTrace` 确实 assert。两个实现对同一契约的执行不一致——契约文本说「需要的实现」所以不算违约，但参数化契约测试要对此显式分开。

## 七、已确认的决定

1. **范围**：本轮 = `trace/` 除 Langfuse 外的部分；Langfuse 整体放到 trace 线最后一个阶段，单独走 intent / spec / plan。`tests/direct/trace/` 其余文件不动，留给 direct 那一轮。
2. **门面用例**：`test_trace_store.py` 里测 `TraceTool` 的 7 个用例只做搬家（移到 `tests/direct/trace/test_trace_tool_contract.py`），断言不改。
3. **T3 / T4**：T3 先复现，确认失败时不落半个文件后把行为写进 `append` 的 docstring；T4 不加 assert，仅记录。
4. **T1**：收窄 `_scan_events` 的异常范围，作为第一个修复检查点（先写跳过用例钉住行为，再改生产代码）。
5. **包边界测试**：以 AST 扫描进 pytest；`scripts/check_trace_self_contained.py` 保持不动。
6. **T2**：在最后一个检查点修注释与 AGENTS.md / CLAUDE.md 第九节（字段数、排序键），两份保持逐字一致；已获准改这两份文件。

## 八、成功的样子

- `tests/trace/` 读完就知道：`TracePort` 承诺什么、`LocalTrace` 落盘什么、读回什么、怎么排序、怎么容忍坏文件；
- `TracePort` 契约写成实现可替换的形状，Langfuse 阶段只需往夹具里加一个实现；
- `tests/trace/` 里不再出现 `TraceTool` 和 `FromHarnessToTraceToolAppendReq`；
- trace 包「零 import 其余部分」由测试守住，而不是靠人跑脚本；
- 默认 pytest 下 `tests/trace/` ≤ 3 秒，全量用例数只增不减（迁移前后逐文件核对收集数）。
