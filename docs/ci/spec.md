# CI 门禁 —— 说明与 spec（v1，2026-10-22）

状态：用户已确认范围（见 D1–D5）。单检查点任务，CHANGELOG 604；若 GitHub 上首跑变红，红的部分另开 605 修。

## 一、为什么做

- `.github/workflows/ci.yml` 已存在（ruff + pytest，3.11/3.12 矩阵），但从未验证过：本地 `main` 领先 `origin/main` 145 个提交，`tests/` 入库后 CI 没有跑过这些代码。
- 2026-10-22 在干净克隆（Linux、Python 3.11、`uv sync --frozen`）实测：
  - `ruff check .`、`ruff format --check .`：全绿（ruff 0.17.2，960 个文件已格式化）。
  - 现有 workflow 的安装方式 `pip install -e ".[dev]"` 会导致 pytest 收集阶段 4 个错误：`deepeval`（在 `[dependency-groups].dev`，不在 extras）与 `pydantic_ai`（`reviewer` extra）都没装。
  - `uv sync --frozen --extra dev --extra reviewer --group dev` 可装好全部依赖。
  - 探针沙箱不通 HuggingFace，`tests/memory/store/test_store_refresh_changed.py` 与 `tests/reviewer/test_memory_view.py` 各 1 例失败，疑为 fastembed 首次使用要下载嵌入模型（`BAAI/bge-small-zh-v1.5`、`BAAI/bge-reranker-base`）；GitHub runner 能联网，但需缓存。这只是推测，以 GitHub 首跑为准。探针未跑完整个套件，全量结果未知。
  - 三个边界脚本：`check_prompt_boundary.py`、`check_world_self_contained.py` 全过；`check_trace_self_contained.py` 报 1 条违规（其 B 项引用已过时，ledger 已记为遗留）。

## 二、决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | 门禁内容 = 用户口径「GitHub 推送时会做的」：`push main` 与 `pull_request → main` 触发 lint、默认 pytest、边界脚本 | 不含 `slow`（默认被 `-m "not slow"` 排除）、不含真实模型、不含 eval |
| D2 | 依赖：`astral-sh/setup-uv` + `uv sync --frozen --python 3.11 --extra dev --extra reviewer --group dev`，只测 3.11 | 与 `uv.lock` 一致；去掉 3.12 矩阵（耗时减半）；`--frozen` 保证锁文件不一致时直接红 |
| D3 | 三个 job 并行：`lint`、`boundary`、`test`；全部通过才算绿 | 原来 test 依赖 lint 串行，改并行更快；分支保护要求三个 job 名都必过 |
| D4 | 边界脚本只接 `check_prompt_boundary.py` 与 `check_world_self_contained.py`；`check_trace_self_contained.py` 暂不接（现在就红，B 项过时） | 另案修脚本后再接，记遗留。执行方须自行核对两个脚本的真实退出码（违规时是否非 0） |
| D5 | pytest 前设置 `FASTEMBED_CACHE_PATH` 指向工作目录内的缓存目录，并用 `actions/cache` 缓存（键含 `uv.lock` 哈希）；不设 `DEEPSEEK_API_KEY`；加 `concurrency`（同分支新提交取消旧运行）与 `workflow_dispatch` | 首跑未命中缓存要下载模型，较慢，可接受 |

## 三、检查点 CP1（CHANGELOG 604）

只改 `.github/workflows/ci.yml` 与 `CHANGELOG.md`（顶部一条）。不改 `pyproject.toml`、`uv.lock`、任何 `pokemon_agent/`、`tests/`、`scripts/`。

验证（执行方本地能做的部分）：
1. YAML 语法能被解析。
2. 在 worktree 里手工执行 workflow 中 `lint`、`boundary` 的命令，退出码符合预期；`test` job 的 pytest 命令在本机跑一遍，汇报尾行。
3. workflow 中引用的每个脚本路径、extra / group 名在仓库里真实存在。
4. GitHub 上的真实运行本机验证不了，由用户推分支开 PR 后看结果。

## 四、停止条件

- 需要改动允许文件之外的任何文件；
- 本机 pytest 有失败（汇报失败清单，不修）；
- 边界脚本（prompt、world）退出码非 0；
- 需要执行被禁止的 git 命令、需要真实模型调用才能继续。

## 五、验收后的步骤

1. 设计侧验收并提交（分支 `ci/gate`）。
2. 用户推送 `ci/gate` 并开 PR → main，看三个 job 是否绿。本地 `main` 比远端领先 145 个提交，PR 的 diff 会很大，属预期。
3. 红的部分贴回，设计侧归因，另开 605 修。
4. 全绿后合入 main；用户在 GitHub 设置里把 `lint`、`boundary`、`test` 设为 main 的必过检查（分支保护）。

## 六、非目标与遗留

- 不做 slow 测试的定时运行、eval 回归门禁（ROADMAP F5）、覆盖率门槛。
- 遗留：`check_trace_self_contained.py` B 项过时，修好后接入 `boundary` job；Windows 本机与 Linux CI 的差异（路径、行尾）如首跑暴露，另案。
