# 夜间自治协议 —— prompt 模块 CP2 至 CP5b

> 适用：执行方在设计侧不在线期间连续执行 CP2 → CP3 → CP4 → CP5a → CP5b。
> 依据：`intent.md`、`spec.md`（v1.0）、`plan.md`、`migration-order.md`；本文只放宽流程，不改设计。
> 授权人：用户（因休息，委托执行方自验收；设计侧次日统一复核，必要时用 `git revert` 按检查点回退）。

---

## 一、授权范围

1. 执行方可连续做完 CP2、CP3、CP4、CP5a、CP5b，每个检查点自行验收、自行提交，通过后直接进入下一个。
2. **不在授权内（做到 CP5b 即停）**：CP6（删除旧字段、删除 `memory/` 旧记忆、改 evals 数据集）、CP7（删旧包、改 `AGENTS.md` / `CLAUDE.md`）。CP5b 提交后写总汇报并停下。
3. 不合并、不推送、不改 main：只在 `refactor/prompt-module` 分支、本 worktree 内工作。

## 二、放宽的 git 权限（仅限本 worktree、本分支）

- 允许：`git add`（只加本检查点允许范围内的文件）、`git commit`（每个检查点一次提交，见第五节标题格式）。
- 仍然禁止：`merge`、`rebase`、`reset`、`stash`、`checkout`、`push`、`branch -D`、`worktree` 操作、改写历史。
- 回退只靠设计侧事后 `git revert`，执行方不得自行回退已提交的检查点；检查点内部可以直接改文件。
- 提交前 `git status` 必须只含本检查点允许范围的文件；有范围外改动一律不提交，停下汇报。

## 三、允许改动的范围（比 plan 第四节的目录级清单略宽，但不越出）

| 检查点 | 编号 | 允许触及 |
|---|---|---|
| CP2 | 589 | `pokemon_agent/world/**`、`pokemon_agent/schemas/memory/datastore/act_memory.py`、`pokemon_agent/mcpclient/**`（仅序列化与契约）、`tests/world/**`、`tests/mcpclient/**`、`tests/prompt/**`、`docs/mcp/**`、`CHANGELOG.md`；另可把 CP1 遗留的 `pokemon_agent/prompt/**` 英文 docstring 改为中文、修正 `BrainTool.build` docstring 中被插断的句子（仅注释，不改逻辑） |
| CP3 | 590 | `pokemon_agent/prompt/**`、`pokemon_agent/direct/brain_tool.py`、`tests/prompt/**`、`tests/direct/prompts/**`（仅当对应测试需要转写）、`CHANGELOG.md` |
| CP4 | 591 | 同 CP3，另加 `pokemon_agent/harness/knowledge_query.py` 及其测试 |
| CP5a | 592 | `pokemon_agent/prompt/**`、`pokemon_agent/direct/brain_tool.py`、`pokemon_agent/mcpclient/action_space.py`、`pokemon_agent/world/interface/domain/action_space.py`、`tests/mcpclient/**`、`tests/world/**`、`tests/prompt/**`、`docs/mcp/**`、`CHANGELOG.md` |
| CP5b | 593 | `pokemon_agent/prompt/**`、`pokemon_agent/direct/brain_tool.py`、`pokemon_agent/harness/episode/perceive/retrieve_object_semantic_memory.py` 及 harness 中为 `known_objects` 传原始事件所必需的最小文件、对应 `tests/harness/**`、`tests/prompt/**`、`CHANGELOG.md` |

- 范围外的文件一律不改；确需改动时停下汇报，不自行扩范围。
- **任何检查点都不得**：删除 `pokemon_agent/direct/prompts/**` 及任何旧 `render` / `index_line` / 旧字符串字段（它们到 CP6 / CP7 才删）；改 `evals/**`；改或删 `memory/` 下任何文件；改 `tests/prompt/golden/**` 中已有文件（golden 是基线，只读）。

## 四、每个检查点的自验收（全部满足才可提交）

1. 起点：上一个检查点的提交已在 HEAD；全量 pytest 无失败无错误。
2. 实现按 `spec.md` 第五节对应小节，第一版**不改任何措辞**（D14）。
3. 对拍：CP3 起，已迁移任务经网关渲染的输出与 `tests/prompt/golden/` 逐字节一致；差异一律视为缺陷，在本检查点内修到一致。历史输入经 `tests/prompt/legacy_adapter.py`（CP2 建立，用往返证明）转换。无法无损还原的样本不入对拍集，数量如实汇报；超过对拍集的 20% 即停下汇报（spec 停止条件 7）。
4. 全量 `pytest`、`ruff check`、`ruff format --check` 全绿。
5. 破坏验证：每个检查点至少两处（例如改动某个 md 一个标点、篡改一个 hash、让守卫触发），确认指定用例失败后原字节还原。
6. `python scripts/check_prompt_boundary.py` 退出码 0。
7. CHANGELOG 用本检查点编号、四段式、数字为亲眼所见；「取舍」段如实记录一切偏离与自行裁量。
8. 守卫新增：CP3 起 `tests/prompt/test_boundary_guards.py` 补充「已迁移任务不再 import `direct.prompts`」的检查，并带负例。
9. 把本检查点汇报写入 `.coordination/prompt-module/reports/CP<n>.md`（目录不存在则新建；该目录被忽略，不进提交）。汇报格式见第六节。

## 五、提交格式

- 标题复用 CHANGELOG 条目标题，加 Conventional Commit 前缀：CP2 `feat(world)`；CP3、CP4、CP5a、CP5b 用 `refactor(prompt)`。例：`refactor(prompt): 2026-10-22（590）—— prompt 模块 CP3：…`。
- 正文末尾两行（原样）：
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WiZceeSdbfNzLhGTZ6u4zz
  ```
- CHANGELOG 标题日期用提交当天的实际日期。

## 六、汇报格式（每个检查点一份，写入第四节第 9 条的文件）

1. 起点 HEAD 与起点 pytest 末行。
2. `git diff --stat` 与未跟踪文件清单（提交前）。
3. 本检查点的关键决定与自行裁量（没有就写「无」）。
4. 对拍结果：用例数、一致数、适配器还原率与跳过原因。
5. pytest、ruff check、ruff format --check、守卫的输出末几行。
6. 破坏验证过程与结果。
7. 提交哈希。

最后一个检查点（CP5b）提交后，另写 `.coordination/prompt-module/reports/SUMMARY.md`：五个提交的哈希、各自的取舍与偏离汇总、CP6 开工前要设计侧决定的事项清单。

## 七、停止条件（遇到立即停下，不重试、不绕过；已提交的检查点不动）

1. spec 第八节全部 8 条。
2. 起点全量测试不绿。
3. 同一个检查点内，对拍差异经两轮修复仍无法在允许范围内消除。
4. 需要改允许范围外的文件、需要被禁止的 git 命令、需要删除任何文件。
5. 需要任何真实模型调用。
6. 发现 spec 与代码事实矛盾，且按任一读法都会改变生产行为（措辞或逻辑）。
7. 任一检查点自验收未全部满足。

停止时：不提交半成品，把现状写入当前检查点的汇报文件（注明停在哪、为什么、已改了哪些文件），保持工作区原样等待设计侧。

## 八、设计侧次日复核

- 逐提交复核：生产 diff、对拍、取舍与偏离、守卫、CHANGELOG。
- 复核发现的缺陷以新提交修复；严重的用 `git revert` 回退到对应检查点之前。
- 通过后再放行 CP6（需用户授权删除 `memory/`）。
