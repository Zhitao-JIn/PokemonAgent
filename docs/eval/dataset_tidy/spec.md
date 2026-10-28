# spec —— 评测数据集整理（版本退役与默认版本收口）

> 前置：迁移、判稳、中期数据集（683、685）与中期规则（684）已合入 main；归档 tag `archive/eval-datasets-before-tidy-20261028` 已打在整理前的 main 上（含全部旧版本，随时可 `git show <tag>:<路径>` 或 `git checkout <tag> -- <路径>` 取回）。
> 编号：686。直接在主仓库 main 工作区做（不开 worktree、不开分支），执行方不提交，设计侧验收后提交。

## 一、目标

把 `evals/agent_short_goal_run/dataset/` 收口到"现行的三个版本"，去掉不再使用的历史版本，消除"默认版本是 v1、配置里默认是 merged_583"这类过时的默认值；不改任何现行样本内容。

## 二、决定表

| 编号 | 决定 |
|---|---|
| D1 | **保留**三个版本：`v20261021_retest5`（短期的自由拆解对照，也是 `short_frozen.py`、`mid_dataset.py` 两个构建脚本的父版本）、`v20261028_short_frozen`、`v20261028_mid`。一个字节都不改 |
| D2 | **退役**六个版本：`v1`、`v2`、`v20261021_corrected`、`v20261021_current_state`、`v20261021_merged_583`、`v20261021_retest4`。整目录删除（含各自 `states/`），内容由归档 tag 保存。删除用 PowerShell；路径过长时用"robocopy 镜像空目录再 `rd /s /q`"的办法 |
| D3 | **不做存档去重**：退役后只有 `retest5` 与 `short_frozen` 各一份相同的 22 个存档，约 3.6 MB，不值得改 `source_state` 的解析方式。新增版本时再议（候选做法：共享存档目录加 sha256 引用） |
| D4 | `evals/config.json` 的 `version` 改为 `v20261028_short_frozen`（原来是 `v20261021_merged_583`）；该文件其余字段不动 |
| D5 | `dataset/loader.py` 里 `load_samples`、`load_rubric`、`load` 三个函数现在的默认参数 `version="v1"` 去掉，改为必传（位置参数）。所有调用方显式传版本：生产代码里已有的调用本来都传了；测试里不传的（`tests/evals/agent_short_goal_run/test_budget_wiring.py`、`test_cancel_start.py` 等，先 `git grep -n "load_samples()"` 找全）改为传 `"v20261028_short_frozen"`，若该版本的样本内容导致**已有断言**不成立，则改传 `"v20261021_retest5"`，仍不成立就停下汇报，不许改断言 **追加（设计侧更正）**：此前写的"生产代码里已有的调用本来都传了"不对：`evals/common/capture_selection.py`（第 9 行）、`capture_batch.py`（第 204 行）、`capture_case.py`（第 66 行）三处生产代码都是无参 `load_samples()`，一直靠默认的 `"v1"`。这三处改为显式传版本：在 `capture_selection.py` 里定义一个模块常量 `CAPTURE_DATASET_VERSION = "v20261021_retest5"`（采集走自由拆解的版本，不是冻结版），三个文件都用它；对应的测试里凡是加载真实 `v1`（经默认值或显式 `"v1"`）而失败的，按本条前半句的规则改传 `"v20261021_retest5"`（其次 `"v20261028_short_frozen"`），已有断言不成立就停下汇报，不许改断言。只是在合成数据里把 `dataset_version="v1"` 当作标签的测试不用改 |
| D6 | `tests/prompt/test_prompt_generalization.py` 里读 `v20261021_merged_583` 的 `samples.jsonl` 做"活动提示词注册表不得命中 e2e 样本文本"的检查：改为同时读 `v20261028_short_frozen` 与 `v20261028_mid` 两份 `samples.jsonl`（该脚本的 `--samples` 参数本来就可重复传）。零命中的要求不变；若中期样本新文字被提示词命中（理论上不会），停下汇报命中位置，不要改提示词或放宽检查 |
| D7 | 数据集清单文档 `docs/eval/datasets.md` 由设计侧另写（执行方不碰 docs/） |
| D8 | 不改：现行三个版本的任何文件、`pokemon_agent/`、`docs/`、评分规则与它们的测试、`evals/dataset/` 下的旧格式冻结数据（那是 D33 的 72 个跳过测试的数据，另行处理）、`evals/world_script_execute` 等其他评测的数据 |

## 三、做法

1. 先检索，把结果贴进汇报：`git grep -n "v20261021_retest4\|v20261021_merged_583\|v20261021_current_state\|v20261021_corrected" -- . ":(exclude)CHANGELOG.md" ":(exclude)changelog" ":(exclude)docs"`，以及 `v1`、`v2` 作为数据集版本的引用（`dataset/v1`、`dataset/v2`、`version="v1"` 一类）。预期除退役目录自身、`retest5` 与现行版本的 `revision.json`/`rubric.json`/`coverage.md` 里作为"父版本名字"出现的文字、`evals/config.json`、`test_prompt_generalization.py` 外无其他命中；有别的命中就停下汇报，不要自行处理。
2. 删六个目录（D2）。
3. 改 `evals/config.json`（D4）、`loader.py`（D5）、相关测试（D5、D6）。
4. 不新增常驻测试去断言"哪些版本存在"（会让版本一变测试就坏）；只在生成后做一次核对（第四节）。

## 四、整理后核对（构建步骤的核对，不写成常驻测试，输出贴进汇报）

1. `Get-ChildItem evals\agent_short_goal_run\dataset -Directory` 只剩 `build`、`v20261021_retest5`、`v20261028_mid`、`v20261028_short_frozen`（外加 `__pycache__`）。
2. 三个现行版本逐个 `loader.load(version)` 与 `loader.check`：retest5 得 20 条、short_frozen 得 20 条、mid 得 5 条，都通过；retest5 的 `validate_tiers` 按现状（它没有 tier 字段的旧样本是否通过，以现状为准，如实报告，不为此改任何东西）。
3. 第三节第 1 条的检索再跑一遍，剩下的命中逐条说明为什么保留（父版本名字、文档里的历史叙述）。
4. 现行三个版本的文件哈希与整理前一致：对每个版本目录算全部文件的 sha256 列表（相对路径、sha256），与整理前（可用 `git show HEAD:<路径>` 取）逐个比对，应全部一致。

## 五、验收

- 起点先取全量 pytest 基线（带 `--deselect tests/evals/test_eval_service_wiring.py::test_world_case_caller_closes_world_service_after_each_worker_outcome`，解释器 `D:\Users\GummiGu\PycharmProjects\Pokemon_Agent\.venv\Scripts\python.exe`，junit 用 Python 的 re 读 `<testsuite ` 一行，读完删临时文件；**不要在改文件的同时跑 pytest**）；预期基线 `tests=2961`、failures=0、errors=0、skipped=72。最终 failures=0、errors=0；skipped 为 72 或更少（若有跳过测试原本读的是退役版本，写明）；`tests` 可能略减（若有测试只服务于退役版本而被一并删除，逐个列出并说明理由，不得删除"有效但读不到数据"的测试）。
- 守卫四条 `[ OK ]`；ruff 三项；两种 `git diff --stat` 逐行一致（删除的目录用目录汇总）；`CHANGELOG.md` 顶部新增 686 条目（五段，数字只写亲眼读到的）。
- 汇报"与指示有出入处"如实写：删了什么、改了哪些已有测试断言（预期无）、任何范围外的文件。
- 允许范围：`evals/agent_short_goal_run/dataset/` 下六个退役目录的删除（由用户用 `git rm` 完成，执行方不删）、`evals/agent_short_goal_run/dataset/loader.py`、`evals/config.json`、`evals/common/capture_selection.py`、`capture_batch.py`、`capture_case.py`（只改 `load_samples()` 的调用与那一个常量）、读旧版本或不传版本的测试、`tests/prompt/test_prompt_generalization.py`、`CHANGELOG.md`。超出就停下汇报。不启动模拟器，不调用真实模型。

## 六、不做

不去重存档（D3）；不重新生成数据；不动旧格式冻结数据；不把 oracle 提升入库（另排，等复核的 oracle 写法定下来）；不改 `docs/`。
