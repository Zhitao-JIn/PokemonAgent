# spec —— tests/ 入库（取消 .gitignore 忽略，提交现有测试基线）

> 状态：**已定稿，待执行**
> 起草：2026-10-14
> 决定人：用户（2026-10-14：“重写后的 test 入库”）
> 关联：`docs/test/brain-test-intent.md`、`docs/test/brain-choose-spec.md`（本任务是它的前置）
> CHANGELOG 编号：（N）。**编号不写死**：并行任务也在占用 CHANGELOG 编号。动手写条目的那一刻，读 `CHANGELOG.md` 最上面**已提交**条目的编号 X（用 `git show HEAD:CHANGELOG.md` 看，不看工作区），N = X + 1；写条目前再重读一次 HEAD 版（同一分支上并行任务可能刚提交）。提交信息、条目标题、汇报里的编号都用这个实数。只要工作区的 `CHANGELOG.md` 有**未提交**的改动（别的任务正在写条目），仍然停下汇报。

## 一、一句话意图

让 `tests/` 进入版本库：删掉 `.gitignore` 里的 `tests/` 一行，把现有测试作为基线一次提交，此后每个功能目录的测试正常随提交入库、可回滚、被 CI 看见。

## 二、为什么

1. 我们正按模块重写全部单元测试；重写没有版本控制就没有回退点，也没有可审的 diff。
2. 仓库 `.gitignore` 的 `tests/` 来自历史决定（`925dbe4 移除test` 前后），当时的理由没有记录；用户现在明确要入库。
3. `.github/workflows/ci.yml` 本来就配了 `pytest`，测试不入库等于 CI 的那一步什么都没测。

## 三、决定表

| # | 决定 | 理由 / 代价 |
|---|---|---|
| D1 | **一次性把当前 `tests/` 作为基线入库**，不等重写完成 | 旧测试已搬好目录且全绿；留一部分不入库要写 `.gitignore` 例外，反而乱。代价：git 里会先出现将被重写的旧测试，之后的重写在 diff 里是替换，这正是想要的回退点 |
| D2 | `.gitignore` **只删 `tests/` 这一行**，并把紧跟的两行注释里“跟 `tests/` 同一性质”的措辞改成只说 `experiment/real_check/`；`/experiment/` 的忽略保持不变 | 最小改动；`__pycache__/`、`*.py[cod]`、`.pytest_tmp/` 的忽略保持，不会误入库 |
| D3 | **不提交** brain/choose 任务的 6 个新文件（`tests/_doubles/llm.py`、`tests/_doubles/brain_choose.py`、`tests/brain/choose/` 下四个测试） | 它们属于下一个任务（`brain-choose-spec.md`），按其步骤随它的提交入库；本任务基线 = 其余 81 个文件 |
| D4 | `tests/` 现在会被 `ruff check .` / `ruff format --check .` 扫到（此前因被忽略从未被扫过）。**本任务内修掉 tests 里现存的 ruff 问题**，只做 lint / 格式修正，不改任何用例的行为 | CI 的 lint 闸是 `ruff check .`，入库后必须绿。我在 ruff 0.17 上预扫到 4 处：`tests/direct/trace/test_trace_seq.py:45` B905（`zip()` 缺 `strict=`）、`tests/mcpclient/game_tools/test_game_tools_action_space.py:59` SIM300（Yoda 条件）与 `:64` E501、`tests/mcpclient/memory_tool/test_object_recall_content.py:3` I001（import 排序）；你的 ruff 版本不同，以你实际跑出来的为准 |
| D5 | **不改** `.github/workflows/ci.yml`、`pyproject.toml`；CI 里 `pytest` 能不能在 ubuntu 上全绿（缺 ROM、`deepeval` 只在 dependency-groups 里、sandbox 之外的网络等）**不在本任务内核实**，作为遗留另案 | 本任务只做入库；CI 只在 `main` 的 push / PR 上跑，本分支不触发 |
| D6 | 文档里“tests 本地、gitignore”的历史描述（如 `docs/mcp/memory-admin-spec.md` 第 59 行）**不改** | 它们是写作当时的事实，不是规范 |
| D7 | 行尾：工作区是 CRLF、HEAD 是 LF。新增文件按仓库现有的 git 换行规范化入库（本机 git 已配置），**不手工转换**；提交后用 `git show --stat HEAD` 核对没有整文件异常膨胀 | 与（446）起的做法一致 |

## 四、改动清单

1. `.gitignore`：删 `tests/` 一行，改写紧跟的注释（D2）。
2. `tests/**`：新增入库 81 个文件（现盘上共 87 个，减去 D3 的 6 个）。
3. tests 里满足 D4 的 lint / 格式修正（文件数以实际为准，汇报里逐个列出）。
4. `CHANGELOG.md`：追加（N）条目。

### CHANGELOG（N）

标题：`## 2026-10-14（N）—— tests/ 入库：取消 .gitignore 忽略并提交现有测试基线`

- **改了什么**：`.gitignore` 删掉 `tests/`；把 `tests/` 下 81 个文件作为基线提交；修掉入库后才会被 ruff 扫到的 lint / 格式问题（逐个写明文件）。
- **为什么这么改**：要按模块重写全部单元测试，需要可回退、可审 diff 的基线；`.github/workflows/ci.yml` 已配 pytest，测试不入库等于那一步什么都没测。
- **取舍**：一次性入库当前（含将被重写的）测试，而不是等重写完再入库——留一部分不入库要写忽略例外，反而更乱；CI 能否在 ubuntu 上全绿（缺 ROM、`deepeval` 只在 dependency-groups）本次不核实，另案。
- **影响面**：版本库新增 `tests/`；本地 `ruff check .` / `ruff format --check .` 的扫描范围从此包含 `tests/`；不改任何 `pokemon_agent/` 代码，不改 CI 配置。

提交信息（逐字复用标题，去掉 Markdown 修饰）：
`chore(tests): 2026-10-14（N）—— tests/ 入库：取消 .gitignore 忽略并提交现有测试基线`

## 五、验证

1. 动手前：起点 `python -m pytest`（全新 `--basetemp=.pytest_tmp/run_<序号>`）、`ruff check .`、`ruff format --check .` 的尾行；记下当前 `tests/` 下 `.py` 文件数（不含 `__pycache__`），应为 87；
2. 改 `.gitignore` 后：`git check-ignore -v tests/brain/providers/test_provider_json_mode.py` 无输出；`git status --short tests/` 列出的未跟踪项恰好是 87 个文件所在的目录项（不含 `__pycache__`）；
3. `git add` 用**显式路径列表**（从 `find tests -type f -not -path '*/__pycache__/*'` 的输出里剔除 D3 那 6 个）；提交前 `git diff --cached --name-only | wc -l` = 81 + `.gitignore` + 修正过的文件**不重复计数**（修正过的 tests 文件本来就在那 81 个里）+ `CHANGELOG.md`；提交前不应出现任何 `__pycache__`、`.pyc`、`.pytest_tmp`；
4. 提交后：`git ls-files tests | wc -l` = 81；`ruff check .`、`ruff format --check .` 全绿（现在含 tests）；全量 pytest 与起点同口径（首选全绿；仍触发沙箱删除守卫时用“失败集合不变”兜底），passed 数不变；
5. D3 的 6 个文件提交后仍是未跟踪状态，用 `git status --short tests/` 列出并在汇报里点名。

## 六、停止条件

停下汇报，不自己决定，不重试，不绕过：
1. 起点 ruff 在 `pokemon_agent/` 或其他非 tests 路径上不绿；
2. 修 tests 的 lint 问题时，某个修正会**改变用例行为**（例如给 `zip()` 加 `strict=True` 而两侧长度可能不同；删掉看似未使用但有副作用的 import）；
3. 修完后 ruff 仍有无法在 tests 内解决的问题；
4. `git status` 显示 `CHANGELOG.md` 或 `.gitignore` 里有别的任务的未提交改动；
5. 暂存区里出现 `__pycache__`、`.pyc`、`.pytest_tmp*`、`.venv` 或 D3 那 6 个文件；
6. 全量 pytest 终点与起点不同口径或有新增失败；
7. 任何真实模型调用、联网、读取 ROM。

## 七、遗留（另案，不并入本项）

- CI 的 `pytest` 在 ubuntu 上能否全绿：`deepeval` 目前只在 `[dependency-groups].dev`，而 CI 装的是 `pip install -e ".[dev]"`；缺 ROM 的用例是否都 skip；
- `docs/mcp/memory-admin-spec.md` 等文档里“本地 tests / gitignore”的历史表述；
- `AGENTS.md` / `CLAUDE.md` 第十节“现状”里关于 tests 的核实日期与条数，等整体重写完一并更新。

## 八、非目标

重写任何测试内容；改 CI；改 `pyproject.toml`；brain/choose 的测试（在 `brain-choose-spec.md`）。
