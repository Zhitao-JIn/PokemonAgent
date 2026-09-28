# intent —— Langfuse 接入：让真实 run 可观测、可定位、可关联评测

> 流程位置：**langfuse-intent.md** → langfuse-spec.md → langfuse-plan.md → implementation
> 状态：**讨论稿**；本文件只定义意图与边界，不授权连接外部服务或上传现有运行数据
> 起草：2026-09-27
> 关联：`docs/eval/{intent,spec,plan}.md`、`docs/spec/trace/SPEC.md`、`docs/spec/evals/SPEC.md`

---

## 一、一句话意图

把每次真实 Harness run 的关键执行过程，以可追溯的层级视图呈现在 Langfuse，方便定位模型调用、任务步骤、耗时与失败；目标是使用本机自托管 Langfuse 作为权威 trace 后端，并可选地把观测发送到线上 Langfuse。

## 二、为什么现在讨论

项目已有结构化 trace、分层的 run / episode / task 控制流、trace 解析与离线 eval 框架。目前事件落在本地 JSON 文件中，逐次查看跨层决策、模型调用和耗时仍需要人工拼接账本；接入本机自托管 Langfuse 的目标，是让成熟的第三方服务成为本地持久化与观测后端。后续接入 Inspect AI 后，也需要把评测样本、运行过程和评分关联起来。

Langfuse 可提供模型调用与应用执行的观测界面；官方当前 Python SDK 基于 OpenTelemetry，支持自定义 observation、generation 及评测相关能力。接入设计应使用当前 SDK/API，不沿用旧版 SDK 示例。参考：[Langfuse Python/JS SDK 概览](https://langfuse.com/docs/observability/sdk/overview)、[Python SDK instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation)。

## 三、角色分工

| 组件 | 回答的问题 | 数据/职责 |
|---|---|---|
| 本机自托管 Langfuse | 这次 run 实际发生了什么？ | 本地权威 trace 存储与观测 Dashboard；应用经 Langfuse SDK 写入，trace 适配层提供项目所需的读接口 |
| 线上 Langfuse | 运行过程在哪一步、哪次模型调用出了问题？ | 暂不接入；将来若需要远端观测，再单独设计传输 / 同步 |
| Inspect AI（后续接入） | 固定评测样本上表现如何？ | 评测执行、样本编排与 scorer / 结果汇总的候选归属；不在本 intent 内设计 |
| `evals/e2e` | 本项目现有判据如何从 trace 得出结果？ | 现有机械判据与报告；不因 Langfuse 接入而迁移或改变判定口径 |

Langfuse 的分数或 judge 输出不能覆盖机械判据，也不能成为 checkpoint 恢复的状态来源。`checkpoint_save` / `checkpoint_restore` 仍可供 trace 读侧拼接分支历史；恢复本身只依赖 checkpoint 存档。Inspect AI 与 Langfuse 的具体数据交换方式留待后续设计。

## 四、期望的使用体验

开发者能从一条 run 的视图向下查看 episode、task、step 和关键模型调用，并能从 Langfuse observation 的 metadata 找到对应的本地事件 UUID 与 checkpoint。模型、prompt/链路、token 用量（模型有提供时）、耗时、重试和失败应能按 run 聚合或切片。

测评接入后，Langfuse 中的观测应能携带稳定的 `sample_id`、评测批次标识及本地 `run_id`，让开发者从一个失败样本打开运行细节；评测结果仍由本项目或后续 Inspect AI 中版本化的 scorer 规则给出。

## 五、核心原则与边界

1. **本机权威，线上暂缓**：本机 Docker Compose 自托管 Langfuse 是目标中的持久化 trace 后端，并提供本机 Dashboard。当前阶段只连接本机服务；线上 Langfuse 暂不接入。Python SDK 是本机客户端，需配置指向本地服务；SDK 的后台队列不视为磁盘持久化。
2. **按 Port 接入**：Harness 继续只通过现有 `TraceToolPort` 读写；Langfuse observation 与项目 `TraceEvent` 的转换由 trace 适配实现。Langfuse SDK 类型不得渗入 `brain`、`world`、`memory` 或 harness 的公共契约。
3. **Langfuse 是本机唯一 trace 存储**：`LangfuseTrace` 直接使用 SDK 写入本机自托管 Langfuse，并用 Observations API 读回；不与 `LocalTrace` 双写，不建立本地事件副本。Langfuse 服务端承担持久化，SDK 异步发送队列不等于本地磁盘 outbox。
4. **接受最终一致性并定义故障边界**：append 返回不保证 API 立即可查。SDK `flush()` 只等待事件发送，服务端 ingestion 与查询模型仍可能有延迟。服务不可用时 SDK 可重试，但强制退出可能丢失尚未发送的内存队列；事件缺失不影响 checkpoint 状态恢复。
5. **区分事实与解释**：机械判据、模型 judge、人工 rubric 与 Langfuse 上的辅助评分分别标明来源和版本，不能混成一个“成功”字段。
6. **先最小数据、再扩展**：默认不写入 ROM、模拟器存档、截图、完整记忆库或密钥。模型输入/输出可能含 prompt、游戏画面转写或记忆正文，是否记录到本机必须先明确；未来若接线上实例，再另定外发策略。
7. **一个 run 一条 Langfuse trace**：同一个 `run_id`（包括该 run 恢复出的所有 `branch`）使用同一个确定性 Langfuse `trace_id`；不同 `run_id` 使用不同 trace。`branch`、`episode_id`、`task_id`、`step` 和本地事件 UUID 放在 observation metadata 用于切片与回链，不能只靠这些标签代替层级关系。Langfuse observation ID 遵循 SDK / OTel 生成规则，不冒充本地事件 UUID。
8. **checkpoint 状态恢复不依赖 trace 查询**：图状态、世界、记忆及恢复分支由 checkpoint 清单和存档决定。`checkpoint_save` / `checkpoint_restore` 在 trace 中的关联只用于读侧血缘拼接与分支视图。恢复分支的来源 checkpoint 与父 branch 身份以 checkpoint manifest 的 `checkpoint_id` / `branch` 为准；适配层在 Langfuse 中查找对应的 `checkpoint_save` observation 并建立父子关系。该查询或观测写入失败不得阻止 checkpoint 状态恢复。
9. **父子链表达因果与包含**：run root → branch → episode → task → step / operation。真实模型调用用 generation observation，作为发起该调用的 step / operation 的子项；按键、感知、记忆读写、验证等瞬时事件作为最近所属 step/task 下的 event observation。调用来源、模型、结果等字段放在 observation 上，不为同一工作重复造无意义层级。
10. **跨 run 只关联，不串成树**：不同 `run_id` 的 trace 不互相设父子关系；同一 `sample_id`、评测批次或模型版本可以作为 metadata 做查询关联，但不把多次独立执行伪装成一个 trace。`session_id` 是否用于批次聚合留待 spec 决定。
11. **观测副作用可控**：明确同步/异步、flush 时机、超时与缓冲上限；SDK 不能在 Harness 关键路径上无限等待或无限堆积。

## 六、建议纳入的观测范围

先覆盖能回答“模型做了什么、环境如何响应、失败发生在哪”的最小集合：

- run 根观测，以及 episode / task 层级和结束状态；
- branch 与恢复分叉：同一个 `run_id` 保持同一个 Langfuse `trace_id`；恢复出的 branch 是来源 checkpoint observation 下的新 branch span，后续 episode/task/step 挂在该 branch 子树；来源 checkpoint 与父 branch 的标识从 checkpoint 清单读取，再经本地事件 UUID 等关联键映射到 Langfuse observation ID；
- 各模型链路的 generation：模型名、输入/输出（遵循后续批准的数据策略）、耗时、token/成本元数据（可得时）、重试与错误；
- task 的感知摘要、决策/宏调用、执行结果与验证结论之间的关联；
- 项目 trace 事件 UUID 与 Langfuse observation metadata 的关联字段；
- 可选的评测上下文：数据集版本、`sample_id`、评测批次 ID、scorer 结果引用。

不默认把所有领域事件正文都写入 Langfuse。哪些事件只作为 span/event metadata、哪些输入输出可记录、帧图是否需要受控抽样，属于数据策略决策，不在 intent 阶段拍板。

## 七、成功标准

1. 一次 run 的观测由本机 Langfuse 服务持久化并可在本机 Dashboard 查看；本阶段不连接线上 Langfuse。
2. 现有 `TraceToolPort` 读写语义有 Langfuse 适配实现：追加后能读回、按 meta 等值筛选、按 `(ts, uuid)` 排序；checkpoint 恢复不依赖 Langfuse 的血缘查询。
3. 每个 `run_id` 恰有一个 Langfuse trace；同 run 的不同 branch 都留在此 trace 内并形成父子树：恢复出的 branch 挂在 checkpoint 清单所指来源点对应的 `checkpoint_save` observation 下，不把恢复后的事件接到父 branch 的末尾；不同 `run_id` 不混在同一 trace。可用本地事件 UUID 等关联字段找到对应 observation。即使 Langfuse 不可用或映射暂时缺失，checkpoint 状态恢复仍按清单和存档完成。
4. 观测可帮助定位至少三类问题：模型调用失败/重试、task 行为或验证失败、某层耗时异常。
5. 观测记录足以区分模型 judge、机械 scorer、人工评分和平台自身评估；评分来源、版本与样本关联明确。
6. 本阶段所有 Langfuse 观测只发往本机自托管服务；不会连接线上 Langfuse 或把观测导出到外部。
7. 后续 Inspect AI 试点能关联同一 `sample_id` 与 run，而不要求 Langfuse 接管评测执行或重写本项目判据。

## 八、本阶段不做

- 本 intent 确认本机自托管 Langfuse 为目标后端，但不在 spec 和契约验证前直接删除 `TracePort` / `LocalTrace`；
- 不把 Langfuse SDK 类型暴露给 `brain`、`world`、`memory` 或 harness 的公共接口；
- 不迁移当前 `evals/e2e` 的样本、机械判据或报告；不在本文件定义 Inspect AI 集成；
- 不自动上传完整 prompt、completion、截图或记忆；不在没有数据策略决定前连接 Langfuse Cloud；
- 不依赖 Langfuse UI 中的数据来判断游戏是否达成目标；
- 不在本阶段做在线告警、仪表盘定制、CI 门禁或成本配额系统。

## 九、spec 已定方向与实施前的运行配置

**一致性选择已定：不要求立即可读。** `append()` 将 observation 交给 SDK 队列后返回；`read_events()` 查 Langfuse Observations API，允许刚写事件因 ingestion 延迟暂时缺席。读侧仍按 `(ts, uuid)` 排序并精确筛选可见事件；完整观测通过运行边界 flush 后等待 Langfuse 服务端处理再查询。checkpoint 恢复永远不等待 trace 查询，也不因 lineage 暂缺失败。

| 编号 | 问题 | 讨论点 |
|---|---|---|
| L1 | 本机部署 | **已定**：本机 Docker Compose 自托管作为权威存储。需在 plan 阶段核对当前 Langfuse v4 Compose 资源与持久卷配置。 |
| L2 | 数据外发策略 | **本阶段已定**：项目现有 trace 的完整 `content`（包括其中已有的模型 I/O、决策与记忆正文）只发送到本机自托管服务；不新增截图、ROM、模拟器状态或整库记忆采集。线上外发需另行批准。 |
| L3 | 线上同步 | **暂缓**：当前阶段不接线上 Langfuse；如未来需要，再决定双写、定期导入或手动迁移。 |
| L4 | 层级映射 | **方向已定**：trace=root run；branch / episode / task / step(operation)=父子 span；瞬时领域事件用最近作用域下的 event；模型调用用 generation。具体 `TraceKind` 到 observation 的映射进 spec。 |
| L5 | 模型调用采集 | 由当前 provider/tool 层生成 generation，还是由本地 `model_call` trace 转出？如何避免重复 instrumentation？ |
| L6 | ID 对齐 | **方向已定**：`run_id` 确定性映射为 trace ID；本地 UUID、branch、episode、task、step 放 metadata；恢复 branch 作为同 trace 下来源 `checkpoint_save` observation 的子树；父 checkpoint / branch 的本地身份取自 checkpoint 清单，adapter 通过稳定本地 ID 映射 Langfuse parent observation。映射算法与 Langfuse ID 索引的持久化方式进 spec，且不得成为恢复前置条件。 |
| L7 | 评分归属 | 机械判据与 Inspect AI scorer 在哪计算；Langfuse 是否只展示/存储评分，或也参与其 Dataset/Experiments 能力？ |
| L8 | 凭据与开关 | 本机连接配置、默认开关、服务不可用时的行为、SDK flush 与关闭时机。 |
| L9 | 本机持久性 | Langfuse Compose 数据卷、备份 / 恢复策略；**不设置本地 outbox**，服务端是唯一 trace 持久层。 |
| L10 | 最终一致性 | **已定**：不要求 append 后立即可读；API 查询可暂时漏掉尚未完成 ingestion 的 observations，完整查询在 flush 并等待服务端处理后进行。 |

建议最小试点：使用本机自托管 Langfuse v4 验证一个 run 的层级、恢复 branch 分叉树、分页读回、meta 筛选与事件 UUID 回链。只使用本机 Dashboard；线上同步不在本阶段。试点不作为正式评测结果，也不改变现有测评基线口径。

## 十、实现设计的官方参考

- [Langfuse SDK 概览](https://langfuse.com/docs/observability/sdk/overview)：当前 Python SDK 基于 OpenTelemetry；Cloud 与 self-hosted 使用相同 SDK，凭据和 base URL 不同。
- [Instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation)：observation、generation、trace 与 OpenTelemetry span 的映射及 ID 约定。
- [Trace IDs & Distributed Tracing](https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing)：确定性 trace ID、显式 trace context 与 parent span context。
- [Data Model](https://langfuse.com/docs/observability/data-model)：一个 trace 聚合同一 `trace_id` 下 observations；物理父子关系由 observation 关系表达。
- [Event queuing / batching](https://langfuse.com/docs/observability/features/queuing-batching)：SDK 后台排队、批量发送及 flush / shutdown 行为。
- [Query data via SDKs](https://langfuse.com/docs/api-and-data-platform/features/query-via-sdk)：Observations API 的查询能力与新数据可查询延迟；用于评估写后即读门槛。
- [Experiments via SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)：Langfuse 自带数据集实验入口；需与 Inspect AI 的评测职责明确分工，避免重复维护 runner/scorer。
- [Experiments via OpenTelemetry](https://langfuse.com/docs/evaluation/experiments/experiments-via-opentelemetry)：若未来评测 runner 负责执行，可通过 span 属性把实验项关联到 Langfuse。

以上链接反映起草时查阅的官方文档；SDK 主版本、兼容性和 API 细节应在编写 spec / plan 时重新核实。
