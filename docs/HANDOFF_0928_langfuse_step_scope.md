# HANDOFF 0928 — Langfuse step scope 删除后的 rehearsal crash + 两个新任务

> 交接自 0928 凌晨 session（313 轮）。前情：CHANGELOG 313（verdict 删 io + 3ms 垫 +
> 测试污染结案）已闭环；本轮在其上落地 **step scope 删除**（用户 0928 定稿），
> smoke 已过，**rehearsal 复跑 crash 未解**；用户追加两个新任务（下文任务 A/B）。

---

## 〇、先读这条：上 session 沙箱读数不可信（纪律）

上 session 工具输出多次出现**与磁盘事实矛盾**的回执，包括：

- Edit 回执报不存在的路径变体（`Pokemon_Agent` / `D:\GummiGu\`）；
- 同一文件两次 Read 返回不同内容；
- `ls` 同时列出目录与其 `.tar.gz` 同名变体；
- grep / pytest 回显中出现 AI 起草中、还没写进盘的文案；
- Glob `.env*` **漏掉了项目根的 `.env`**（用户确认文件在——三件套
  `LANGFUSE_BASE_URL` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` 就在里面）；
- 自写仲裁脚本带 bug 却报成功。

**纪律**：关键文件状态要么多工具交叉核对，要么请用户本机 PowerShell
（`Select-String` / `Get-Content`）钉死；发现任何矛盾**立即停手盲改**，如实报告。
pytest / grep 回执别轻信，异常文案出现即视为污染。

---

## 一、已落码（用户本机验证过落盘）

step scope 整层删除（0928 定稿：task_start 直挂 episode_start 子级，不要 step 层）：

- `pokemon_agent/trace/langfuse_trace.py`：
  - 模块 docstring 更新（step 不建 scope，task_start 是最小分组锚）；
  - 新增 `_ANCHOR_KINDS`（task_start/task_end/task_error/checkpoint_save/
    checkpoint_restore——锚账名是树形与恢复伪造的匹配键，**不加** step 标注）；
  - `_parent_for` task 层分支删 step_scope 查找，操作账直挂 task 锚，
    先于 task_start 的开局 `checkpoint_save` 退挂 episode 锚；
  - 删 `_scope_for_step` / `_ensure_step_scope` 两方法；
  - 新增 `_is_task_step_account`（判据：`episode and task and task != run_id
    and task != episode`）+ `_display_name`（非锚的 task 层账名加
    ` (step:N)` 后缀）；append 处 `"name": self._display_name(...)`。
- `tests/test_langfuse_trace.py`：5 用例改按 uuid 取账 / 断言新账名 /
  删 step_scope 查找 / 负断言无 `step:` scope——修后 **29 条全绿**。
- smoke **24/24**（run `handoff-6d8905`，trace `385b5537...`）。

## 二、断点：rehearsal 恢复线 422 crash（未解）

**现象**：rehearsal 第二次复跑 crash；首次复跑报"通过"但分支行数可疑
（3/2/1 vs 此前 15/14/13）。真实 traceback 尾部：

```
File "...pokemon_agent\trace\langfuse_support.py", line 384, in read_observations
    response = client.api.observations.get_many(**kwargs)
langfuse.api.core.api_error.ApiError: ... 422,
body: {'message': 'Your query could not be completed. Please narrow your request
by adding more specific filters (e.g., a shorter date range).\n...',
'error': 'Request timed out'}
During task with name 'review_and_judge' ... During task with name 'act'
```

**触发链**：rehearsal 恢复线 `review_and_judge._settle` → `deps.trace.read_events(...)`
→ `tools/trace/__init__.py:307` `lineage_of(...)` → `langfuse_trace.read_events`
→ `read_observations` → SDK `observations.get_many` 422。

**静态线索**（`langfuse_support.py`）：

- `read_observations`（:368-391）每页都带
  `from_start_time=1970-01-01`（`observation_time_bounds` :347-356）——
  下界故意用 epoch 是因为**恢复线要读上一实例写的历史账**（checkpoint_save 等
  早于本进程构造时刻），数据集只靠 `trace_id` 收窄；
- 422 报文正是 Langfuse 服务端查询超时的标准提示（ClickHouse timeout），
  "shorter date range" 直接点名宽时间窗；
- 但 05:35 rehearsal 同一宽窗通过过——变量不是本轮代码改动（step 删除只会
  减少 span 数），更像 **Docker 内数据积累 / 后台 merge / eventual consistency**
  （首次 3/2/1 很像 OTEL 导出延迟下读到的半量数据）。

**下一步（按序）**：

1. 先复跑一次 rehearsal 判稳定性（瞬时 vs 稳定 422）；
2. 稳定复现则写探针脚本（只连 localhost、密钥不回显，红线见
   `docs/eval/langfuse-test-handoff.md`）：同一 trace_id 二分时间窗
   （epoch → 当天 → 当小时），定位"窗宽×数据量"的阈值；
3. 若收窄即过，修窗口策略。候选：
   a. `read_observations` 增参可传窗口下界（恢复线知道目标 run 的 trace 起点）；
   b. 分页逐页推进 `from_start_time`；
   c. `fields` 减重（`io` 最重；verdict 已删 io 副本，生成侧已经轻了）；
   d. 用户 Docker 侧 ClickHouse/查询超时调参（最后手段）。
   **约束**：下界不许用"本实例构造时刻"（会瞎掉恢复线，docstring :347-356）。

## 三、新任务 A：episode 级账删 task id（用户 0928 定向，未动工）

- 现状（harness 位约定，`_parent_for` / `_is_task_step_account` 反映）：
  meta 三位 `run_id` / `episode_id` / `task_id`——run 层账 task 位放 run_id、
  **episode 层账 task 位放 episode_id**、task 层账 task 位放真 task 号。
- 用户定稿：**episode 级没必要记 task id** → episode 层账的 task 位清空/不写。
- 动工时的连带检查面（先读源码再改）：
  1. 写入侧 meta 组装（`langfuse_trace.py` append 处的 stamped_meta）；
  2. `_is_task_step_account` 判据可简化：episode 层 task 位清空后，
     `task != episode` 条件多余（task 位要么空、要么 run_id、要么真 task 号）；
  3. `_remember_scope` / `_parent_for` 的 scope 键（episode 键是否依赖 task 位）；
  4. LocalTrace 对照 backend 的 meta 口径同步（防 backend 间行为漂移）；
  5. 渲染层 / node_io 按 meta 匹配处；测试里 episode 层账的 meta 断言。
- 顺序建议：**先与任务 B 一起定 meta/树形口径，一次改**。

## 四、新任务 B：task 内 step 之间混杂（用户 0928 定向，未动工）

- 现状：step scope 删了，一个 task 下所有 step 的操作账（sense_frame /
  press_key / generation / verdict / memory 账）全平铺挂 task_start，
  step 边界只剩账名 `(step:N)` 后缀。
- 用户反馈："目前测试时一个 task 里面 step 之间是混杂的"。
- **第一步是定形状，别直接冲修复**：向用户要删 scope 后的 Dashboard 截图，
  确认"混杂"具体指什么——字典序（`step:10` 排 `step:2` 前）？时间序交错
  （长时长账把相邻 step 的账隔开）？还是分组边界消失的观感？
- 候选方案空间（按用户"轻标注、不要 step 层"的方向）：
  1. 账名 step 号补零（`step:03`）治字典序——最小改动；
  2. step 号挪进 name 前缀（`step:3 press_key`）——排序友好度更高；
  3. Dashboard 端排序不可控（Langfuse 自带 UI），若靠时间序则需确认
     Langfuse 同级 observation 的默认排序规则；
  4. 确认混杂形状后与任务 A 合并定一次改动。
- 锚账名稳定性约束（`_ANCHOR_KINDS`）不变：锚账不加任何 step 标注。

## 五、收尾清单（rehearsal 全绿后）

1. **CHANGELOG 313 增补**：step scope 删除条目（本轮改动还没记 CHANGELOG）；
2. 当日日志 `.workbuddy/memory/2026-09-28.md` 追加；
3. `MEMORY.md` 断点更新；
4. 用户 Dashboard 人工抽查新树形（task_start 直挂 episode_start、
   操作账带 `(step:N)`、verdict 行无 input/output）；
5. 用户本机清理 basetemp 残留：`.pytest_tmp_poll1~4` / `.pytest_tmp_wrap1` /
   `.pytest_tmp_step1` / `.pytest_tmp_step2`。

## 六、环境速查

- **LANGFUSE 三件套在项目根 `.env`**（上 session 沙箱 Glob 漏检过，别再找不到）；
- Langfuse Docker 用户本机起（v4.46.0；observations v2 会 308 重定向，
  `langfuse_support.py:139` 自建 httpx client `follow_redirects=True` 已治）；
- smoke：`scripts/langfuse_smoke.py`；rehearsal：`scripts/langfuse_tree_rehearsal.py`；
- 定向测试：`tests/test_langfuse_trace.py`（29 条）；**pytest 一律传全新
  `--basetemp`**（用户级 memory 三号条）；
- 真机 harness 起跑仍归用户本机（用户级 memory 二号条），Langfuse 探针类
  轻量 HTTP 请求 AI 沙箱可跑。
