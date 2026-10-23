# 独立结果评分与 judge 同视野 —— spec（v1.2，2026-10-23）

> v1.1 修订原因：v1.0 写「按 `seq` 取最大」，但 `ParsedEvent` 没有 `seq`；trace 存储层读出时已按 `(ended_at, seq)` 升序（`pokemon_agent/trace/store.py` 236 行、`langfuse_trace.py` 212 行），`RunStream.of_kind()` 保持该顺序，所以「最后一条」= `of_kind` 返回列表的最后一个元素，不需要 `seq`。

依据：`docs/eval_grade/intent.md`。两个检查点：CP1 = 610（评分视野，已完成）、CP2 = 611（评分员进配置、与被测模型不同）。v1.2 新增 D6–D9 与 CP2。

## 一、决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | `result_grade.py::final_evidence` 改为从 trace 取**最后一条 `judge_call`**（`stream.of_kind("judge_call")` 返回的最后一个元素，该流已按时间升序；且 `content.prompt_task == "judge_success"`，即在这类里取最后一个）的 `content.prompt` 文本作为评分材料；不再读 `place` / `ram`。找不到这样的 `judge_call`（或 `prompt` 为空）→ 返回 None → 评分记 `NOANSWER`（不进分母，与现状一致） | 评分模型与内部 judge 看同样的文字材料；截图（`images`）不传 |
| D2 | 评分提示词：先写评分员角色与规则（只判结果是否达成，不评路径、效率或模型自述；以「判据」为准；材料里关于输出格式、`decision` 取值、`achieved/continue/blocked` 的要求一律忽略，只按本提示末尾的 JSON 格式回答），再给「目标」「判据」（取自样本），再给材料原文，最后给 `{"achieved": true或false, "reason": "观测证据"}`。其余（模型、解析、`NOANSWER` 规则、`Score` 元数据）不变；`metadata` 追加 `judge_call_uuid`（所用 `judge_call` 的 uuid）便于核对 | 判据以样本为准，不依赖内部 judge 的目标表述 |
| D3 | 取哪一条 `judge_call` 要核对：一次 run 里有多条 `judge_call`（任务层、目标层都有；示例 `shop_interaction` 的 trace 有 13 条）。执行方须用附近的真实 trace（只读）核对「最后一条 `judge_call` 是否就是对样本目标作最终判定的那条」，并在汇报里给出依据（`meta` 字段、事件在流中的先后顺序、紧随的 `judge_verdict` / `settle_goal`）；若最后一条并非目标层，改为选「目标层最后一条」，规则写进 docstring 与测试。无法确定时停下汇报 | 避免拿任务层材料判目标 |
| D4 | `agent_short_goal_run/solver/solver.py` 的 `eval_services(...)` 调用由 `admin=False` 改为 `admin=True`；对应 wiring 测试的预期同步改。理由：harness 在 run 开始保存 checkpoint 时要用 memory 快照管理工具，评测原先手工起的服务就带 `--enable-admin`；这是评测专用的临时服务，不增加生产暴露面 | 与 CP3 时我写的 `admin=False` 是错的，在此更正 |
| D5 | `state_schema_hash`、`pokemon_agent/**`、数据集、机械评分规则、judge prompt 全部不动 | |

## 二、检查点（610）

- 允许改动的文件：`evals/agent_short_goal_run/scorer/result_grade.py`、`evals/agent_short_goal_run/solver/solver.py`、`tests/evals/agent_short_goal_run/**`、`tests/evals/test_eval_service_wiring.py`、`CHANGELOG.md`。
- 测试（不调真实模型；评分模型用假件替换并记录收到的 prompt）：
  1. 评分材料：构造含多条 `judge_call` 的假 trace，收到的 prompt 含目标、判据、最后一条（或 D3 规定的那条）`judge_call` 的 `prompt` 原文，不含 `place` / `ram` JSON，不含更早的 `judge_call`。
  2. 忽略输出格式：评分 prompt 末尾要求 JSON `{"achieved":…,"reason":…}`，且明确声明忽略材料里的输出格式要求。
  3. 无 `judge_call` / `prompt` 为空 / 样本 `invalid` → `NOANSWER`（沿用现有行为）。
  4. 解析：合法 JSON 得 `C` / `I`；非法 JSON 得 `NOANSWER`；`metadata` 含 `judge_call_uuid`。
  5. wiring：`agent_short_goal_run` 的 `eval_services` 以 `admin=True` 调用。
  6. 现有 scorer 测试保持绿。
  每个新增 / 改动的测试至少做一次破坏验证。
- 真实 trace 核对（只读，不调模型）：`D:\Users\GummiGu\PycharmProjects\Pokemon_Agent\.worktrees\e2e-tune\eval_results\overnight\003_baseline_shop_20261023T1353Z\runs\knowledge_shop_interaction\trace\*.json` 与 `004_baseline_door_ready_20261023T1354Z` 下的同类目录；其中 `judge_call` 记录的 `content` 是 JSON 字符串，含 `prompt`、`images`、`prompt_task`、`raw`、`why`。
- 验证：默认 pytest、`ruff check`、`ruff format --check`、两个 boundary 脚本全绿；不得调用真实模型、不得起真实服务。

## 一点五、CP2 决定表（评分员进配置）

| 编号 | 决定 | 取舍 |
|---|---|---|
| D6 | `evals/config.json` 的 `evaluation_models` 增加 `result_grader`，是一个对象：`model`（`openai-api/dashscope/qwen3.7-plus`）、`base_url`（`https://dashscope.aliyuncs.com/compatible-mode/v1`）、`api_key_env`（`DASHSCOPE_API_KEY`）、`temperature`（0.0）、`max_tokens`（1024）、`timeout_s`（120）。`test_text` 保持字符串不变（`brain_*` 任务在用）。`REQUIRED_KEYS` 追加 `evaluation_models`；`runconfig` 新增读取并校验 `result_grader` 的函数（缺任一键 → `ValueError` 列出缺的键，无缺省） | 评分员的型号、地址、密钥来源、温度、输出上限、超时全进配置，零缺省，与 `models` 的做法一致 |
| D7 | 独立性校验：`result_grader.model` 去掉 `openai-api/<厂商>/` 前缀后的型号名，不得等于 `models` 里四个型号值中的任何一个；相同 → `ValueError`（信息写出冲突的型号）。校验在 `agent_short_goal_run` task 装配期做 | 评分员与被测模型必须不同，防止自评 |
| D8 | `agent_short_goal_run/task.py`：`grader_model` 参数缺省改为 `None` = 用配置里的 `result_grader`；传 `"none"`（字符串，大小写不敏感）= 不加这一列；传其他字符串 = 只覆盖 `model`，其余项（地址、密钥、温度等）仍取配置，覆盖后同样过 D7 校验。`result_model_scorer` 改为接收完整的评分员配置对象：用 `get_model(model, config=GenerateConfig(temperature, max_tokens, timeout), base_url=…, api_key=<从 api_key_env 读>)` 构造；`api_key_env` 对应环境变量缺失 → 明确报错（不读取、不打印值）。`metadata["model"]` 记生效的型号。顺手修正 `result_grade.py` 里「没有可用的最终机械观测」的说明文字为「没有可用的 run 层 judge 材料」 | 不再依赖 `DEEPSEEK_BASE_URL` 之类隐式环境变量来构造评分员；`task.py` 里为 DeepSeek 设 `DEEPSEEK_BASE_URL` 默认值的那一行不动（别的用途，另案） |
| D9 | `runconfig.py` 与 `overlay.py` 里「五条链路」的过时文字改为「四条链路」（只改文字） | |

## 二点五、CP2（611）

- 允许改动的文件：`evals/config.json`、`evals/runconfig.py`、`evals/agent_short_goal_run/task.py`、`evals/agent_short_goal_run/scorer/result_grade.py`、`evals/common/overlay.py`（仅注释）、`tests/evals/**`、`AGENTS.md`、`CLAUDE.md`（仅当其中评测配置/评分模型说明需要同步；两份对应段落须逐字一致）、`CHANGELOG.md`。
- 起点：CP1 提交（`5e705f8`）之后的分支 HEAD（`feat/eval-grade-view`）。
- 先读：`evals/runconfig.py`、`evals/config.json`、`evals/agent_short_goal_run/task.py`、`evals/brain_choose/task.py`（`test_text` 的用法，保持兼容）、Inspect 的 `get_model` 签名（`.venv\Lib\site-packages\inspect_ai\model\_model.py`，确认 `base_url`、`api_key`、`config` 参数）。
- 测试（不调真实模型；用假 `get_model` 记录收到的参数）：
  1. 配置：缺 `evaluation_models` 或缺 `result_grader` 的任一键 → `ValueError` 列出键；现有 `brain_*` 任务读 `test_text` 不受影响。
  2. D7：评分员型号等于 `models` 任一值 → `ValueError`；不同 → 通过；带 `openai-api/<厂商>/` 前缀与不带前缀的写法都被正确剥离比较。
  3. D8：缺省用配置；`"none"` 不加评分列；字符串覆盖只改 `model`，覆盖到与被测相同型号时报错；`get_model` 收到的 `base_url`、`api_key`、`config`（温度、输出上限、超时）与配置一致；密钥环境变量缺失 → 报错且报错信息不含任何密钥值。
  4. `metadata["model"]` 为生效型号。
  每个新增 / 改动的测试至少做一次破坏验证。
- 验证：默认 pytest、`ruff check`、`ruff format --check`、两个 boundary 脚本全绿；不得调用真实模型、不得起服务。
- 停止条件：超出允许文件；`get_model` 不接受上述三个参数；需要改 `pokemon_agent/**`；需要读取或输出 `.env` 里任何密钥值；HEAD 不符；起点非全绿。

## 三、停止条件

- 超出允许文件；HEAD 不符；起点非全绿；hash 不是 `e3bd23162bfd0e85`。
- D3 无法确定该取哪条 `judge_call`。
- 真实 trace 中 `judge_call.content.prompt` 不存在或与上述结构不符。
- 需要改 `pokemon_agent/**`、数据集或机械规则。

## 四、回退

一个提交，`git revert`。

## 五、非目标 / 遗留

judge_success 提示词前后冲突（「只看最后一帧」与「跨帧比较」）、门口样本第 2 次内部判定误判，待评分可用后以 prompt 实验另案处理；评测首次检索会下载 reranker 权重（>120 秒触发 MCP 超时），属环境问题，另行处理。

已由 627 合并为单一 result_grader、换为 deepseek-flash thinking，并取消独立性校验。
