# 搭测评框架：judge 机械复核从"引用过但已删除"到可运行 + 接 CI

- 日期：2026-09-01
- 关联 Issue：路线图 P3（`docs/EXPERIENCE_DOCS.md` 第六节）
- 关联 commit：本次改动（`evaluation/` 新增 + CI 接入）
- 系统状态：P0-P2 未完成（`docs/EXPERIENCE_DOCS.md` 路线图），本地 `trace_data/`
  只有自由目标探索的 run，没有 `knowledge_*` 批次数据；`0827` 那批（124 次
  run、13.9% 假阳率）的原始 trace 已不在仓库

## 一、分析（现象）

用户要求"把测评搭起来"。先读 `docs/EXPERIENCE_DOCS.md` 路线图：P3 测评依赖
P0（护栏）+ P1（可观测）+ P2（可审计）都完成，而这三项现状都没做完。同时
两篇经验文档（`0827-false-positive-analysis.md`、`0827-knowledge-baseline.md`）
反复强调一件事：`task_stats` 里 judge 记的成功率不可信（115/124 机械复核后
102/124，13.9% 假阳率，且集中在 5/19 条任务），而复核用的
`probe/audit_verdicts.py` 在当前仓库里**已经不存在**。

## 二、定位（调查路径）

1. `git log --diff-filter=D -- 'probe/*'` 确认 `audit_verdicts.py` 曾存在，
   在 `70f4c4c`（"重构：命名语义统一 + 目录三包"）那次提交被删掉，没有留下
   替代实现；
2. 读 `pokemon_agent/experiment/tasks.py` 头部的九条判据规则 + 自查清单——
   这已经是"判据设计 rubric"，机械复核规则要能翻译这十九条 `success_criteria`
   的字面文本，不是另起一套标准；
3. 读 `pokemon_agent/schemas/domain/observation_from_world.py`（`facts` 字段
   顺序与含义）、`pokemon_agent/world/pyboy_world.py`（`options` 的拼接格式
   是 `" / ".join(screen.options)`）、`prompts/perceive_screen.md`（`foe_hp`
   只能是"危险/较低/过半/较高/满"五档之一）、`schemas/domain/place_in_world.py`
   （`where` 的渲染格式），确认每条规则要读的字段名和字面格式；
4. 用一条真实 trace（`trace_data/run-20260831-192944-4d8827`）核对 JSONL
   的实际形状（`observe` 事件的 `payload.facts` 是 JSON 字符串，`episode_end`
   的 `payload.success` 是字符串 `"True"`/`"False"`），发现本地没有任何一条
   `judge` 来源的事件——本地 trace 全是自由目标探索（`run_episode.py` 走的
   路径），不是 `run_all_tasks.py` 产的 `knowledge_*` 批次，说明**这次没有
   真实数据可以拿来验证复核规则对不对**；
5. 用户中途明确两个方向：先定义 metric/rubric 再写代码；新文件统一放
   `evaluation/`、要接标准 CI/CD——据此把草稿从 `docs/spec/eval/` 挪进
   `evaluation/`，并决定 `evaluation/` 不依赖 `pokemon_agent` 包（只解析
   trace JSONL 的字面结构），换取它的测试可以在 CI 里独立、快速地跑。

## 三、解决（改动与取舍）

- `evaluation/SPEC.md`：四个指标定义（success rate 拆两个数字 + 假阳/假阴/
  无法核对率、cost per run、无效步占比复用现有停摆键 `stall_key()`、每链路
  token 按 `Source` 分组）+ 两块 rubric（判据设计沿用 `tasks.py` 九条，追加
  两条；judge 机械复核五条规则）；
- `evaluation/audit_verdicts.py`：19 条任务的机械复核规则，`RULES: dict[str,
  Callable]` 注册表 + `load_episode()`（纯 stdlib 解析 JSONL）+
  `audit_task()`（按 `chain_id` 复核一条任务的全部 run，产出假阳/假阴/无法
  核对计数）+ CLI；
- `evaluation/tests/test_audit_verdicts.py`：32 个用例。**取舍**：没有真实
  `knowledge_*` 批次数据，改用两种验证——每条规则至少一个手写正例，
  以及**直接把两篇经验文档里写下来的误判场景抄成测试**（"judge 把我方 HP
  下降当成对方受伤的证据""`Choose a POKéMON.` 被当成第三个选项""终帧其实是
  买成功的台词"），让"审计工具能不能拦住那次真实发生过的错误"本身成为可
  运行的断言，而不是空等一批新数据；
- `.github/workflows/ci.yml`：lint（`ruff check` + `ruff format --check`）
  + test（`pytest`，Python 3.11/3.12 矩阵）。**取舍**：不接入
  `audit_verdicts.py` 跑真实批次——它读的 `trace_data/`/`experiment_results/`
  是运行产物、不进 git，CI 环境天然是空的，"审计工具"和"审计工具的单测"
  是两件事，前者需要真实数据才有意义。

## 四、验证（测试变化）

- `evaluation/tests/test_audit_verdicts.py`：32 个用例全绿（`pytest -q`，
  在用户本机真实跑过，exit code 0）；
- `ruff check` + `ruff format --check` 对 `evaluation/` 全过（真实跑过）；
- **遗留（写在 `SPEC.md` 第七节）**：下一次真的跑一批 `knowledge_*` 短任务
  时，把 `evaluation/audit_verdicts.py` 的输出和当时的 `task_stats` 手工
  核对一遍——这是这批规则第一次接触真实数据，之前的验证全部基于合成场景，
  合成场景只能证明"规则读对了 rubric 里写下来的东西"，不能证明"规则在真实
  分布的噪声下不会有新的假阳/假阴"；
- CI workflow 本身未在真实 GitHub Actions 上跑过（本次改动未推送），
  下一次 push/PR 到 `main` 是它的第一次真实验证。

## 方法论沉淀

**判据 rubric 和机械复核规则必须共享同一份"字段从哪来"的调查**——不是先设计
复核逻辑再回头对字段，而是先读 `facts` 怎么拼出来的（`world/pyboy_world.py`
`prompts/perceive_screen.md`），复核规则才不会凭空猜格式（比如 `options` 是
`" / ".join`，`foe_hp` 只有五个合法词，这些不读源码猜不出来）。

**没有真实数据不是停下来的理由，是"用什么代替真实数据"要显式说清楚的理由**：
这次用经验文档里记录过的误判场景当断言，前提是那些场景本身是真实发生过的
（不是编的），复用它们让测试同时起到"回归"和"文档"两个作用；但这不能替代
用真实批次数据验证一遍——遗留项要写下来，不能让"暂时用合成数据"悄悄变成
"永远没有真实验证"。
