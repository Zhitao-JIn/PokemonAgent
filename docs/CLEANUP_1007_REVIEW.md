# 1007 清理执行记录

按 PLAN_cleanup_1007 与用户后续答复执行，七个阶段已完成本轮范围。第六阶段只做数据盘点，不生成新真值。本轮不提交、不推送、不调用真实模型。

## 定案与清理结果

- 已读取用户提供的 C:/Users/GummiGu/Downloads/ai-coding-paradigm.skill 内的 SKILL.md，按契约、注入、显式签名与用法示范要求执行。
- 347–353 实际已提交，最近为 f168289，当前分支 codex/unify-script-execution。本轮编号从 354 起，保持 tests/、/experiment/ 忽略规则。
- 删除旧 e2e batch/view/report/process/rubric/cases、旧 diff/evallog、零消费者报告模型和 model_graded 辅助实现；保留 run-one、RunResult 和现行 Inspect 评分。RUN_RECORD/RUN_RESULT 迁入 one.py。load_rubric/rubric.json 仍被现行数据校验消费，保留。
- 删除旧 diff 是用户明确选择，对旧 spec2 保留口径校验的有意偏离。未新增 .eval 比较器，冻结文档不改，现行 evals SPEC 已说明。
- 删除两个一次性脚本、三个空目录、整个 observation_check 与 real_check。旧观察数据、工具一并按用户要求删除，现有冻结 evals/data 保留。screen build 只接受显式新采集目录，不再读取旧 v1 来源。
- Web Reviewer 三种场景迁入 tests：人工答复、无人答复、后端断开。原自测误把空白插话算作已回答，按后端已有契约修正断言，后端行为不变。node_io 核对器仍被测试消费，迁入 tests/_harness_fixtures。
- MCP 注册表 45 项：7 原子、租约归还、14 地图/场所脚本、23 脚本。静态签名按场合分文件；shop_buy/shop_sell 是内部组合步骤。客户端保留 report.events，信封支持接管失败码；内存 MCP 传输验证 shop_quit 成功与错误场合拒绝。
- config.py 的唯一系统缺省改 local；显式 Langfuse 健康检查保留。补获授权的接管 prompt 与平铺 args 用法测试。
- 删除 11 条死代码测试：view 三条；model_graded 两条、报告投影一条；旧判定一致性、报告 evaluate、stall limit 各一条、LLMGrader 两条。保留现行 RunResult 与 run-one 测试。

图源码：[执行流程](CLEANUP_1007_FLOW.puml)、[测评数据流](CLEANUP_1007_DATAFLOW.puml)。

## 阶段六：独立真值缺口

读取冻结数据得到以下数量；分组可以重叠。没有用待测输出生成答案。

| 项目 | 现有数量 | 建议采样 |
|---|---:|---|
| WRAM 帧 | 1047 | 按人工截图场合分层选代表帧 |
| decode 文字组 | 45，未标 1002 | 完整文字复核、选单滚动、数量框；45 不代表每个字段完整 |
| 接管视图 | 8，未标 1039 | 队伍、背包、商店、PC、战斗的正常与边界状态 |
| 地形语义 | 2，未标 1045 | 草、水、墙、台阶、柜台互动、NPC 重叠和门口规则 |
| scene / at_start | 0 个独立评分字段 | 初态与非初态成对选样，人工判场景规则 |
| screen_interpret 真值输入 | 45 | 核解码观测真值后增加歧义、边界输入 |
| memory | 3 记录、3 查询 | 五类记忆、同义查询、困难负例、多相关及无相关查询 |
| judge | 4，正负各 2 | 购买、出售、回血、移动、战斗的正负例与矛盾证据 |
| decide_action 组件测评 | 未立项 | 后续确定独立判据与预算，本轮不加 task |

相对现有帧的未标数已列出；目标规模未定，不能给出达到目标还差几条。并不要求全部帧标满，也不需要抄每帧完整 walk_map；需要验证 RAM 解码后的分类与解释，例如队伍状态、overlay、scene、对象重叠与通行规则。

入口：python -m evals frames build --capture <目录> --version v2 接收含 manifest.jsonl 的新人工采集记录；python -m evals freeze-frames 负责冻结帧。自动预标不成为独立真值。旧 label_tool 已删除，新人工标注工具在后续重建数据集时搭建；observe.py 是待测解码适配器。

## Skill Agent 工程清单

这是本轮核对，不声称补齐既有路线图缺项。

| 项 | 结论与落点 |
|---|---|
| 1 自然语言到工具 | 有：brain Action 解析、BrainTool 重试、ActionEntry 与 MCP 签名 |
| 2 prompt 中心 | 有：direct/prompts、world/prompts |
| 3 上下文与成本 | 有：harness perceive、config 预算、ModelCall trace；未扩展裁剪策略 |
| 4 黑盒工具与结构化输出 | 有：tool Ports、Pydantic 信封、ScriptResult、MCP 失败码 |
| 5 执行与业务状态 | 有：三图状态、trace、memory；在线状态归并缺，属既有路线图 |
| 6 持久化与恢复 | 有：三级开局 checkpoint 与恢复测试；任意 step 恢复缺，非本轮范围 |
| 7 人类介入 | 有：harness/reviewing、review_backend，本轮验证三种场景 |
| 8 代码掌控控制流 | 有：LangGraph、动作掩码、脚本策略与预算 |
| 9 结果学习 | 有：反思、task/episode 蒸馏与 memory；MC 回填缺，属既有路线图 |
| 10 小而专注 | 有：brain 各方法、独立文本/视觉测评与分组 scorer |
| 11 多触发入口 | 有：build、Inspect/CLI 调同一核心；定时/webhook 不适用于此次清理 |
| 12 无状态大脑 | 有：brain 参数契约，状态外置于 harness、checkpoint、trace、memory |

## 验证

- 完整 pytest：488 条，486 通过、2 条 Langfuse 检查跳过。相对 492 条基线，删除 11 条、增加 7 条获授权测试。
- world_actions：106 个冻结真模拟器用例全通过，0 sample error；日志 .pytest_tmp/world_actions_cleanup，未调用模型。
- ruff check pokemon_agent evals tests scripts 通过。本轮改动 Python 文件已格式化；全目录 format --check 仅剩未改动 scripts/langfuse_smoke.py 的既有格式差异，未扩改。
- evals list 七项、e2e run-one --help、screen build --help 正常。退役模块源码消费者清零，历史文档提及保留。
- 用户原有 assets/rom.ram、assets/rom.state 修改及其它未追踪运行数据保留；冻结文档、ROADMAP 和忽略规则未改。

## 阶段七：提交分组建议（尚未执行）

实际标题逐字复用 CHANGELOG 编号标题；CHANGELOG 整体追加随最后相关提交保存，不手拼行区间。

| 编号 | 前缀建议 | 文件范围 |
|---|---|---|
| 354 | refactor(evals) | evals/core、data loader/build/cli、e2e、schema、scorers；schemas/harness/domain/run_io.py；两个一次性脚本删除；docs/spec/evals/SPEC.md |
| 355 | refactor(tests) | real_check 引用清理：brain/interface/domain/model_call.py、direct/prompts/judge_success.py、direct/trace/render.py、schemas/harness/domain/trace_kind.py；迁入 tests 的核对器/集成测试被忽略 |
| 356 | feat(mcp) | mcp_servers/common.py、world_server.py、world_server_cli.py、world_script_tools/、mcpclient/world_tool.py；docs/spec/mcp/SPEC.md、tools/SPEC.md；MCP 测试被忽略 |
| 357 | fix(config) | config.py，含退役 real_check 环境引用清理；test_build.py 被忽略 |
| 358 | test(brain) | 两条新增测试均在忽略的 tests/；保持规则时无可普通提交的测试文件，仅留日志，不能假称测试入库 |
| 359 | docs(evals) | 此审计的数据盘点、skill 核对及两份 PlantUML 源码 |
| 360 | docs(cleanup) | 此审计最终验证、提交分组与 CHANGELOG 整体追加；与 359 共用文档可最后一次保存，不拆行 |

tests 改动及 experiment 删除不进普通提交，按用户决定保持规则、不强制添加。不包含用户存档、PLAN_cleanup_1007.md 或其它既有未追踪文件；未执行任何 Git 写操作。
