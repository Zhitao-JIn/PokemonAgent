# plan —— prompt 模块

> 依据：`intent.md`（已确认）、`spec.md`（v1.0）、`migration-order.md`。
> 本文管：角色、顺序、允许改动文件、编号台账、worktree、回退、合入、遗留。

---

## 一、角色

- **设计侧（我）**：写文档、取号、建分支与 worktree、派发、验收、提交、维护台账、裁决停止汇报。
- **执行方**：只做执行（改代码、写测试、跑命令、按给定编号写 changelog、汇报）。**不提交**：不运行 `git add` / `commit` / `merge` / `rebase` / `reset` / `stash` / `checkout`，只用只读 git 命令。
- **用户**：把分支合入主线；在 CP6 授权删除旧记忆；确认任何真实模型运行（本项目无）。

## 二、工作位置

| 项 | 值 |
|---|---|
| 分支 | `refactor/prompt-module` |
| worktree | 仓库内 `.worktrees/prompt-module/` |
| 基线 | `main` @ `2c95ab9` |
| 解释器 | 复用主仓库 `.venv` 的 Python；在 worktree 里不运行 `uv run` / `uv sync` / `pip install` |
| 首个提交 | 设计文档（`docs/prompt_module/{intent,spec,plan,migration-order}.md`），由设计侧在派发前提交 |
| 合入 | 全部检查点验收后由用户合入；同步主线用 merge，不用 rebase |

## 三、检查点顺序与依赖

| 检查点 | 内容 | 前置 | 编号 |
|---|---|---|---|
| CP0 | 对拍基线 | 无 | 587 |
| CP1 | 骨架：网关、注册表、版本入账、守卫、配置 | CP0 | 588 |
| CP2 | world 增量字段化 + 文本→字段适配器 | CP0 | 589 |
| CP3 | 记忆渲染入模块；迁 verify / summarize / summarize_task / summarize_run | CP1、CP2 | 590 |
| CP4 | 迁 judge_success / decompose / run_plan；共用片段 | CP3 | 591 |
| CP5a | decide_action 模板收编；常量消失；ActionSpace 瘦身 | CP4 | 592 |
| CP5b | task_frame、known_objects、脚本排版、重试并入 | CP5a | 593 |
| CP6 | world 与记忆收缩；旧记忆删除；消费方同步 | CP5b | 594 |
| CP7 | 收口：删旧包、守卫全开、文档同步 | CP6 | 595 |

- CP1 与 CP2 无文件交集，但为降低验收复杂度，**默认串行**：先 CP1 再 CP2。
- 编号 596 预留给 spec 补充或某个检查点的修正；任务被驳回时该号留空，不回收。
- 当前台账里 `tests/trace-unit` 占用 584–586，与本线无交集。

## 四、允许改动的文件

### CP0

- 新增：`scripts/capture_prompt_golden.py`
- 新增：`tests/prompt/test_golden_baseline.py`、`tests/prompt/golden/**`
- 新增：`tests/_doubles/prompt_cases.py`（合成用例构造，供对拍复用）
- 修改：`CHANGELOG.md`（条目 587）
- **不得改任何 `pokemon_agent/**`、`evals/**`、其他 `tests/**`。**

### CP1

- 新增：`pokemon_agent/prompt/**`
- 新增：`pokemon_agent/settings/schema/prompt.py`；修改 `pokemon_agent/settings/schema/__init__.py`、`app_config.py`、`pokemon_agent/settings/default.json`
- 修改：`pokemon_agent/direct/brain_tool.py`、`pokemon_agent/build.py`
- 新增：`scripts/check_prompt_boundary.py`
- 新增：`tests/prompt/**`（网关、注册表、hash、compose、守卫）；按需修改 `tests/settings/**` 中枚举配置键的测试
- 修改：`pyproject.toml`（仅当需要把 `.md` / `.json` 打进包数据）、`CHANGELOG.md`（条目 588）

### CP2–CP7

各自派发前补充精确清单（做法同 brain-goal-judge-expansion 的「CP 精确文件范围」补充）。预先登记它们的**触及目录**，供派发前跑文件交集：

| 检查点 | 触及目录 |
|---|---|
| CP2 | `pokemon_agent/world/{interface/domain,task_perception.py,screen_text.py}`、`pokemon_agent/schemas/memory/datastore/act_memory.py`、`tests/world/**`、`tests/prompt/**`、`docs/mcp/**` |
| CP3 | `pokemon_agent/prompt/**`、`pokemon_agent/direct/brain_tool.py`、`tests/prompt/**` |
| CP4 | 同 CP3，另加 `pokemon_agent/harness/knowledge_query.py` |
| CP5a/5b | `pokemon_agent/prompt/**`、`pokemon_agent/direct/brain_tool.py`、`pokemon_agent/mcpclient/action_space.py`、`pokemon_agent/world/interface/domain/action_space.py`、`pokemon_agent/harness/episode/perceive/retrieve_object_semantic_memory.py`、`tests/mcpclient/**`、`docs/mcp/**` |
| CP6 | `pokemon_agent/world/**`、`pokemon_agent/schemas/memory/**`、`pokemon_agent/direct/trace/render.py`、`pokemon_agent/reviewer/hub/context.py`、`evals/decode/**`、`evals/dataset/**`、`evals/dataset/brain_annotations/choose_review.py`、`evals/agent_short_goal_run/scorer/**`、`tests/**` |
| CP7 | `pokemon_agent/direct/prompts/**`（删）、`evals/common/legacy_requests/**`、`AGENTS.md`、`CLAUDE.md`、`docs/spec/**`、`scripts/**` |

## 五、各检查点我的核对点

- **通用**：`git status` 与 `git diff --stat` 在允许文件范围内；CHANGELOG 条目用给定编号、数字为亲眼所见的实数；全量 `pytest`、`ruff check`、`ruff format --check` 三项全绿；行尾未被整体改写（`git diff --ignore-cr-at-eol` 核对）；读承重改动的 diff。
- **CP0**：生产 diff 为空；对拍集规模与跳过数；golden 体积；`test_golden_baseline` 在干净环境通过两次。
- **CP1**：守卫的负例确实触发；注册表校验的四种失败各有测试；盖章三键进入 `payload` 并出现在 trace；旧测试一行未改。
- **CP2**：新旧字段同帧一致；适配器成功率与跳过原因。
- **CP3–CP5**：对拍逐字节一致；旧 `build_prompt` 调用点按任务清零；破坏验证。
- **CP6**：读方清零证据；删除清单；经适配器的对拍仍一致。
- **CP7**：intent 第八节八项逐条机械验证。

## 六、changelog 编号台账

| 号 | 内容 | 状态 |
|---|---|---|
| 587 | CP0 对拍基线 | 已登记，未派发 |
| 588 | CP1 骨架 | 已登记 |
| 589 | CP2 world 增量字段化 | 已登记 |
| 590 | CP3 记忆渲染与四个蒸馏任务 | 已登记 |
| 591 | CP4 judge / decompose / run_plan | 已登记 |
| 592 | CP5a decide_action 收编 | 已登记 |
| 593 | CP5b decide_action 其余 | 已登记 |
| 594 | CP6 收缩与旧记忆删除 | 已登记 |
| 595 | CP7 收口 | 已登记 |
| 596 | 预留（spec 补充或修正） | 预留 |

## 七、回退

一个检查点一个提交，回退用 `git revert <提交>`，不重写历史。CP2 与 CP6 是对称的一增一减：回退 CP6 不影响 CP2 引入的字段。

## 八、合入

- 全部检查点验收后，由用户把 `refactor/prompt-module` 合入主线。合入前我核对：分支相对基线的提交范围；基线之后主线上是否有别的任务改了 `pokemon_agent/world/**`、`pokemon_agent/schemas/memory/**`、`pokemon_agent/direct/**`。
- 涉及生产代码的合并冲突，操作者停下汇报，由我读两边 diff 后裁决。

## 九、耗时（估计）

CP0 约半天；CP1 约 1 天；CP2 约 1 天；CP3 约半天；CP4 约 1 天；CP5 约 1.5 天；CP6 约 1.5 天；CP7 约半天。验收按检查点逐个进行。

## 十、遗留清单（合入后另案）

- 措辞优化：以新版本形式单独进行，不并入本项目。
- reviewer 的 prompt 纳入注册表：本次明确不做。
- 版本化的评测：用「换注册表文件」跑 A/B，需要评测侧补一个入口（不在本项目内）。
