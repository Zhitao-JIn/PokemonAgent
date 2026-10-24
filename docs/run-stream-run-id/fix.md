# RunStream.load 的 local 后端按 run_id 过滤 —— 缺陷修复说明

状态：已确认（2026-10-24，用户答复"ok"）。编号：CHANGELOG 636。基线：main 10b1546。

## 根因

`evals/agent_short_goal_run/scorer/stream.py` 的 `RunStream.load`，local 后端读 `trace_root` 下全部事件（空 meta 全量），只按 `meta.branch` 过滤，没有按 `run_id` 过滤。langfuse 后端按 `(run_id, branch)` 寻址，不受影响。

CHANGELOG 633 之后 run 粒度样本的取局口径是“本执行线全部局”（`run_episodes()`、`utils.target_episodes`），其注释与 spec 写的“`run_id` 已由 `load` 定死”对 local 后端不成立。eval 默认每个样本一个独立 trace 目录，平时不暴露；多个 run 共用一个目录时会串账。

离线实测（设计侧评审，旧商店 trace）：传入一个不存在的 run id，`load` 仍读回同样的 276 条事件，并判通过。

## 修法

1. `RunStream.load` 的 local 路径：在 `meta.branch == branch` 之外再要求 `meta.run_id == run_id`（`EventMeta.run_id` 每条账都有，见 `pokemon_agent/direct/trace/content.py` 的 `EventMeta`）。langfuse 路径同样加这个过滤（无副作用）。
2. 更正 `stream.py` 的 `run_episodes()` docstring 与 `scorer/utils.py` 的 `target_episodes` docstring：归属键是 `run_id`，由 `load` 在读取时过滤，不再写“已定死”。
3. 测试：同一个 trace 目录里放两个 run 的账（run A、run B，各有 `episode_start` 与帧）；`load(run_id=A)` 只含 A 的事件，`run_episodes()` 不含 B 的局；传入不存在的 run id 得到空 `RunStream`，`mechanical_scorer` 判 unjudgeable。
4. 核对四个调用方传入的 `run_id` 与写账时用的 run id 一致（`scorer/result_grade.py`、`scorer/task_scorer.py`、`scorer/trace_adapter.py`、`solver/solver.py`）；写账用的是 `solver/runner/one.py` 的 `run_id_for(sample_id, epoch)`。

## 允许改动的文件

`evals/agent_short_goal_run/scorer/stream.py`、`evals/agent_short_goal_run/scorer/utils.py`、`tests/evals/agent_short_goal_run/` 下新增或修改的测试文件、`CHANGELOG.md`。

## 非目标

不改 `TraceTool`、不改 `pokemon_agent/` 下任何代码、不改其他评分器、不引入目标血缘字段。

## 停止条件

- 起点不是全绿（PYTHONPATH 清空后）。
- 四个调用方中任何一个传入的 `run_id` 与写账用的不一致（修完会读空）。
- 需要改 `allowed` 之外的文件才能让测试通过。
- 需要执行被禁止的 git 命令；任何真实模型调用。

## 验证

全量 pytest（PYTHONPATH 清空）、`ruff check`、`ruff format --check`；破坏验证：临时去掉 local 路径的 `run_id` 过滤，新增的隔离用例必须失败，随后还原。
