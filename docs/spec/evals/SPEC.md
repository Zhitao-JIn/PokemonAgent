# 测评契约

## 2026-10-08 真值修补与地形适用范围

按 `truth_patch_1007.json` 对 490 帧应用 713 条批准操作。每条 set/delete/replace_group 核对 before；新增 unresolved 的两条额外核对键不存在。原始真值保留在 `eval_results/labeling_1007/truth_before_patch_1008.jsonl`，未修改样本、截图、WRAM、存档或补丁之外的真值字段。

地图适用性统一调用 `world.ram.map_settled`：通行表指针非零且静态地图头 tileset 与 WRAM 的 D367 一致。原 1032 个地图已载入帧中，13 个 tileset 不一致的换图中间帧不再适用地形，加原 13 个无地图帧，共 26 帧地形为 N；适用帧为 1019。c-0109 的 walk_map、neighbors 无法确定，各在 unresolved_fields 保留原因、相应真值键删除；其他三项仍参与评分，不把整帧地形判 N。

scene/screen/takeover 均覆盖 1045 帧；terrain 的 map_id/where/facing 各覆盖 1019，walk_map/neighbors 各覆盖 1018，另有 c-0109 的两项 unresolved。coverage 的 unaccounted_fields 为空。完整诊断各组全为 C，地形仅不适用的 26 帧为 N。13 字段修补后基线为 962/1045，修复后为 1045/1045，regressed 为空。逐字段基线、四组 Inspect 日志、覆盖检查和原值核对报告均在 `eval_results/labeling_1007/`。

这批冻结帧同时用于定位和验收，没有独立留出集或真实模拟器操作验证；不由匹配率推断操作成功率。

对外有六个任务，统一登记在 `evals/registry.py`：四个 DeepEval 模块入口、两个 Inspect task 文件入口。B 类使用 `python -m evals.<任务名>`，C 类使用 `inspect eval evals/<任务名>/task.py`；不提供 evals 根级 CLI。DeepEval 保存原生 test_run JSON，Inspect 保存 .eval。

旧批跑、report、diff 入口及只供其使用的报告模型已按用户决定删除。旧 diff 只读
`header.json` / `results.jsonl`，无法比较现行 `.eval`；本轮未新增 Inspect 日志比较器，
不再提供旧口径一致性校验。单样本子进程本体是 `evals/agent_short_goal_run/solver/worker.py`，由 solver 经 stdin 交一份 `RunOneRequest` 启动，不是对外命令。

| task | 被测对象与输入 | scorer | 模型 |
|---|---|---|---|
| brain_goal_judge | 真值目标与观测历史交给生产判定器 | TP / FP / FN / TN 次数 | 判定模型 |
| agent_short_goal_run | 完整系统执行目标，按最终结果判 | 机械结果、红线、独立 model-graded 结果 | 完整系统与结果评分模型 |

## task 分层与描述

测评按三层归类：**结果层**看系统最终有没有把事办成；**工具层**看每个组件单独是否可靠；**流程层**看大脑的决策环节（规划、判定、验证、反思）。分层只是归类，不改变各 task 的评分口径；`tests/integration/test_harness_integrity.py` 是集成测试、不是 inspect task，不在下列分层内。过程指标（重复动作、A-B-A 振荡、预算耗尽后的收尾）继续只写日志做诊断，不另立评分 task。

命名为 `agent_<范围>_goal_run`：`short` 指单个冻结场景内的短目标，`long` 指从真实开局出发的多里程碑长程。标"规划中"的 task 尚无数据集、solver、scorer，也不在 `evals/registry.py` 里。

### 结果层

**agent_short_goal_run**（已实现；原名 agent_goal_run）
测什么：完整系统（含记忆）从冻结的单场景起点出发，能否完成一个短目标。20 个起点覆盖对话推进、NPC 对话、进出门、受阻移动、宝可梦中心进入与治疗、商店（交互、开买菜单、选物、确认、取消）、战斗（行动菜单、招式菜单、选招、换人、用道具、逃跑）、遭遇野生宝可梦、抓捕（削弱、投球）。评分只看最终结果：机械结果规则、红线、独立 model-graded 结果。
不测：跨场景的长程推进、卡住后的恢复、记忆是否带来增益。

单样本 worker 的硬超时仍为 `evals/config.json` 的 600 秒。评测只在该文件的
`budget` 段覆盖总量：运行时长 600 秒、最多三局、累计动作 60 次；task 把这段写成
报告目录下的 `run_config.json`，在 `baseline_context.json` 记录路径与 SHA256，worker
将文件路径交给 `build_real(config=…)`。分层预算与生产共用，生产默认最多 50 局、
总时长和累计动作不限；连续失败护栏不能替代总量预算。
`knowledge_battle_action_menu` 只要求在当前战斗菜单移动光标并停在 RUN，禁止确认、
逃跑、重新遇敌和逃跑收尾。任务描述同时保存在样本与冻结存档的 run_goal、pending task 中，
修改时须同步；机械真值仍是 battle/choice/RUN。2026-10-14 的旧配置十样本基线在第七例
被用户中止，前六例结果仅为子集，不作为修改后配置或视觉删除的完整迁移基线。

**agent_long_goal_run**（规划中，优先级高）
测什么：从真实开局出发，系统在步数与时间预算内能推进多远。以里程碑为单位判分（如离开家、到达第一个城镇、拿到初始宝可梦、通过第一片野外区域、进入第一个道馆，清单待定），报告里程碑达成率、最远里程碑、到达每个里程碑的步数。一次运行的分母是里程碑，不是一个目标。
不测：单个场景内的操作细节（由 short 与工具层覆盖）。

**agent_stall_recovery_run**（规划中，优先级高）
测什么：起点刻意放在容易卡住的情境（门被挡、对话循环、菜单层级错乱、重复遇敌），看系统能否发现自己没有进展并脱困。指标为脱困成功与否、卡住持续的步数、卡住期间是否反复执行同一动作。卡住的判据来自世界真值（坐标、场合、地图编号长时间不变），不靠模型自述。

**agent_memory_ablation_run**（规划中，优先级中）
测什么：同一批目标、同一模型，分别在"带结构化记忆"与"不带记忆"两种条件下成对运行，报告成功率差与步数差，回答记忆是否真的带来增益。不新增评分口径，复用 short / long 的结果评分，新增的只是对照设计与成对比较。

### 工具层

**decode**（已实现）
测什么：同一帧冻结 WRAM 经机械解码后，输出是否与独立真值一致。1045 帧，用 DeepEval 按真值键逐字段计分，未标注字段跳过，显式空值照常比较。原生输出字段通过率及计分数、帧级通过率。不调用模型、不启动模拟器。
不测：视觉读取与在线执行。

**episode_vision_read**（已实现）
测什么：生产视觉节点的纯视觉部分。只给截图，视觉模型能否读出场景、覆盖层、对话文字、选项、光标，以及解析是否成功。需要视觉模型，当前为 deepseek-flash。代码在 evals/episode_vision_read/，默认四线程；支持 --vision-model、--per-scene、--all。六列指标对应原 C/I/N，无从判跳过，解析失败的适用列判负；调用不通帧不造用例，运行末尾打印一行列出原因。

**world_script_execute**（已实现）
测什么：世界侧多步脚本在真实模拟器上执行是否正确，共 106 例。代码与数据位于 evals/world_script_execute/；每例独立进程，300 秒墙钟超时后终止，已取得开跑帧的脚本记 crash=超时，装配超时则抛专名异常。原生 code/truth 的 Total 各为 106，38 个 pass.<脚本名> 的 Total 合计 106，不再单列 kind 分组。按脚本自报结局与前后世界真值比对评分，自报成功不等于世界真值。不调用 LLM。
不测：脚本被中途打断后的恢复。

**memory_store_recall**（已实现）
测什么：冻结记忆库经真实 MemoryTool 写入、读回，再对带相关性标签的查询做检索，测存储是否无损，以及 recall@k、MRR。代码与 v1 数据在 evals/memory_store_recall/，每条记录与查询各一个 DeepEval 用例；storage 看通过率，recall_at_k/mrr 看平均分，满分阈值为 1。当前只有 3 条 knowledge 与 3 个查询，是用法示范规模。不调用 LLM，使用本地 embedding 与 reranker。
不测：地图拓扑记忆、情节记忆的蒸馏。

**world_navigate_path**（规划中，优先级高）
测什么：在冻结地图上给定起点与目标格，路径规划与逐格执行能否到达，包括门、换图、NPC 与障碍阻挡。真值来自已有地形标注，评分为是否到达与绕行步数，确定性、不调用 LLM。

**memory_map_recall**（规划中，优先级中）
测什么：探索过若干地图后，记忆能否回答"从 A 到 B 怎么走"，即地图间连接（门、换图口）的写入与检索是否正确。与 memory_store_recall 的区别：后者测知识条目，这里测空间拓扑。

**memory_distill_fidelity**（规划中，优先级中）
测什么：task 记忆与 episode 记忆这两级派生蒸馏的正文是否忠于下级 act 源记录，正负标注是否与 verify 结果对应。依据"派生物可重建、来源章不从正文反推"的约定。

**brain_action_format**（规划中，优先级低）
测什么：大脑输出的动作能否通过 `Action` 解析，统计解析失败率与按键越出动作空间的比率。可先从 trace 统计，再决定是否独立成 task。

另：战斗状态数值（HP、PP、状态异常）的解码作为 decode 的新分组加入，不新建 task。

### 流程层

**brain_goal_judge**（已实现）
测什么：生产判定器拿到真值目标与观测历史，能否正确判定目标是否达成，统计 TP / FP / FN / TN。目前只有 4 条用例，是运行契约示范，不能代替完整能力评估。

**brain_step_verify**（规划中，优先级高）
测什么：步骤验证（`StepVerifyVerdict`）对"这一步是否生效"的判断，重点是假阳性率。世界状态没变却判成功是卡死的主要诱因。输入前后观测与动作，对照世界真值统计 TP / FP / FN / TN。

**brain_reflect_replan**（规划中，优先级中）
测什么：注入失败情境（门没进去、对话没推进等），看反思能否指出根因，重规划是否针对该根因。以人工标注的根因为参照，由独立评分模型判定。

**brain_plan_decompose**（规划中，优先级低）
测什么：给定目标，任务分解是否包含必要的前置步骤、顺序是否合理（如治疗前先找到宝可梦中心）。以人工标注的必要步骤清单为参照。

## 帧与独立真值

`evals/dataset/frames/v2/samples.jsonl` 是唯一的 v2 帧集（1045 帧）；`source` 只记录采集来源，不决定 decode 的评分组。原基础帧、接管快照、地形快照均已合并，加载器不再拼接来源文件。采集命令按来源替换统一帧集中的对应样本，保留其余来源。decode、episode_vision_read 共用加载器，按所需标注筛选。现场模拟器只用于数据采集，decode 不再启动模拟器。

`evals/dataset/frames/v2/truth.jsonl`是decode独立真值的唯一存储，按sample_id记录scene_truth、screen_truth、takeover_truth、terrain_truth。所有已标字段直接挂到帧上计分，删除reviewed及配套组/字段审核标记，不再按审核状态过滤。未标字段跳过，不进入该字段分母；unresolved_fields记录无法判定原因。decode不从label_checked或label回退取答案。1045帧已标全部适用字段，地图稳定的1019帧有地形标注；c-0109的walk_map与neighbors为unresolved，其余26帧地形不适用。网页审阅意见独立保存，不控制真值计分。视觉任务保留自身原有label_checked口径。

`scene_truth` 查三个字段：`scene`、`covered_by_script`、`at_start`。`covered_by_script=true` 表示当前场合由脚本负责，包含未回初态的子菜单；有可选脚本的场合允许按键，covered_by_script 为 false。真值从独立标注场合和已核对的八类脚本对应关系补出，不读取被测分类器结果。1045 帧已标此字段；两帧完整空菜单重绘按2026-10-08裁决标为start_menu（c-0419）和bag（c-0440）。该字段只测覆盖识别是否正确；实际退回初态与执行结果由 `world_script_execute` 验证，模型选择目标脚本由决策 prompt 约束，本次未运行真实模型验证。

## B 类运行方式与目录规则

decode 的代码全部位于 `evals/decode/`：`dataset.py` 将帧转为用例，`solver.py` 解码，
`compare.py` 纯比较，`scorer.py` 提供 `FieldMatch`，`__main__.py` 调用 `evaluate()`。
共用帧集保留在 `evals/dataset/frames/`；其他任务迁移前保持原目录。

一帧一个 `LLMTestCase`，actual_output 与 expected_output 分别为整帧输出与真值 JSON。
扫描真值键并集生成 23 个字段指标，名称如 `screen.options`。缺键未标注时抛
`MissingTestCaseParamsError`，配合 `ErrorConfig(skip_on_missing_params=True)` 跳过，
不进该字段分母。真值为 null、空字符串、空列表、false 或 0 均照常计分；
输出必须含有对应键且值相等。`screen_contains` 要求每条文字都在屏幕文本中。

四个 B 类共用 evals/common/run.py；默认只列失败帧，DeepEval 原生输出 Aggregate Metrics 与帧级 Pass Rate。
各字段 Total 等于有标注帧数；帧级通过要求该帧全部计分字段通过。
至少有一个计分字段的帧进入帧级分母；全部跳过的帧由 DeepEval 排除。
不再单列四组 C/(C+I)，需要时可由逐字段记录推导。
每次运行原生 JSON 保存到 `eval_results/decode/`，有失败返回 1，成功返回 0。
`--frame ID` 可重复，`--scene NAME` 按真值场合筛选，两者取交集。
未知 ID 或空选择返回参数错误；不通过 pytest 启动评测，不调用模型、不启动模拟器。

## 模型与启动

视觉为 `evals/config.json` 的 `models.vision_model = deepseek-flash`；五条完整系统链路使用配置的各自型号。

真实模型测试使用配置型号；视觉可用 --vision-model 覆盖。第二阶段按用户授权只对每场景一帧的 9 帧执行旧基线与新入口验证；默认仍是人工核过的 45 帧。该次新入口 8/9 通过，退出 1；同批保存输出的六列判定新旧一致。

```powershell
python -m evals.decode
python -m evals.decode --frame p-option_screen
python -m evals.decode --scene bag
python -m evals.world_script_execute --workers 1
python -m evals.memory_store_recall --k 5
python -m pytest tests/integration/test_harness_integrity.py
python -m evals.episode_vision_read --vision-model deepseek-flash --per-scene 1
python -m evals.dataset.frames.build.freeze
python -m evals.dataset.frames.build.terrain
```

harness_integrity 位于 `tests/integration/test_harness_integrity.py`，属于集成测试，不参与 inspect 评分。默认运行 local 的正常完成与预算耗尽剧本；Langfuse 测试默认跳过，仅在显式 `TEST_LANGFUSE=1` 时核真实写入/读回。失败直接是 pytest 失败。mock 装配位于 `tests/_harness_fixtures/`，不会进入测评包。

## 当前覆盖与结果口径

world_script_execute 共 106 例，统一按脚本的调用、结局与前后世界真值评分。所有脚本共用同一个 ScriptRun 执行多步操作，等待、中断、初态恢复与收尾属于脚本自己的配置或步骤。保留原用例依据与世界真值。被测脚本自报成功不是世界真值；重构不根据实际输出改写期望。

memory_store_recall 初始冻结库为三条 knowledge 与三个相关性查询，可按同一 schema 扩充其他记忆类型。brain_goal_judge 初始四条独立真假历史；这些小型用例是运行契约示范，不能代替完整能力评估。

agent_short_goal_run 评分只看任务最终结果、红线和独立结果评分模型。路径、步骤、花费可留在日志用于诊断，不作为另一个 judge_process task 或成功评分。缺少可评分材料是 NOANSWER；基础设施或模型调用失败是 sample error，报告应同时披露错误数。

agent_short_goal_run 的过程在 Inspect View 的 Transcript 中查看，Langfuse 仍可用于定位同一执行线。
solver 在子进程结束后经 `RunStream.load` 读取 local / langfuse 类型化账本，按原顺序与
UTC 时间回放；`-T transcript=false` 关闭回放，缺省开启。solver 通过
`AgentRunRecord` store 交接 run_id、branch、invalid、error、work_dir 与原始 run_result；
两种 scorer 从该记录定位账本，不反读 transcript。无效与超时只写说明事件。

| 项目账 | Inspect 事件 |
|---|---|
| run / episode / task 的 start | SpanBegin + 保留正文的 Info |
| 三层 end / error | Info + 对应 SpanEnd；未配对结束不关闭外层，遗留 span 在最后账时间收口 |
| parse.MODEL_CALL_KINDS 的调用账 | Model：真实链路型号、prompt、原图、raw、全部用量、错误、完整请求 |
| act_call、历史 press_key / run_macro、get_action_space、read_* / write_* | Tool：完整 meta 与 JSON 正文结果 |
| 其余账 | Info：type、meta、content |

正文事件 uuid 使用原账 uuid；派生 span 的 uuid 加 begin / end 后缀以避免重复，span id
使用 start 账 uuid。所有事件 metadata 的 kind、type、trace_uuid 对应原账。时间按 Inspect
datetime 的微秒精度保留；模型与工具的 completed 使用 ended_at。原图交给 Inspect 自动
附件化与去重。回放经内部 `_event` 接口追加，并临时保留全部模型 API 请求，避免默认
只保留前几次的裁剪。Inspect 固定为 0.3.271，升级时须重跑回放与交接测试。


## decode 标注覆盖（2026-10-07）

冻结帧1045个，所有适用 decoder 输出字段已有独立参考标注：scene 三字段、screen 十三个字段、takeover 的 view 与非空视图全部嵌套成员，各覆盖1045帧；terrain 的map_id/where/facing覆盖1019帧，walk_map/neighbors覆盖1018帧，c-0109的两项记unresolved；另26帧地形不适用。完整字段、原始证据和边界裁决见 `docs/DECODER_TRUTH_COVERAGE_1007.md`。

这些参考标注不代表1045帧均经人工逐帧审核。默认 decode 采用全部独立真值，404起已删除审核过滤；用户批准本次审计裁决和713条补丁不等于新增留出集验证。逐字段比较，已标键相等为 C，不等为 I，未标为 N（DeepEval 跳过）；字段通过率为 C/(C+I)，Total 为有标注帧数，帧级通过要求全部计分字段通过。显式null期望仍要求实际输出该键。

参考标注从原始冻结 RAM/ROM、固定名称表及既有独立文字/场合标注产生，不读取待测解码输出。候选完成后才跑 decoder 作差异诊断。参考程序、逐帧字节及哈希位于 `eval_results/labeling_1007/full_truth/`；运行 `python -m evals.dataset.frames.build.coverage` 检查顶层字段与视图嵌套字段。

此前只核代表性规则、不标机械字段的范围已按用户要求扩大为全输出覆盖。地址、字节序与物理图块规则仍需独立复核，完整参考标注不能替代人工审核和真实环境行为验证；菜单遮挡时的 walk_map 只核当前图块缓冲投影。

0926 探测45帧的自动预标 scene/at_start 不作独立答案。原8/8接管与2/2地形只代表当时已审键符合；全量标注覆盖和正式准确率分别报告，不混为一谈。

接管组仅含 view；重复的 scene 和 screen 归场合与文字组。原已审 scene、screen_contains 移到所属分组并保留原审核粒度，完整 view 的旧已审点路径由加载器按路径投影，不重复存储相同字段。审阅页整屏参考只显示一次。


## 测评代码与冻结数据的归属（第二阶段后）

每个任务集中在 `evals/<任务名>/`：B 类由 `__main__.py` 装配 dataset、solver、compare、scorer，
C 类由 `task.py` 装配原有 Inspect 链路。文件多时使用同名子包，冻结数据版本紧邻加载代码。
共享帧、数据工具保留在 `evals/dataset/`，共享运行器与模拟器装配位于 `evals/common/`。
旧 `tasks/`、`solvers/`、`scorers/` 槽位已删除。

数据包出口只导出 `load()` 与样本类型；读取时核冻结文件、重复 id、版本内引用和来源哈希，
失败抛 `evals.dataset.errors.DatasetError`。judge 的 task 参数与 memory 的 --version 均默认为 v1。

| 数据包 | 默认版本与冻结物 | 构建工具 |
|---|---|---|
| frames | v2，1045 帧 samples.jsonl 与独立 truth.jsonl | build/；sources/ 收采集输入与13份存档 |
| agent_short_goal_run | v1，20 个起点、样本、rubric 与档案 | build/pack.py |
| world_script_execute | v1，106 条 cases.jsonl 与所用存档 | 106 条统一读取；核对函数在 scorer |
| memory_store_recall | v1，dataset.json（一份3条记录/3个查询的库） | 无 |
| brain_goal_judge | v1，dataset.jsonl（4条） | 本次不扩容 |

agent 的 source_state 与 manifest.memory_archive 均相对版本目录；恢复前由 solver 在工作目录
生成路径适配清单，冻结原件不写回。world 用例的 state 相对版本下的 states/，
`start_world` 接收完整 Path。experiment 原存档保留，数据包中的副本内容不变。

```powershell
python -m evals.agent_short_goal_run.dataset.build.pack --samples knowledge_dialogue_advance
python -m evals.dataset.frames.build.coverage
python -m evals.dataset.frames.build.cli build --capture <capture_dir> --version v3
```

2026-10-13 按用户授权重建 agent v1 全部 20 份起点存档，结构哈希更新为
`570c830a9cf52445`。来源 `.state`、目标定义、rubric 与世界存档字节保持不变；
旧存档备份和逐份真实恢复核对位于 `eval_results/archive_rebuild/`。
恢复核对不开跑目标、不调用模型，不能作为新的 agent 评分结果。

以下保留早期数据整理的历史核对记录，不代表本次第二阶段的执行结果：

迁移验收：106 条真机运行记录的完整裁决逐条相同；正式冻结帧与真值不变。
旧采集工具重跑已会改变当前 v2，迁移前后重采产物逐字节相同，但与正式冻结物不同；
本次仅在副本验证，没有将重采结果覆盖 v2。新 pack 工具在副本打包的 world.state 与现有档案一致。
真实 LLM 测评未重跑；三个无 LLM task 已全量运行，world 的原有 switch_from_party_list 失败保持不变。
