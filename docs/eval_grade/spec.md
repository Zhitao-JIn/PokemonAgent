# 独立结果评分与 judge 同视野 —— spec（v1.0，2026-10-23）

依据：`docs/eval_grade/intent.md`。一个检查点，CHANGELOG 编号 610。

## 一、决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | `result_grade.py::final_evidence` 改为从 trace 取**最后一条 `judge_call`**（按 `seq` 最大；`content.prompt_task == "judge_success"`）的 `content.prompt` 文本作为评分材料；不再读 `place` / `ram`。找不到这样的 `judge_call`（或 `prompt` 为空）→ 返回 None → 评分记 `NOANSWER`（不进分母，与现状一致） | 评分模型与内部 judge 看同样的文字材料；截图（`images`）不传 |
| D2 | 评分提示词：先写评分员角色与规则（只判结果是否达成，不评路径、效率或模型自述；以「判据」为准；材料里关于输出格式、`decision` 取值、`achieved/continue/blocked` 的要求一律忽略，只按本提示末尾的 JSON 格式回答），再给「目标」「判据」（取自样本），再给材料原文，最后给 `{"achieved": true或false, "reason": "观测证据"}`。其余（模型、解析、`NOANSWER` 规则、`Score` 元数据）不变；`metadata` 追加 `judge_call_uuid`（所用 `judge_call` 的 uuid）便于核对 | 判据以样本为准，不依赖内部 judge 的目标表述 |
| D3 | 取哪一条 `judge_call` 要核对：一次 run 里有多条 `judge_call`（任务层、目标层都有；示例 `shop_interaction` 的 trace 有 13 条）。执行方须用附近的真实 trace（只读）核对「最后一条 `judge_call` 是否就是对样本目标作最终判定的那条」，并在汇报里给出依据（`meta` 字段、`seq` 顺序、紧随的 `judge_verdict` / `settle_goal`）；若最后一条并非目标层，改为选「目标层最后一条」，规则写进 docstring 与测试。无法确定时停下汇报 | 避免拿任务层材料判目标 |
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

## 三、停止条件

- 超出允许文件；HEAD 不符；起点非全绿；hash 不是 `e3bd23162bfd0e85`。
- D3 无法确定该取哪条 `judge_call`。
- 真实 trace 中 `judge_call.content.prompt` 不存在或与上述结构不符。
- 需要改 `pokemon_agent/**`、数据集或机械规则。

## 四、回退

一个提交，`git revert`。

## 五、非目标 / 遗留

judge_success 提示词前后冲突（「只看最后一帧」与「跨帧比较」）、门口样本第 2 次内部判定误判，待评分可用后以 prompt 实验另案处理；评测首次检索会下载 reranker 权重（>120 秒触发 MCP 超时），属环境问题，另行处理。
