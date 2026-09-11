# 审计/判定调用 43-77 秒：step 记忆渲染里 walk_map 占大头

- 日期：2026-08-31
- 关联 commit：观测台首跑后、审计器上线当天
- 系统状态：全局限速（60fps）后、`audit_steps` 刚上线、StepMemory.render 未精简

## 一、分析（现象）

真实 run 的 trace 里，`judge`/`audit` 的 `model_call` 延迟异常：
单次 43.7 秒、77 秒；`input_tokens` 高达 16K、3.4K。同样的决策调用只有几秒。
影响：一次 episode 收尾（审计+蒸馏）比整局决策还慢，可观测台明显卡顿。

## 二、定位（调查路径）

1. 先看 trace：`model_call` 的 `input_tokens` 是 16K（judge）、3.4K（audit），
   而 `latency_ms` 43s/77s——**LLM 调用时长与输入长度强相关**，先怀疑输入膨胀；
2. 测 `StepMemory.render()` 的实际长度：**一条记忆 1300 字符**；
3. 拆长度构成：before+after 各一份，`walk_map` 字段每份 ~400 字符，
   **两条共 ~800 字符（占 62%）**——而 judge 渲染 3 条历史、audit 渲染整局 8 条，
   输入就这么叠出来的；
4. 关键判断：walk_map 在记忆的前后对比里**几乎不变**（同一地图内恒定），
   而「四邻」（北 G 南 G 西 G 东 G）已给出各方向可通行性，撞墙判断够用。

## 三、解决（改动与取舍）

- `StepMemory.render` 新增 `_render_obs`：渲染 before/after 时**排除 `walk_map`**，
  单条记忆 1300 → 356 字符（-73%）；
- **取舍**：只从渲染排除，原始 `facts` 里 walk_map 仍在（需要坐标推理的消费方可
  直接读，不丢信息）；不用 `max_tokens` 硬截断（会切坏 JSON，见 1024 前科），
  从数据源头瘦身才是正解。

## 四、验证（测试变化）

- 无测试断言长度（渲染是纯展示层，长度变化不影响契约）；
- 端到端复跑：**审计延迟 77s → 11.4s**，审计 `output_tokens` 3420 → 436；
- 遗留：judge 历史（`JUDGE_HISTORY=3`）与审计输入随渲染同步缩 3/4，
  但 token 用量仍无聚合视图（见路线图 P1 可观测）。

## 方法论沉淀

「LLM 调用慢」先看 `model_call` 的 `input_tokens`——**输入膨胀是长延迟的第一嫌疑**；
输入长，先拆渲染/序列化层有没有冗余字段，而不是急着加超时或换模型。
