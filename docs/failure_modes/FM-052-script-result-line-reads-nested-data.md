# FM-052 脚本结果摘要读错报告层级，只剩结局码

- 整理日期：2026-10-27（Europe/Berlin）
- 分类：编排执行/观测与记忆缺失
- 状态：已定位，由 step-observation CP2 取代（`result_line` 删除，改存结构化 `outcome`）
- 适用边界：针对 665 之前的实现；以下证据来自代码与一份真实 trace，不是全量统计。

## 现象与触发

脚本动作的 `last_result` 与 `ActMemory.result` 只有结局码（如 `ok`、`battle_started`），脚本本该附带的摘要或失败原因（"钱 3000→2000""钱不够"）没有进入 agent 的下一步输入与记忆。

## 证据与定位

- `pokemon_agent/harness/task/script_report.py::result_line` 取 `report["data"]` 里的 `summary` / `reason`。
- 真实报告是扁平的：`mcp_servers/world_server.py` 把信封 `data` 组装成 `{ok, code, **result.data, calls}`，`mcpclient/world_tool.py` 重建为 `{**body["data"], "events": ...}`，没有名为 `data` 的那一层。
- 真实 trace（`eval_results/full_eval_20261020_01/.../knowledge_wild_encounter/trace`）里脚本的 `write_act_memory` 的 `result` 是裸码。
- 测试喂的是带 `data` 层的嵌套形状，所以一直是绿的。
- `detect_stall` 的停摆签名同样读不到成功脚本的摘要。

## 根因与确认边界

测试夹具的形状与真实报告的形状不一致，没有一个用真实形状的断言。对 agent 决策的实际影响没有做对照实验（下一步观察里仍有钱和背包的新读数，所以多数情况下不会因此做错）。

## 处理方向与取舍

不再拼一行字符串：`ActMemory` 保存结构化 `outcome`（`code`、`ok`、`summary`、`reason`，取自报告顶层），由提示词模块渲染；停摆签名改读 `outcome`。

## 验收要点

用真实的扁平形状断言 `outcome` 带出摘要与原因；成功脚本摘要不同则停摆签名不同，同目标重复仍判停摆。

## 原始记录

- docs/step_observation/spec.md（D5、D7、D8）
- CHANGELOG 668
