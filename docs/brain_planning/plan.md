# plan —— 两层规划实施与二十场景重采

> 状态：实施计划，尚未开始落码或采集。
> 依据 `intent.md` 与 `spec.md`；每阶段完成检查后进入下一阶段。
> 当前用户要求先交付 spec/plan，因此本次止于设计文档。

## 1. 提交与执行顺序

按契约 → 状态与身份 → 调度 → 评测 → 采集控制器 → 重打重采顺序推进。
每项代码变更追加倒序 CHANGELOG 四段条目，commit 与编号标题对应。
冻结采集提交后不再边运行边改代码；修复后必须使用新批次或明确的新尝试版本。

## 2. 契约与 prompt

改动位置：

- `brain/interface/domain/run_plan.py`、`decomposition.py` 及其导出。
- judge 结果袋、BrainPort、生产解析和 direct 门面结果转换。
- plan/decompose/judge 请求与响应信封、Port、mock、prompt 组装和模板。

工作内容：

1. 两层输出统一为 new_items/updates/execution_order/why，子目标使用显式单位预算。
2. plan 请求补齐 run_goal 与验收条件；两层状态表显示同等追踪信息。
3. judge 输出改为 decision/why，保留 task interrupted；派生旧 done/success 读法。
4. judge 请求增加 L0 表和最新规划复判素材；严格区分规划主张与执行证据。
5. 原子验证表操作和执行顺序；非法模型输出按现有具名错误及尝试账重试。
6. 盘点所有解析、trace 展示、review、假实现与评测调用点，防止仅修改生产返回形状。

验证：公开 Port 用例覆盖空新增、单位错误、越界/重复修订、非法顺序、决策解析、重试账；
假 provider 与真实 provider 仍满足同一协议，brain 独立性检查通过。
不在本阶段调用真实模型。

## 3. 状态表与执行身份

改动位置：`schemas/harness/domain/{goal_entry,task_entry,entry_status,task_io,termination}.py`、
run/episode 状态与 dispatch、TaskMemory 来源章、结算与 review。

工作内容：

1. 两层增加 blocked 表状态；L2 增加稳定 entry_id、attempts 和 last_task_id。
2. 派发创建独立 task_id；TaskInput/Output、记忆和 trace 关联逻辑条目及执行。
3. 旧尝试继续保留；移除 task 失败后自动放弃全部剩余 pending 的行为。
4. 应用修订保持表行稳定，派发顺序保存稳定 ID 引用，更新整版原子采纳。
5. 重开不返还父层预算；blocked 不增加、不清零失败计数，派发次数照常累计。
6. 同步人审推翻、预算闸门的 running 结算和预期异常兜底路径。

验证：同条目两次执行的身份、来源章和全部输出可独立回查；普通失败、blocked、
interrupted 与 review 推翻各有清晰结算。scope 检查证明 L2 背景仍按同局同目标文本读取。

## 4. 图调度与有界复判

改动位置：run/episode 图、plan_run/plan_episode、review_and_judge、budget_nodes、
RunBudget/config、收尾与 checkpoint。

工作内容：

1. 每次子执行后若继续都规划，包括已有 pending；入口正常判定策略保持明确。
2. 规划后有 pending 才派发，无 pending 直接复判，复判继续才再规划。
3. 最新规划、版次和复判原因进可序列化 state；复判不重复 perceive、吸收或结算。
4. 新增 run 规划轮数上限与 PLANNING_EXHAUSTED；episode 沿用拆解轮数上限。
5. 按 spec 设置生产 max_planning_rounds=20、max_decompositions=12；
   二十场景显式设置为 6、12，保留 3 局、60 动作、600 秒限制。
   核对 review 重写消耗，记录原 max_decompositions=2 不适合逐 task 重规划的原因；
   不依赖 LangGraph recursion_limit 代替业务预算，也不将两批结果作为同规划预算直接对照。
6. achieved/blocked 经过对应 review 决策后统一收尾；机械预算和错误出口继续独立。
7. 零执行也能返回明确来源章与原因；schema 指纹升级，旧存档不强行恢复。

验证：FakeLLM + MockWorld 端到端演示保留任务、补前置、重开任务、空规划有待办、
空规划无待办后继续、blocked 上返、review 推翻、零执行收尾及预算耗尽。
检查恢复到无待办复判与重开后的派发点，不重用 ID、不重复消费预算。

## 5. 离线评测迁移

改动位置：四族任务的 dataset/solver/scorer、公共 advisory 评分、brain_calls 构建与标注契约。

工作内容：

1. 先支持新请求/候选 schema，再采集；新旧版本按 manifest 选择明确 schema 或适配器。
2. 旧版本入口不能拿旧冻结请求静默调用不兼容的新契约，必要时保留旧 solver 适配路径。
3. plan/decompose 结构评分接受空新增，核对操作、单位和完整派发顺序。
4. AI 质量评分继续建议式多解；实际 prompt/附图与 solver 相同，标签只交给 scorer。
5. judge 保留完整调用账、异常及新 decision；扩充多类别标签和指标。
   旧 false 逐例审阅后才能区分 continue/blocked/interrupted，证据不足明确排除。
6. 为数据适配保存来源版本、记录指针、请求/证据哈希；不伪补缺失字段。
7. 新数据分别发布 choose/plan/decompose/judge 后续版本；summary 三层请求与响应独立保留。

验证：Fake Solver/Fake Grader 证明参考不泄漏、空规划合理可得分、非法修订扣结构分、
judge 各类统计和排除分母正确。旧冻结文件与版本 manifest 哈希不变。

## 6. 采集控制脚本

基于 `evals/common/capture_batch.py`、`capture_case.py`、`capture_audit.py`、
`brain_capture.py`、`invocation.py` 和专用服务管理扩展；本节命令为待实现接口。

新增 `python -m evals.common.capture_control`，提供：

| 命令 | 行为 |
|---|---|
| start --out <新目录> | 后台启动 preflight、pack、capture、audit、export 顺序流水线 |
| status --out <目录> | 读取原子状态/报告，返回阶段、完成数、异常及产物位置 |
| stop --out <目录> | 请求停止派下一例，当前例按既定超时结束 |
| resume --out <目录> | 校验指纹后续跑，完整例跳过，不完整例进入新 attempt 目录 |

工作内容：

1. 用 Pydantic 定义批次、阶段、case/attempt 和退出原因报告；状态更新原子写。
2. pack 支持独立 archive 输出根，capture_case 支持显式 archive 来源，
   不继续依赖覆盖 `dataset/v1/archives` 的旧流程。
3. Windows 后台进程隐藏窗口；控制器保存 PID 与启动身份，避免误停止其他批次或共享服务。
4. 固定 git/schema/代码/prompt/config/模型/来源哈希，运行期间漂移自动中止。
5. 完整保留所有 Port 的请求、响应、失败、pending、模型尝试和耗时；
   扩充审计以核对 judge/plan/decompose 的 review 等待，区分未询问、已完成、pending、缺失。
6. 业务失败继续采集，基础设施失败按显式有限策略暂停/失败；
   request pending 或双向对账缺口不能被归入成功批次。
7. 验收报告自动汇总阶段结论和路径，控制器不依赖助手实时读日志。
8. export 写独立暂存原料目录，通过校验才发布 v2；若目标已存在则拒绝覆盖。

验证：用假子进程/专用临时目录演示正常运行、worker 超时、停止与恢复、版本漂移、
已有产物保护及调用/等待缺口。状态命令不读取密钥、不暴露环境变量。

## 7. 实施完成后的检查门槛

1. Ruff check 与 format、接口/分层与文件函数大小检查通过。
2. 相关单元与集成测试通过，再运行一次全量非 slow 测试；测试进程禁用真实模型密钥。
3. frozen dataset、标注、原始模拟器状态和旧 archive 的哈希未意外改变。
4. checkpoint 指纹和所有新请求/候选 schema 导出完成；mock 跑通新图与新录制器。
5. 将代码、配置、prompt、脚本与对应文档提交，固定本次采集版本。

未通过门槛不开始真实采集；不通过删断言、放宽事实范围或跳过审计绕过失败。

## 8. 重打与二十场景采集

是否重新收集：需要。新任务表、执行身份和 judge 复判素材无法从旧现场完整推导，
而下游 choose/summary 的实际输入也会随新规划改变。
可复用原始二十个模拟器 .state；本次重打新的 harness 起点，重新跑二十场景。

实施检查完成后，由控制脚本执行：

1. preflight：核密钥可用性但不输出值、服务启动条件、二十来源哈希、磁盘和固定版本。
2. pack：从原始状态建立新 schema 的二十起点，写入批次独立 archives 和 pack_report。
3. capture：串行运行二十例，全量记录 judge/plan/decompose/choose/summary 与旁证。
4. audit：自动核请求闭合、模型尝试双向对账、review 等待及各层覆盖；业务失败单列。
5. export：完整性通过后构建 brain_calls v2 候选，保存来源档案、schema、配置及统计。

助手通过 start/status/stop/resume 控制脚本；不 tail 日志、不用 UI 或逐秒轮询作运行控制。
异常诊断读取脚本输出的失败摘要及定向证据，修复后新版本重启，不混合版本。
采集自然未触发的路径在覆盖报告中明确列出，另做定向补采，不能以总调用数替代覆盖率。

## 9. 标注与交付

依据每次实际请求的可见历史独立标注；候选 baseline 和未来执行不作为答案依据。
plan/decompose 给非穷尽建议、合法表操作与空规划适用条件；judge 标完整 decision。
summary 保留来源与原料，不自动新增公开任务。

交付分开报告：代码验证、二十例采集、完整性审计、独立标注、新数据版本、真实模型评分。
最后一项只有实际执行后才报告分数；本次采集授权不等于必须顺带重新跑全部质量评分。
每项报告带固定提交、schema/config 指纹、完成数、排除原因及产物路径。
