# 递归规划二十例标注与任务切换报告（v20261020_1846）

## 数据

- 原料：`brain_calls/v20261020_1846`，由十四例（`3ca4ecd`）与补采六例（`97ab011`）合并；两段 schema 哈希同为 `5d3630f2b479ee78`；`DatasetManifest.source_parts` 记录来源。562/563 只改 trace 渲染与采集控制器，未改被测行为。
- 控制账：`skipped_calls` 一条（door_transition 预算跳过），不是缺失的模型响应。
- 旧版本（v1–v4 等）字节不变，作为参考留档。

## 标注

| 家族 | 总数 | 已标注 | 排除 | 方式 |
|---|---|---|---|---|
| judge | 183 | 183 | 0 | 70 机械标签（保留来源）+ 113 请求可见证据裁定 |
| choose | 122 | 122 | 0 | 建议式；15 例机械动作集合并入可接受动作 |
| plan | 21 | 21 | 0 | 建议式；空计划合法 |
| decompose | 41 | 41 | 0 | 建议式；空更新合法 |

judge 二元标签 64 达成 / 119 未达成；修订后决策标签 130 例（achieved 64、continue 66）。53 例仅评二元准确率，不进完整决策矩阵：33 例机械未达成，以及 20 例生产渲染口径不足以强判 continue/blocked 的墙格目标。

## 判定约定

- 只用请求可见的现场与同请求历史，不读采集时的模型应答。
- 对话文字被截断的现场（“Here you”“All ri”）按“尚未出现完整结果文字”；仅当前缀已能唯一确定结果（“Got away safel”“All right! PIDGEY was”）才算达成。
- blocked 必须有当前层无法解决、需要上层调整的具体阻塞证据；连续撞墙、预算耗尽、下层失败或未出现菜单都不能单独证明。未达成但本层动作或规划仍可推进为 continue。完整决策证据不足时保留二元标签，expected_decision 留空，不强填类别。
- 原始请求含有某字段不代表生产模型能看到它。task judge 的 render_sequence 不展示 walk_map，不能用该地图推出强制 blocked；来源哈希只验证输入对应，不证明标注推理成立。

## 2026-10-20 逐例修订

- choose 修订 86 条：删除只开列表时的出招/用道具/换人/购买宏建议；方向按当前光标或坐标计算；只引用当前 memories，不提前引用按 a 和左右摆动的后续失败；南邻为墙时不建议反复 down；不要求 choose 输出不存在的 stop/重规划动作。
- judge 修订 33 条：门口可绕行 6 条、治疗 task 4 条、治疗 episode/run 2 条、尚未结束的商店对话 1 条改为 continue；另 20 条墙格目标保留 achieved=false，清除超出生产可见证据的强制 blocked。原 33 条 blocked 不再保留为硬标签。
- plan 修订 21 条：明确 updates 只改本层条目的 status/note，不能修改既有目标、验收或预算；失败后唯一目标需重开或替换，不越层修改下层 task 表。
- decompose 修订 22 条：门口 10 次规划按本次坐标、可走地图和状态表给出具体恢复建议，不再把 pending 等同于前置成立；其他后续规划明确更新范围，换目标须新增替代项。
- 重跑 recursive_build/publish_recursive 生成同一批次的修订旁账与四族发布清单；输入、原始参考、sources.zip、20 例采集与旧版本均未改变。Git 提交保留修订前字节，已缓存该版本的消费者需按新清单哈希刷新。
- 本批次修订后没有证据充分的 blocked 硬标签，因此不能用它单独衡量 blocked 召回率；不为维持类别数量而制造真值。
- 修订验证：来源包与五族输入全量核验、367 条 annotation loader 核验通过；递归标注/任务/合并测试 18 passed，既有旁账/建议式评分/判定指标与数据测试 41 passed、7 skipped（依赖旧的两批采集原料，独立 worktree 未恢复）；ruff check 与 ruff format 通过，819 个文件无需格式改动；git diff 确认 brain_calls 原料目录零改动。

## 任务

四个 Inspect 任务默认版本切到 `v20261020_1846`：`brain_choose`、`brain_plan`、`brain_decompose`、`brain_judge`。plan/decompose 的结构检查已使用新请求字段（`max_push`、`max_tasks`、表快照），无需改动。

## 验证

- 假端口跑完整数据集：choose 122、judge 183、plan 21、decompose 41 样本全部成功；假评分员下 choose/plan/decompose 的质量分母等于样本数。
- `ruff check` / `ruff format --check` 通过；`tests/evals`（不含需 deepeval 的两个目录）通过。
- 未调用任何真实模型；真实模型评测另行运行。
- 环境限制：本机缺 `deepeval`（磁盘不足无法安装）、ROM 与旧 `eval_results` 目录，相关既有测试未能运行，与本次改动无关。
