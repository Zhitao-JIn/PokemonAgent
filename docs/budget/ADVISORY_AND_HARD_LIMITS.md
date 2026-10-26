# 父级建议与配置硬预算

2026-10-25，CHANGELOG 641。此文更新旧run-budget-spec.md中D7的clamp语义。

父级规划输出的`budget.limit`只表示完成子目标的建议用量。采纳时仍保存在
`Task.max_steps`，不改旧模型输出JSON格式，也不覆盖为配置值。建议可以低于或高于
配置，超出建议不触发机械失败、不自动代表完成或受阻。

机械硬限来自本次生效的`AppConfig.budget`：

| 范围 | 单位 | 配置 | 计数 |
| --- | --- | --- | --- |
| run | episodes | max_episodes | 已派episode数 |
| episode | tasks | episode_max_tasks | 已派task数 |
| task | actions | task_max_steps | 已执行ACT数 |
| run | actions | max_total_actions | 跨局累计ACT数 |
| run | seconds | wall_clock_s、reserve_s | 共享Deadline及收尾预留 |
| run | rounds | max_planning_rounds | 已用逻辑规划轮数 |
| episode | rounds | max_decompositions | 已用逻辑拆解轮数 |

ACT沿用当前harness口径：一次键动作或一次脚本调用计一次，不将脚本内物理按键展开。
本次不修改脚本计数、停止原因词表、机械评分或DeepSeek费用保护。

run规划、episode拆解、task动作选择都接收`budget_context`。每项有kind
（advisory/hard）、scope、unit、source、limit、used、remaining。
父级建议与本层配置硬限使用同一实际计数，但分别计算剩余量；超过建议时保留真实used，
建议remaining为0，不能据此停止。下层还收到派发时剩余的全局动作额度和共享时间余量。
run没有父级建议，规划时另列每个下层episode/task的配置上限。

`loop.episode_max_tasks_per_plan`与`loop.plan_max_new_goals`仍是单版新增建议量，
不是整个执行的硬预算。拆解单版建议量还会参考配置剩余task数；已有待办不被静默裁剪。
模型输出正整数budget的结构校验、解析重试和trace保持。人审修改引发的逻辑重规划轮次
会更新预算素材，内部解析重试不额外消耗逻辑轮次。

task入口不再clamp父级建议；task图recursion_limit从配置task_max_steps换算。
episode/task出口断言使用配置硬限，摘要及派生记忆来源章中的max_steps表示实际配置硬限，
父级建议原值可在规划提案、开局trace和模型调用预算素材中追溯。
配置硬限仍能提前结束；现有task最终判定可以在最后额度对应的观测确认成功。
全局时间/动作、episode任务数等外层守卫保持原有优先级，本次不增加末尾模型调用。

prompt新增run_plan v5、decompose v8、decide_action v7，基于原活动版本仅补预算语义和
动态素材；固定规则在前，具体额度在后。旧版本只读。预算素材在harness与独立prompt模块
分别声明同构Pydantic模型，tool通过已有JSON转换桥接；brain不依赖settings或harness。

状态schema哈希会随Task字段说明及嵌套请求契约变化，仅影响harness运行中完整checkpoint的恢复；
这些checkpoint继续由现有哈希保护拒绝不兼容加载，不绕过保护或自动迁移。
agent_short_goal_run已于606取消评测起点打包，直接加载原始.state，不受此schema哈希影响，
无需重新打包或重采评测起点。本次没有恢复打包器或重打任何存档。旧付费结果保留为历史证据；
修复后的成本与调用收益须另做匹配基线。

验收使用FakeLLM+MockWorld真实三层图，无网络：建议1/99均不改变配置硬停机点；真实模型
调用trace中的prompt可见建议、硬限、单位、来源及逐步变化的剩余量；累计动作、时间耗尽、
逻辑重规划、存档与原有终止行为由相关回归测试检查。本次不启动付费评测。
