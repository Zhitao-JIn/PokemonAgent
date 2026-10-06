# 测评契约

对外只有七个 inspect task。`python -m evals list` 列出入口，`python -m evals run <task> <inspect 参数>` 统一启动；`.eval` 记录样本、输入、输出、评分与错误。

| task | 被测对象与输入 | scorer | 模型 |
|---|---|---|---|
| decode | 同一帧冻结 WRAM，机械解码一次 | ScreenText、接管视图、地形/位置三个分组 | 无 |
| vision_perceive | 生产视觉节点的纯视觉部分，输入截图 | scene、overlay、dialog_text、options、cursor、解析成功 | 视觉模型 |
| screen_interpret | 生产读屏 prompt，输入人工核过的真值解码观测 | 标注的读屏字段 | 文本模型 |
| world_actions | 常规脚本与原宏统一走脚本执行通道，真实模拟器 | 自报结局与世界真值 | 无 |
| memory | 冻结库经真实 MemoryTool 写入、读回，再检索带相关性标签的查询 | 存储分、检索 recall@k / MRR | 无 LLM，本地 embedding/reranker |
| judge | 真值目标与观测历史交给生产判定器 | TP / FP / FN / TN 次数 | 判定模型 |
| e2e | 完整系统执行目标，按最终结果判 | 机械结果、红线、独立 model-graded 结果 | 完整系统与结果评分模型 |

## 帧与独立真值

`evals/data/screen_reading/dataset/v2/samples.jsonl` 是基础帧；`evals/data/frames/takeover.jsonl` 是原接管视图场合的冻结快照；`evals/data/frames/terrain.jsonl` 是带独立存档事实依据的两帧地形快照。decode、vision_perceive、screen_interpret 共用加载器，按所需标注筛选。现场模拟器只用于数据采集，decode 不再启动模拟器。

每帧分别保存可选的 `screen_truth`、`takeover_truth`、`terrain_truth`。未标的分组是 NOANSWER，不进入该组分母；空标注也不能获得成功分。基础帧只有 `label_checked` 为真的文字标注计分；接管帧保留原手写场合、视图字段与屏幕文字期望。地形组支持 `map_id`、`where`、`facing`、`walk_map` 与 `neighbors`，`terrain.jsonl` 当前有两帧辅助标注，依据既有存档说明并复核截图，标注 map_id/where/facing/neighbors；完整 walk_map 尚未逐格核过，不参与评分。

`interpret_inputs.json` 冻结人工核过的 dialog_text/options/cursor/quantity；不把待测解码器输出当成真值，也不把待判 overlay 放入输入。45 帧具备此输入。未核过的自动预标不能作为准确率分母。

同一帧只跑一次机械解码，三个 scorer 复用结果。`judged_accuracy` / `judged_count` 读取未做 epoch 数值归并的原始 C/I/N，每次重复运行作为独立观测统计，确保 N 不被转换为失败进入分母。

## 模型与启动

正式文本读屏为 `evals/config.json` 的 `evaluation_models.screen_interpret = openai-api/qwen/qwen3.8-max`；视觉为 `models.vision_model = deepseek-flash`。五条完整系统链路仍使用配置的各自型号。文本读屏的 QWEN 密钥取现有 DASHSCOPE_API_KEY（或生产 provider 同款的 ANTHROPIC_AUTH_TOKEN），不另存密钥。

真实模型测试统一覆盖 deepseek-flash；文本读屏用 `-T text_model=openai-api/deepseek/deepseek-flash`，视觉用 `-T vision_model=deepseek-flash`。本轮重构验证没有调用真实语言或视觉模型。

```powershell
python -m evals list
python -m evals run decode --log-dir eval_results/decode
python -m evals run world_actions --log-dir eval_results/world_actions
python -m evals run memory --log-dir eval_results/memory
python -m pytest tests/test_harness_integrity.py
python -m evals run screen_interpret -T text_model=openai-api/deepseek/deepseek-flash
python -m evals run vision_perceive -T vision_model=deepseek-flash
python -m evals freeze-frames
```

harness_integrity 位于 `tests/test_harness_integrity.py`，属于集成测试，不参与 inspect 评分。默认运行 local 的正常完成与预算耗尽剧本；Langfuse 测试默认跳过，仅在显式 `TEST_LANGFUSE=1` 时核真实写入/读回。失败直接是 pytest 失败。mock 装配位于 `tests/_harness_fixtures/`，不会进入测评包。

## 当前覆盖与结果口径

world_actions 共 106 例，统一按脚本的调用、结局与前后世界真值评分。31/75 只是两批历史用例来源；常规与接管都交出控制权执行多步操作，现在共用同一个 ScriptRun，等待、中断、初态恢复与收尾属于脚本自己的配置或步骤。保留原用例依据与世界真值。被测脚本自报成功不是世界真值；重构不根据实际输出改写期望。

memory 初始冻结库为三条 knowledge 与三个相关性查询，可按同一 schema 扩充其他记忆类型。judge 初始四条独立真假历史；这些小型用例是运行契约示范，不能代替完整能力评估。

e2e 评分只看任务最终结果、红线和独立结果评分模型。路径、步骤、花费可留在日志用于诊断，不作为另一个 judge_process task 或成功评分。缺少可评分材料是 NOANSWER；基础设施或模型调用失败是 sample error，报告应同时披露错误数。


## decode 标注覆盖（2026-10-06）

冻结帧 1047 个；有 RAM 与截图不等于有独立期望。未标组记 NOANSWER是数据缺口或字段不适用，不是通过。

| 字段组 | 目前计分的独立标注 | 具体缺口 |
|---|---|---|
| ScreenText 与 overlay | 45 帧的 overlay/dialog_text/options/cursor | 其他帧的实际叠加界面、选项/光标语义与选项排布尚需独立核对 |
| 场合与接管视图 | 8 帧，八种场合各一个，标指定字段子集 | 场景/初态规则正负例；队伍的倒下、异常状态、在场成员等解释规则；自动预标 scene/at_start 不能当独立真值 |
| 地形规则 | 两个 Route 1 帧的 map_id/where/facing/neighbors | 台阶、草、水、墙、门与人物遮挡的解释是否对应实际行为；按规则准备代表性验证，无需人工抄每帧完整 walk_map |

标注的核心是从 RAM/图块/文字推导出的分类和解释是否符合实际，而非把直接读到的每个原始字段重新抄一遍。地址、偏移、字节序等机械读取契约由 pytest 验证；场景、overlay、队伍状态与地形解释需要独立规则真值。walk_map 是按 tile 通行表、台阶、水及对象覆盖规则从 RAM 推导的网格，不是 RAM 中现成的字符串；验证这些规则可用独立地图资料和真实模拟器行为，没必要逐帧人工标满90格。

0926 探测45帧只有原始文字/overlay 人工期望；build_v2 的 _prelabel_probe 另外由分类器填 scene/at_start，label_checked 不应扩张成这两个字段已有独立真值。decode 不采用这些自动场景标签作答案。

8/8 与 2/2 仅代表已标字段符合。扩展数据应先依据实际界面/游戏规则写真值，再跑待测解码器，不能从输出生成答案。
