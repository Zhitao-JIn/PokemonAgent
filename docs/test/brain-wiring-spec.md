# spec —— brain/wiring 单元测试（四个 provider 的缺省与回退）

> 状态：**已定稿，待执行**（v1，2026-10-14）
> 上游：`docs/test/brain-test-intent.md` 第 6 节；写法与验证口径沿用 `docs/test/brain-json-utils-spec.md`
> 被测：`pokemon_agent/brain/brain.py::Brain.__init__` 的装配规则，**只经六个公开方法的行为测**（不读 `_decide` / `_verify_llm` 等私有属性）
> 复用夹具：`tests/_doubles/llm.py` 的 `ScriptedJudge` / `text_reply`（不得修改）

## 一、为什么只剩一个很小的文件

intent 里 wiring 目录原计划三条用例。其中两条已被前面的目录实际覆盖，不再重复：
- 「`verify` / `plan` 缺省回退 `judge`」「显式 provider 优先于 `judge`」→ 已在 `tests/brain/judge_verify/`（verify、summarize）与 `tests/brain/plan/`（plan、decompose）里各有专门用例；
- 「每个方法的入口 assert 点名缺的 provider」→ 六个方法在各自目录里都有一条 `pytest.raises(AssertionError, match=...)`。

本目录只补**前面任何目录都没有钉住的两件事**：
1. **谁不回退**：`decide_llm` 不回退到任何 provider；`judge_llm` 不会借用 `verify_llm` / `plan_llm`；`verify_llm` 只服务 verify + summarize，`plan_llm` 只服务 plan + decompose。只有 `verify_llm`、`plan_llm` 缺省时回退 `judge_llm`。这张「四个槽位 × 六个方法」的可用性矩阵就是装配规则本身；
2. **四个都给时各走各的**：每个方法打到自己那一个 provider 上，不串。

## 二、矩阵（已用真实代码探针核实）

只给某一个槽位，其余缺省时，六个方法的结果：

| 只给的槽位 | choose | judge | verify | summarize | plan | decompose |
|---|---|---|---|---|---|---|
| `decide_llm` | 可用 | AssertionError | AssertionError | AssertionError | AssertionError | AssertionError |
| `judge_llm` | AssertionError | 可用 | 可用 | 可用 | 可用 | 可用 |
| `verify_llm` | AssertionError | AssertionError | 可用 | 可用 | AssertionError | AssertionError |
| `plan_llm` | AssertionError | AssertionError | AssertionError | AssertionError | 可用 | 可用 |

## 三、决定表

| # | 决定 | 理由 / 代价 |
|---|---|---|
| D1 | 一个文件 `tests/brain/wiring/test_provider_wiring.py`；矩阵用一个参数化函数，24 组，`id` 形如 `judge_llm-verify` | 失败时一眼看出是哪格 |
| D2 | 「可用」= 调用不抛、且该 provider 收到恰好一次请求；「AssertionError」= `pytest.raises(AssertionError)`，**不**断言文案（文案已在各方法目录断言） | 避免与前面目录重复 |
| D3 | 每个方法给一份最小合法回复，在测试文件顶部用一张表 `CALLS` 定义（方法名 → 调用函数 + 合法回复文本） | 输入空间只有一处 |
| D4 | 不新增 `_doubles` 文件，不改已有文件 | 与前几个目录一致 |
| D5 | 实现与矩阵不符：**停下汇报，不改生产代码，不放宽断言** | 不把缺陷钉成预期 |

## 四、文件与用例

新增（目录不存在则新建，不加 `__init__.py`）：`tests/brain/wiring/test_provider_wiring.py`。

顶部定义：`CALLS: dict[str, tuple[Callable[[Brain], object], str]]`，键是方法名，值是（拿 `Brain` 去调该方法的函数，该方法的最小合法回复文本）。六项：

| 方法 | 调用 | 合法回复 |
|---|---|---|
| `choose` | `brain.choose(prompt="p", keys=["up"])` | `{"action": "up"}` |
| `judge` | `brain.judge(prompt="p", goal="g", history=[])` | `{"done": true}` |
| `verify` | `brain.verify(prompt="p", entries=["e"], goal="g", knowledge="k")` | `[{"index": 0, "positive": true, "why": "w"}]` |
| `summarize` | `brain.summarize(prompt="p", goal="g", history=["h"], success=True, steps=1, max_steps=2)` | `{"summary": "s", "quality_score": 0.5, "quality_rationale": "q"}` |
| `plan` | `brain.plan(prompt="p", goal_stack=[], history=[], max_push=1)` | `{}` |
| `decompose` | `brain.decompose(prompt="p", goal="g", context=[], max_tasks=1)` | `{"tasks": [{"goal": "a", "success_criteria": "s", "max_steps": 1}]}` |

| 函数名 | 装配 / 步骤 | 断言 |
|---|---|---|
| `test_a_method_is_available_only_through_the_provider_slots_that_serve_it`（参数化 4 槽位 × 6 方法 = 24 组；期望值按第二节矩阵） | `Brain(**{slot: ScriptedJudge(text_reply(该方法的合法回复))})`，槽位取 `decide_llm` / `judge_llm` / `verify_llm` / `plan_llm`；调用该方法 | 矩阵里是「可用」：不抛，且该 provider 的 `requests` 长度为 1；矩阵里是「AssertionError」：`pytest.raises(AssertionError)` |
| `test_each_method_uses_its_own_provider_when_all_four_are_given` | 四个 `ScriptedJudge`（`d`、`j`、`v`、`p`），各自按需排足回复：`d` 给 `choose` 的合法回复一条；`j` 给 `judge` 的一条；`v` 给 `verify` 的一条和 `summarize` 的一条（按调用顺序）；`p` 给 `plan` 的一条和 `decompose` 的一条；`Brain(decide_llm=d, judge_llm=j, verify_llm=v, plan_llm=p)`，依次调用六个方法 | 全部不抛；`len(d.requests) == 1`、`len(j.requests) == 1`、`len(v.requests) == 2`、`len(p.requests) == 2` |

合计 25 条（以参数化展开后的实数为准）。

## 五、验证

1. `python -m pytest tests/brain/wiring -p no:cacheprovider` 全绿；
2. 全量 pytest + `ruff check .` + `ruff format --check .`：起点基线与终点逐条一致，passed = 起点 + 新增数；
3. 破坏验证，两处各一次再还原：
   - (a) `Brain.__init__` 里把 `self._verify_llm = verify_llm or judge_llm` 临时改成 `self._verify_llm = verify_llm`：矩阵里 `judge_llm` 行的 verify、summarize 两格必须失败；
   - (b) 把 `self._plan_llm = plan_llm or judge_llm` 临时改成 `self._plan_llm = plan_llm`：矩阵里 `judge_llm` 行的 plan、decompose 两格必须失败；
   还原后 `git diff pokemon_agent/` 必须为空。

## 六、CHANGELOG

标题：`## <日期，同最近条目>（N）—— brain/wiring 单元测试`
- **改了什么**：新增 `tests/brain/wiring/test_provider_wiring.py`，钉住四个 provider 槽位对六个方法的可用性矩阵，以及四个都给时各走各的。
- **为什么这么改**：「谁回退、谁不回退」是 `Brain.__init__` 的装配规则本身，此前各方法目录只各自验证了「缺了会报错」，没有任何用例防止回退关系被改乱。
- **取舍**：缺 provider 的 assert 文案与回退的单项验证已在 judge_verify / plan 目录，不重复；本文件只测矩阵与不串线。
- **影响面**：只增测试，不动 `pokemon_agent/`；新增用例数与 pytest 数字只写亲眼见到的实数。

提交信息标题复用 CHANGELOG 标题原文，前缀 `test(brain): `。

## 七、停止条件

1. 起点 ruff / pytest 不是基线（只有 `test_evals_script_timeout.py` 的 2 条已知失败）；终点失败集合与起点不同；
2. 矩阵任一格与上表不符（贴出槽位、方法、期望、实际）；
3. 需要改 `pokemon_agent/` 或已有测试文件；
4. 暂存区出现预期之外的文件，或 CHANGELOG 暂存 diff 远大于条目大小；
5. 任何真实模型调用、联网、ROM 读取。

## 八、非目标

`reflect` / `domain` / `errors` / `providers` / `factory` / `schemas` 目录；入口 assert 文案；回退的单项验证（已在前面目录）；任何生产代码改动。
