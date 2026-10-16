# spec —— 删除视觉感知档

> 关联：`remove-vision-intent.md`（意图，已确认）
> 状态：**v1.3：S3 提前删除 `evals/episode_vision_read`（它 import 本步要删的 world 视觉模块，原顺序无法同时满足“删除前无他处引用”与“全量测试通过”）；D5 的哈希变化（`b143f3ee76954378` → `4f1cac6fcc7216d5`）已接受，S3 同次重打 v1 存档；待执行**
> 配套：`remove-vision-plan.md`（角色、关卡、回退）
> 前置：CHANGELOG 442（"掩码只由 world 给出"）已测试、已提交。
> 性质：生产代码改动。执行者按 S0–S5 顺序，每步独立提交。

---

## 一、决定（D1–D9）

| # | 决定 |
|---|---|
| D1 | run、episode 的 `sense` 节点改调 `harness/sensing.perceive_task`，观测类型为 `TaskObservation`。`sensing.perceive_once` 删除。 |
| D2 | 凡声明为 `Observation` 且需要保留 `scene` 的状态字段，类型标注改 `TaskObservation`：`harness/run/run_state.py`、`harness/episode/episode_state.py`、`schemas/harness/communication/FromHarnessToBrainToolDecomposeReq.py`、`schemas/harness/domain/episode_io.py`。原因：pydantic 按声明类型序列化，子类装进基类字段会丢 `scene`/`takeover`。`FromHarnessToTraceToolAppendReq.obs` 同理，但要兼容旧账（见 D8），执行者先查 task 层现在怎么存，沿用同一做法。 D2 的类型迁移会改变 `state_schema_hash`，这是预期且已接受的（2026-10-15 裁决），S1 在同一提交里重打 v1 存档。 |
| D3 | 删 `Observation.perceived` 字段与 `BLIND_NOTE`（world 与 `schemas/memory/datastore/act_memory.py` 两处）。`ActMemory.Observation` 保留 `perceived` 字段只为读旧记忆，渲染不再输出那一行。`direct/trace/render.py` 里的 `perceived` 键同步去掉（旧账解析不受影响）。`direct/brain_tool.py` 里的 `_blind` 与 `SNAPSHOT_BLIND` 是记忆过滤（排除 `known_objects`、`knowledge`），保持原样不动。 |
| D4 | 知识检索（`harness/episode/perceive/retrieve_knowledge_semantic_memory.py`）的"场景键"从 `obs.facts.scene_value` 改为 `obs.scene.value`（`TaskScene`）。query 里的 `scene:` 同改。`Facts.scene` 本身**不动**（仍是战斗/空，解码评测的真值用到它），记为遗留，另案处理。 |
| D5 | 删 `overview`：`Facts.overview`、`ScreenState`（整个类及 `NEEDS_OVERVIEW`、校验器）。`ActMemory.Observation.Facts` 里的 `overview` 字段与渲染条目**保留**，只为旧记忆可读。执行者先 `grep overview evals/dataset`，若有真值文件带该键，报告后再动。 |
| D6 | 两个被 `task_perception.py` 借用的函数搬走再删旧文件：`_battle_fields` 移入 `world/task_perception.py`（或 `readout.py`，就近）；`_png_data_uri` 移入新文件 `world/frame_encoding.py`，改名公开的 `png_data_uri`。引用它们的 docstring（`brain/providers.py`、`review_backend/page.py` 等）同步改路径。 |
| D7 | `PyBoyWorld.__init__` 去掉 `vision`、`prompt_name`。所有构造点同步：`mcp_servers/world_server_cli.py`、`mcpclient/game_tools.py`（`GameTools.build`）、`evals/common/world_case.py`（其中的假 vision 删掉）、本地 tests。 |
| D8 | 旧账兼容：`TraceKind.SENSE_CALL`（`schemas/harness/domain/trace_kind.py`）、`direct/trace/{parse,render,__init__}.py` 里它的映射**全部保留**，docstring 标"已停止产出"。`ModelCallContent`/`ModelCall` 因 `step_verify` 等仍在用，不动。`evals/agent_short_goal_run/solver/transcript.py:22` 里 `sense_call → vision_model` 一行删除，并确认该文件对旧账不会因缺这一行而报错。 |
| D9 | `JudgeProvider` 不再借 world 的协议名：在 `brain/interface/llm_provider.py` 里 `JudgeProvider(LLMProvider, Protocol)` 自己声明 `describe(req: VisionDescribeReq) -> VisionDescribeResp`，用 brain 自己的 `brain/schemas/vision.py`。brain 的 `describe()`、`ImageNotDelivered`、`_MultimodalMixin` 全部保留。`brain/vision_factory.py` 整个删除（判定器另有 `judge_model`，不依赖它）。 |

## 二、逐步清单

### S0 基线（执行者 + 用户）
1. 确认 HEAD 含 CHANGELOG 442，`python -m pytest` 全绿，`ruff check` 与 `ruff format --check` 通过。
2. **用户**在 HEAD 上跑一次 `agent_short_goal_run`，存档为基线（费用由用户确认）。基线目录名记入 CHANGELOG。
3. 记录当前 `state_schema_hash`；后面每步跑完看它变没变（变了要重建 agent 存档，归用户）。

### S1 切换取帧（行为变化，先不删代码）
- D6 搬函数；D1、D2、D3、D4 落地。
- `harness/run/perceive/sense.py`、`harness/episode/perceive/sense.py`：改调 `perceive_task(deps, step=frame_step)`；不再记 `SENSE_CALL`；仍记 `SENSE_FRAME`，账面步号语义不变。docstring 中"视觉调用"删去。
- `harness/sensing.py`：删 `perceive_once`，模块 docstring 改为只讲 `perceive_task`。
- 取帧失败语义：`perceive_task` 不抛感知错误，节点里相应的 `MaxRetriesExceeded` 处理分支（若有）删除，并确认 run 层"感知耗尽→整个 run 作废"的路径随之消失（`errors.py`、`harness/run` 里找）。
- 新增/更新测试：sense 节点产出 `TaskObservation`；渲染不含"没做视觉感知"；知识检索场景键随 `TaskScene` 变化而重查；`TaskObservation` 经 state 序列化往返后 `scene` 不丢。
- 提交：`改：run/episode 取帧换成内存观测`。

### S2 删调用链（harness 以下，world 以上）
- 删：`mcpclient/game_tools.py::perceive_with_retry` 及其 `PerceptionAttemptFailed` 翻译；`mcpclient/world_tool.py::perceive_with_retry` / `perceive_once`；`direct/interface/ports.py` 中 `perceive_with_retry` 声明；`schemas/harness/communication/FromHarnessToGameToolPerceiveOnceResp.py`（及其 `__init__` 导出）。
- 删 `mcp_servers/world_server.py::perceive_once` tool；`reset`/`step` 等 tool 中若有"顺带感知"的路径一并核对。
- `backoff.py`、`errors.py`、`brain/errors.py` 里提到 `perceive_with_retry` 的 docstring 改写，`MaxRetriesExceeded` 仍服务 `BrainTool._attempt_loop`，不动。
- 提交：`删：perceive_once 调用链`。

### S3 删 world 视觉档
- 删文件：`world/visual_perception.py`、`world/perceive_frame.py`、`world/prompts/perceive_screen.md`、`world/prompts/__init__.py`（整个 `prompts/` 目录，先确认再无他用）、`world/interface/vision_provider.py`、`world/interface/domain/{perceived.py,vision_describe.py,screen_state.py}`。
- 改：`world/pyboy_world.py`（D7，删 `perceive_once`）、`world/interface/world_port.py`（删 `perceive_once`）、`world/errors.py`（删 `PerceptionAttemptFailed`，保留 `WorldError`）、`world/__init__.py` 与 `world/interface/{__init__,domain/__init__}.py`（导出表、懒加载表去掉 `VisionProvider`、`Perceived`、`ScreenState`、`VisionDescribe*`、`parse_screen`）、`world/interface/domain/facts.py`（D5）、`observation.py`（D3）。
- **v1.3 增补（从 S4 提前）**：删 `evals/episode_vision_read/` 整个目录；`evals/registry.py` 去掉对应条目（六项变五项）；`evals/dataset/frames/build/cli.py` 里对 `episode_vision_read` 的引用同步去掉（先读懂，只删与该评测相关的部分，其余不动）；`evals/dataset/frames/snapshot.py` 的 docstring 里 `perceive_frame` 改为 `perceive_task`；`tests/evals/episode_vision_read/` 整个目录与 `tests/evals/test_evals_tasks.py` 中涉及该评测的用例删除或改写。原因：该评测实际 import 并调用 `world.prompts`、`world.visual_perception`、`VisionProvider`、`PerceptionAttemptFailed`，不随 world 视觉档一起删，仓库就会留下失效评测和测试收集错误。`evals/dataset/frames` 的数据本身不动。
- **v1.3 增补（D5 哈希）**：删 `Facts.overview` 使 `state_schema_hash` 由 `b143f3ee76954378` 变为 `4f1cac6fcc7216d5`，已接受；本步同一提交内用 `python -m evals.agent_short_goal_run.dataset.build.pack` 重打 20 份 v1 存档，`world.state` 的 sha256 必须逐项不变；不再被 manifest 引用的旧 memory 快照 zip 用 `git rm` 删除。
- 提交：`删：world 视觉感知档，并重打 v1 存档`。
- 此步之后 `mcp_servers` 与 `world/` 不再有任何 prompt 文件，也不 import `brain`。

### S4 接线、配置、评测
- 删 `brain/vision_factory.py`；D9；`brain/providers.py`、`brain/schemas/__init__.py` 等处 docstring 改写。
- `build.py`：去掉 `vision_model` 形参与 `"vision": vision_model` 记录（~55、188、322 行）；`GameTools.build` 去掉 `vision_model`；`world_server_cli` 去掉 `--vision-model` 与 provider 构造。
- `evals/config.json` 删 `models.vision_model`；`evals/runconfig.py:36` 的键列表、各处 `--vision-model` 参数删除。
- （v1.3：`evals/episode_vision_read/` 的删除、注册表六变五、`snapshot.py` docstring 已提前到 S3；`evals/common/world_case.py` 的假 vision 也在 S3 随 D7 删除。本步只剩 `vision_model` 接线与配置。）
- 提交：`删：vision_model 接线`。

### S5 测试与文档
- 本地 `tests/` 里：`test_evals_checks`、`test_evals_perceive`、`test_evals_tasks`、`test_evals_vision_cases`、`test_mcp_world_server`、`test_mcp_world_tool` 中涉及视觉档的用例删除或改写；`tests/` 被 gitignore，不进提交，但要全绿。
- 文档：`AGENTS.md`、`CLAUDE.md`（两份同步，约 34/236/337/502/512 行附近）；`docs/spec/world/SPEC.md`、`docs/spec/tools/SPEC.md` 及 `docs/` 下其余提到视觉档的文档：**当前有效的文档改写，历史文档（`changelog/`、`docs/perceive/spec.md`、`plan.md`、各 1007 系列）只在文件头加一行"视觉档已于 YYYY-MM-DD 删除，见 remove-vision-spec.md"**，不改正文。
- `docs/eval/` 中的任务清单与评测分类文档里 `episode_vision_read` 的条目标记为已删除。
- `CHANGELOG.md` 新增一条，写明删了什么、`state_schema_hash` 是否变化、验证命令与结果。
- 提交：`文档：视觉感知档删除`。

## 三、验证

1. 每步结束：`python -m pytest`、`ruff check`、`ruff format --check` 全绿；贴出尾行。
2. S3 之后：`grep -rIn -E "perceive_once|VisionProvider|PerceptionAttemptFailed|perceive_frame|visual_perception|perceive_screen|vision_model|build_vision_provider" pokemon_agent evals` 应只剩：旧账兼容说明、历史文档标注；逐条列出剩余项并说明。
3. S3 之后：`python -m evals --list`（或等价命令）显示五项。
4. 旧账读取：拿一份含 `sense_call` 的旧 trace 目录，经 `direct/trace` 的解析与渲染跑通，无异常（可用现成归档或 `tests` 里的样例）。
5. 端到端（**用户确认费用后**）：S5 完成后再跑一次 `agent_short_goal_run`，与 S0 基线并排给出：整体通过率、逐任务结果、平均每局模型调用数与耗时。**期望**：模型调用数明显下降（少了每圈一次视觉调用）；通过率不显著低于基线。显著下降时，不回滚，报告并列出失败样本的 sense 帧渲染，由我们判断是缺信息（补解码）还是 prompt 问题。
6. S1 的哈希变化（→ `b143f3ee76954378`）与 S3 的哈希变化（→ `4f1cac6fcc7216d5`）已接受并分别随提交重打存档；S4、S5 任一步让哈希再变，先报告，不自行处理。

## 四、停止条件（遇到就停下报告，不自行决定）

- D2：`FromHarnessToTraceToolAppendReq.obs` 无法同时兼容旧账与带 `scene` 的新观测。
- D5：评测真值或数据文件里出现 `overview` 键。
- S1 之后 run/episode 的 prompt 渲染出现 `None`/空块，或出现与旧输出结构不同的新段落。
- 任一步让 `agent_short_goal_run` 无法加载存档以外的原因导致失败。
- 需要改动本 spec 范围外的文件（task 层、解码器、`Facts.scene`、brain 的节点逻辑）。

## 五、非目标

不补解码器；不改 task 层与其 prompt；不动 `Facts.scene` 的取值；不动 brain 的多模态图片通道；不重做 agent 评测的数据口径；不处理 `agent_reviewer`（其"vision"字样与本感知档无关，执行者在 S3 后 grep 确认并在提交说明里写一句）。
