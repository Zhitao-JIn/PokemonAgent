# spec —— Graphiti 元数据检索与时序关系图探针

> 状态：设计稿，待实施；2026-10-20。
> 本次只定义探针，不安装服务、不迁移生产记忆、不改现有 MCP 或正在重采的版本。
> 依据：`pokemon_agent/memory/ports.py`、`docs/brain_scope/spec.md`、
> `docs/brain_planning/spec.md`、`docs/mcp/memory-admin-spec.md`。

## 1. 要回答的问题

验证开源 Graphiti 是否能作为统一 memory 服务的底座：原始记忆包含正文、向量和元数据，
不同记忆类型通过元数据区分；在相同底座上维护可追溯、带有效时间的实体关系图。
查询与三处存储触发位置可以继续由现有 harness 调度，不要求一并更换 plan/decompose。

探针必须给出四个独立结论：

1. 原始记忆能否无损存取，并按正文做语义召回。
2. 元数据条件能否在截断结果之前生效，严格排除范围外记录。
3. 图能否表达变化、追溯原始记忆，并遵守相同的来源范围约束。
4. 经 MCP 调用、重启、快照和恢复后，上述能力能否保持。

“框架允许扩展”不等于原生实现已经通过；搜索成功也不等于成功检索了原始记录。

## 2. 约束与非目标

- 不更新模型权重，不起游戏模拟器，不运行新一轮游戏 eval，不读取真实记忆或密钥正文。
- 不修改 brain scope、状态表或现有 Port；实验接口与生产接口分开。
- 存储类型合并是本探针假设，不在此文修改现有按 kind 分目录的实现。
- memory 继续是存储与索引模块；实体抽取等语义计算属于实验性的处理/适配层。
  生产落地前另出设计，不能把 Graphiti 的 LLM 处理静默塞进现有 MemoryStorePort。
- 图是原始记录的派生视图；模型抽取结果不得覆盖 harness 的来源章、成败或验收结果。
- 本探针不验证自主多轮检索 agent 的规划能力，也不宣称游戏效果优于现状。

## 3. 固定版本与证据分组

优先验证一个确定的 Graphiti release 与 Neo4j 后端；实施时填写准确版本，禁止依赖浮动 main。
若某能力仅在另一个后端或提交存在，为它建立独立 profile，不能把多套结果拼成一套通过。

| profile | 含义 | 允许的变化 |
|---|---|---|
| native | 开源原生完整接口 | SearchConfig、SearchFilters、recipes、自定义类型、公开 CRUD 等正式扩展点 |
| adapted | 在相同底座上的候选适配 | 显式属性盖章、索引、参数化查询、自定义过滤/记录向量路径；逐项记录代码和代价 |
| platform | 可选 Zep 对照 | 单独凭据、SDK、文档与结果；不计入开源版验收 |

native 必须检查高级接口，不限于 `search()` 或参考 MCP 默认工具。
若原生数据模型不能覆盖正文向量检索，记录 unsupported；不得偷偷把 adapted 结果记入 native。
native 缺项后可以继续其他测试，便于知道适配到底缺多少。

`manifest.json` 固定：探针提交、Graphiti 版本/提交与包哈希、依赖锁、Python 版本、
数据库版本与镜像 digest、schema/索引、配置、fixture 与查询哈希、LLM/embedding/reranker
型号和维数、prompt 哈希、profile、随机种子、超时/重试与费用预算、文档 URL 和查阅日期。
不保存 API key 或完整进程环境；模型后端不能固定快照时注明限制。

## 4. 实验契约

实施时先声明本探针的 Pydantic 输入/输出模型和注入的 Protocol，再实现适配器。
以下是实验形状，不是新增生产 Req，也不直接等同于 harness 的 recall hints。

```text
ProbeRecord:
  record_id: str
  metadata: dict[str, str]
  payload: JSON value
  text: str

ProbeQuery:
  query_id: str
  mode: filter | semantic | graph
  query: str
  conditions: dict[str, str]
  limit: int | null
  as_of: datetime | null

ProbeResult:
  records: list[原始记录及分数]
  facts: list[关系、有效区间、source_record_ids]
  timings: dict[str, float]
  backend_request_ref: str
```

元数据至少覆盖 `memory_type`、`run_id`、`branch`、`goal_id`、`episode_id`、`entry_id`、
`task_id`、`step`、`termination`；值是字符串，保持与现有存储接口一致。
不适用字段的缺失和空串必须区分。`memory_type` 是实验映射字段，不要求生产调用方传 kind。
元数据由适配层确定性写入，不让 LLM 从正文猜测这些身份字段。

纯 filter 对条件取 AND-of-equalities；空条件表示全体记录，缺键不匹配，空串只匹配空串。
semantic 的 query 非空、limit 为正；先限制候选，再排序截断。
纯 filter 的 query 为空，limit=null 必须返回完整集合或透明读完分页，不得隐藏召回上限。
text 为空的记录仍可点查/filter，但不参与原始正文语义召回。

每个查询独立给出 allowed_record_ids、required_record_ids 和 forbidden_record_ids。
精确过滤用独立 fixture 求交集生成 oracle，不能调用候选后端本身生成预期答案。
语义等价与关系时间的参考由人工可读 fixture 明确给出，不从候选输出反推。

## 5. 数据集：40 条小型确定性记录

fixture 用 `probe:` 前缀 ID，写入独占临时数据库/namespace，禁止复用游戏服务的存储根。
具体文本、元数据与预期集合随实施保存为 JSONL；类别数量必须与 manifest 对账。

| 类别 | 条数 | 内容 |
|---|---:|---|
| scope 镜像 | 16 | 相同/近似正文，交叉分布在 act/task/episode/run、两 run、两 L1 goal、两 episode 与不同执行 task |
| 元数据边界 | 8 | 缺键、空串、中文、引号、不同大小写、字符串 1/01/10、无匹配组合 |
| 时序来源 | 6 | 玩家位置 A→B、队伍受伤→治疗、同一存档恢复后的另一分支；事件时间与写入顺序刻意不同 |
| 高相关干扰 | 8 | 与查询完全同词但 scope 不合法，或和合法记录共享实体，制造排序/图遍历诱饵 |
| 空检索正文 | 2 | text 为空但 metadata/payload 有效，其中一条 payload 含嵌套数组和图片占位字符串 |

scope 镜像中显式包含：不同 run 使用同一个 goal_id 字面值；同 run 的不同 goal 使用同一目标文本；
同 episode、同 entry 的多次 task 执行。不能把文本相同当作身份相同。
至少四条记录共享中性名称“经历记录”，仅正文语义不同，防止名称 embedding 冒充正文召回。
原始 payload 与 text 存取后按规范化 JSON/UTF-8 指纹检查，不接受返回摘要代替原文。

## 6. 检查矩阵

### P0：启动、版本与接口能力

固定版本后建立 capability 表，列出公开写入/点查/完整枚举/语义搜索/图搜索/删除/备份恢复接口。
为每项记录真实函数签名、所选 backend、配置与已知限制；区分开源文档和 Zep SDK 文档。
缺能力显式记录 unsupported，缺环境记录 blocked，二者均不得冒充零结果通过。

### P1：无损写入与读取

写入全部 40 条，逐 ID 读回 metadata、payload、text；测试批量读、缺失 ID、进程重启后读回。
后端生成 UUID 时保存 record_id↔UUID 映射，快照覆盖该映射；不能从正文解析身份代替元数据。
探针外观对同 record_id、同指纹重试应幂等，内容冲突明确失败；上游额外产生的重复项单列。
原始数据确认持久化与派生图/向量可检索分别记录；异步处理必须等待明确完成屏障。

### P2：精确元数据过滤与空结果

至少 24 个查询：单字段、两/三/四字段组合、空条件、缺键、空串、未见值、冲突组合、
中文/引号值、大小写、1 与 01 等字符串等值；每个查询对照 oracle 检查完整集合。
限制值 limit=1/3/100 与 null 分别验证截断和完整枚举，返回数不能超过声明上限。
三个负例包含不存在的 scope 且查询正文与范围外记录完全相同，必须返回空集合。
参数不能靠拼 Cypher 字符串实现；存入引号值不能改变条件含义。

### P3：原始正文语义检索与过滤顺序

固定 12 个语义查询，其中至少 6 个使用同义改写，包含门/入口、治疗/恢复、受阻/绕路。
分别执行向量单路、全文单路、混合检索；混合路径另检查实际启用的 RRF/重排配置。
每个查询保存底层对象类型、向量对应的文本与原始 record_id；相关实体或事实命中单列为图检索，
不能拿它代替“原始正文向量召回”通过。若映射原始记忆为自定义 Entity，仍须证明嵌入的是检索正文。
在 limit=1/3 下让范围外诱饵占据全局高分位；查询仍应从合法候选中取够结果。
禁止全局 top-k 后删掉范围外项充当先过滤；定向补拉也须证明不会因扫描上限漏掉合法项。
同时保存生成的查询/后端调用证据；仅检查最终结果无泄漏不能证明过滤发生在排序之前。

### P4：生产 scope 回放

本阶段只验证存储与适配，不把全量直属历史改成相似度 top-k：

| 调用 | 必须保留的范围语义 |
|---|---|
| L0 plan/judge | 当前 run 全部 EpisodeMemory；其他 run 的 RunMemory 仅作背景索引 |
| L1 decompose/judge | 当前 episode 全部 TaskMemory；背景只来自同 run、同 L1 goal 的其他 episode |
| L2 choose/judge | 当前执行 task 的全部 ActMemory；背景为同 episode、同目标文本的此前 TaskMemory |

详情与背景分开构造、记录 ID 和渲染角色，不能先混为一个候选池。
同层生成器与 judge 复用同一份上下文；映射现有 recall hints 时保存展开后的条件与集合。
branch 不默认全等过滤：恢复后可见祖先前缀与当前分支后缀，兄弟分支和恢复点后的祖先事件不可见。
探针用显式允许 ID 集合表达该血缘规则；生产血缘规则不在此修改。
无须模型判断的 ID、类型、时间与血缘条件必须由适配层保证。

### P5：图关系、时序与来源边界

先以公开 CRUD/三元组接口写入确定的实体关系，隔离检索能力与 LLM 抽取误差。
随后再用最多 6 条时序来源记录跑真实抽取，抽取正确率单列，不覆盖确定性图测试的结果。
对 A→B、受伤→治疗，分别在变更前、变更后和事件边界查询；使用显式有效区间 [start,end)。
逆序写入测试依据事件时间而非 created_at 回答，保留旧事实来源，不把失效当作物理删除。
在两个分支写互斥事实，查询相同 as_of 仍须保持分支隔离；墙钟时间不能代替执行血缘。
事实命中必须给出合法来源 ID；若实体/摘要融合了其他 scope 的来源，不能仅凭“至少一条合法来源”放行。
增加跨 scope 的两跳捷径，确认 BFS、中间节点、community 摘要与排序特征不引入范围外信息。
若无法证明聚合物的来源隔离，将该类聚合物标为不可用于受限上下文，不能默默返回。
来源删除后检查孤立关系、多来源关系的行为；由明确保留政策决定失效/移除，结果必须可追溯。

### P6：MCP、持久化与恢复

在同一 profile 下对照直连 SDK 与实验 MCP：输入条件、结果集合、身份映射、错误一致。
三个存储触发位置以三类合成输入回放，记录各自映射，不依赖启动三套独立存储。
实验 MCP 工具与现有生产工具分开；不把参考 MCP 缺少参数等同于核心能力缺失。
能力若需自定义 MCP 工具暴露，记为 adapted 的接入工作量。
强制超时/重试验证幂等；停止服务再启动验证持久化，不把进程缓存当作数据库状态。
在 S0 拍快照，S1 新增记录并使一条事实失效，再恢复 S0；原始数据、向量、图、映射与处理水位
必须一起回到 S0，S1 的新增、失效标记和缓存不得残留。恢复后分叉再查询不能看见另一分支后缀。
快照可使用数据库官方备份，不限定必须是 SDK 方法；注明是否停写、停服务以及恢复耗时。
重建图需 LLM 时可能非确定，不可据此宣称精确 checkpoint 恢复；报告重建与快照恢复的区别。
MCP 管理面沿用内容传输、sha256 核验的现有约束，不能要求客户端共享服务端文件路径。

## 7. 执行、预算与产物

未来代码位置建议 `experiment/memory_graph_probe/`；结果使用忽略目录
`eval_results/memory_graph_probe/<batch>/<profile>/`，不写入生产 memory、tracelog 或 frozen dataset。
不增加通用 agent 框架，不改全局依赖锁；使用独立环境和独占数据库，禁止探针清空共享库。

脚本控制 preflight→seed→filter→semantic→scope→graph→MCP→restore→report。
提供 start/status/stop/resume；停止在可核对的阶段边界生效，恢复仅跳过指纹一致且已完成的阶段。
每个 Port/模型/后端操作保存请求、响应或显式异常、起止时间；失败与 pending 不能被汇总丢弃。
所有证据经实验注入的 trace sink 记录，不在四个独立模块增加 trace 实现依赖。

默认预算：每次外部操作 30 秒、单阶段 180 秒、整 profile 30 分钟；LLM 总尝试不超过 50 次、
每请求最多 2 次，embedding 和 reranker 调用单列；真实图抽取最多 6 条，不为过测试无限重试。
启动前固定总 token/费用上限；无可靠价格时记费用 unknown，以 token 与次数硬闸控制。
超时保留证据并将阶段标为 blocked/failed，不改 fixtures、参考或阈值补救。

必须输出：manifest.json、capabilities.json、fixtures.jsonl、queries.jsonl、
record_id_map.json、每次调用账、生成的过滤查询、stage_results.json、metrics.json、REPORT.md。
REPORT.md 是实验报告，不新增 README；报告逐项链接证据并列出所有适配文件和后端限制。

## 8. 判定标准

| 门槛 | 标准 |
|---|---|
| 无损存取 | 40/40 指纹一致；原始 ID 映射完整，重启后仍成立 |
| 精确过滤 | 全部过滤查询与 oracle 集合一致；缺键/空串语义一致 |
| scope | 全部详情/背景集合一致；禁止来源命中、正文和图路径泄漏均为 0 |
| 向量能力 | 证明原始正文向量参与；不能仅依靠名称向量或全文命中 |
| 语义质量 | 12 个固定语义查询中至少 10 个在 top-3 命中指定相关原始记录，按 profile/检索模式分别统计 |
| 过滤顺序 | limit=1/3 的诱饵测试通过且有候选过滤先于截断的后端证据 |
| 图检索 | 确定性关系、时间边界、逆序写入、合法来源和分支用例全部通过 |
| 恢复 | S0 原始/派生状态及查询集合恢复一致；S1 后缀零残留 |
| MCP | 与相同 SDK profile 等价，错误与超时不静默降级，调用账无遗漏 |

语义阈值是本探针预设验收值，不是官方性能承诺；漏召回与泄漏必须分开报告。
性能记录每次耗时、总耗时与 token；样本小时不把单次观测宣称为稳定 p95 或生产 SLA。
LLM 抽取另列正确/漏抽/错抽及成本；不以生成文字“看起来正确”替代图和原始 ID 检查。

最终结论分为：native_ready、adaptation_required、not_suitable、inconclusive。
native_ready 要求原生 profile 全部硬门槛通过；adaptation_required 必须列清原生缺项，
且候选适配 profile 通过全部门槛；只在理论上能补记 inconclusive，不能宣称已适配。
无法满足原始向量、scope 或恢复契约且没有可接受适配方案时记 not_suitable。
Zep platform 的通过不能改变开源 profile 的判定。

## 9. 官方资料与待核实点

以下资料于 2026-10-20 查阅；实施时必须关联到 manifest 的固定版本重新核对。

- [Graphiti 完整搜索](https://help.getzep.com/graphiti/working-with-data/searching)：search_、SearchConfig、recipes 与排序。
- [自定义类型](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types/)：属性建模与抽取；身份元数据另由代码盖章。
- [命名空间](https://help.getzep.com/graphiti/core-concepts/graph-namespacing)：group_id 的范围语义。
- [公开 CRUD](https://help.getzep.com/graphiti/working-with-data/crud-operations)：无需抽取的节点/关系操作。
- [开源过滤接口](https://github.com/getzep/graphiti/blob/main/graphiti_core/search/search_filters.py)：字段声明不能替代后端实测。
- [Neo4j 搜索实现](https://github.com/getzep/graphiti/blob/main/graphiti_core/driver/neo4j/operations/search_ops.py)：候选过滤、排序与截断位置。
- [参考 MCP](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md)：公开工具与核心 SDK 能力分别验收。
- [Zep 平台搜索](https://help.getzep.com/searching-the-graph)：property_filters / metadata_filters 的平台对照，不能视为 OSS 保证。

重点待核实：任意元数据的持久化/组合过滤是否端到端生效；原始正文是否有独立语义向量路径；
同一实体跨来源合并是否破坏 scope；快照能否恢复向量、图状态与血缘。此文不预设通过或失败。
