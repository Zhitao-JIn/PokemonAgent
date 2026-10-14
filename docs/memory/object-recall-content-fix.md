# 修复 —— object 族 recall 条目的 `content` 必须是字符串

> 性质：缺陷修复（生产代码，memory 模块）。独立提交，不并入 MCP 管理面或视觉删除。
> 起草：2026-10-14
> 触发：memory MCP 管理面 P4 端到端的第三个样本 `knowledge_npc_dialogue` 失败：
> `ValidationError: 1 validation error for FromHarnessToMemoryToolRecallItem / content / Input should be a valid string, input_value={'episode_id': …}, input_type=dict`。

## 一、根因

契约与实现不一致，且**与传输方式无关**：

- 契约：`FromHarnessToMemoryToolRecallItem.content: str`（"渲染好的可读文本"），且 `extra="forbid"`。
- 实现：`memory/recall.py::_recall_objects` 把 `content` 填成 `event.model_dump(mode="json")`，是 **dict**。
- 进程内的 `MemoryTool.recall` 同样用 `FromHarnessToMemoryToolRecallItem(**item)` 组装信封，所以**进程内模式命中 object 事件时同样会抛错**，MCP 模式只是在 P4 里先遇到。
- 引入于 `f1edaff`（2026-09-29，recall/memorize 收敛）。其余几族的 `content` 都是字符串（act 为动作名、task/episode 为摘要或 markdown、knowledge 为正文）。
- 现有消费方读 object 条目时都用 `item.payload`（`retrieve_object_semantic_memory.py:58`、`read_plan_context.py:63`），不读 `content`，所以改 `content` 的形状不影响它们。
- 为什么测试没拦住：没有任何测试在"库里已有 object 事件"的情况下走完整的 `MemoryTool.recall`。

**对其他工作的影响**：任何在记忆库里已有 object 事件、之后又按 `place` / `map_id` 回忆的运行都会在这一步失败。视觉删除的 S0 基线若不先修，可能混进这类失败样本。

## 二、修复

`_recall_objects` 的 `content` 改为字符串：`json.dumps(event.model_dump(mode="json"), ensure_ascii=False)`。

- 取舍：object 事件没有现成的"可读文本"渲染；JSON 字符串无损、可读、确定性，且消费方只用 `payload`。不为此新增一套渲染。
- `payload` 不变（仍是原始 `payload`）。
- 不改 `FromHarnessToMemoryToolRecallItem` 的字段类型（`content: str` 是对的，错的是产出方）。
- 不改其他几族的 `content`。

## 三、测试（本地 `tests/`，需全绿）

1. 回归：库里先 `memorize` 若干 object 事件，再 `recall(conditions={"place": …})` 或 `{"map_id": …}`，断言返回的 `FromHarnessToMemoryToolRecallItem.content` 是 `str`，且 `json.loads(content)` 等于 `payload` 校验后的 `ObjectFactEvent.model_dump(mode="json")`。**进程内 `MemoryTool` 与经 MCP 的 `MemoryTool` 各测一遍**，结果一致。
2. 混合回忆：同一次 `recall` 同时命中 act / task / object / knowledge，全部条目能通过 `FromHarnessToMemoryToolRecallItem` 校验。
3. 全量 `python -m pytest`、`ruff check`、`ruff format --check` 全绿。

## 四、提交

`修:memory 的 object 回忆条目 content 改为字符串（契约要求 str，进程内与 MCP 同样受影响）`
同一提交附 CHANGELOG 一条（写明根因、影响面、为何此前未暴露）。

## 五、停止条件

- 发现有消费方实际读取 object 条目的 `content` 并依赖它是 dict。
- 其他族也存在 `content` 非字符串的情况（则先汇报清单，不顺手改）。
- 需要改动 `FromHarnessToMemoryToolRecallItem` 的字段定义才能做成。
