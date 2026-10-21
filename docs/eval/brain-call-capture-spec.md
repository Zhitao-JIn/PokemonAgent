# 三层脑调用采集与测评数据

本轮按用户 2026-10-19 授权执行：重打二十份正式起点，串行恢复运行，构建
judge、plan、decompose、choose、summary 五类数据。不修改冻结来源 state 或旧版本真值。

## 范围与录制

L0 为 plan / run judge，本 run 全部 EpisodeMemory，背景为其他 run 的 RunMemory。
L1 为 decompose / episode judge，本局全部 TaskMemory；背景只来自本 run 同一个
L1 goal 的其他 episode，按 run_id + goal_id 关联。L2 为 choose / task judge，
本 task 全部 ActMemory；背景为本局同目标文本的此前 task。

在实际生产 Port 入口先保存类型化请求与开始记录，再原样调用；响应、异常与结束时间
分文件独占创建。start 无 end 表示未完成，不能把缺少响应当成成功或普通错误。
所有 retry 的原始 prompt、实际 images、raw、用量与尝试时间保留在响应 calls 或异常 calls。
工具调用总耗时包含模型等待、重试、退避与解析，不把它冒称纯 HTTP 服务端耗时。
reflect 不调用模型，仍保存其输入输出。task / episode / run summary 分层保存。

## 版本与隔离

使用当前 config 的模型与预算；采集从重新打包的正式 archive 恢复，保持目标、
判据、初始 task 和记忆上下文，不另拼一份输入。每例使用专用 MCP world 与空 memory。
这保证样本独立，但不覆盖持久跨 run 记忆的实验条件；报告必须说明背景的实际覆盖。

pack 前核二十份原始 state 哈希，备份旧 archives；pack 后核 schema 与新 manifest。
采集期间固定 HEAD、运行代码和 prompt 哈希、配置哈希与各 archive 哈希。
逐例保存报告和模型尝试双向对账；硬超时也保留全部产物与 pending。
业务失败不丢样本；版本变化或录制缺账中止后续样本并明确报告。

## 五类测评数据

共同字段为调用层、完整生产请求、来源坐标与文件哈希、对应已记录模型尝试、响应状态。
被采集模型的旧响应仅为 baseline 答案，不用于生成期望答案。

- judge：按调用时刻的独立 RAM / 历史状态证据标已达成与未达成；无法独立判的留待审，
  不使用被测 judge 的 done 或后续整局结果反推。三层分列。
- choose：从完整当时请求标可接受动作集合，并校验原始动作空间；不从旧响应抄答案。
- plan：标当前目标表允许的调整、必要目标、禁止的重复／无关目标与预算约束。
- decompose：标目标的必要前置步骤、顺序约束、当前已满足的步骤和不可执行／无关任务。
- summary：用完整下级源记录、verify 标注、来源章构建事实保真度与正负保留要求，
  不要求摘要逐字匹配；task、episode、run 分列。

评测输入与评分真值分离。缺标签不计入相应指标分母；待审材料不得伪称可评分 golden。
不同生产 schema 的既有 judge / choose 冻结版本保留，新采集另建版本。


## 已落地的数据版本与消费边界

二十例在固定提交 `5d1ff1e` 上运行，schema 为 `11a4afa05e6ed43d`。
原始请求和响应、开始/结束、trace、正式起点与逐例报告保存在
`evals/dataset/brain_calls/v1/sources.zip`，逐条 SHA 见 `sources.manifest.json`。
完整生产输入在五族 `inputs.jsonl`，独立评分依据在 `references.jsonl`，旧输出不进真值。
`load_inputs` 与 `load_references` 分开提供；范围不一致直接拒绝导出。

`brain_goal_judge` 已改名 `brain_judge`；`brain_choose_action` 已改名 `brain_choose`。
已有 judge v1/v2 与 choose v1 按原始字节保留，默认版本不变。
新 judge v3 显式携带层级与原始身份，运行指标按层分列；episode 原始空 task_id 不补造。
choose v2 只收独立规则能给出动作集合的子集，保留方向键和等价脚本。
其余调用完整保留，使用证据 rubric 或待审标记，不混入动作命中率/四格指标分母。
plan 与 decompose 已各自注册独立公开任务，独立清单固定本批输入与参考哈希；summary 的输入、约束与证据量表继续单独保留。

```powershell
python -m evals.dataset.brain_calls.verify_dataset evals/dataset/brain_calls/v1
inspect eval evals/brain_plan/task.py -T version=v1
inspect eval evals/brain_decompose/task.py -T version=v1
inspect eval evals/brain_judge/task.py -T version=v3
python -m evals.brain_choose --version v2
```

从新批次构建时使用不存在的输出目录；入口不调用模型、不覆盖冻结数据：

```powershell
python -m evals.dataset.brain_calls.build --batch eval_results/<batch> --out <collection> --judge-out <judge-version> --choose-out <choose-version>
```

本批检出两个旧机械规则覆盖缺口：商品选项解码未变时，原屏幕已经出现数量框；
投球失败的 `Aww! It appeared to be caught!` 未被旧文本枚举覆盖。
新独立标签严格匹配对应判据与原屏幕/结果文字，不让旧规则覆盖明确原证据。
`baseline_scores.json` 仍如实保留旧机械诊断，不能将其失败无条件解释为真实未达成。
17 条预算跳过账单列，未发生的调用不伪造请求。所有 12 个 Port 的耗时和覆盖见 REPORT。
