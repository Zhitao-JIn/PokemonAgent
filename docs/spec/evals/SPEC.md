# 测评契约

## 2026-10-08 真值修补与地形适用范围

按 `truth_patch_1007.json` 对 490 帧应用 713 条批准操作。每条 set/delete/replace_group 核对 before；新增 unresolved 的两条额外核对键不存在。原始真值保留在 `eval_results/labeling_1007/truth_before_patch_1008.jsonl`，未修改样本、截图、WRAM、存档或补丁之外的真值字段。

地图适用性统一调用 `world.ram.map_settled`：通行表指针非零且静态地图头 tileset 与 WRAM 的 D367 一致。原 1032 个地图已载入帧中，13 个 tileset 不一致的换图中间帧不再适用地形，加原 13 个无地图帧，共 26 帧地形为 N；适用帧为 1019。c-0109 的 walk_map、neighbors 无法确定，各在 unresolved_fields 保留原因、相应真值键删除；其他三项仍参与评分，不把整帧地形判 N。

scene/screen/takeover 均覆盖 1045 帧；terrain 的 map_id/where/facing 各覆盖 1019，walk_map/neighbors 各覆盖 1018，另有 c-0109 的两项 unresolved。coverage 的 unaccounted_fields 为空。完整诊断各组全为 C，地形仅不适用的 26 帧为 N。13 字段修补后基线为 962/1045，修复后为 1045/1045，regressed 为空。逐字段基线、四组 Inspect 日志、覆盖检查和原值核对报告均在 `eval_results/labeling_1007/`。

这批冻结帧同时用于定位和验收，没有独立留出集或真实模拟器操作验证；不由匹配率推断操作成功率。

对外有五个 Inspect task 和独立的 DeepEval decode 入口。`python -m evals list` 列出入口，`python -m evals run <task> <inspect 参数>` 统一启动；`.eval` 记录样本、输入、输出、评分与错误。

旧批跑、report、diff 入口及只供其使用的报告模型已按用户决定删除。旧 diff 只读
`header.json` / `results.jsonl`，无法比较现行 `.eval`；本轮未新增 Inspect 日志比较器，
不再提供旧口径一致性校验。`agent_goal_run run-one` 保留供现行任务执行单个目标。

| task | 被测对象与输入 | scorer | 模型 |
|---|---|---|---|
| episode_vision_read | 生产视觉节点的纯视觉部分，输入截图 | scene、overlay、dialog_text、options、cursor、解析成功 | 视觉模型 |
| world_script_execute | 脚本统一走执行通道，真实模拟器 | 自报结局与世界真值 | 无 |
| memory_store_recall | 冻结库经真实 MemoryTool 写入、读回，再检索带相关性标签的查询 | 存储分、检索 recall@k / MRR | 无 LLM，本地 embedding/reranker |
| brain_goal_judge | 真值目标与观测历史交给生产判定器 | TP / FP / FN / TN 次数 | 判定模型 |
| agent_goal_run | 完整系统执行目标，按最终结果判 | 机械结果、红线、独立 model-graded 结果 | 完整系统与结果评分模型 |

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

默认只列失败帧，DeepEval 原生输出 Aggregate Metrics 与帧级 Pass Rate。
各字段 Total 等于有标注帧数；帧级通过要求该帧全部计分字段通过。
至少有一个计分字段的帧进入帧级分母；全部跳过的帧由 DeepEval 排除。
不再单列四组 C/(C+I)，需要时可由逐字段记录推导。
每次运行原生 JSON 保存到 `eval_results/decode/`，有失败返回 1，成功返回 0。
`--frame ID` 可重复，`--scene NAME` 按真值场合筛选，两者取交集。
未知 ID 或空选择返回参数错误；不通过 pytest 启动评测，不调用模型、不启动模拟器。

## 模型与启动

视觉为 `evals/config.json` 的 `models.vision_model = deepseek-flash`；五条完整系统链路使用配置的各自型号。

真实模型测试统一覆盖 deepseek-flash；视觉用 `-T vision_model=deepseek-flash`。本轮重构验证没有调用真实语言或视觉模型。

```powershell
python -m evals list
python -m evals.decode
python -m evals.decode --frame p-option_screen
python -m evals.decode --scene bag
python -m evals run world_script_execute --log-dir eval_results/world_script_execute
python -m evals run memory_store_recall --log-dir eval_results/memory_store_recall
python -m pytest tests/test_harness_integrity.py
python -m evals run episode_vision_read -T vision_model=deepseek-flash
python -m evals freeze-frames
```

harness_integrity 位于 `tests/test_harness_integrity.py`，属于集成测试，不参与 inspect 评分。默认运行 local 的正常完成与预算耗尽剧本；Langfuse 测试默认跳过，仅在显式 `TEST_LANGFUSE=1` 时核真实写入/读回。失败直接是 pytest 失败。mock 装配位于 `tests/_harness_fixtures/`，不会进入测评包。

## 当前覆盖与结果口径

world_script_execute 共 106 例，统一按脚本的调用、结局与前后世界真值评分。所有脚本共用同一个 ScriptRun 执行多步操作，等待、中断、初态恢复与收尾属于脚本自己的配置或步骤。保留原用例依据与世界真值。被测脚本自报成功不是世界真值；重构不根据实际输出改写期望。

memory_store_recall 初始冻结库为三条 knowledge 与三个相关性查询，可按同一 schema 扩充其他记忆类型。brain_goal_judge 初始四条独立真假历史；这些小型用例是运行契约示范，不能代替完整能力评估。

agent_goal_run 评分只看任务最终结果、红线和独立结果评分模型。路径、步骤、花费可留在日志用于诊断，不作为另一个 judge_process task 或成功评分。缺少可评分材料是 NOANSWER；基础设施或模型调用失败是 sample error，报告应同时披露错误数。

agent_goal_run 的过程在 Inspect View 的 Transcript 中查看，Langfuse 仍可用于定位同一执行线。
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


## 测评代码与冻结数据的归属（S1 / S2）

`tasks/<task>/task.py` 只装配数据集、solver 与 scorer；执行和运行记录归 `solvers/`，
评分、metric 与结论类型归 `scorers/`。`evals/core/`、`evals/data/`、`evals/schema/` 已解散。

数据包出口只导出 `load()` 与样本类型；读取时核冻结文件、重复 id、版本内引用和来源哈希，
失败抛 `evals.dataset.errors.DatasetError`。judge / memory 的 task 参数改为 `version=v1`。

| 数据包 | 默认版本与冻结物 | 构建工具 |
|---|---|---|
| frames | v2，1045 帧 samples.jsonl 与独立 truth.jsonl | build/；sources/ 收采集输入与13份存档 |
| agent_goal_run | v1，20 个起点、样本、rubric 与档案 | build/pack.py |
| world_script_execute | v1，106 条 cases.jsonl 与所用存档 | 106 条统一读取；核对函数在 scorer |
| memory_store_recall | v1，dataset.json（一份3条记录/3个查询的库） | 无 |
| brain_goal_judge | v1，dataset.jsonl（4条） | 本次不扩容 |

agent 的 source_state 与 manifest.memory_archive 均相对版本目录；恢复前由 solver 在工作目录
生成路径适配清单，冻结原件不写回。world 用例的 state 相对版本下的 states/，
`start_world` 接收完整 Path。experiment 原存档保留，数据包中的副本内容不变。

```powershell
python -m evals agent_goal_run run-one --help
python -m evals.dataset.agent_goal_run.build.pack --samples knowledge_dialogue_advance
python -m evals.dataset.frames.build.coverage
python -m evals frames build --capture <capture_dir> --version v3
```

迁移验收：106 条真机运行记录的完整裁决逐条相同；正式冻结帧与真值不变。
旧采集工具重跑已会改变当前 v2，迁移前后重采产物逐字节相同，但与正式冻结物不同；
本次仅在副本验证，没有将重采结果覆盖 v2。新 pack 工具在副本打包的 world.state 与现有档案一致。
真实 LLM 测评未重跑；三个无 LLM task 已全量运行，world 的原有 switch_from_party_list 失败保持不变。
