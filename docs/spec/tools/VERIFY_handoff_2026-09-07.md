# 交叉验证交接文档（2026-09-07，供第二模型独立复核）

> 触发背景：用户对 09-07 的 harness 解耦重构（方案
> `docs/spec/tools/PLAN_harness_decoupling.md` v5）不放心，换模型重新检测。
> 本文件把**已完成什么、验证过什么、没验证什么、环境坑、判断点**全部摊开，
> 让复核方不依赖原会话上下文就能独立重检。

## 0. 提交链（分支 `feat/model-call-observability-and-providers`，8 个提交）

| commit | 内容 |
|---|---|
| `ca5a407` | 基线快照（重构前工作区全部未提交 WIP，含 BrainTool 层） |
| `dced1b2` | utils 归位：删包根 `utils.py`；`strip_json_fence`→brain 私有；`permission_was_denied`→`episode_utils.py` |
| `617c6eb` | 协议改名：23 个类 → `From{调用方}To{被调方}{函数名}{Req\|Resp}`，文件=类名，req/resp 分文件 |
| `8ee7e3c` | TraceTool：`TraceKind`(28) + `FromHarnessToTraceToolAppendReq`；渲染函数迁 `tools/trace_render.py`；`trace/utils.py`/`tag_attempt.py` 退役 |
| `67b4a8f` | BrainTool 接线：harness 零 `BrainPort`/`FromBrainToolToBrain*`，Brain 只在 `build.py` |
| `69b72e6` | 收尾（断言/import 补漏） |
| `06b7f23` | 方案文档：providers 协议定论不改 |
| `05a3742` | 集成测试跑通，修掉 4 个 req 化接线 bug（见第 3 节） |

**复核第一步：`git log`、`git cat-file -p HEAD`（看 parent）、`git fsck`**——
本机环境的 git 分支 ref 会被静默删除（见第 5 节环境坑 1），链条是手工
恢复的，需要独立核验父链无断裂。

## 1. 五个验收标准 + 可执行检查

```bash
# A. brain 不碰任何实现层（期望 0）
grep -rn -E "from pokemon_agent\.(harness|tools|world|memory|trace|providers)" pokemon_agent/brain --include="*.py" | grep -v __pycache__ | wc -l
# B1. harness 无 BrainPort/TracePort 代码引用（期望 0；docstring 文字引用可留）
grep -rn -E "\b(BrainPort|TracePort)\b" pokemon_agent/harness --include="*.py" | grep -v __pycache__ | wc -l
# B2. harness 不 import brain/world/memory/providers/LocalTrace（期望 0）
grep -rn -E "from pokemon_agent\.(brain|world|memory|providers)|LocalTrace" pokemon_agent/harness --include="*.py" | grep -v __pycache__ | wc -l
# C. tool 只在装配点 new（期望只在 build.py 与 tools/ 自身）
grep -rn -E "BrainTool\(|TraceTool\(" pokemon_agent --include="*.py" | grep -v __pycache__
# D. 旧协议名已死（期望 0）
grep -rn -E "\b(BrainToolDecideReq|BrainDecisionReq|RunPlanReq|BrainPlanResp|MemoryKnowledgeQueryReq|WorldPerceptionResp|MemoryEpisodeSummaryResp|BrainVerdictReq|ReflectReq|VerifyAndSummarizeReq)\b" pokemon_agent evaluation --include="*.py" | grep -v __pycache__ | wc -l
# E. 三个 utils 已死（期望文件不存在）
test ! -f pokemon_agent/utils.py && test ! -f pokemon_agent/trace/utils.py && test ! -f pokemon_agent/harness/tag_attempt.py && echo dead
```

## 2. 集成测试

```bash
# 专用 venv（见环境坑 4），PYTHONPATH 必须先清空（见环境坑 2）
PYTHONPATH= C:/Users/GummiGu/.workbuddy/venvs/pokemon/Scripts/python.exe \
  -m pytest tests/test_integration_tool_layer.py -q
```

测试 = 真实 EpisodeHarness 17 节点图 + 真实 RunHarness + 真实
BrainTool/TraceTool/GameTools（含权限切面）+ 真 LocalTrace + 假
Brain/World/记忆后端。断言：协议翻译（大脑收到的全是第二跳契约）、
调用顺序、trace 事件序列/attempt 盖章/event_id 单调、episode 与 run 的
结算。

**已点亮的 TraceKind**：EPISODE_START/END、RUN_START/END、OBSERVE、
JUDGE_VERDICT、MODEL_CALL(DECISION/JUDGE/PLAN/VERIFY)、THINK、ACT、
LOOK_AFTER、STALL_CHECK、STEP_ADVANCE、MEMORY_READ(四路检索)、
MEMORY_WRITE、JUDGE_CALL、VERIFY_CALL、VERIFY_RESULT、ACTION_SPACE、
PLAN_VERDICT、retrieve_node。

**未点亮（建议补测）**：EPISODE_ERROR、RUN_ERROR、DECISION_FAILED、
PERMISSION_SKIPPED、OBJECT_NOTE、EPISODE_MEMORY_WRITE、
EPISODE_SUMMARY_ERROR、HUMAN_NOTE_INJECTED、memory_read 的
known_objects/knowledge 非空分支。

## 3. 集成测试抓出并已修的 4 个 bug（05a3742）

① 六种边界账（EPISODE_START/RUN_START/RUN_END/RUN_ERROR/EPISODE_ERROR/
PLAN_VERDICT）req 缺 `step`（原实现硬编码 0，episode_end 用 outcome.steps）；
② `OBSERVE` 缺 `step=obs.step`；③ `store_step_episode_memory` 没解包
reflect 响应的 `.entry`；④ run_start 的 `goals`（TaskForHarness）撞
observe 的 `goals`（GoalForBrain），拆出独立 `run_goals` 字段。
→ 提示：原转换是脚本批处理，复核时若发现同类"req 缺字段/字段带错"模式，
很可能还有漏网——第 2 节"未点亮"清单是首选排查区。

## 4. 已知遗留（非本次改动引入，复核时别算到我头上）

- ruff 旧账：E501（中文宽度计 2，几十条）、B905×4、UP042（StrEnum 类）、
  ANN401（`Any`），全部存在于基线（用户 WIP）；
- `pyboy` 未声明进 pyproject 依赖（装 venv 时踩到）；
- `trace_render.py` ~700 行 > 300 行拆分线（取舍记录在 CHANGELOG）；
- tests/ 与 evaluation/tests 在 .gitignore（测试文件未入库，用
  `git add -f` 才可见）；
- harness 直引 `pokemon_agent.trace` 的截图辅助函数
  `read_screenshot`/`screenshot_filename`（唯一残留的跨模块文档性依赖，
  用户已知情未拍板）；
- `memory_tool` 的 `_knowledge_*` 是 mtime 键控确定性 embedding 缓存
  （tool 无状态原则的字面例外，用户已知情）。

## 5. 本机环境坑（复核时直接照做）

1. **git 分支 ref 会被环境静默删除**：任何 `git commit` 后都可能丢
   `refs/heads/feat/...`。恢复：`mkdir -p .git/refs/heads/feat &&
   printf '<sha>\n' > .git/refs/heads/feat/model-call-observability-and-providers`；
   丢 ref 后找提交：`git fsck --lost-found` 挑 dangling commit（按 parent
   + 时间戳）。备份在 `_to_delete/branch_ref_backup.txt`。
2. **uv/pip 子进程会被注入 shim**（safe-delete fail-closed），构建隔离必挂：
   运行前 `export PYTHONPATH=""`；uv 还需 `UV_CACHE_DIR` 指到工作区内。
3. heredoc 里 python 的 `\n` 转义可能被传输层写成 `/n`——改文件用
   `chr(10)` 或逐行 splitlines。
4. 项目专用 venv：`C:/Users/GummiGu/.workbuddy/venvs/pokemon`
   （含 pyboy；项目根 `.venv` 是 Linux 布局残留，Windows 不可用）。

## 6. 建议重点复核的判断点（我做过取舍的地方）

1. `FromHarnessToTraceToolAppendReq` 是"公共字段 + 30 个可选领域字段"
   的宽模型，靠渲染函数入口 assert 兜每个 kind 的必填——宽模型的
   可维护性是否接受；
2. `trace_render.py` 按 kind 内聚单文件 vs 300 行拆分线的取舍；
3. 两跳契约类型不共用、tool 纯转发（model_dump）是否真的比"共享类型"
   更符合分工语义；
4. run 级事件沿用"episode_id 位放 run_id、step=0"的旧约定，没有另设
   字段——是否该为 run 级独立建模。
