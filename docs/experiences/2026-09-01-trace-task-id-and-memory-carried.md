# trace 该不该记 task_id：一次质疑一错一半对，外加一个真实的打包 bug

- 日期：2026-09-01
- 关联 Issue：`docs/EXPERIENCE_DOCS.md` 六·1 节（无效步定义、批次记忆隔离）
- 关联 commit：本次改动（`trace/utils.py` `memory_carried` + `pyproject.toml` 打包修复）
- 系统状态：`evaluation/` 刚落地（见前一篇经验文档），P0-P2 仍未完成

## 一、分析（现象）

上一轮我提出四点对 trace schema 的质疑，用户逐条反驳/确认：`task_id` 缺失
那条被指出"是不是没读现有代码"；`episode_memory` 跨 run 检索那条被确认
"是之前的问题"；另外两条（无效步判定、run 级无护栏）用户认为需要更深入的
分析，先记进 roadmap，这次不动。同时要求做一次全局工程视角的复盘。

## 二、定位（调查路径）

1. 读 `pokemon_agent/harness/run_harness.py` 与
   `pokemon_agent/schemas/communication/run_plan.py`：确认 run 级自主拆解的
   目标确实还有 `task_id` 字段（`TaskForHarness.task_id`），但它是 harness
   生成的序号 `plan-{run_id}-{i}`，不携带跨局可比的语义——docstring 原文
   就写着"run 级自主拆解的目标没有实验分组键（那是实验层的概念）"；
2. 读 `tests/reference/example_trace_utils.py`：`test_episode_start_payload_
   carries_goal_and_max_steps` 用 `assert "task_id" not in event[4]` 把
   "实验概念不泄漏"这条契约钉死了——这不是疏漏，是刻意设计并且有测试守着；
3. 结论：**这次的质疑是我读代码不够**。批次实验的分组键（`knowledge_
   wild_encounter` 这类）靠 `run_id` 前缀区分（`run_all_tasks.py` 的
   `batch_run_ids`），trace 本身不需要、也不该重复记这份信息；
4. 读 `pokemon_agent/tools/memory_tool.py` 的 `query_episode_summaries`：
   确认它检索 `all_episode_summaries()`——磁盘上全部历史摘要，只按 `scene`
   过滤，不分是哪个 run、哪个批次写的。这条**质疑站得住**：不是 bug（跨局
   学习就是要这样检索），但对"测评结果能不能当独立试验解读"是个真实风险；
5. 读 `docs/spec/harness/SPEC.md`、`docs/spec/tools/SPEC.md`：发现两份文档
   都写着 `EPISODE_START` 该有 `task_id`/`memory_carried` 两个字段，但代码
   里只有前者被正确移除、`memory_carried` 从来没被实现过——文档描述了一个
   代码从未兑现的承诺；
6. 顺手核实这份承诺现在还成不成立：`memory_carried` 原定义是
   `episode_step_count()`（单步记忆条数），但 2026-08-31 那次"记忆生命周期
   收紧"改动之后 step 记忆按 episode 隔离、蒸馏后即弃，开局时这个数恒为
   0——原定义已经过时，真正能反映"开局带着多少经验"的是
   `episode_summary_count()`（跨局摘要池大小）；
7. 动手改代码前，先跑了一次 `pip install -e ".[dev]"` 想装齐依赖验证，
   撞上 `Multiple top-level packages discovered in a flat-layout:
   ['log', 'web', 'assets', 'config', 'evaluation', 'trace_data',
   'pokemon_agent']`——这条命令在这次改动之前就没有真的跑通过，`evaluation/`
   只是撞见这个坑的第一个新目录。

## 三、解决（改动与取舍）

- `trace_utils.episode_start()` 新增必填参数 `memory_carried: int`（无默认值，
  强制调用方显式传），payload 加一个字段；`EpisodeHarness._begin()` 在写
  `EPISODE_START` 前取 `self._memory.episode_summary_count`；
- 三份 SPEC 文档同步：去掉 `task_id` 的过时声称，`memory_carried` 的定义
  改成 `episode_summary_count` 并写清楚原因；`DATAFLOW.md` 补字段；
- `docs/EXPERIENCE_DOCS.md` 新增"六·1 已知问题"小节：无效步判定方法本身
  站不住（只能抓"连续动作+画面机械状态完全相同"这一种最窄的无效，
  `STALL_LIMIT=5` 在 `max_steps=15` 的短任务里形同虚设）、批次记忆隔离
  要不要做还没结论——两条都只是列出来加一段解释，不在这轮动手；
- `evaluation/SPEC.md` 补两处说明：无效步占比是"下界不是准确值"；
  `memory_carried` 是诊断批次内记忆污染的入口，报表要把它和每次 repeat
  的结果并排列出；
- `pyproject.toml` 补 `[tool.setuptools.packages.find] include =
  ["pokemon_agent*"]`。**取舍**：不做批次记忆隔离（会改
  `build_real`/`run_experiment.py` 的装配方式，且"要不要隔离"取决于
  "测的是纯能力还是带学习的能力"这个还没讨论清楚的问题）；`memory_carried`
  不给默认值（这一局能看到多少经验是调用方已知的事实，不该被这一层悄悄
  归零）。

## 四、验证（测试变化）

- `tests/reference/example_trace_utils.py` 的契约测试同步更新并用
  `python3 -m py_compile` 做了语法检查（本机 Python 3.10，没法真跑
  `pokemon_agent` 全量 pytest——项目要求 >=3.11，装依赖也没有完整跑通过）；
- `evaluation/tests` 32 个用例照旧全绿（这轮没碰 `evaluation/` 的实现代码，
  只改了它的 SPEC 文档）；
- `pip install -e ".[dev]"` 修完打包声明后，`Getting requirements to build
  editable` 那一步从报错变成 `finished with status 'done'`——包发现问题
  确认修好；卡在下一步是本机 Python 版本（3.10 < 3.11），不是打包声明的问题；
- **遗留**：`pokemon_agent/trace/utils.py`/`harness/episode_harness.py` 这两处
  改动没有真实跑过 `pytest`，CI 是它们的第一次真实验证（CI 用
  `actions/setup-python` 装真正的 3.11/3.12，不受本机版本所限）。

## 方法论沉淀

**被质疑"是不是没读代码"时，先去读，不要先辩护。** 这次两条质疑，一条
（`task_id`）确实是读得不够就下结论，代码里连契约测试都钉死了；另一条
（`episode_memory` 跨 run）确实是真实风险。分不清这两种质疑之前，任何回应
都可能是错的——读代码找证据是唯一能分辨"我错了"还是"这确实是个问题"的办法。

**"顺手核实一下能不能装起来"经常比读代码更快找到真实 bug。** 这次的打包
声明缺失、`memory_carried` 定义过时（指向一个生命周期已经变了的方法），
都不是靠读逻辑推出来的，是靠"真的跑一遍"撞出来的——静态阅读代码能确认
设计意图，但确认不了"这套东西现在到底能不能跑起来"。
