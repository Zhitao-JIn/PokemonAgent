# PLAN_console_reviewer —— 控制台交互：同步提问的 review 机制

> 用户 0914 00:2x / 01:5x 定调（两轮纠正后定稿）：**这是控制台，不是观测台。**
> 观测台那套（`RunInteraction` 三槽 + 前端 `POST /runs/{id}/goals` 整栈原子替换）是为
> "另一个线程在写、图线程在读"设计的；控制台没有第二个线程，**槽这个机制整个不成立**。
>
> 人与图之间只剩**两种机制，按"人对什么不满意"分**：
> **插话** = 人对 LLM 返回的**多字段结构体**不满意 → 说一句 → **LLM 带着这句重填**；
> **审** = 人对一个**已给的单一结论**不满意 → **人直接表态**（认 / 推翻）。
>
> 本文是设计，不含实现。**它取代三槽那套，但不取代 `PLAN_planner_v2.md`
> ——后者是 plan 位置 input 的将来实现（渐进披露 + 状态化任务表），本文是它的外套。**

---

## 0. 一句话结论

把"人"从一个**信箱**（谁都能往里投信、图隔一会儿去取）改成一个**函数调用**
（图在某个节点里停下来问一句、拿到答复再继续）。承担这个调用的是 `ConsoleReviewer`，
它是 **harness 内部类**，由 `build.py` 注入图；它要实现的 Protocol 写在
`harness/interface/`（因为**以后还会有别的实现**——测试假件、脚本化回放、
将来真接一个 TUI）。

**它对外只开一个方法**——`inject(req)`：图给一张"表单"（一个多字段结构体的当前版本 +
人能看到的一切上下文），人回一句话（可以是什么都不说），然后由**图自己**带着这句话
去**重问 LLM**。`ConsoleReviewer` 不重问 LLM、不改结构体，它只负责"把人的那句不满
拿到手"。**重问是调用方节点的事**（见 §3.2）。

图本身**一个节点都不加**——人只在**已有节点的内部**被问到。这条约束的硬理由：
`recursion_limit` 是"图长什么样"的函数（`episode_graph.py` 模块文档 + 两个节点数常量），
加节点=改预算；而"问一句"不该付这个代价。

**唯一的例外是 `plan` 位置**：它那里要的不是"对已有东西提意见"，而是"从零给一版目标"，
所以它另有一个 `Planner`（input 来源），不在 `ConsoleReviewer` 的方法面上（§3.1）。

---

## 1. 为什么槽机制必须走

### 1.1 槽为跨线程而生，控制台没有第二个线程

`harness/interaction.py::RunInteraction` 的全部复杂度都来自一件事：**写入方与读取方
不在同一个调用栈上**。

| 槽 | 写入方 | 读取方 | 为什么需要信箱 |
|---|---|---|---|
| `goals` | HTTP 请求线程（`POST /runs/{id}/goals`） | 图线程的 `plan` | 两条线程，只能靠一块共享内存 + 锁 |
| `human_note` | HTTP 请求线程 | 图线程的 `think_action` | 同上 |
| `review` | 图线程 `review` 节点 | HTTP 请求线程（等答复） | **反向**：图会阻塞等，所以要 `await_review_response` 轮询 + 超时 |

控制台里这三对**都不存在**：人就在图的调用栈上（图打印一行、读一行 stdin），
写完的瞬间图就已经拿到了。信箱、锁、轮询间隔（`REVIEW_POLL_INTERVAL = 0.2`）、
超时（`REVIEW_TIMEOUT`）**全部失去存在理由**。

**判决**：`RunInteraction` 整个类删除。它的三个槽按下面三种方式重新落地。

### 1.2 "整栈原子替换"只在有草稿面板时成立

`FromFrontendToRunHarnessSubmitEditReq{kind: "push", goals: list[Task]}` 的语义是
"前端把整张目标表当本地草稿改，点一下全量同步过来"。它的前提是**前端有一份独立的、
可随意编辑而不影响图的副本**——那是网页才有的东西（DOM 里那份草稿）。

控制台里人在命令行打字，不存在"一份脱离图的草稿"。**这个信封删除。**

---

## 2. 两种机制，按"人对什么不满意"分

**判据只有一条**：人不满意的那个东西，是**多字段结构体**还是**单一结论**？

| | **插话** | **审** |
|---|---|---|
| 人不满意的是 | LLM 返回的**多字段结构体** | 一个**已给的单一结论** |
| 那个东西长什么样 | `Action` / 对帧的判读 / 裁决 / goals 表——字段多 | 一个可判定的值：这一局成还是败 |
| 人做什么 | 说一句"这里不对"（**可以什么都不说**） | 直接表态：认 / 推翻 |
| 谁产出最终结果 | **LLM 带着这句话重填** | 人自己（推翻后由 harness 重新盖章） |
| 阻塞？ | **是**——图停下、把表单亮给人、拿到那句（或空）再走 | **是**——图停下等一个表态 |
| 落点 | `observe` / `think` / `act` / `judge`（§3.2） | **只有 `review` 节点**（§3.3） |

**两条关键推论**（都是用户 01:5x 纠正后才对了的）：

1. **"接管（人自己按键）"整个不存在。** 我一度把 `act` 当成"人替代模型按键"，
   **错**。`act` 要处理的 `Action` 字段多（按键名、理由、次数、是否链尾），
   **人填不了**——所以它和 `observe`/`think`/`judge` 一样是**插话**：
   人觉得这一键不对，就插一句，让 LLM 重填那个 `Action`。
   人**从不手填任何字段**。这条路径删掉后，`ConsoleReviewer` 不需要"读键"能力。

2. **"插话"不是信箱投条。** 它和审一样**是阻塞的**——图停下来、把结构体亮给人、
   等人说完（或直接回车跳过）再继续。区别只在**返回值**：插话返回一句"不满"
   （字符串），审返回一个"表态"（枚举）。槽那套的非阻塞语义在这里完全不成立。

**所以 `ConsoleReviewer` 的方法面**：

```python
class ConsoleReviewer:          # harness 内部类，不是一个 Protocol
    def inject(self, req: InjectReq) -> str: ...
        """把一张表单亮给人，收一句反馈（可为空串）。不重问 LLM。"""

    def audit(self, req: AuditReq) -> AuditVerdict: ...
        """把一条结论亮给人，收一个表态。只在 review 节点用。"""
```

> **命名说明**：`Reviewer` 这个名字留着（用户要求保留 `review` 的名字），
> 它下面两个方法分别对应两种机制。审的那个方法**不叫 `review()`**——
> 因为 `review` 在本项目已经指"那个节点"，叫 `audit()` 免得和方法名打架
> （见 §8-Q1 的备选）。

---

## 3. 落点：五个位置，两种机制

用户定调（0914 00:2x）：

> "我以为你说的是 plan，decide，observation 位置的 review 和 review 节点。"

即这不是"某一个节点的功能"，是一个**横切机制**——可以挂在多个节点上。
五个位置，两种机制：

| 位置 | 机制 | 人对什么不满意 | 重问谁 |
|---|---|---|---|
| **plan 位置** | 插话（+ `Planner` 供 input） | 这一版 goals 不对 | `Planner`（现在人 / 将来模型） |
| **observe** | 插话 | 对帧的判读错了 | vision 模型 |
| **think** | 插话 | 这次动作不对 | decide 模型 |
| **act** | 插话 | 这一键不对 | **同一个 decide 模型**（见下） |
| **judge** | 插话 | 这个裁决不对 | judge 模型 |
| **review 节点** | **审** | 这一局成/败的裁定不对 | **人自己** |

### 3.1 plan 位置 —— `Planner` 供 input，插话外套

plan 位置是**唯一有"插槽"概念**的地方，因为它要的东西（下一步做什么）现在有、
将来也有不同来源：

```
        ┌────────────────────────────────────────────────┐
        │  plan 位置                                      │
        │                                                │
   ┌───▶│  ① Planner 给一版 goals                        │
   │    │     └ 现在：人（在控制台里写出这一版）          │
   │    │     └ 将来：模型（PLAN_planner_v2 的渐进披露+  │
   │    │             状态化任务表）                    │
   │    │  ② 插话：这版不行                              │
   │    │     └ 什么都不说 → 落进目标表                  │
   │    │     └ 说一句"不对" → 重来（不限次）             │
   │    │  ③ 表末检：无 PENDING → 可判 done             │
   └────┴────────────────────────────────────────────────┘
```

**两个概念必须分开**（`Planner` 是单独的，用户 0914 00:2x 明确纠正过一次）：

| 概念 | 是什么 | 现在 | 将来 |
|---|---|---|---|
| **`Planner`** | **input 的来源**——给出一版目标 | 人（在控制台里写出） | 模型（`planner_v2` 方案） |
| **插话** | **对这一版的表态**——说一句不满 | 人 | 人（**不换**） |

**为什么要把这两件事拆开**：因为 input 的来源马上要换掉（人→模型），
而**人对模型那一版的否决必须现在就存在**——换来源的那天，否决机制必须已经跑通，
否则就是"换了模型先裸奔一段"。这也是用户说"还是要否决"的原因。

**为什么否决不限次**（用户定调）：控制权全在人手上。真无人值守的那条路不走这里
（见 §6 的 headless 说明）。

**`MAX_GOAL_RETRIES` 删除**：它现在的作用是"同一个目标自动重试几次"
（`reflect.py::goal_retries_exhausted`）。用户定调"有也不是这里决定"——
重试几次是 **plan 读历史后的决策**，不是一个配置常量能预先拍死的。

### 3.2 节点内插话 —— 局内四个位置

`observe` / `think` / `act` / `judge` 四个位置**同一套机制**：在节点**内部**、
在**LLM 产出之后、结果落 state 之前**，把那个结构体亮给人，收一句反馈；
**拿到反馈就带着它重问一次 LLM**（节点内循环，不出图）。

| 位置 | 亮给人的"表单"（结构体） | 收到反馈后做什么 |
|---|---|---|
| **observe** | 对当前帧的判读 | 带反馈重问 vision |
| **think** | `Action`（链路 + 理由 + 次数） | 带反馈重问 decide |
| **judge** | 裁决（成/败 + why） | 带反馈重问 judge |
| **act** | **同一个 `Action`** | 带反馈重问 decide（见下） |

**`act` 的落点要说清楚（这是写文档时发现的一个坑）**：
`Action` 是 `think_action` 产出、并**在那里就展开成逐键队列**的（`pending_presses`），
`act` 只是弹队首、推进世界——**它手里根本没有 LLM 调用**，重问 LLM 不可能在它内部发生。

所以"人觉得这一键不对"必须在**产出 `Action` 的那一格**解决，也就是 `think_action`
的插话点上。**`act` 自己不需要新增任何提问点**——它保持现在"只推进世界"的纯粹性。

那为什么还把它列成一个位置？因为**它是人做这个判断的时机**：
人是在看见"队首那个键要按下去"的瞬间说"不对"。实现上，这个插话点
**位置在 `think_action` 的出口，触发时机是链开始执行之前**。

> **实现注意（必须写进 CHANGELOG）**：插话点落在 `think_action` 出口意味着
> **重问发生在"这一整条链按下第一个键之前"**——所以一条链要么整条按原样执行、
> 要么整条被重出，**不存在"按了前两个键再改后面"**。这是好事（回退问题不存在），
> 但要在文档里说死，免得将来有人以为能在链中间改。

**四个都是"节点内调用"**，一条判据就能记住为什么：

> **提问是一个函数调用，不是一个节点。** 加一个图节点要付 `recursion_limit`
> 的代价（那两个节点数常量），而"问一句"不改变图的形状。

节点内插话的形状（在 LLM 产出后、`return` 前）：

```python
# think_action 内（示意，非最终代码）
action = resp.action
...落 THINK 账...
# ↓ 新增：结构体产出后亮一次，人说了不满就带着它重问
note = deps.reviewer.inject(InjectReq(form=action, obs=state.observation, space=state.action_space))
while note:
    resp = deps.brain_tool.choose(req_with_retry_note(note))   # 带这句重问
    action = resp.action
    ...落账...
    note = deps.reviewer.inject(InjectReq(form=action, ...))    # 再亮一次
# 没反馈（note 为空）才往下展开 pending_presses
```

**重问循环放在节点里而不是 `BrainTool` 里**（与 `choose` 现有的"重试循环在 tool 层"
刻意不同）：tool 层那个循环处理的是**机器失败**（解析错、调用错），
这个循环处理的是**人的意见**——两者触发的条件、要不要带 note、要不要记 `HUMAN_NOTE`
事件都不一样。混在一起会让 tool 层同时认识"重试纠正说明"和"人的不满"两种东西。

### 3.3 局末 —— `review` 节点：**唯一一个"审"**

用户定调（0914 00:1x）：

> "关于 review 节点现在删减功能，只做保留成功和失败的判断。"
> "review 节点（局末）除了裁定成败，还要不要带否决？ → **只裁定成败**"

所以 run 图那个叫 `review` 的节点（名字保留）**只做一件事**：这一局算成算败。
它是**全项目唯一走"审"的地方**——因为只有它面对的答案是**单一结论**（成/败），
人可以自己对它表态；另外五个落点（plan 位置 + 局内四位置）面对的都是多字段结构体，
只能插话让 LLM 重填。

**它接替 `reflect` 的全部工作**（用户定调"去掉 reflect，由 review 节点接替其工作"）：

| 原来 `reflect` 做的 | 现在 `review` 做 |
|---|---|
| `outcomes + [outcome]` | 照做 |
| 成功 → 弹栈 | 改成：置 `COMPLETED`（表化后不删行，见 §4） |
| 失败 + 预算耗尽 → 弹栈 | 改成：置 `FAILED`（**"耗尽"不再是常量算的**——重试与否由 plan 读表决定，§3.1） |
| 失败 + 预算内 → 保留栈顶（重试） | 改成：置回 `PENDING`，等 plan 再决定派不派 |
| **不做路由**（路由在 `_should_retry`） | 接线：人表态 + 状态迁移一起做 |

**为什么人能推翻判定**（用户定调）：

> "可以产生，因为模型会幻读，需要人类纠正。相当于人类否定的时候加一条 note 拼装在最后。"

模型判"这一步成了"可能是幻读（自己觉得做完了，其实没有）。人在局末看 trace，
判错了就推翻，并把**纠正理由作为一条 note 拼在提示词最后**——下一条链（或重开的那一局）
的决策就带着这条纠正。这是 review 节点身上唯一超出"裁定"的职能，且它是
**把 note 交给下游**，不是自己改流程。

**所以 `review` 节点出口**（归 `run_graph.py`）：

```
review ─┬─ 表态为"继续" ─→ plan      （表里还有 PENDING，或人新加了）
        └─ 表态为"结束" ─→ END       （表里没有 PENDING 且人不加）
```

`done` 由 review 写（判据见 §4.3）。

---

## 4. 顺带落地：目标表取代目标栈

用户定调：**"不是弹栈，而是一个目标一个状态"** + **"要层次，作为教训"**。

这与 `PLAN_planner_v2.md` §2 是同一件事——**本文的目标表就是那份设计的 §2.1 数据形状，
外加一个 `parent_id` 字段**（用户新增的要求，planner_v2 原稿没有）。

### 4.1 数据形状

```python
# pokemon_agent/schemas/harness/domain/goal_entry.py（跨层契约）

class GoalStatus(StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    ABANDONED = "abandoned"

class GoalEntry(BaseModel):
    task: Task
    status: GoalStatus = PENDING
    attempts: int = 0
    last_episode_id: str | None = None
    note: str = ""
    parent_id: str | None = None      # ★ 本文新增：层次
```

`RunState`：

```python
plan: list[GoalEntry]      # 替代 goals + attempts（invariant len(attempts)==len(goals) 结构上消失）
outcomes: list[...]        # 不动
```

### 4.2 层次怎么用（教训）

- 一个新目标可以**挂在某个 FAILED/ABANDONED 的目标下面**（`parent_id` 指它）。
  语义是"这个新目标是为了解决那个老目标而拆出来的"。
- **被弃的条目留表**，它同时是两样东西：
  1. **层次上下文**（子目标知道自己在为谁服务）；
  2. **教训**——plan 每次读全表就看见"这个我试过、跑挂了、为什么"
     （`note` 里有人/模型给的失败理由），不用去 trace 里捞。
- **渲染层靠 `parent_id` 缩进**（`prompts/run_plan` 的目标表渲染）：`[0]` / `[1]`
  的 depth 由父子链算，不再由列表下标算。
  **`tools/trace/render.py` 那两处 goal 渲染器改成不记层级了**（0914 定案，本条
  的"两处"作废）：trace 信封里 `Task` / `Goal` 都不带 `parent_id`，层级根本算不出来；
  而位置能从目标文字那行自己数出来，另记一份只会跟 `run_plan` prompt 的**全表序号**
  （`[i]`，含 completed/failed/abandoned 行）撞成"同一个 `[0]` 两种含义"。
  见 `CHANGELOG.md` 2026-09-14 第 91 条。

### 4.3 done 判据与权限划分

**权限**（沿用 `PLAN_planner_v2.md` §2.2 的 R2 裁定，本文不重新论证）：

| 迁移 | 谁 | 触发 |
|---|---|---|
| `PENDING → RUNNING` | `dispatch` | 选中第一个 PENDING 并派发 |
| `RUNNING → COMPLETED` | **harness** | 本局判成功（`outcome.success`，或人推翻了"败"的裁决） |
| `RUNNING → PENDING` | **harness** | 本局失败但**不下结论**——置回待派，让 `plan` 读表后决定"再派 / 换做法 / 放弃" |
| `RUNNING → FAILED` | **harness** | 人审时表态"这个目标放弃"（`MAX_GOAL_RETRIES` 已删，没有"自动耗尽"这条路） |
| 任意 → `ABANDONED` | 人（控制台） / 模型（将来） | 主观放弃 |
| 新增 → `PENDING` | `Planner`（现在人 / 将来模型） | 新目标 |

**注意 `RUNNING → PENDING` 现在是"默认落点"**：一局失败、人没推翻也没放弃，
条目就置回 `PENDING` 等 `plan` 表态。**重试不再是一个自动动作**——
它是 `plan` 看完表之后的一次显式决定（§3.1 那句"重试几次是 plan 的决策"）。

`COMPLETED`/`FAILED` **只能由 harness 盖章**——它们是机械事实（`success` 来自 judge
裁决），让 LLM 或人直接写等于违反 R2「摘要不当证据」。人能做的是**推翻 judge 的裁决**
（§3.3），推翻之后由 harness 重新盖章，人自己不写状态。
（`ABANDONED` 是唯一人能直接写的状态——它是**主观决定**，不是事实，不归 R2 管。）

**done 判据**（`plan.py` 现在的 `not state.goals and not pushes` 作废）：

> 表里没有任何 `PENDING`/`RUNNING` 条目 **且** `Planner` 不新增 → 可判 done。

---

## 5. 具体改动清单

### 5.1 新增

| 文件 | 内容 |
|---|---|
| `harness/console_reviewer.py` | **`ConsoleReviewer`**——读 stdin、写 stdout 的实现（两个方法 `inject` / `audit`）。藏在 `harness/` 内，**不进 `interface/`**（它是**一个实现**，不是契约） |
| `harness/interface/planner.py` | **`Planner` Protocol**——给出一版 goals。控制台实现是"问人"；将来是模型 |
| `harness/interface/reviewer.py` | **`Reviewer` Protocol**——`inject` / `audit` 两个方法（见 §5.3 命名待定） |
| `schemas/harness/domain/goal_entry.py` | `GoalEntry` + `GoalStatus` |

### 5.2 删除

| 文件 | 为什么 |
|---|---|
| `harness/interaction.py`（整个） | 槽机制为跨线程而生，控制台没有第二线程（§1.1） |
| `harness/interface/domain/human_decision.py` | `HumanDecision` 三值（continue/stop/retry）全废——表态现在是 `AuditVerdict`，重试是表状态 |
| `harness/interface/human_reviewer.py` | 被新的 `Reviewer` Protocol 取代（**不是改名，是重新定义契约**——旧的是"给个决策"，新的是 `inject` 收一句 + `audit` 收一个表态） |
| `harness/auto_reviewer.py`（`AutoContinueReviewer`） | 无头模式走新的默认实现（见 §6） |
| `schemas/frontend/communication/FromFrontendToRunHarnessSubmitEditReq.py` | 整栈原子替换是观测台概念（§1.2） |
| `harness/run/nodes/reflect.py` | 并入 `review`（§3.3） |
| `run_graph.py::_should_retry` | 表化后重试是状态迁移，不是路由判断 |
| `config.py::MAX_GOAL_RETRIES` | 重试几次是 plan 的决策，不是常量（§3.1） |
| `RunState.plan_failed` | plan 位置的失败现在由插话处理；`plan_failed` 这个字段没有读者了 |
| `experiment/real_check/common.py::make_interaction_pair` | 造一对槽类；改成造 `ConsoleReviewer` |

### 5.3 改写

| 文件 | 改什么 |
|---|---|
| `harness/run/nodes/review.py` | 走 `audit()` + 状态迁移 + 收 `reflect` 的工作 |
| `harness/run/nodes/plan.py` | plan 位置改成"问 `Planner` → 插话 → 落表"；`apply_goals_edit` 删除 |
| `harness/run/nodes/dispatch.py` | 取第一个 `PENDING`（不再是 `goals[-1]`）；`attempts` 贴着条目加 |
| `harness/run/run_graph.py` | 删 `reflect` 节点与两条边；`plan`/`review` 出口按表判据重写 |
| `harness/run/run_state.py` | `goals`+`attempts` → `plan: list[GoalEntry]`；`plan_failed` 删除 |
| `harness/deps.py` | `reviewer` 类型换成新 Protocol；`interaction` 字段删除 |
| `harness/interface/__init__.py` | 那段"`HumanDecision` 立即加载 / `HumanReviewer` 懒加载"的循环 import 说明**整段作废**（两个名字都没了，循环随之消失） |
| `harness/episode/decide/think_action.py` | **插话的主力落点**：`Action` 产出后亮表单 + 重问循环；`human_note` 那套来源改掉 |
| `harness/episode/press/act.py` | **不改**——它没有 LLM 调用，"act 位置"的插话落在 `think_action`（§3.2） |
| `harness/episode/open/record_observation.py` | 新增插话点（亮判读给对人） |
| `harness/episode/gate/judge.py` | 新增插话点（亮裁决） |
| `schemas/harness/communication/FromHarnessToReviewerReviewReq.py` | `goals: list[Task]` → 整表；响应换成 `AuditVerdict` |
| `tools/trace/render.py` | **本条作废（0914）**：原写"两处 goal 渲染器（第 81、825 行）按 `parent_id` 算 depth"——trace 侧拿不到 `parent_id`（`Task`/`Goal` 都不带），两处 goal 渲染器（`run_start` / `observe`）收成**共用的一份、不记层级前缀**，见 §4.2 与 CHANGELOG 第 91 条 |
| `pokemon_agent/config.py` | 删 `MAX_GOAL_RETRIES`；docstring 里解释它的那段（第 47-49、86 行附近）同步清 |
| `pokemon_agent/build.py` | 造 `ConsoleReviewer` 注入；删 `RunInteraction`/`AutoContinueReviewer` 装配 |
| `experiment/real_check/check_harness.py` | `interaction, reviewer = make_interaction_pair()` → 直接造 reviewer |

**一个容易漏的点**：`observe` 的插话要亮"对帧的判读"——但那个判读**不是 LLM 返回的结构体**，
它是 `PyBoyWorld` 通过 `VisionProvider` 产出的 `Observation`（`world/` 内部）。
所以 observe 位置的插话**要跨到 world 的感知链路**去重问，落点比另三个深。
**一期可以先不做 observe**，把它排到最后（见 §9 的 C5）。

---

## 6. 无头模式（headless）怎么办

控制台实现的另一半是**没有控制台**的时候（真机 run 跑实验、CI、自动回放）。

现在的答案是 `AutoContinueReviewer`（永远 `CONTINUE`）。新的语义变成：

> **`NullReviewer`**：`inject()` 恒返回空串（人从不说任何话）；`audit()` 恒返回"认账"；
> `Planner` 恒返回空表（不新增目标）。

于是无头 run 的行为等价于"人从不插话、从不推翻"：LLM 出什么就是什么，
目标表只由初始那批目标驱动，跑完就结束。**这条路上不再有任何自动重试预算**
——这是 `MAX_GOAL_RETRIES` 删除的代价，需要用户确认接受（见 §8-Q2）。

---

## 7. 与 `PLAN_planner_v2.md` 的关系

**两份文档并存，互不取代。**

| | `PLAN_planner_v2.md` | 本文 |
|---|---|---|
| 管什么 | plan 位置**读什么、怎么读**（记忆索引式披露） | 人**怎么在环里**（提问机制） |
| 状态 | 用户自己的中间思路，**将来用来替换 input** | 现在就要落地的外套 |
| 谁来落 plan 位置的 input | 将来：模型 | 现在：人（`Planner` 的控制台实现） |

**接缝是 `Planner` 这个 Protocol**：本文把它定义成"给出一版 goals"，
控制台实现就是"问人"，`planner_v2` 那套落地后换成"问模型"——
**换的是 `Planner` 的实现，不换审、不换表、不换图**。这正是把 input 与审分开的全部意义。

`planner_v2` §2.1 的数据形状（`GoalEntry`）本文直接采用（外加 `parent_id`），
所以 §5 落地时**两份文档的改动点会重叠在同一批文件上**——
实施顺序上，`planner_v2` §5 的 S1（状态化任务表）与本文 §5.3 的表化改动是**同一批工作**，
做一次即可。

---

## 8. 待拍板

1. **`Reviewer` Protocol 的命名**：用户已定调实现类叫 `ConsoleReviewer`（harness 内部类）；
   **Protocol 的名字尚未定**。另外**两个方法名**也待定——现在写的是
   `inject()` / `audit()`。`inject` 会不会和旧的 `human_note_injected` 事件混淆？
   `audit` 与 `verify`/`judge` 的语义边界要不要拉开？
2. **无头模式接受零重试预算吗**（§6）：删掉 `MAX_GOAL_RETRIES` 后，headless run
   一个目标只跑一局，失败就 `FAILED` 留表、plan 不重试。实验跑法会因此改变
   （现在的默认是 `1 + 2 = 3` 局）。**这条要用户确认。**
3. **插话的触发粒度**：四个局内位置每个都亮一次表单，跑真机时会变成
   "每一条链都停下来等人回车"。要不要**默认静默、人主动喊停才亮**？
   还是**每个位置独立开关**？这直接决定控制台实际好不好用。
4. **重问的次数上限**：人在同一个位置连说十次"不对"要不要拦？现在设计是
   **不限次**（与 plan 位置一致）。但不限次 + 阻塞 = 图可以被人无限吊住，
   至少要有"连续 N 次没有实质变化就报错退出"之类的兜底。
5. **observe 位置跨链到 world 怎么落地**（§5.3 末尾）：它的插话要重问
   `VisionProvider`，而那个链路在 `world/` 里、`harness` 只通过 `GameToolPort` 说话。
   要拉一条新路径（world 暴露"带 note 重感知"），还是**一期不做 observe**？
6. **插话的 note 怎么进 prompt**：`think_action` 现在有 `human_note` 占位符
   （`HUMAN_NOTE_INJECTED` 事件 + `FromHarnessToBrainToolChooseOnceReq.human_note`）。
   人的插话走这条现成管道，还是新开一个字段？**建议复用**（语义几乎相同），
   但那就要决定旧槽机制删掉后 `human_note` 字段的**新来源**就是 `inject()` 的返回。

---

## 9. 实施顺序

| 步 | 内容 | 依赖 |
|---|---|---|
| **C1** | `GoalEntry` + `RunState.plan` 表化（含 `dispatch`/`review`/`plan` 的读写点）——与 `planner_v2` S1 合并做 | 无 |
| **C2** | `Planner` + `Reviewer` 两个 Protocol；`ConsoleReviewer` 实现（`inject` / `audit`） | 无 |
| **C3** | plan 位置接上（`Planner`→插话→落表），删 `apply_goals_edit`/`FromFrontend...SubmitEditReq` | C1, C2 |
| **C4** | `review` 节点改写（`audit` + 状态迁移 + 收 `reflect`），删 `reflect` 节点与 `_should_retry` | C1 |
| **C5** | 局内插话点：**think 先做**（主力落点，复用现有 `human_note` 管道）→ judge → **observe 最后**（它要跨进 world，见 §5.3/§8-Q5） | C2 |
| **C6** | 清理：`RunInteraction`/`HumanDecision`/`AutoContinueReviewer`/`MAX_GOAL_RETRIES`/`make_interaction_pair`；清 docstring 与注释 | C1–C5 |
| **C7** | `CHANGELOG.md` 一条（四段格式）；`scripts/check_graph_phases.py` 跑一遍（节点数变了：run 图 6 → 5） | 全部 |

**C7 的机械核对要点**：run 图从 6 个节点（begin/plan/dispatch/episode/reflect/review）
变成 5 个（删 `reflect`）；那个脚本按 `ast` 抽 `add_node` 字面量核对，
节点数常量与相位表要同步改。

**C5 的 `act` 说明**：`act` 不在改动清单里（§5.3 已写明它不改）——
"act 位置"的插话落在 `think_action`，因为 `Action` 在那里产出、也在那里展开。
