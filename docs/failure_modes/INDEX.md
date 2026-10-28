# 失败模式索引

整理于2026-10-25，当前共 **53个模式，每个模式一个文件**。按机制归并重复案例，保留历史修正和证据强弱；原始三轮coordination、结果和经验文档不移动、不覆盖。

## 最新预算设计结论（用户已确认，待实现）

父级给的是**建议预算**；**硬预算由配置文件给出**。建议预算与硬预算都必须放进prompt，并分别说明单位、总量、已用、剩余与来源。父级建议用尽本身不应机械终止；是否停止由相应配置硬预算决定。这里说的是agent运行预算，不改变DeepSeek资金预算与预留守卫。

641已将父级budget.limit改为建议，机械硬限从配置读取，并补齐规划/拆解/动作预算素材；FM-001和FM-002已完成离线回归，真实模型待新基线验证。旧报告中“父级真实硬预算=1”的说法描述当时实现，不是最新接受的设计；此前继续用goal.max_steps统一硬闸的建议已被本次澄清取代。

## 使用约定

- 先读状态和原始版本。已修复、候选待验证、历史未复核、根因未定位分开，不把历史全部列为当前bug。
- 机械I、评分N、原始失败、离线校正结果及候选未执行分别保留；不丢失败样本。
- 错误较多时优先优化，但用户没有要求零错误硬门槛；旧控制脚本仍需修订，见FM-040。
- 无新模型调用、无新增付费评测、无commit/merge/push；此次文档整理不自动恢复heartbeat。

## 模式目录

| 编号 | 失败模式 | 分类 | 状态 |
| --- | --- | --- | --- |
| FM-001 | [父级建议预算被执行为硬停止条件](FM-001-advisory-budget-used-as-hard-stop.md) | 预算/编排 | 641已实现，离线回归通过，待真实模型验证 |
| FM-002 | [拆解prompt缺少建议预算与硬预算的完整上下文](FM-002-budget-context-missing-or-inconsistent.md) | 预算/输入 | 641已补传预算，离线回归通过，待真实模型验证 |
| FM-003 | [连续过程被拆成过多中间task或L1目标](FM-003-over-decomposition-of-continuous-work.md) | 规划效率 | 已观察；候选有改善线索，未证稳定 |
| FM-004 | [不可变run goal被塞入可编辑plan槽位](FM-004-run-goal-in-editable-plan.md) | 目标建模 | 633–635改动已处理；历史案例保留 |
| FM-005 | [run级评分只按原goal ID找局导致不可判](FM-005-scorer-uses-only-original-goal-id.md) | 评分范围 | 633修复已落地；旧N不改写 |
| FM-006 | [RunStream未先按run_id过滤导致证据串run](FM-006-run-stream-cross-run-leak.md) | trace/评分 | 636已修复；历史缺陷 |
| FM-007 | [run总目标判据被误读成只验当前task流水](FM-007-run-criterion-treated-as-current-task-only.md) | 判定/作用域 | 历史证据分歧；候选口径需统一 |
| FM-008 | [独立评分材料落后于最后动作或观测](FM-008-grader-material-stale-after-final-action.md) | 评分证据 | 历史已确认；不能声称637彻底覆盖此问题 |
| FM-009 | [判定器缺少RAM数值而误以为没有状态证据](FM-009-judge-missing-numeric-ram-evidence.md) | 观测/判定 | 637接线；iter09治疗重测通过，非普遍保证 |
| FM-010 | [切图事实与scene或当前帧规则冲突导致继续执行](FM-010-map-transition-and-scene-evidence-conflict.md) | 判定/证据解释 | 已观察；根因混合，未证单一prompt解释 |
| FM-011 | [分页结果文字被单帧正则漏判](FM-011-paged-dialogue-regex-false-negative.md) | 机械评分 | 用户授权修复并仅离线校正iter01 |
| FM-012 | [用截断前缀或常识补齐完成结果](FM-012-truncated-text-treated-as-complete-result.md) | 判定假阳 | 候选judge v7/捕捉知识；新全量单次通过 |
| FM-013 | [执行者站位与交互对象坐标混淆](FM-013-actor-and-object-coordinates-confused.md) | 规划/对象归属 | 有多次实例；知识候选，未单独验证 |
| FM-014 | [移动对象当前位置被当成起点对象身份凭据](FM-014-moving-object-identity-inferred-from-nearby-position.md) | 判定假阳 | judge v6/NPC知识候选；尚无身份机制保证 |
| FM-015 | [换目标后仍反复打开上一对象对话](FM-015-reopening-previous-object-after-target-change.md) | 动作/停滞 | 历史反例；未证明已解决 |
| FM-016 | [连续失败阈值后仍派task](FM-016-failed-task-streak-still-dispatched.md) | 红线/编排 | 历史R2事实；代码根因未定位 |
| FM-017 | [子任务要求读取未提供的后台记录](FM-017-child-goal-requires-unobservable-backend-record.md) | 拆解/验收 | decompose v7候选；iter17有改善线索 |
| FM-018 | [success_criteria输出数组而契约要求字符串](FM-018-success-criteria-array-instead-of-string.md) | 结构化输出 | decompose v6候选；后续未稳定复现该类型 |
| FM-019 | [budget输出数值而契约要求对象](FM-019-plan-budget-scalar-instead-of-object.md) | 结构化输出 | run_plan v4候选；旧A仍可出现 |
| FM-020 | [execution_order引用不存在或错误状态的条目](FM-020-execution-order-reference-invalid.md) | 结构化规划 | 已有显式校验/纠正；错误模式仍需保留 |
| FM-021 | [JSON缺少最外层闭合括号](FM-021-json-outer-bracket-not-closed.md) | 结构化输出 | 摘要v4等有候选修正；不能声称彻底消除 |
| FM-022 | [JSON字符串内引用原文未转义](FM-022-json-string-unescaped-quotes.md) | 结构化输出 | verify v5候选；后续单轮未复现不代表保证 |
| FM-023 | [摘要字符串数组中出现对象项](FM-023-summary-string-list-contains-objects.md) | 结构化输出 | summarize_task v5候选 |
| FM-024 | [JSON对象中拼入无键名数组或位置值](FM-024-json-unkeyed-positional-values.md) | 结构化输出 | summarize_task v6仅三例验证；未完整全量验收 |
| FM-025 | [摘要额外套type/content包装](FM-025-summary-type-content-wrapper.md) | 结构化输出 | 旧A仍发生；候选约束待持续验证 |
| FM-026 | [独立评分员输出字段与评分schema不匹配](FM-026-grader-response-schema-mismatch.md) | 评分格式 | 630增加有限格式纠正；历史N保留 |
| FM-027 | [起点预检在reset前读世界](FM-027-preflight-perceive-before-reset.md) | 启动/生命周期 | 630已修复；历史启动失败 |
| FM-028 | [ExceptionGroup只记录外层字符串掩盖启动根因](FM-028-exception-group-hides-leaf-and-startup-trace.md) | 错误可观测性 | 630展开异常；历史记录缺口保留 |
| FM-029 | [CLI启动缺少公开API端点配置](FM-029-cli-public-endpoint-not-initialized.md) | 启动/环境 | 历史修复于启动环境；不是密钥问题 |
| FM-030 | [模型超时留下未知服务端费用和重试链](FM-030-timeout-with-unknown-server-usage.md) | 接口/计费 | 历史与近期均有；不能靠prompt保证消除 |
| FM-031 | [思考消耗额度却没有可解析正文](FM-031-thinking-consumes-output-before-answer.md) | provider/重试 | 已有EmptyCompletion与纯文本降级；本探针未复现 |
| FM-032 | [变量或条件分支切断静态缓存前缀](FM-032-dynamic-content-breaks-static-cache-prefix.md) | 缓存布局 | 多版布局已调整；收益依场景验证 |
| FM-033 | [provider支持显式缓存但配置链路未接通](FM-033-explicit-cache-capability-not-wired.md) | provider/缓存 | 已接线；Claude iter03机制探针通过 |
| FM-034 | [把预热或路径差异误归因于布局](FM-034-cache-warmth-and-path-confound-attribution.md) | 实验归因 | 已明确限制；需重复/控制对照 |
| FM-035 | [局部压缩或每ACT降价掩盖全任务变贵](FM-035-local-compression-or-per-act-metric-masks-total-cost.md) | 效率评估 | 多轮已出现；不接受单指标选优 |
| FM-036 | [历史前后观测反复渲染不变大地图](FM-036-repeated-before-after-map-bloats-history.md) | 输入/延迟 | 2026-08历史已优化；当前渲染需另审 |
| FM-037 | [事实整理和局部校验出现高额thinking长尾](FM-037-thinking-on-low-value-calls-and-long-tail.md) | thinking成本 | 638节点开关已接线；质量收益仍待验证 |
| FM-038 | [缺货币charge或未落盘用量被误作零成本](FM-038-cost-scorer-n-and-partial-ledger.md) | 计费/指标 | 持续统计限制；不是已确认无费用 |
| FM-039 | [混合版本或未完成批次被当完整基线](FM-039-mixed-baseline-and-incomplete-trials.md) | 实验完整性 | 已标明限制；历史结果原样保留 |
| FM-040 | [把错误优先优化擅自收紧为零错误硬门槛](FM-040-unauthorized-zero-error-acceptance-gate.md) | 执行流程 | 用户已纠正；旧控制器逻辑仍待修订 |
| FM-041 | [报告器对缺失参照样本直接索引](FM-041-reporter-joins-nonexistent-reference-sample.md) | 报告工具 | iter07已离线修复；未额外模型调用 |
| FM-042 | [向量缓存与磁盘记忆生命周期不一致](FM-042-vector-cache-and-disk-lifetimes-diverge.md) | 记忆/缓存 | 2026-08历史已修；现有实现未本次重测 |
| FM-043 | [跨run经验携带使重复实验不再独立](FM-043-memory-carryover-confounds-independent-trials.md) | 记忆/实验 | 历史风险；取决于实验目的，不能一律叫bug |
| FM-044 | [文档声称的观测字段未实现或语义过时](FM-044-observability-contract-never-implemented-or-stale.md) | 可观测/文档 | 历史修订；不能据此声称当前trace缺字段 |
| FM-045 | [多顶层目录导致editable安装包发现失败](FM-045-flat-layout-package-discovery-breaks-install.md) | 工程/打包 | 2026-09历史包发现修复；运行环境另有版本限制 |
| FM-046 | [预算收尾跳过已存在task正文](FM-046-budget-exit-drops-existing-task-summary.md) | 记忆/收尾 | 历史已确认；当前预算路径未本次复核 |
| FM-047 | [分层局部预算无法约束全run资源与正常收尾](FM-047-nested-budgets-do-not-bound-whole-run.md) | 预算/生命周期 | 历史预算方案已改造；父建议语义本次另行更新 |
| FM-048 | [把我方HP下降当作对方受伤证据](FM-048-hp-owner-confused-in-success-evidence.md) | 历史判定假阳 | 仅历史经验二级证据；原始批次trace不在本工作区 |
| FM-049 | [界面说明文字被计入菜单选项](FM-049-instruction-text-counted-as-menu-option.md) | 历史观测/判定 | 仅历史经验二级证据；当前未复现 |
| FM-050 | [目标只到中间菜单却继续操作到成交状态](FM-050-overshooting-menu-goal-before-stopping.md) | 历史验收/过冲 | 历史二级证据；近期仍需看overshoot |
| FM-051 | [记忆写入路径回读 trace 账](FM-051-memory-write-path-reads-trace-ledger.md) | 编排执行/性能与耦合 | 评审阶段发现，修法已定（D17），待合入 |
| FM-052 | [脚本结果摘要读错报告层级，只剩结局码](FM-052-script-result-line-reads-nested-data.md) | 编排执行/观测缺失 | 已由 step-observation CP2 取代；影响未做对照实验 |
| FM-053 | [脚本内的对话与自动过场不进账](FM-053-script-internal-dialog-not-recorded.md) | 观测与记忆缺失 | 逐键观察已合入分支，自动过场需实测核对 |

## 来源覆盖与追溯

下表记录本次归并使用的来源及落入的模式。不是对整个仓库所有历史故障做穷尽保证；覆盖本次e2e三轮已保留总结、iter01/03–19相关审计和已有experiences中的相关失败记录。原记录缺失的0827原始trace等只作二级证据，不补造复现。

| 来源 | 模式 |
| --- | --- |
| [.coordination/e2e-overnight/SUMMARY.md](../../.coordination/e2e-overnight/SUMMARY.md) | FM-008, FM-010, FM-015, FM-016, FM-020, FM-029, FM-046 |
| [.coordination/e2e-overnight-2/SUMMARY.md](../../.coordination/e2e-overnight-2/SUMMARY.md) | FM-010, FM-026, FM-027, FM-028, FM-038 |
| [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md) | FM-006, FM-011, FM-020, FM-026, FM-027, FM-028, FM-031, FM-033 |
| [docs/eval/spec.md](../eval/spec.md) | FM-011 |
| [docs/run-goal-split/spec.md](../run-goal-split/spec.md) | FM-001, FM-004, FM-005, FM-006, FM-007 |
| [docs/run-goal-split/recent-ram-evidence.md](../run-goal-split/recent-ram-evidence.md) | FM-007, FM-008, FM-009 |
| [.coordination/e2e-overnight-3/CACHE_LAYOUT_PLAN.md](../../.coordination/e2e-overnight-3/CACHE_LAYOUT_PLAN.md) | FM-032, FM-033 |
| [.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md](../../.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md) | FM-004, FM-005, FM-019, FM-032, FM-034 |
| [.coordination/e2e-overnight-3/THINKING_ANALYSIS.md](../../.coordination/e2e-overnight-3/THINKING_ANALYSIS.md) | FM-003, FM-010 |
| [.coordination/e2e-overnight-3/THINKING_COST_REVIEW.md](../../.coordination/e2e-overnight-3/THINKING_COST_REVIEW.md) | FM-037 |
| [.coordination/e2e-overnight-3/RUN_THINKING_DISTRIBUTION.md](../../.coordination/e2e-overnight-3/RUN_THINKING_DISTRIBUTION.md) | FM-037 |
| [docs/budget/run-budget-spec.md](../budget/run-budget-spec.md) | FM-001, FM-047 |
| [docs/experiences/2026-08-31-audit-77s-input-bloat.md](../experiences/2026-08-31-audit-77s-input-bloat.md) | FM-036 |
| [docs/experiences/2026-08-31-keyerror-cross-run-leak.md](../experiences/2026-08-31-keyerror-cross-run-leak.md) | FM-042 |
| [docs/experiences/2026-09-01-trace-task-id-and-memory-carried.md](../experiences/2026-09-01-trace-task-id-and-memory-carried.md) | FM-043, FM-044, FM-045 |
| [docs/experiences/2026-09-01-eval-framework-bootstrap.md](../experiences/2026-09-01-eval-framework-bootstrap.md) | FM-048, FM-049, FM-050 |
| [docs/spec/build/NODE_THINKING.md](../spec/build/NODE_THINKING.md) | FM-031, FM-037 |
| [.coordination/e2e-overnight-3/efficiency-loop/OVERNIGHT_ERRORS.md](../../.coordination/e2e-overnight-3/efficiency-loop/OVERNIGHT_ERRORS.md) | FM-040 |
| [.coordination/e2e-overnight-3/CONTINUATION.md](../../.coordination/e2e-overnight-3/CONTINUATION.md) | FM-040 |
| [pokemon_agent/harness/episode/plan_episode/plan_episode.py](../../pokemon_agent/harness/episode/plan_episode/plan_episode.py) | FM-002 |
| [eval_results/overnight3/iter01/ROUND_REPORT.md](../../eval_results/overnight3/iter01/ROUND_REPORT.md) | FM-011, FM-030, FM-034, FM-035, FM-038 |
| [eval_results/overnight3/iter06/ROUND_REPORT.md](../../eval_results/overnight3/iter06/ROUND_REPORT.md) | FM-013, FM-032, FM-034, FM-035 |
| [eval_results/overnight3/iter07/ROUND_REPORT.md](../../eval_results/overnight3/iter07/ROUND_REPORT.md) | FM-004, FM-005, FM-039, FM-041 |
| [eval_results/overnight3/iter08/ROUND_REPORT.md](../../eval_results/overnight3/iter08/ROUND_REPORT.md) | FM-009, FM-039 |
| [eval_results/overnight3/iter09/ROUND_REPORT.md](../../eval_results/overnight3/iter09/ROUND_REPORT.md) | FM-009, FM-039 |
| [eval_results/overnight3/iter10/ROUND_REPORT.md](../../eval_results/overnight3/iter10/ROUND_REPORT.md) | FM-018 |
| [eval_results/overnight3/iter11/ROUND_REPORT.md](../../eval_results/overnight3/iter11/ROUND_REPORT.md) | FM-003, FM-013, FM-018, FM-019 |
| [eval_results/overnight3/iter12/ROUND_REPORT.md](../../eval_results/overnight3/iter12/ROUND_REPORT.md) | FM-014 |
| [eval_results/overnight3/iter13/ROUND_REPORT.md](../../eval_results/overnight3/iter13/ROUND_REPORT.md) | FM-014, FM-021 |
| [eval_results/overnight3/iter14/ROUND_REPORT.md](../../eval_results/overnight3/iter14/ROUND_REPORT.md) | FM-021, FM-022, FM-030, FM-040 |
| [eval_results/overnight3/iter15/ROUND_REPORT.md](../../eval_results/overnight3/iter15/ROUND_REPORT.md) | FM-012, FM-023, FM-024, FM-050 |
| [eval_results/overnight3/iter16/ROUND_REPORT.md](../../eval_results/overnight3/iter16/ROUND_REPORT.md) | FM-017, FM-035 |
| [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md) | FM-003, FM-012, FM-017, FM-019, FM-024, FM-040 |
| [eval_results/overnight3/iter18/ROUND_REPORT.md](../../eval_results/overnight3/iter18/ROUND_REPORT.md) | FM-024, FM-025, FM-038, FM-039 |
| [eval_results/overnight3/iter19/ROUND_REPORT.md](../../eval_results/overnight3/iter19/ROUND_REPORT.md) | FM-001, FM-002, FM-003, FM-037, FM-038 |
| [eval_results/overnight3/iter11/ANALYSIS.json](../../eval_results/overnight3/iter11/ANALYSIS.json) | FM-019 |
| [eval_results/overnight3/iter12/ANALYSIS.json](../../eval_results/overnight3/iter12/ANALYSIS.json) | FM-014 |
| [eval_results/overnight3/iter13/ANALYSIS.json](../../eval_results/overnight3/iter13/ANALYSIS.json) | FM-021 |
| [eval_results/overnight3/iter14/ANALYSIS.json](../../eval_results/overnight3/iter14/ANALYSIS.json) | FM-021, FM-022, FM-030 |
| [eval_results/overnight3/iter15/ANALYSIS.json](../../eval_results/overnight3/iter15/ANALYSIS.json) | FM-012, FM-023, FM-024 |
| [eval_results/overnight3/iter16/ANALYSIS.json](../../eval_results/overnight3/iter16/ANALYSIS.json) | FM-017 |
| [eval_results/overnight3/iter17/ANALYSIS.json](../../eval_results/overnight3/iter17/ANALYSIS.json) | FM-024 |
| [eval_results/overnight3/iter18/ANALYSIS.json](../../eval_results/overnight3/iter18/ANALYSIS.json) | FM-025 |
| [eval_results/overnight3/iter19/ANALYSIS.json](../../eval_results/overnight3/iter19/ANALYSIS.json) | FM-001, FM-002 |
| [eval_results/overnight3/iter03/PROBE_REPORT.md](../../eval_results/overnight3/iter03/PROBE_REPORT.md) | FM-007, FM-033 |

## 不误列为当前失败的情况

- reviewer.mode=off且trace answered=false/by=none是本批明确配置，不是reviewer偷偷启动失败。
- 缓存首次冷请求、短前缀不命中，本身不等于provider故障；缓存比例下降也可能由输入组成变化。
- 预算守卫因预估越界阻止启动是保护成功，不算模型失败；iter18未跑full不能标作full质量失败。
- task_id“不该承载实验分组键”是历史设计，之前缺task_id的质疑已撤回，不编造缺陷。
- 历史材料只一笔带过“权限漏配静默降级”等背景，缺独立定位证据，本次不杜撰根因/修复文件；后续找到原案例再建独立模式。
- 若需要继续迭代，应从原始trace和当前代码重新核验，而不是直接执行历史文档中的旧路径/命令。
