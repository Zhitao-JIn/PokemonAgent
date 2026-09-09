# 项目路线图（ROADMAP）

> 单一权威版本。别处（`docs/EXPERIENCE_DOCS.md`、`evaluation/SPEC.md`）只做链接，
> 不再各自维护一份路线图表格。
> 最后更新：2026-09-09。

## 状态图例

`✅ 完成` `🚧 进行中` `📋 排好序、没开始` `💬 有方案但没拍板` `❓ 连方案草稿都没有`

## 当前优先级（2026-09-02 起）

用户最新明确调整：**前后端交互统一（`RunDataCenter`）排第一优先级**，可观测第二、
测评体系搭建第三——排在最前面是因为它是这次会话发现的最大缺口：人工审查
（`HumanReviewer`）协议齐全但完全没有传输层，线上永远是自动放行的占位桩，"人机
协作"目前是假的；顺带把这条路修好，将来接 LLM 当 reviewer 也是同一套传输层，不用
再建一次。可观测和测评体系的相对顺序判断不变（可观测先、测评体系直接在它的聚合
数据上报数），只是都往后挪了一位；P0 护栏仍然排在三者之后，判断理由不变。下面第一
条排第一，其余按现在的优先级从上到下排列。

**0904 用户改口，提前两项优先级**：第 3 条里"prompt 自动更新和版本管理"（0903 曾
明确说可以往后放，见下方第 3 条正文）、以及一个尚未细化的新想法"episode 打分聚类"
（跟第 18 条 `quality_score` 沾边但不是同一件事——18 条是把已有的单条质量分接入
检索排序，这条听起来是要按分数把 episode 分组/聚类，具体定义什么、聚类完拿来干嘛
还没跟用户对齐），用户现在要求"早点放上日程"。两条都还没有方案（`episode 打分聚类`
连雏形都没有，是这次会话原样记下的新想法），暂不改动它们各自的正文小节，只在这里
把"需要提前"这个信号记下来，具体往优先级列表哪个位置插、要不要先补齐方案讨论，
留到下次接着定。

## 路线图

### 1. ✅ 前后端交互统一：`RunDataCenter`（意图/审查槽位 + trace/frame 转发；审查面板 UI 已补完）

现在前后端交互是三条各自为政的通道，形状不统一：trace/frame 走 SSE 单向推送
（后端→前端，纯转发，`GET /runs/{id}/events`/`GET /runs/{id}/frames`）；GoalsEdit 是
塞在 `RunHarness` 内部的单槽+锁（`self._edit`/`self._edit_lock`/`self._latest_goals`，
`plan()` 节点每轮消费）；**人工审查协议齐全但没有传输层**——`HumanReviewer` 是
`Protocol`，`RunHarness.review()` 节点确实会调它，但默认实现 `AutoContinueReviewer`
不看任何上下文、永远返回 `CONTINUE`，`api.py` 没有任何端点接收
`HumanReviewRespFromFrontend`，前端 `types.ts`/`api.ts` 的注释也明确写着"harness 阶段性
自动 CONTINUE，前端无交互，做审查面板时再接"。

**拍板方向**：做一个 `RunDataCenter`——每个 run 一个实例，`api.py` 和 `RunHarness`
各持一个引用，双方都只对它读写，不互相直接调对方的方法：

- **goals 槽位**：把 `RunHarness._edit`/`_edit_lock`/`_latest_goals` 原样搬过来，
  语义不变——非阻塞，`plan()` 读到就应用、没读到跳过，最新一条覆盖旧的。
- **review 槽位（新）**：两个子槽。请求槽由 harness 在 `review()` 节点写入，带上
  `HumanReviewReqFromHarness`——这个 schema 要新增 `episode_trace: list[TraceEvent]`
  字段，装刚跑完那一局的**完整** trace（不是全量 run trace，一次请求自带审查所需
  的全部依据，前端不用自己维护跨会话的历史缓存）；决策槽由前端 `POST
  /runs/{id}/review` 写入 `HumanReviewRespFromFrontend`。**harness 侧读决策槽必须是
  阻塞轮询（配超时兜底），不能读一次没有就当默认**——那样等于没有真的问人，跟现在
  的自动放行桩没区别。前端发现"有请求待处理"复用现在已经在跑的 `GET /runs/{id}`
  2 秒轮询，不新开推送通道。
- **trace/frame**：不新增状态，方法直接转发给已有的 `TracePort`/`FrameSlot`——纯
  粹是让前后端交互统一收口到同一个对象上，读写口子一致。

**这次设计顺带打开的口子**：review 槽位统一之后，`HumanReviewer` 的决策来源不必是
真人——接一个 LLM 驱动的 reviewer（模型读 `HumanReviewReqFromHarness`，尤其是新加
的 `episode_trace`，自己判断 continue/stop/retry/push）可以复用同一套协议和传输层，
只是决策槽的生产者从"人在前端点按钮"换成"另一个模型调用"。这是这次设计特意留的
扩展点，不是这次实现范围。

改动面：新模块 `RunDataCenter`；`RunHarness` 构造函数接收它而不是自己持有三个内部
字段，`plan()`/`review()` 节点改成读写它；`api.py` 的 `/runs/{id}/goals` 改写
datacenter，新增 `POST /runs/{id}/review`，`GET /runs/{id}` 响应体加"有没有待审查
请求"字段（前端 `types.ts` 里提到的 `review_pending` 坑位正好补上）；
`HumanReviewReqFromHarness` 加 `episode_trace` 字段，构造时从 `TracePort.events(None)`
按 `outcomes[-1].episode_id` 过滤出这一局事件（新增一个纯函数放 `run_utils.py`）；
前端 `api.ts` 加 `submitReview()`，`types.ts` 把之前故意留白的 review 类型补上，
新增审查面板 UI。

**实现现状（0902）**：上面改动面里除"新增审查面板 UI"外全部完成——`RunDataCenter`
（goals 槽 + review 槽，`await_review_response` 真阻塞轮询带超时兜底）、
`DataCenterReviewer`、`RunHarness`/`api.py` 接线、`GET/POST /runs/{id}/review`
端点、`HumanReviewReqFromHarness.episode_trace` 字段 + `run_utils.episode_trace_events`
过滤函数，见已完成表。`REVIEW_TIMEOUT` 默认设成 0（`POKEMON_REVIEW_TIMEOUT`
环境变量可调）——面板没做之前阻塞等一个不存在的人没有意义，0 秒退化成跟以前
`AutoContinueReviewer` 一样的行为，传输层接好但先不启用真阻塞；等面板做完把这个
值调大（或设环境变量）即可，不用再改代码。前端只做了数据层（`types.ts`/`api.ts`/
`useReview.ts` 轮询 hook），可视化的审查面板组件本身是剩下的唯一缺口。

**审查面板 UI 补完（0902 第二轮）**：唯一缺口也做完了。`REVIEW_TIMEOUT`
默认值 0 → 5（用户拍板"先设成5吧"），真正启用阻塞式人工审查；
`RunDataCenter` 新增 `review_timeout`/`_review_deadline`/`review_deadline()`，
`GET /runs/{id}/review` 响应体多一个 `deadline_ts` 字段，前端拿它渲染倒计时
（不用自己猜后端超时秒数是多少）。`web/src/App.tsx` 新增 `ReviewPanel` 组件：
展示 outcomes/last_task，四个按钮对应 continue/stop/retry/push（push 复用
`readGoalForm`），倒计时 + 一条"上一轮审查已超时，自动按 continue 处理"的
4 秒自动消失提示（本地靠"outcomes 长度识别是不是同一轮"+"有没有手动提交过"
两个信号推断是不是被后端超时兜底的，不是后端主动推送的事件）。另外发现
`useReview.ts` 原来 2s 的轮询间隔配 5s 超时太粗——最坏情况下审查请求要
接近 2s 才会在面板里冒出来，5s 窗口被吃掉快一半，改成专用的
`REVIEW_POLL_INTERVAL_MS = 500`（只影响这一个 hook，`useRunGoals` 那种非
时间敏感的轮询没动）。

**已知连带回归（留到解冻信号）**：`tests/test_api.py::test_review_endpoint_removed`
断言"审查端点不存在"，现在端点真实存在了（无待处理请求时返回 409 而不是 404），
这个测试需要跟着改，按约定等"等我信号统一更新"再动。

### 2. 🚧 可观测：token/延迟按链路聚合 + 观测台（已完成）；权限配置完整性校验 + 降级告警（未做）

现在 trace 已经把事件记下来了，但没有聚合视图——想知道"这一局 token/延迟花在哪条
链路"得手工过 trace 事件。这次已经把 `Source`/`EventType` 精细化过（`Source.PLAN`
从 `HARNESS` 分出来、记忆相关事件统一到 `Source.MEMORY`、补了 `EventType.STALL_CHECK`，
见已完成），这是可观测的地基，但地基上还没盖东西，至少要有：

- **token/延迟按 `Source` 聚合的报表或轻量观测台**——能直接回答"decision/judge/memory/
  plan 各占多少 token、多长时间"，不用每次手工翻 trace。第 10 条"决策延迟长尾"卡在
  "还没有一份 latency 对 output_tokens 相关性的数据"，本质就是缺这一层聚合能力；
- **权限配置完整性校验**——`agent_permission` 的降级路径（`permission_skipped`）现在
  能正常记账，但没有校验"配置本身是不是完整、一致"的机制，配置写错会悄悄走降级分支
  而不报警；
- **降级告警**——降级事件目前只进 trace，不会主动冒出来，得回头查才会发现。

跟第 4 条（trace 生命周期不闭合：无 `RUN_START`/`RUN_END`、进程中断不留痕）是同一个
方向但不同层——那一条是"trace 记没记全"，这一条是"记全了之后怎么聚合着看"。第 4 条
更基础，建议先做那部分小修，再在完整的 trace 之上建聚合视图。

**观测台实时数字——0902 当晚完成。** 新增 `GET /runs/{id}/metrics`：run 还在
跑的时候调用，看到的就是到目前为止的数字，不用等结束——数据源是
`handle.trace.events()`（跟 SSE 事件流读的同一份内存表），不读磁盘。复用
`evaluation/eval_report.py::aggregate_events` 这个核心，而不是重新写一份聚合
逻辑：`evaluation/SPEC.md` 10.7 早就记下"包内 import 会破坏装包"这个顾虑，
这次的解法是**惰性 import**（放函数体内，不放模块顶部）——`evaluation/`
缺失时只有这一个端点会炸，`pokemon_agent.api` 本体的可导入性不受影响，算是
10.7 提的两个方案（挪核心 / API 侧包一层）之外的第三条路，成本最低。踩了一个
坑：`TraceEvent.source` 字段类型是 `Source`（`str, Enum`），直接 `str(source)`
当 JSON key 会得到 `"Source.VERIFY"` 这种 repr 而不是 `"verify"`——`str, Enum`
混入类默认继承的是 `Enum.__str__`，不是 `str.__str__`；改成
`getattr(source, "value", source)` 才是真正的字符串值，顺带兼容
`eval_report.py` CLI 路径读 JSONL 拿到的纯字符串。前端 `useMetrics.ts`（2s
轮询，同 `useRunGoals` 节奏）+ `App.tsx` 的 `MetricsPanel`（按链路一行的原始
表格：调用/成功/失败/重试/tokens/p50/p90，外加降级/错误/审计失效率的文字
明细，run 级汇总一行），没有做图表——用户对这块的要求是"能用就行"。
验证方式：这台 device VM 装不上 `agent_permission`（同前几轮的环境限制），
没能跑 `TestClient` 端到端；改用真实的 pydantic `TraceEvent` 构造一批合成
事件，直接喂 `aggregate_events` 并复现端点里的字典拼装逻辑，断言
`by_source` 的 key 是 `"verify"` 不是 `"Source.VERIFY"`、`verify_total`/
`verify_unreliable`/`duration` 等数字都对得上，`json.dumps` 能序列化。
`tsc --noEmit` 前端侧无报错。

**0904 补一条：`ModelCall.payload` 新增 `prompt` 字段，`frame_png` 挂载点从
OBSERVE 挪到感知的 MODEL_CALL。** 起因是复盘时想看"这次调用到底问了模型
什么"，得去翻拼装代码才知道，没有直接落在 trace 里。6 个模型调用来源
（`Source.DECISION`/`JUDGE`/`VERIFY`/`PERCEPTION`/`PLAN`/`MEMORY`，对应
`brain.py::choose_once/judge/verify_steps`、`pyboy_world.py::perceive_once`、
`harness/run_utils.py::ask_planner_with_retry`、
`memory/episode/episode_store.py` 的摘要蒸馏）各自的 `ModelCall(payload={...})`
都补上 `"prompt": <实际发给模型的文本>`——包括失败路径，理由跟 `raw` 字段
一样：失败的调用也烧了 token，得留痕方便离线复盘/改解析器。顺带解决一个
架构上的别扭：原来 `TraceEvent.frame_png`（这一帧的原始画面）是从
`WorldPerceptionResp` 经 `EpisodeRunState.pending_frame_png` 这个专门开的
"跨节点暂存槽"转手一轮，最后由 `look()` 挂到 OBSERVE 事件上——纯粹是为了
把感知节点产出的字节搬到下一个节点用。既然现在 MODEL_CALL 本来就要记
"这次调用的输入"，画面本身就是感知那次调用最直接的输入，没道理再绕一圈：
改成 `episode_utils.perceive_with_retry()` 在给感知 MODEL_CALL 调
`trace.append(*args, frame_png=result.frame_png)` 时直接带上，函数签名从
返回 `tuple[ObservationFromWorld, bytes]` 简化成只返回 `ObservationFromWorld`。
`EpisodeRunState.pending_frame_png` 字段整个删除，`episode_harness.py` 里
`_begin()`/`look()`/`look_after_action()` 三处相应去掉这个字段的传递。
验证方式同前几轮的环境限制：`ast.parse` 语法检查全部通过，未跑真实
import/pytest。

机械复核（曾经是 `evaluation/audit_verdicts.py`，19 条任务规则，2026-09-02
已按用户决定删除——见 `evaluation/SPEC.md` 五节）现在已经不存在，只剩
`verify_steps` 这类零散校验，还没有一份"要测哪些指标、每个指标怎么打分"的
统一规范。至少要覆盖：success rate（已有）、cost per run、每链路 token；
无效步占比先按"已知是下界"接受（见第 7 条），不等它解决。落地脚本是
`evaluation/eval_report.py`。**排在可观测之后的第二优先级**：报表要用的
"每链路 token/延迟"聚合就是第 2 条要建的东西，两条高度相关，可以共用。

**0903 用户重新表述了范围**（起因：trace#20 出现"正上方即为宝可梦中心入口门"这类无
依据结论，见下方已完成表的 `map_hint.md` 修复）——用户要求先只做 prompt 层修复，
不做代码层机械检测器，同时把测评体系拆成三块：

1. **权威的"任务是否完成"LLM-as-judge**——现有 `judge_success.md`（独立判定员，
   默认"没完成"、要求证据在历史帧里真的出现过）已经是这个角色的雏形，但历史上有
   13.9% 假阳性率（`docs/experiences/` 里有记录），"权威"要到什么程度、要不要
   多轮/多模型交叉验证——还没定义，需要跟用户对齐。
2. **可审计和测评**——`eval_report.py` 的 `error_kinds`/`degraded`/审计失效率
   聚合是现成的基础设施；`verify_steps`（`Source.VERIFY`）是现成的步骤可靠性
   校验通道。这条与已删除的 `evaluation/audit_verdicts.py`（19 条任务规则的机械
   复核器，0902 因用户"不清楚这个工具在做什么"而删除，见已完成表）在主题上高度
   相关，但用户当时否决的理由是不理解工具用途，不是否决"审计"这个目标本身——
   重建前需要先跟用户对齐这次要的是什么形态，不能假设就是把旧工具原样找回来。
3. **基于 1、2 的自动更新管理**（prompt 改动的自动更新和版本管理）——**用户已明确
   说这条可以往后放**，不是本次范围。

**0903 用户确认范围（先只记进 roadmap，暂不开工）**：

- 第 1 点（judge 权威性要做到什么程度——单模型优化 / 多轮多模型交叉验证 /
  judge+机械规则双保险）**用户还没选，先把 1/2/3 三点整体记进 roadmap，具体
  往哪个方向做留到之后再定**。
- 第 2 点（可审计和测评）用户明确要看到两样产出：
  1. **judge 判定的可追溯性**——每次 `done=true/false` 都能回溯到具体是哪一帧
     `observation`、`history` 里的哪句话被当成证据，事后能复查，而不是只留一个
     布尔值和一句 `why`。
  2. **错误分类统计报表**——在现有 `eval_report.py` 的 `error_kinds`/`degraded`
     基础上，把 judge 误判、`verify_steps` 不可信这些也按类型分类计数出报表，
     不是本次现场决定怎么改代码，只是先把要看到的产出形状记下来。
- 第 3 点（prompt 自动更新和版本管理）0903 用户曾明确说往后放；**0904 用户改口，
  要求提前优先级**（见文件开头"当前优先级"一节）——具体要提前到什么位置、要不要
  先给这条本身补一份方案（现在还是"以后要做"级别的一句话，没有设计），还没跟用户
  对齐，留到下次接着定。

**prompt 更新注意事项**（0903 对全部 `pokemon_agent/prompts/*.md` 做了一轮
逐文件复核并按"一个一个改"改完，沉淀下来的坑，供以后手改 prompt 或做上面
第 3 点"自动更新和版本管理"时参考）：

1. **引号风格全项目统一用 `「」`，不要用中文弯引号 `""`。** 老文件基本都是
   `「」`；这次复核发现两类问题都出在"新加的内容"上——要么是我自己新写的段落
   习惯性用了 `""`（`decide_action.md`、`map_hint.md` 都犯过），要么是同一句话
   里前半用 `""` 后半用 `「」`（`perceive_screen.md` 第 12 行）。改完 prompt 后
   搜一下自己新加的段落有没有 `"` 字符，比通读全文更可靠。
2. **JSON 输出指令统一说"不要有其他文字"，不要额外禁止 ```json 围栏。**
   `decide_action.md`/`judge_success.md`/`run_plan.md` 都用带围栏的例子演示格式，
   说明项目约定是"照例子抄，围栏可以有"——下游 `strip_json_fence()` 两种都能处理。
   `perceive_screen.md` 曾经在结尾单独写"不要有```json包裹"，跟它自己第七节
   的所有例子都带围栏是**直接自相矛盾**；`episode_summary.md` 则是完全没给
   任何例子、字段全是 `"str"`/`"float"` 这种类型占位符——两种问题都改成了
   "统一说明 + 一份完整的、内容具体的带围栏例子"。以后新写/改 JSON 输出类
   prompt，例子必须是能直接 `json.loads` 的具体内容，不能留类型占位符。
3. **共享内容只留一个源头，其他地方用变量拼进去，不要手抄一份。**
   地形图例（`.`/`G`/`D`/`S`/`N`/`#`/`@` 各是什么）原来在 `map_hint.md` 用
   `terrain_legend()` 生成，`perceive_screen.md` 却手写了一份措辞不同的副本
   （尤其 `@` 那一行两边写法都不一样）——改成 `perceive_screen.md` 也用
   `$terrain_legend` 占位符、`pyboy_world.py::perceive_once()` 传参数进去，
   只在自己文件里补一句它需要的额外说明（这里是"两套坐标系不能混进 overview"）。
   **改公共来源（比如 `TERRAIN_MEANING`）之前一定要 `grep` 一遍它还被谁用**：
   这次曾经考虑过把 `@` 从 `TERRAIN_MEANING` 里删掉来去重，查出来
   `pokemon_agent/world/ram.py` 拿它派生的 `MAP_CHARS` 做每帧 `walk_map` 的
   合法字符校验（`bad = set(row) - MAP_CHARS`），删掉会导致每一帧校验都报错——
   属于"看起来是无害的措辞去重，实际是运行时校验会挂"的坑，改之前一定要查引用。
4. **增量改 prompt 时，加新规则之后要回头看有没有跟旧内容重复或矛盾。**
   `decide_action.md` 这次改了三拍，`rationale` 字段的要求每次都加新的硬规则，
   到第三拍时发现"最后再叮嘱一遍"式的旧段落其实在用不同措辞重复前面刚加的
   硬规则——改完新内容之后，通读一遍受影响的那个字段/小节的**全部**要求，
   别只看自己新加的那几行。
5. **"固定存在的规则" vs "按需检索的知识"要在总 prompt 里分开成独立小节，
   各自说明"这是什么、可信度多高、覆盖不到的时候怎么办"。** 这是这次结构性
   重写的核心原则：`decide_action.md` 现在有"已知事实"（RAM 直读，100% 准）、
   "检索到的相关知识"（跨地图规律，覆盖不保证，不能替代当前帧证据）、
   "相关记忆"（本局内，未经复核的当时判断）、"跨局摘要记忆"（跨局自己写的，
   可能带偏差）四个独立小节，顺序按可信度从高到低排列。以后往总 prompt 里加
   新的数据来源，先想清楚它属于哪一档可信度，给它单独一节而不是塞进"已知事实"。

### 4. 📋 trace 生命周期不闭合：进程中断不留痕（P0，a 已完成，b/c 还开着）

同一次 run 的实锤：ep3 执行中被杀（中断后端），最后一条事件停在 step2 的
`memory_read`（正要调 decision）——**没有 EPISODE_END、没有 ERROR 事件**；那次 run 级
trace 全 run 也只有 1 条 plan 的 MODEL_CALL，从头到尾没有 RUN_START/RUN_END。后果：

1. **中断与卡死无法区分**：replay/统计拿到"进行中"状态的 run，不知道它其实已经死了，
   中断局会被当成进行中/超时，成本与成功率统计失真；
2. **run 生命周期不可观测**：观测台/报表无法判断一个 run 是正常收尾还是中途被杀。

修复方向三块，进度分开记：

- **a) 收尾事件闭环——已完成。** `RunHarness.run()` 现在开局写 `RUN_START`
  （`EventType.RUN_START`，`trace_utils.run_start`），正常收尾写 `RUN_END`
  （`trace_utils.run_end`，带 `total`/`succeeded`/`success_rate`），异常路径
  （图内部抛出未捕获异常）也补 `RUN_END`（`trace_utils.run_error`，带
  `why`）后原样抛出——跟 `EpisodeHarness.run()` 对 `EPISODE_START`/
  `EPISODE_END` 的处理是同一个模式。冒烟验证过正常/异常两条路径都补上了
  首尾事件。
- **b) 进程层兜底——还没做。** uvicorn `lifespan` shutdown hook 里对未收尾的
  run 补一条 `INTERRUPTED` 事件，处理"进程被杀、graph.invoke 本身没有机会
  抛异常"这类 a) 补不到的情形。是否做取决于测评要不要统计"被中断的 run"。
- **c) run 级 trace 记全每次 plan 调用——复查代码没找到独立漏记的 bug，暂
  当已解决，留个尾巴。** 当时那次真实 run（3 个 episode 只记了 1 条 plan
  的 MODEL_CALL）跟"图撞 `GraphRecursionError` 无声截断"是同一批数据（那个
  bug 已经在别处修过，见已完成表的 `recursion_limit` 撞限修复）。复查现在
  的 `run_utils.ask_planner_with_retry`：`plan()` 节点每被图访问一次就完整
  跑一遍这个函数，每次调用（成功失败都算）都会 `trace.append`，没有旁路能
  绕开记账。所以"只记 1 次"更像是那次撞限截断的症状，不是这里的独立漏记——
  但这是代码走查的结论，还没有一次真正跑完的多目标 run 反过来验证"plan
  调用次数 == 实际 dispatch 次数"，等测评体系（第 3 条）真正跑批次数据时
  顺带核对一次，核对通过就可以把这条从待办里划掉。

### 5. 📋 P0 护栏（往后排）

run 级总目标数/总步数/总时长上限、无效动作拦截、STALL 阈值相对 max_steps
动态化。本该最先做（是测评能收敛的物理前提），现在按上面的优先级调整往后
排，等测评体系能跑出数字之后再补，用来验证"加了护栏之后数字是不是变好了"。

### 6. 💬 内存环境框架重构

四类记忆（跨局摘要 / 单步情景 / 知识先验 / 物件语义）现在存储方式不统一：

| 记忆类型 | 现在的类 | 能不能指定目录 |
|---|---|---|
| 跨局摘要（global episode） | `FileEpisodeMemoryStore` | 能 |
| 单步情景（step episode） | 同上，`_steps` 字典 | 不能，纯进程内 |
| 知识先验（knowledge semantic） | `KnowledgeStore` | 能，形状最干净 |
| 物件语义（object semantic） | `InMemoryObjectStore` | 不能，纯进程内 |

批次测评需要给每次跑一个干净、隔离的"环境"（类比 `pytest` 的 `tmp_path`），
四类记忆应该都能被同一个根目录接管、各自落一个子目录。提议：照着
`KnowledgeStore` 的形状统一其余三个，再造一个 `MemoryEnvironment` 工厂拼装
四个 store。**没定的地方**：单步情景要不要真的落盘——现在是刻意不落盘
（持久化靠 trace），给它一个目录是否意味着要重新引入磁盘持久化，这个要先
讨论清楚。**这一条不实现，等下一轮确认方案。**

### 7. ❓ "无效步"怎么定义——现有 STALL 检测站不住，没有满意的替代方案

唯一的无效步信号是 L2 护栏（`detect_stall`）：比较这一步和上一步的
`action + obs.stall_key()` 是否完全相同，连续 5 次相同才判定停摆。这检测的
是"动作和画面机械状态都没变"，不是"这一步有没有价值"——来回试探、绕远路、
reroll 同一个决策换个措辞，这些"在变但没推进"的情况完全抓不到。而且
`STALL_LIMIT=5` 在 `max_steps=15` 这种短任务里基本形同虚设，很多局在真正
触发停摆前就已经因为步数用尽结束了——`evaluation/SPEC.md` 里"无效步占比"
这个指标现在只能算出真实值的下界。**这是需要深入解析的任务，不是顺手能
改的小修**：怎么定义"这一步有没有朝目标推进"本身就不平凡（要不要引入某种
进度度量？要靠 judge 每步都判一次会有额外模型调用成本；要不要用记忆检索
命中率反推"是不是在重复同一个错"？）——现有方案和几个候选方向目前都没有
一个让人满意的，先立项、不下方案。

### 8. ❓ 跨局摘要记忆（episode_memory）现在不分 run 检索

`MemoryTool.query_episode_summaries()` 读的是全部落盘的跨局摘要，不按
`run_id` 过滤，只按场景和相关性排序。一次新实验跑起来，会检索到**所有
历史 run** 写下的摘要，不只是本次 run 内的——跟"批次记忆隔离"不是同一个
问题（那个是同一 run 内，后面的 episode 能看到前面 episode 的经验；这个是
跨 run，上周跑的实验这周还在被检索到）。要不要按 run 隔离没有定，跟第 6
条内存环境框架是同一个方向的问题。这是之前就知道的老问题。

**0904 补一条明确的优先级依据**：第 18 条（检索按质量分加权）的消融实验、
第 3 条（测评体系）要跑的基线，都要求"这批任务测出来的数字只反映这批任务
自己的历史"——如果这条不解决，基线本身就可能被更早、不相关 run 留下的
摘要污染，跟第 12 条是同一类风险（只是第 12 条那次是具名文件，这条是
运行时持续累积的一般性问题）。**建议**：跑第 3 条真实基线之前，至少要有
一个"这批任务只检索本批次内摘要"的临时手段（哪怕不是这条要的完整方案），
不必等这条完全设计定型。

### 9. 🚧 verify_steps 改检索增强验证（0902 拍板，代码已落地）；改造完补真实数据验证

step 记忆是模型自述、不验证，错误的自我描述会被固化进摘要、跨局传播（真实
例子：战斗菜单 `down×3` 被自己记成"逃跑"，实际是打开了道具袋）。所以已经从
`summarize()` 拆出独立节点（`judge → verify_steps → summarize`），用独立判定器
逐条把关，只把可信子集喂给蒸馏。

**0902 拍板：领域规则从 prompt 写死改成检索召回。** 原来判据是 `step_verify.md`
里写死的领域规则（battle 2×2、方向键/交互键语义那几条）——用户指出这覆盖不了
场景全集：现在只有 battle/menu 导向，后续加商店/门/更多场景就得持续往 prompt 堆
规则，静态领域知识不全时校验器会判错。定稿方案：

```
judge done → 取本局 step memory → 由 entries 构造检索 query（每局一次）
  → 召回 knowledge → StepVerifyReq(goal, entries, knowledge=召回文本)
  → Brain.verify_steps：方法论判自洽 + 对照召回知识判领域合理性
  → 兜底：召回覆盖不到 → reliable=false，why="无相关领域知识，无法确认"
```

三个已拍板的点：a) **整局一次检索**（不逐条），一次 LLM 调用内逐条判，成本不变；
b) **空召回/覆盖不到 → 判不可靠**（宁少喂，不可把错的当对的）——空召回也照常跑
一次：方法论层（前后快照矛盾、声称有效但无变化）不依赖知识仍能抓一部分；
c) **prompt 分层**——写死的领域规则全删，单一事实源 = `knowledge/`（battle 2×2
本来就在 `battle_actions.md`，`step_verify.md` 是同源重复，正好借这次去掉）；
保留不依赖场景的通用自洽判据作为方法论层。

改动面：`StepVerifyReq` 加 `knowledge` 字段；`episode_utils` 新增
`build_verify_knowledge_query(entries)`（参照 `build_knowledge_query` 的教训——
只按 goal 检索时战斗/菜单先验在 BM25 匹配不上，query 必须拼观察特征；这里用整局
entries 的 scene/overlay/动作并集）；`episode_harness.py::verify_steps` 节点加一次
`query_knowledge` + 检索记账（`memory_read`，收尾路径没有 `enrich_observation`，
节点自己记，否则 trace 看不出"校验器看到了什么知识"）；`step_verify.md` 重写。

**改造后的测量问题没消失，反而更该做**：检索增强后校验器抓没抓到真的坏记忆、
有没有误伤好记忆，依旧没有真实数据核对——需要一批人工标定的 step 记忆当
ground truth，这正是"这个校验器到底有没有用"的答案来源，跟第 3 条测评体系
一起跑。

**trace 两处欠账的等待条件更新**：原来写"等第 3 条跑出结论再动"——现在校验器
确认要改（这次改造动 `StepVerifyReq`/prompt/记账，本来就碰这两处），不再无限期
等测量结论，随本次改造一起定：
1. **和 `judge()` 共用 `Source.JUDGE`**——两条链的 token/延迟混在一条聚合里
   分不开，算不出校验器自己的失效率（`docs/spec` 早就写了这句期望）。改造时
   顺便拆独立 `Source`（比如 `VERIFY`）。
2. **结构化 `verdicts`（每条 `index`/`reliable`/`why`）现在直接扔了**——只把
   `reliable` 集合算出来筛记忆，trace 里只留一条 `MODEL_CALL` 的 `raw`。改造时
   一并把 verdicts 结构化落 trace，否则事后反解析才能知道"这局判了几条不可信、
   为什么"。

**实现现状（0902）**：上面改动面全部落地——`StepVerifyReq.knowledge`、
`episode_utils.build_verify_knowledge_query`、`step_verify.md` 重写（领域规则全删，
单一事实源改成检索）、独立 `Source.VERIFY`、结构化 `verdicts` 落 trace
（`trace_utils.verify_call`），见已完成表。

**落地时按用户要求做了一次架构修正，没有偏离"每个节点只改一处状态"的约束**：
最初实现把 step 记忆检索、知识检索、校验三件事揉进一个 `verify_steps` 节点，
用户指出这违反 `EpisodeHarnessPort` 文档里明确写的接口约束——已改成三个独立节点
`retrieve_verify_step_memory`（只改 `verify_step_entries`）→
`retrieve_verify_knowledge`（只改 `verify_knowledge`）→ `verify_steps`（只改
`verified_steps`，读 state 里已经查好的两项，不自己查库），路由在
`retrieve_verify_step_memory` 之后按"有没有 step 记忆"分流，没有就直接跳
`summarize`。图从 17 节点变成 19 节点，`recursion_limit` 公式（`max_steps*16+20`）
的 `+20` 余量还够，没改。顺带把 `Brain.verify_steps` 的模型从强制共享 `judge_llm`
改成独立可配置的 `verify_llm`（缺省仍等于 `judge_llm`，向后兼容）。

**还没做**：改造后校验器抓没抓到真坏记忆、有没有误伤好记忆，仍然没有真实数据
核对——需要一批人工标定的 step 记忆当 ground truth，跟第 3 条测评体系一起跑，
是这一条唯一剩下的开口。

### 10. 💬 单局内决策延迟偏高——已修两处、真正的长尾原因还没查清楚

0827 批次实测（`docs/experiments/0827-knowledge-baseline.md`）：decision 中位
延迟 10.6s，p90 **45.7s**；感知（3.4s/4.4s）、判定（1.5s/2.0s）都很紧凑，
优化空间几乎全在 decision 这条链路。

**已经修的两处（无头模式排队等待偏长的根因，跟 decision 本身的模型延迟是
两回事）**：

1. `pokemon_agent/world/pyboy_world.py` 里发现一份未提交、半途而废的重构
   ——无头模式（不 watch）本该不限速（`set_emulation_speed(0)`），被意外
   改成不分 watch 一律按 `speed`（默认 1，等于实时）演化，`step()` 按完键
   后纯演化 10 秒游戏时间、决策等待期间的 `evolve()` 也按实时推进——批次跑
   的时候这些全按真实秒数在等。改动还顺带删掉了 `_tick`/`_frame_png`/
   `latest_frame` 三个方法的定义、只留调用点，跑起来会直接崩溃。**已恢复**：
   无头不限速、三个方法补回。
2. **决策的 async 等待机制已移除**：原来 `choose_with_retry` 把决策请求丢进
   线程池、等待期间靠 `game.evolve()` 空转填充——这是在无头模式意外限速的
   前提下才有意义的设计（演化能看见"世界在等待期间继续走"）。现在无头不
   限速，evolve 填充等待省不出时间，异步+轮询反而是多余的复杂度。已改成
   `choose_once` 同步调用；`Brain.choose_once_async`、`_executor`、
   `IDLE_FRAMES_PER_POLL` 一并删掉。

**还没查清楚的**：两处修完之后 decision 本身的 LLM 调用延迟（p90 45.7s
这个数字）没变——两个已知线索都指向"token 偏多"：`ActionFromBrain.thought`
没有长度上限，`max_tokens=25600` 只是留了余量，实测单步 `thought` 冲到过
2235 token；judge/verify_steps 链路上同类输入膨胀问题修过一次（`walk_map`
字段占记忆渲染 62%，去掉后审计延迟 77s→11.4s，见
`docs/experiences/2026-08-31-audit-77s-input-bloat.md`），但 decision 的
记忆渲染（`MEMORY_RECALL_LIMIT=5`，每条全量 `render()` 含 reason）还没同样
查过。还没有一份"latency 对 output_tokens 相关性"的数据来确认长尾是不是
输出 token 拖的；候选方向（给 `thought` 定软上限 / 精简 decision 记忆渲染 /
换更快模型）都还没验证优先级。**排在测评体系之后**——先把测评跑起来，能
看到"改了之后数字/耗时是不是真的变好"再动。

### 11. 💬 `TaskForHarness.task_id` 要不要改名 `goal_id`——暂不改

`task_id` 是活跃、有实际功能的标识符：run 级目标编辑 API、前端目标列表
（React key）、`GoalsEdit` 处理逻辑都直接依赖它；批次实验里 `task_id` 就是
任务类别（这个用法本身没问题）。改名要同时动 schema、后端、前端 TS、若干
测试、十来处文档，影响面大，而且前端目标编辑功能看起来还在开发中，这时候
大范围改一个依赖字段风险偏高。"task_id 不该进 trace"这个问题已经解决，字段
名本身目前没有制造真实理解混乱。**这次不改**，等前端那条线稳定下来再提。

### 12. ❓ 记忆库可能"泄题"——具体一批文件已清掉，一般性风险仍未解决

对照业界测评方法论时发现：`pokemon_agent/memory/episode/memory/` 下已经
提交了大量形如 `battle_choice_cursor_to_run.md` 的记忆文件，文件名本身
几乎就是任务的解法。如果这些记忆在跑 19 条 `knowledge_*` 短任务时会被检索
到（检索不分批次、不分任务来源，见第 8 条），那"这条任务的成功率"测的可能
是"agent 会不会读记忆库里已经写好的答案"，不是"agent 会不会做"——这比批次
内记忆污染更严重。

**0904 更新**：这一批具名文件本身已经从磁盘和版本库里删掉（"运行产出退出
版本库"那次清理，`FileEpisodeMemoryStore` 是纯 `glob("*.md")` 读盘、没有
独立索引，文件不在了就检索不到，这批具体实例的风险已经解除）。**但一般性
问题没有解决**：往后新 run 蒸馏出的摘要一样会不分批次地被下一批任务检索
到，只是现在没有"文件名本身就是答案"这么直白的具体案例——本质上是第 8 条
（跨局摘要不分 run 检索）没解决的必然后果，两条应该按同一个优先级一起看，
不必再单独核实"这批文件会不会被命中"（已经没有这批文件了）。

### 13. 💬 全项目命名一致性——多处用不同的词描述同一件事

没有统一规范，同一个概念在不同层（graph 节点名 / 方法名 / prompt 文件名 /
trace `Source` / schema 类名）各起了一个名字，读代码时得靠"这几个词其实是
一回事"的隐性知识对齐，容易在扩展时选错挂靠点（比如给一个新事件该配哪个
`Source`）。已发现的几组：

| 概念 | 用到的不同名字 |
|---|---|
| "选动作"这一步 | 图节点 `think_action`、`Brain.choose_once`/`choose_with_retry`、prompt 文件 `decide_action.md`、trace `Source.DECISION` —— think / choose / decide 三个动词都在指同一件事 |
| "看画面拿观测" | 图节点 `look`/`look_after_action`、`World.perceive_once`（`GameToolPort` 接口）、`trace_utils.observe()`/`EventType.OBSERVE` —— look / perceive / observe 三个词 |
| 物件语义记忆里"格子上的东西" | 存储层 `ObjectMemory`（`OBJECT_MEMORY_WRITE`、`memory/semantic/object_*`）包着领域层的 `LandmarkInWorld` —— 一个叫 object，一个叫 landmark，指的是同一个东西 |
| 任务标识符 | `task_id`（活跃字段）vs 概念上其实是"目标"（`goal` 字段、`GoalsEdit`）——已经单独在第 11 条讨论过要不要改名，这里不重复决策，只并入这张总表 |

**这次不改**：这四组名字目前都各自"活"在自己的层里，没有哪个当下会读错
数据（跟第 11 条 `task_id` 的判断一样），批次改名跨 schema/trace/prompt/
前端 TS 好几层，风险和收益不对称。先记下，等有专门做命名规范梳理的时机，
或者哪一组名字开始造成真实理解成本（比如新人反复问错）时再动手；到时候
优先级最高的大概率是"选动作"那组，因为 `Source.DECISION` 这个词已经跟另外
两个动词脱节，新增 trace 触发点时最容易选错。

### 14. ❓ task 级实时意图识别——只是个想法，还没方案

用户想法：给"这一步/这一局"加一层**实时**识别 agent 当前意图（在做什么、
是不是偏离了目标），而不是只靠事后蒸馏的摘要或人工看 trace 回放去判断。现在
最接近"意图"的信号是 `ActionFromBrain.thought`/`rationale`（模型自述的推理，
只进 trace，不参与决策，见 `schemas/domain/action_from_brain.py`）——是**事后
记录**，没有专门的识别/判定环节，也不会实时反馈进循环本身。

还没定的地方（先立项，不下方案）：

- **"意图"具体指什么**——是跟目标（`goal`/`success_criteria`）的对齐度？
  跟第 7 条"无效步"定义（这一步有没有朝目标推进）像是同一个问题从另一个
  角度问，要先想清楚这是不是重复立项。
- **"实时"到什么粒度**——每一步都判一次（多一次模型调用，成本顾虑同第 9
  条 `verify_steps`）？还是攒几步判一次？
- **识别出"意图跑偏"之后干什么**——只记进 trace 供事后分析，还是要反馈进
  循环本身（比如触发纠偏提示、提前终止）？后者会跟 P0 护栏（第 5 条）的
  职责有重叠，需要先分清楚谁管什么、别做出两套互相打架的机制。

跟第 5 条、第 7 条都有交叠，具体往哪个方向投入要等测评体系（第 3 条）先
跑出数字，看清楚"现在哪类错误最值得优先解决"再决定，不是现在就动手设计。

### 15. ✅ 观测台把 think / act / observe 单独展示——现在三类事件混在一列文本里

（用户 0902 提出：前端为 think / act / observe 做单独展示。事件名以 trace 的
`EventType` 规范名为准——`think` / `act` / `observe`，不另起新词，跟第 13 条
命名一致性是同一纪律。）

现状：观测台右栏事件流是一列不分类的日志（`web/src/App.tsx` 顶部注释就写着
"右栏事件流（一列，不分类）"）——每条 trace 事件经 `eventLine()` 统一压成一行
`#id [type] source {JSON}`，payload 完整平铺（注释写明"不截断，排查时截断会丢掉
第一手证据"）。一局看下来，"agent 想了什么 / 按了什么键 / 看到了什么"混在同一列
里，只能逐行从 JSON 里抠；而且 `think` / `act` / `observe` 三种 payload 形状差别
很大（thought 文本 vs 按键动作 vs 观测状态），压成同一种文本格式本来就不互相衬。

方向（📋 阶段，方案细节没拍板）：把三类核心事件拆开做分区展示——比如三栏各渲染
一种：`think` 栏显示 thought 文本、`act` 栏显示动作名与参数、`observe` 栏显示观测
状态。分类目前只发生在 `eventLine()` 这一个渲染函数里，是纯前端改动，不动后端
接口和 trace 形状。

没定的地方：
- 展示形态：三栏并排 vs 一条时间线上三种卡片；
- 其余事件（`memory_read` / `memory_write` / `error` / `cost` / `EPISODE_*`）摆在哪
  ——归入某一栏，还是保留一行日志列作第四栏兜底；
- `observe` 要不要配该步画面帧——帧流已有，但 trace 事件和帧是两条独立流，要对齐
  得靠 step 配对或事件带帧引用，这层成本要先想清楚。

跟第 2 条的关系：第 2 条是"记全了之后怎么**聚合**着看"（token/延迟按 `Source`
聚合报表 + 降级告警），这条是"单步**明细**的展示形态"——同一观测台的两层，
互不阻塞；做的时候是纯前端迭代，不新增 `Source`/事件名（不跟第 9 条那两处
`verify_steps` 的 trace 粒度欠账搅在一起）。

**0902 已完成**：上面"没定的地方"三点按最简单的方向拍了板——四栏并排（2x2
网格）而不是一条时间线上三种卡片；其余事件（`memory_read`/`error`/`done`/
`EPISODE_*`/`RUN_*` 等）落一个"其他"兜底栏，不逐类细分；`observe` 暂不配
该步画面帧，帧流和事件流仍是两条独立通道，对齐成本先不付。`web/src/App.tsx`
的 `thinkLine`/`actLine`/`observeLine` 三个渲染函数 + `EventColumn` 组件，
`docs/ROADMAP.md` 状态本条之前一直停在"📋 未开始"没跟着代码更新，这次一并
修正。

### 16. ✅ 存档/checkpoint 机制——run/episode/step 三级恢复，PLAN_checkpoint.md v4 已实施

**0908 文档对齐**：本条曾长期停在"📋 0906 方案拍板，待实施"，但 0907 会话已
经把完整方案（v4）落地并接线（详见 `docs/spec/harness/PLAN_checkpoint.md`——
三级恢复语义、落盘签名三元组、废弃归档、判断点拍板记录，`CHECKPOINT_handoff_2026-09-07.md`
是同一次工作的架构现状盘点/契约草案/改动触点清单）。**这两份文档才是权威
来源**，本条不再重复方案细节，只记结论、现状与本次核对发现的问题。

**0908 git 对象丢失事件**：`.git/objects` 松散对象一度整体丢失（`00`-`d7`
前缀），checkpoint 相关的 4 次逐条提交（`c288b3fa57` 前置改造 /
`6d154ae3ed` CheckpointTool 实现 / `98ff1e5499` 图接线 / `414760c32f`
DataCenter+测试）连同其余 61 次提交的对象一并不可找回，git 历史里已看不到
这些 commit——但**工作区源码文件本身完好**，损坏只发生在 `.git` 内部
（详见 `docs/spec/GIT_RECOVERY_2026-09-08.md`），代码是真实存在且已实施的，
不是"计划了但没写"。修复时两分支指针改指向各自最后一个有效祖先，当前
工作区状态整体提交为一个恢复快照 `6573b1f`。

**已落地范围**（对照 PLAN v4 §7/§9 逐项核对）：run/episode/step 三级恢复
入口、`save_checkpoint` 图节点（18 节点，episode 图入口）、显式签名三元组
`(run_id, episode_id, step)`（StepMemory/ObjectMemory 落盘记录、模拟器快照
配对 json 均已补 `run_id` 字段）、`CheckpointToolPort`/`CheckpointTool`
（save_step/save_run/load/latest_run/void_after）、废弃时间线归档（截断+搬
voided 目录，不做静默删除）、`WorldPort.load_state`、`RunDataCenter` 事件流
槽（`LocalTrace` 内存表迁移，前端恢复单点重建）、`StepMemory` 落盘写穿
（同构 `EventObjectStore`）。object_fact 事件流本身（`ObjectFactEventBase`/
`ObjectDialogEvent`/`ObjectWarpEvent`/`ObjectStillEvent` + `EventObjectStore`
的 `append`/`query`/`query_range`/`query_map`/`truncate`）已经是这套方案的
地基，跟 `PLAN_checkpoint.md` v3 起的设定完全一致。

**验证（0908 本次核对，非首次实施时的验证）**：
- `pytest tests/` 全绿（8 例：`test_checkpoint_resume.py` 4 例 + 既有 2 个
  测试文件），环境为临时搭建的 Python 3.12 venv（`pydantic`/`langgraph`/
  `rank-bm25`/`agent-permission`，跳过 `fastembed`——本次验证范围不需要它）。
- `ruff check pokemon_agent` 发现一个**真实 bug 并已修复**：
  `run_harness.py::resume_run()` 用到 `ResumeEpisode`（`interfaces` 包已导出
  这个类）但导入块里漏加，是会在恢复路径炸 `NameError` 的死代码，此前没
  测试覆盖到这一行（`test_checkpoint_resume.py` 覆盖的是 `CheckpointTool`
  本身与存储层截断语义，不含 `RunHarness.resume_run()` 的调用路径）——已
  补上 `ResumeEpisode` 导入，`ruff` 与全部测试确认修复后无回归。
- ruff 其余 53 条是既有格式/类型标注类债务（`E501`/`ANN2xx`/`UP042` 等），
  跟 checkpoint 本身无关，不在本次范围内处理。

**还没定的**（PLAN v4 §9 判断点已回答大部分，这两条仍开着）：
- AGENTS.md 九"trace 是追加写的事件序列……checkpoint 存事件序列而非最终
  状态"一句与实际方案不符（实际 = 状态快照 + 事件游标对账，见
  `PLAN_checkpoint.md` §3.2），本条一并同步改掉，见下面 AGENTS.md 改动。
- 档位 B（LangGraph `SqliteSaver` 步级 checkpointer）在 handoff 文档里标为
  "选做，只留接口不做实现"——现状用的是自管 `save_checkpoint` 节点方案
  （handoff §3.1 已拍板 A 方案为必做），档位 B 未做且没有排期信号，暂不
  视为缺口。

### 17. ✅ 本次可观测/审计全项目扫描的其余发现——多为文档滞后，随手修掉；两条明确暂不处理

0902 应用户要求做了一次全项目扫描（可观测 + 审计两个主题），除了上面已经
展开处理的几条（审查面板 UI、`eval_report.py` 审计失效率统计、
`test_step_audit.py` 删除、前端断线提示/性能、第 16 条 LocalTrace 澄清），
还发现几处纯文档滞后，已顺手修正，以及两条用户明确决定暂不处理的：

- **`docs/spec/harness/SPEC.md` 与 `docs/spec/DATAFLOW.md` 关于
  `EventType.INSPECT` 互相矛盾，且都跟代码不符**：前者说"这个枚举值留着，
  `trace/store.py` 里也仍有它的显示分支"，后者说"没有兼容成员……不再保留"，
  实际代码（`EventType` 枚举、`trace/store.py`）两边都没有 `INSPECT` 这个
  成员。已修正 `harness/SPEC.md`，对齐"确实删了、不保留"这个事实。
- **`CLAUDE.md`/`AGENTS.md` 的 trace 事件类型表已过时**：还写着旧版
  `observe`/`think`/`act`/`memory_read`/`memory_write`/`error`/`cost`
  七类，实际 `EventType` 早就是 14 个成员（`memory_write` 拆成
  `STEP_MEMORY_WRITE`/`OBJECT_MEMORY_WRITE`/`EPISODE_MEMORY_WRITE` 三类，
  新增 `RUN_START`/`RUN_END`/`STALL_CHECK`，`cost` 从来不是独立事件类型，
  成本信息挂在 `MODEL_CALL.payload` 里）。两份文档内容完全同步（同一段文字
  被复制维护），已同步修正。`docs/spec/DATAFLOW.md` 的事件总表/`Source` 表
  同理落后（缺 `VERIFY`/`PLAN`/`RUN_START`/`RUN_END`/`STALL_CHECK`），一并
  补上缺的行。
- **权限审计日志（`log/audit.jsonl`，`agent_permission` 库自动写）纯写无读
  ——明确暂不处理**：用户 0902 拍板"先放着"。已记入"工程基础设施缺口"表，
  不是遗漏，是主动决定的优先级。
- **`schema_version` 字段有写无读、`LocalTrace.append()` 无锁**（隐式依赖
  "单线程顺序跑 episode"这个当前成立但没有断言保护的假设）：扫描时发现，
  暂未处理，不阻塞任何当前工作，留在这里当一条记录，以后改并发模型时
  （比如恢复并发判定，或并行跑多个 episode）要记得回头看这两条。


### 18. 💬 检索按质量分加权——`quality_score` 现在只写不读

`episode_memory.py::EpisodeMemory.quality_score`（judge 生成跨局摘要时打分，
0.0–1.0，附 `quality_rationale`）现在只在摘要写入时产生，`memory/retrieval.py::
hybrid_retrieve()` 的 docstring 里提前留了话（"这个分数之上再叠加别的排序信号，
比如质量分、成败，不用重新计算一遍"），但从没真正接上——`MemoryTool.
query_episode_summaries()` 检索排序目前只看 BM25+向量融合+reranker 分数，
质量分完全不参与排序，是个只写不读的字段。

跟第 3 条"测评体系"、第 9 条"`verify_steps` 真实数据核对"是同一个方向：现在
连"质量分能不能提升检索到的记忆有效性"这个假设本身都没有数字支撑。

方向（📋 未拍板）：

1. 把 `quality_score` 接入 `hybrid_retrieve()` 之后的排序（比如 rerank 分数
   与质量分加权求和，或质量分低于某阈值直接过滤）——这是"回写"这半件事；
2. 消融验证：同一批任务，开/关质量分加权各跑一遍，对比成功率——这是能拿出来
   的量化数据，跟第 9 条"人工标定 ground truth"共用一批任务集合，不用重新
   设计实验。

**没定的地方**：加权公式（线性叠加 vs 阈值过滤 vs 两者结合）、要不要区分
"跨局摘要"和"单步情景"两类记忆分别调权（现在 `quality_score` 只在
`EpisodeMemory` 上，`StepMemory` 没有这个字段）。**排在测评体系（第 3 条）
之后**——先有能稳定复现的批次成功率基线，再看加权前后的 delta 才有意义，
现在直接跑消融会因为基线本身不稳定而数字不可信。**0904 补充**：同样要
先看第 8 条（跨局摘要不分 run 检索）——基线本身如果混进了不相关历史 run
的摘要，"稳定复现"这个前提也立不住，两个前置条件缺一不可。

### 19. 📋 数据导出接口：按质量分导出高质量记忆样本

现在 `FileEpisodeMemoryStore` 落盘的跨局摘要记忆已经带 `quality_score`/
`quality_rationale`（判定时打的分+理由），但只用于本地检索，没有对外的导出
通道——想要一批"高质量样本"（比如做进一步分析，或作为下游候选数据）得手工
翻文件。

方向（📋 未拍板）：`api.py` 加一个只读导出端点（或独立 CLI 脚本，两者都能配
`quality_score >= 阈值` 筛选），产出 `.md + frontmatter`（现有存储格式原样
导出，不用转换）按分层分级打包。`api.py` 已经是 FastAPI，这条只是新增一个
端点，不涉及框架选型，可以搭其他服务化改动的顺风车一起做。

**没定的地方**：导出粒度（单条记忆 vs 整局打包）、阈值怎么定（固定值还是按
分布分位数）、导出前要不要额外加校验——`quality_score` 现在评的是"摘要写得
好不好"，不是"内容本身可信"（可信性校验是第 9 条 `verify_steps` 在管的事，
两者现在完全独立），这两者容易被下游误当成同一件事，导出接口的字段命名和
文档需要把这个区分说清楚，避免"高质量"被误读成"已验证为真"。

### 20. ❓ episode 打分聚类——只是个想法，还没方案

0904 用户提出的新想法，跟第 3 点"prompt 自动更新"一起被要求"早点放上日程"，但
连雏形都没有，跟第 14 条"task 级实时意图识别"是同一个成熟度（❓，只有一句话）。

**跟第 18 条的关系，需要跟用户对齐清楚，不能假设是同一件事**：第 18 条是把
`EpisodeMemory.quality_score`（judge 生成摘要时打的单条质量分）接入检索排序，
是"用已有的分数做排序"；这条听起来是"按分数（或别的什么维度）把一批 episode
分组/聚类"，是"给 episode 打分+聚类"两件事，具体是：

- "打分"打的是什么分？复用 `quality_score`，还是需要一个新的评分维度（比如
  按 `judge`/`verify_steps` 的结论、按 trace 里的错误类型、按用了几步）？
- "聚类"聚出来干什么用？是为了发现"这一类失败模式该改哪条 prompt"（那就该跟
  第 3 点的"自动更新"直接挂钩，聚类结果是自动更新的输入）、还是单纯做数据分析
  报表（那就该挂第 3 条"测评体系"下面）、还是别的用途？

这些都还没跟用户对齐，本条先占位记下这个想法存在、且已被要求提高优先级，具体
设计留到下次讨论。


### 21. ❓ criteria 太松 + VLM 感知可靠性——两个可能同时存在的问题，都还没方案

见"已完成"表里对应的诊断行。同一次 run 里连续暴露两条：**a)** `tasks.py` 里
`pokemon_center_enter` 的 `success_criteria`（"scene 是 indoor，且 map_id 和历史里
门外那几步不同"）只要求"换了张图"，任何建筑入口都满足，不是宝可梦中心的专属证据；
**b)** 用户指出同一局里 VLM 把某个房间的 NPC/对话来源误标成"大木博士"，而那个房间
"根本就是宝可梦中心"——如果属实，说明 VLM 对室内场景/NPC 身份的识别本身不可靠，
不只是 criteria 松就能完全解释的。两者可能同时成立、也可能只有一个是真正原因，
现在还分不清楚——需要先回放同一段 trace 的原始画面（帧已经落盘，见"trace 落盘感知帧"
那条）核对 VLM 当时的 `overview`/对话来源判断到底对不对，再决定：criteria 要收紧到
什么程度、VLM 感知这条要不要单独立一个可靠性排查任务（比如同一帧多次感知看方差，
或者引入更强的视觉模型对照一批 trace 帧人工标注）。**暂不动手**，等下一步跟用户对齐
排查方式。

| ✅ 前端重新布局：review + human_note 挪到目标栈旁，review 无待审查时置灰而非隐藏 | 用户要求两点：**a)** `human_note` 和 review 面板放在目标栈现在的位置；**b)** review 的输入（四个决策按钮 + push 的目标表单）只在真有待审查请求时可操作，其余时候按钮置灰而不是整块消失，`human_note` 不受这条门控——任何时候都能发。**改动**：`App.tsx` 把原来浮在页面顶部、`review !== null` 才渲染的 `ReviewPanel` 挪进左栏 `目标栈` 区块内（追加目标表单下方）；`ReviewPanel` 签名从 `review: PendingReview` 改成 `review: PendingReview | null`，内部按 `disabled = review === null || runId === null` 给四个按钮和展开的 push 表单加 `disabled`（`review === null` 时标题也从"待审查"变成"无待审查"，整块面板降低透明度），不再是"没有就不渲染"。新增 `HumanNotePanel` 组件（文本框 + 发送按钮），紧挨着 `ReviewPanel` 下面，只受 `runId === null` 门控，不看 review 状态——一次性语义（发送后清空输入框，不展示"上次插了什么"，避免误以为还在持续生效）。**数据层**：`types.ts` 新增 `HumanNoteReq`/`HumanNoteResp`；`api.ts` 新增 `submitHumanNote()`（`POST /runs/{id}/note`）。**验证**：`node_modules/.bin/tsc --noEmit` 全干净（这台 device VM 有 node 环境，比后端那几轮的 `ast.parse` 验证更实——是真的类型检查，不只是语法检查）；`vite build` 因为这台 device VM 的 `node_modules`（`@rollup/rollup-linux-x64-gnu` 原生依赖缺失，npm 已知的可选依赖 bug）跑不起来，但这是环境问题，跟本次改动无关，`tsc` 通过已经覆盖了类型层面的正确性。**没做**：没有真实启动前端跑一遍看视觉效果（这台 device VM 装不出可运行的 vite dev server）。|

| ✅ 目标栈编辑也跟着 review 状态门控，跟 review 合并进同一个框；顺带修好这台 device VM 的 `vite build` | 用户在上一条前端改版基础上追加两点：**a)** 目标栈的编辑能力（追加目标表单、非栈顶目标的行内改/删）也改成只有真有待审查请求时才能用；**b)** 这部分跟"人工审查"放进同一个带边框的框里，不是两个各自独立的框。**改动**：`App.tsx` 新增派生量 `reviewActive = review !== null && runId !== null`；"追加目标"表单从原来紧跟目标栈列表的位置挪进一个新的 `<section style={styles.reviewPanel}>`（标题按 `reviewActive` 显示"人工审查"/"无待审查"，跟原 `ReviewPanel` 组件用的是同一个视觉语言但只在这一层出现一次），表单三个输入框和提交按钮都加 `disabled={!reviewActive}`；`ReviewPanel` 组件本身**去掉了自带的边框和标题**（改版前它自己也套一层 `styles.reviewPanel` + 标题，跟外层新框嵌在一起会变成"框中框、标题写两遍"），现在只吐内容，边框/标题交给调用方；`GoalRow` 新增 `disabled` prop，栈顶只读行不受影响，非栈顶的行内编辑表单（目标/判据/步数三个输入框 + 保存/删除两个按钮）现在也一起禁用。**顺带修的环境问题**：验证这批改动时被用户指出"没有缺失啊，发我指令"——上一条记录里"`vite build` 因为原生依赖缺失跑不了，是环境问题"这个结论是错的，实际是这台 Linux device VM 的 `node_modules/@rollup/` 只装了 Windows 平台的二进制（`rollup-win32-x64-gnu`/`msvc`），因为 `npm install` 本来是在用户的 Windows 机器上跑的——`npm install @rollup/rollup-linux-x64-gnu --no-save` 补装对应平台包（`--no-save` 不改 `package.json`/`package-lock.json`，`git status` 确认 Windows 那边的锁文件没受影响），`vite build` 之后就能跑通。**验证**：`tsc --noEmit` 全干净；`vite build`（这次是真的跑通，不是"环境限制跳过"）成功产出 `dist/`，为避免撞上一次构建残留的 `dist/` 目录权限问题，改用 `--outDir /tmp/dist-check` 验证，构建日志确认 37 个模块正常转换、产物大小合理。**没做**：没有真实启动前端肉眼看一遍布局（这台 device VM 起不了可交互的 vite dev server 供人眼观察，只能验证类型正确 + 构建成功）；构建残留的 `web/dist/`、`web/vite.config.ts.timestamp-*.mjs` 两个文件这台 device VM 默认无删除权限，留给用户自己清理或后续申请权限处理。|

### 22. 💬 token 预算/上限机制——账本齐全但没有预算，超支时没人拦

现状：token 用量已经**逐调用**落盘——`MODEL_CALL` 事件的 payload 带了
`input_tokens` / `output_tokens` / `cached_tokens`（外加延迟、尝试次数、`raw`、
`prompt`），失败的调用也记账（`schemas/domain/model_call.py` 的"谁控制循环谁记账"），
第 2 条"按链路聚合"也做完了。也就是说**账本和报表都在，缺的是预算**：没有任何
机制在用量超阈值时干预。直接先例是 2026-08-31 那次 77 秒 input 膨胀
（`docs/experiences/2026-08-31-audit-77s-input-bloat.md`）——账单事后能看出膨胀，
但当时没有任何东西拦它，等于只有会计没有风控。

方向（💬 两个落点候选，没拍板）：

- **a) harness 每步检查（倾向）**：累计本 run/本局的 token 消耗，超阈值时走
  已有的 review 槽位问人（`RunDataCenter` 的传输层现成），或配置成自动降级/停。
  优点是实时拦截，缺点是控制流里多一块预算判断逻辑。
- **b) experiment 层跑批后归因**：只在局/run 结束时算账报警，零运行时侵入，
  但单局烧穿时拦不住，只能事后止损。

**没定的地方**：a 还是 b（或两者都要）；阈值怎么定（固定值还是按任务基线 /
历史分位数）；超限的默认动作（停 / 降级 / 只告警）。`MODEL_CALL` 的 payload
里 step、episode_id、source 都齐，聚合口径不是问题，纯粹是"在哪拦、拦了干什么"
两个决策没做。

### 23. 📋 模型分级——装配点已经在分档，但原则没成文、分配没验证过

现状：模型分级**已经在实践里发生**——`build.py` 装配时决策走便宜档
（`text_model = "qwen-plus"`），判定/校验/run 级规划走贵档
（`judge_model` / `verify_model` / `plan_model` 默认豆包 pro），视觉单独一路
（`vision_model = "qwen3.8-max"`）。`Brain` 的 `decide_llm` / `judge_llm`
两个独立槽位就是为这个设计的。**缺的不是机制，是两条**：

- **成文**：AGENTS.md（或 `build.py` 装配注释）里没有"贵模型只放必要步骤"的
  分级原则——现在这个分配（决策便宜、判定贵）是拍脑袋还是验证过，代码里看不出来，
  下次有人动 `build.py` 也没有依据可循。
- **验证**：当前分配是不是最优没测过。决策链（ReAct 循环里每次都调、量最大）
  用便宜档是省钱的正确方向，但降档对成功率的影响没有对照数据；反过来判定链
  用 pro 档的收益也没量化。

**没定的地方**：分级原则写进 AGENTS.md 还是只写装配注释；要不要补一组
"决策链升档/判定链降档"的对照实验——这条跟第 21 条（VLM 感知可靠性）耦合：
先有当前模型的正确率基线，降档实验才有可比的对照组。

### 24. 📋 memory 检索接口重做：项目无关的元数据倒排索引 + 语义检索（0908 拍板，待实施）

**现状**：`MemoryToolPort` 上的读方法是按各自的消费方专门定制的，形状互不相同——
`query_episode_steps(episode_id)` / `query_recent_steps(episode_id, limit)` 按局查，
`query_object_events(map_id, before_step)` / `query_object_events_at(place)` 按图/按格
查（且刻意不按 `episode_id` 过滤，是跨局的“这张图的共有知识”，服务
`decide`/`think_action`），`query_episode_summaries(scene, query, limit, run_id)` 按场景
做语义检索、单独收了一个 `run_id` 参数。每加一种新的检索维度就要新开一个方法，
接口没法直接挪给别的项目用。

**目标（0908 会话拍板）**：memory 只对外提供两种能力——元数据过滤检索、语义
相似度检索——不再为每种检索维度各开一个专用方法。

- **记录标识**：每条记录写入时由 memory 生成一个内部 uuid，不带语义，调用方
  不能也不需要从 `project`/`run_id`/`episode_id`/`step` 反推出它。
- **元数据过滤检索（倒排索引）**：memory 为每个 (字段, 值) 组合维护一份反向表
  （值本身怎么序列化由调用方决定，memory 不理解字段含义）：`(字段,值) → 记录
  uuid 集合`。查询时传一个“字段→值”的过滤条件字典，各字段各查各的候选集合、
  取交集。**所有字段地位完全对等**——`project`/`run_id`/`episode_id`/`step`/
  `map`/`scene`/`kind`……都是同一种字段，没有谁是“主键”、没有谁被结构性标记
  为必选，查询可以任意组合、任意增减字段，不需要为不同字段组合预建索引。
- **语义相似度检索**：向量检索，跟过滤检索是并列、独立的另一条路径，取代现在
  `query_episode_summaries` 这类专用实现。
- **过滤检索只支持等值/成员匹配，不支持大小比较**——这是索引支持的**操作类型**
  的限制，不是字段身份的限制：`step` 能像别的字段一样做等值查询，在过滤检索
  里跟 `map`/`scene` 完全对等；出不去的是“大不大于”这种区间比较，不管作用在
  哪个字段上都一样（不止 `step`）。`step` 的区间查询（“最近 N 步”、`before_step`）
  由 tool 层自己先用其余字段（比如 `episode_id`）把候选集筛到足够小，再对候选
  集里的数值字段做一次普通比较——这是 tool 层的领域知识（“`step` 只有同一局
  内才能比大小”），不是 memory 该内置的规则；tool 层漏传该带的过滤字段，是
  调用方把查询写错了，跟别的查询漏加一个条件是同一类错误，不该也不能靠
  memory 内部强制某个字段必选来兜底。
- **写入侧对称**：harness 把它知道的全部上下文（`project`/`run_id`/`episode_id`/
  `step`，以及 `map`/`scene`/`kind` 这类游戏语义字段）交给 tool 层；tool 层负责
  组装成写入时要带的字段集合、或者查询时要用的过滤条件字典，memory 只机械执行，
  不做任何折叠、派生或语义判定（沿用 `AGENTS.md` 第四节的分层原则）。

**影响面**：`MemoryToolPort` 现有的 `query_episode_steps`/`query_recent_steps`/
`query_object_events`/`query_object_events_at`/`query_episode_summaries` 这批专用
方法要收敛成“过滤检索 + 语义检索”两个通用方法，原来每个方法各自的查询逻辑
（按局、按图、按窗口……）下沉到 tool 层用通用方法自己拼过滤条件字典实现；
`EventObjectStore`/`KnowledgeStore` 等现有存储实现要重新落在这套统一索引结构上。

**没定的地方**：索引数据结构的具体落地（内存字典 / 落盘 B-tree 等）、现有
JSONL 落盘格式怎么迁移到这套“uuid + 元数据字典 + payload”的记录形状、这次
要不要顺带把 memory 拆成独立可复用的包（服务“以后别的项目也用”这个目标）
还是先在本仓库内把接口收敛掉——这几点留到实施前再定，这一条先只定接口设计
本身。

## 后续阶段（P1 起，依赖 P0 完成）

| 阶段 | 内容 | 依赖 | 状态 |
|---|---|---|---|
| P2 可审计 | 审计器失效率统计（`eval_report.py` 已实现，见 `evaluation/SPEC.md` 10.4a）；judge/verify 人工标定样本仍未做 | 第 2 条可观测 | 🚧 进行中 |
| P4 文档体系 | 目录建好、每篇新问题有经验文档、索引持续更新 | 无 | ✅ 运转中 |

（原 P1 可观测已提升为路线图第 2 条，不在这张表里重复列出。）

## 工程基础设施缺口

| 缺口 | 影响 | 优先级 |
|---|---|---|
| 无依赖锁定（无 lock file） | 两次跑同一批实验可能因依赖漂移拿到不同数字 | 中 |
| prompt sha 没接进测评报表 | 人要手工对照版本 | 低 |
| CI 到不了真实集成 | ROM 不进 git，CI 只能跑 mock 路径 | 低，结构性限制 |
| 批次实验严格串行 | 19 条任务顺序跑，一批要跑数小时 | 中，等 P0 做完再考虑 |
| 没有跨批次回归对比 | `eval_report.py` 只产出单批次报表 | 低 |
| `trace_data/`、`log/audit.jsonl` 均无 rotation/归档，持续追加写不清理 | 长期运行单目录读取变慢、磁盘占用不可控；`log/audit.jsonl`（`agent_permission` 库自动写的权限审计日志）目前纯写无读，没有任何代码汇总/告警它；0904 新增 `TraceEvent.frame_png`（原始感知帧，base64 内嵌进 `episodes/*.jsonl` 每一行，不是独立文件——设计中途从"另存 PNG 文件+路径引用"改成"直接存二进制字段"），行体积因此明显变大，同样没有 rotation，长期高频跑量时这条缺口应该优先处理 | 中（原"低"，帧数据加入后磁盘占用增长速度明显变快，权限审计那部分仍按用户 0902 的话"先放着"） |

### 25. 📋 项目拆分五块：主框架 / memory / plan 系统 / judge 系统 / A2A（0909 定方向，细节未定）

**用户 0909 提出的拆分方向**：把现在这个单体项目拆成五块——① 现在的主框架
（harness 靠 tools 跟各外部系统打交道那一套）；② memory 系统，细分三条腿：
a. 元数据查询、b. 相似度查询、c. wiki 类知识库（用户指定参照
[Tencent/WeKnora](https://github.com/Tencent/WeKnora)——文档→可查询 RAG→
agent 自动蒸馏成结构化互链 wiki 词条+知识图谱、自维护不用人工整理）；
③ plan 系统，独立出来、支持背景信息组装 + human review；④ judge 系统，
同样独立、同样支持背景信息 + human review；⑤ A2A 系统，把现在的
`RunDataCenter`（第 1 条）拆出来。**这次只定大方向和建议顺序，每一块具体
怎么改留到分别动手时再定**，写这条只是把方向和顺序记下来，不是开工。

**跟现有条目的关系**（拆分不是从零开始，是把已经存在的接口边界拉开）：

- ①主框架：不是新增职责，是②③④拆完之后的收尾——`RunHarness.plan()`/
  `EpisodeHarness.judge()` 两个节点退化成"调一次独立系统的端口方法"，
  跟现在调 `BrainToolPort.choose_once()` 一个形状。
- ②memory：a/b 两条腿本质上就是**第 24 条**（元数据倒排索引 + 语义检索，
  0908 已拍板待实施）——c 条 wiki 腿是这次新加的第三条，建立在 24 条的
  通用检索能力之上：wiki 词条本身也是"一条记录"，一样吃 24 条的存储/检索
  设计，不需要另起一套存储层。
- ③④plan/judge：现在分别是 `RunHarness.plan()`/`Brain.plan_once()` 和
  `EpisodeHarness.judge()`/`Brain.judge()`，骨架已经对——两个系统形状高度
  相似（问模型 → 背景信息组装 → 可选人工审查 → 写回结果），建议**同批做**，
  不要先做一个再回头改另一个。human review 复用 `RunDataCenter`
  已经跑通的槽位传输层（第 1 条），给 plan/judge 各开一个独立槽位，不是
  重新发明一套协议——现在 `RunHarness.review()` 只有 episode 结算后一个
  时机，这次要拆出"计划生成后""判定给出后"两个更早、更细粒度的介入点。
- ⑤A2A：`RunDataCenter`（第 1 条）现在是 `RunHarness`/`api.py` 共享的
  进程内对象，本质已经是 Task（goals/review 槽=待处理请求，前端轮询）的
  雏形，跟 [Google A2A 协议](https://a2a-protocol.org/latest/specification/)
  的 Task/Message/Agent Card 概念比想象中接近。**不建议一步到位换协议**：
  先让它变成一个能被多个 client（`RunHarness`、`api.py`、以后可能的 plan/
  judge 独立服务）共同访问的边界（哪怕先只是本地 HTTP），协议细节等真的
  需要接第二个独立 agent 时再补。

**建议顺序**：② memory 补 wiki 腿 → ③+④ plan/judge 同批拆（背景信息组装+
review 槽位公共骨架抽一次，两边套用）→ ① 主框架瘦身收尾 → ⑤ A2A 对外拆分。
理由：②是③④的地基（plan/judge 的背景信息组装要吃 memory 检索）；①天然是
③④做完之后的收尾动作；⑤涉及进程边界，最该等前四块内部形状稳定了再动。

**怎么实现（简单描述，接口/schema 等真动手时再细化）**：

- **①主框架**：不新写代码，是②③④拆完后的摘除动作——`RunHarness.plan()`/
  `EpisodeHarness.judge()` 节点体里现在直接调 `Brain.plan_once()`/
  `Brain.judge()` 的部分，换成调新拆出去的 PlanSystem/JudgeSystem 的端口
  方法（形状照抄现在 `BrainToolPort.choose_once()` 那种"harness 只管调、
  不管怎么问模型"的样子），`Brain` 瘦身、两个方法搬家。
- **②memory（补 c 条）**：新开 `memory/wiki/` 包，存储层直接复用第 24 条
  要建的通用倒排索引（词条也是一条"记录"，带 `kind=wiki_entry` 元数据，
  走同一套过滤检索，不用另起存储层）。新增一条"蒸馏成词条"的生成流程，
  形状类似现有 `episode_store.py` 的摘要蒸馏链——定期/按需把一批 episode
  摘要+知识库检索命中喂给模型，产出"新增/更新哪条词条"，词条之间交叉引用
  先用字符串 id 互指（不用真图数据库）；可追溯来源靠现有 trace 的
  `event_id` 反查，不用另建审计表。
- **③④plan/judge（同批做，形状一样）**：各开一个新模块（如
  `plan_system/`、`judge_system/`），每个里面三样东西——① 一个"背景信息
  组装"函数（显式列清楚这次喂模型的上下文：目标栈/历史摘要/知识检索命中，
  不隐式拼字符串）；② 复用 `Brain` 现有的 `plan_once`/`judge` 方法问模型
  （原样保留，只是调用方换了）；③ `RunDataCenter` 里新增两组 review 槽
  （如 `plan_review`/`judge_review`），字段形状和阻塞轮询逻辑照抄现在的
  review 槽，不重新设计协议。`RunHarness.plan()`/`EpisodeHarness.judge()`
  节点问完模型后多一步"发布到对应槽、等（或不等）人工确认"。
- **⑤A2A**：先不换协议，把 `RunDataCenter` 从"`RunHarness`/`api.py` 各持
  一个引用的 Python 对象"改成"自己起一个小 HTTP 服务（进程内嵌或独立进程
  都行，先选简单的），暴露现在那几个方法对应的 REST 端点"——`api.py` 现有
  的 `/goals`/`/review`/`/note` 端点形状不用大改，只是背后从"直接调 Python
  对象"变成"`api.py` 和 `RunHarness` 都通过 HTTP 调同一个服务"，为以后接
  第二个独立 agent（比如独立部署的 plan 系统）铺路。

参考案例（讨论时查的，不是照搬）：[Voyager](https://arxiv.org/abs/2305.16291)
（经验→蒸馏→入库→检索复用的自动化闭环，对应②c 和 Agent 清单第 9 条）、
[HiPlan](https://arxiv.org/pdf/2508.19076)（全局里程碑+每步局部提示的双层
规划，对应③的背景信息组装）、[Architecting Resilient LLM Agents:
Plan-then-Execute](https://arxiv.org/abs/2509.08646)（规划与执行分离、
阶段边界天然是审查点，对应③④的 review 槽位设计）。

## 对照业界：现在的测评覆盖了什么

现在 19 条 `knowledge_*` 短任务（≤15 步、单目标、二元成败）大致对应
BALROG 里 BabyAI 那一档，测的是"认不认识菜单、按不按得对键"，不是"能不能
打通一段有真实策略深度的内容"。

| 类别 | 代表 | 测的是什么 | 我们现在有没有 |
|---|---|---|---|
| 长程里程碑 | Claude Plays Pokemon；`PufferAI/pokegym` | 数千步连续决策一致性，用里程碑而非固定步数二元判定 | 没有——最长任务链只有 3 个子任务 |
| 对战策略深度 | `PokéChamp`（ICML 2025）、`PokeLLMon` | 招式克制、换宝可梦时机等策略决策 | 没有——现在只测操作正确性 |
| 试验一致性 | `tau-bench` 的 `pass^k` | 同一任务独立跑 k 次，是否每次都成功 | 部分有——`--repeat` 能跑 N 次，但没单独拆出"是否每次都成功" |
| 通用长程智能体 | GAIA、SWE-bench、OSWorld | 分难度层级、任务集大部分不公开防止针对性记忆 | 没有——19 条任务判据全公开，且部分解法已提交进仓库（见第 12 条） |

建议吸收但不是现在做：批次报表加"是否 k 次都成功"一列；给长程目标定义
里程碑判据；对战任务加"招式选择质量"判据；核实第 12 条的记忆泄题风险
（优先级最高，可能让现有数字从一开始就不可信）。

Sources: [PokéChamp (ICML 2025)](https://arxiv.org/abs/2503.04094) ·
[BALROG](https://balrog-ai.github.io/docs/index.html) ·
[Claude Plays Pokemon 评测方法（ZenML 摘要）](https://www.zenml.io/llmops-database/building-and-deploying-a-pokemon-playing-llm-agent-at-anthropic) ·
[PufferAI/pokegym](https://github.com/PufferAI/pokegym) ·
[PWhiddy/PokemonRedExperiments](https://github.com/PWhiddy/PokemonRedExperiments) ·
[PokeRL (2026)](https://arxiv.org/abs/2604.10812) ·
[LLM Pokémon League](https://www.emergentmind.com/topics/llm-pokemon-league) ·
[PTCG-Bench (2026)](https://arxiv.org/abs/2605.29653)

## 已完成

| 内容 | 说明 |
|---|---|
| ✅ 经验文档体系 | `docs/experiences/` + 四段式模板，见 `EXPERIENCE_DOCS.md` |
| ⏪ 测评：judge 机械复核（已移除） | `evaluation/audit_verdicts.py` 曾实现（19 条任务规则 + 32 个回归测试），2026-09-02 用户决定不需要、已删除，见 `evaluation/SPEC.md` 五节 |
| ✅ CI/CD 骨架 | `.github/workflows/ci.yml`：lint（ruff）+ test（pytest，3.11/3.12 矩阵） |
| ✅ 打包 bug 修复 | `pyproject.toml` 补显式包声明，`pip install -e .` 之前从未真正跑通过 |
| ✅ `memory_carried` 可观测 | `EPISODE_START` 记录开局时跨局摘要池大小，能看出批次内记忆污染 |
| ✅ 重试循环从 brain 挪到 harness | `Brain.choose_once`/`_perceive_once` 只负责单次尝试，重试驱动移到 `harness_utils.choose_with_retry`/`perceive_with_retry`；trace 里每次 attempt 现在是独立调用，时间戳分得清 |
| ✅ 无头模式限速回归修复 + 决策 async 移除 | `pyboy_world.py` 恢复无头不限速（并补回被误删的 `_tick`/`_frame_png`/`latest_frame`）；`choose_with_retry` 改同步调用，`Brain.choose_once_async`/`_executor`/`IDLE_FRAMES_PER_POLL` 删掉——decision 本身的模型延迟长尾原因仍未查清，见第 10 条 |
| ✅ `Source` 精细化 + 补 `STALL_CHECK` 事件 | 新增 `Source.PLAN`（`RunHarness.plan` 的模型调用从 `Source.HARNESS` 移出，不再和零成本记账事件混算 token）；`MEMORY_READ`/`STEP_MEMORY_WRITE`/`OBJECT_MEMORY_WRITE`/多数记忆相关 `permission_skipped` 统一改 `Source.MEMORY`（以前分散在 `DECISION`/`HARNESS`）；新增 `EventType.STALL_CHECK`，`detect_stall` 每一步把 `stall_key`/`stall_count` 写进 trace，不再只活在内存里。`verify_steps` 的两处 `Source`/事件粒度问题特意没动，见第 9 条 |
| ✅ `recursion_limit` 撞限修复 | `episode_harness.py::run()` 撞过 `GraphRecursionError`——图之前从 5 节点/步拆成现在的 17 节点（continue 分支 15 节点/步），但 `recursion_limit = max_steps * 6 + 20` 是拆图前留的老公式，一直没跟着改，导致 `max_steps` 稍微大一点就会在没跑完步数时被无声打断。改成 `max_steps * 16 + 20`（15 节点 +1 余量），并在代码里加注释警告这个数字要跟 `_compile()` 的节点数同步改。用一个跟真图形状一样（15 节点/步的环）的最小 LangGraph 复现验证：旧公式在 `max_steps=15` 时确实撞 `GraphRecursionError`，新公式跑完整局、`step` 数对得上。`docs/spec/harness/SPEC.md` 里旧的"×6"公式说明还没同步改，等测试/spec 解冻信号一起处理。**0902 已在真实 run 验证**（`run-20260901-195813-c9dd14`，重启后新代码进程）：ep1/ep2 均跑满 `max_steps=3` 正常终止（`max_steps_exceeded`），不再撞限；此前 19:15 那次撞 `recursion limit 38`（= 旧公式 `3×6+20`）确认为改动前旧进程所跑 |
| ✅ 观测台一键启动 `dev.ps1` | PowerShell 5.1 兼容脚本：选 Python（py -3.12 优先）→ 起 `python -m pokemon_agent.api`（:8000）+ vite（:5173，代理 `/health`、`/runs`）→ `Wait-Process` 一个退出即全杀。0901 执行验证通过（前后端均正常、`/health` 返回 ok）；注意：后端慢启动约 8–15s、uvicorn 日志走 stderr（`dev-api.err.log`）、中文 `Write-Host` 在重定向场景乱码（交互终端不受影响），详见 `docs/devrun-2026-09-01.md` |
| ✅ 摘要蒸馏字段长度上限整条拒绝响应 | `MemoryEpisodeSummaryResp.summary`/`EpisodeMemory.summary` 的 `max_length=200` 已删除——0901 真实 run（`run-20260901-195813-c9dd14`）复现过一条字段超长导致 `EpisodeSummaryParseFailure`、整条摘要（含质量很高的 reusable_patterns）被丢弃、本 run 摘要零写入、重试从零开始的问题。**注意**：prompt 模板（`episode_summary.md`）目前没有对应的软性字数要求，字段本身描述里"100字以内"的说法也一并删掉了（那句话本来就没传给模型，是摆设）；要不要在 prompt 里补软约束还没决定 |
| ✅ `run_harness.py` 只留控制流，拆出 `run_utils.py` | 跟之前 `episode_harness.py`/`utils.py` 是同一次重构的第二半：`RunHarness` 只留五个图节点该问哪个依赖、该走哪条边；`_ask_planner`/`_parse_plan`/`_to_tasks`/`_apply_edit`/`_history_lines`/`_goals_lines` 这些重试循环、LLM 调用记账、纯计算全部搬进新文件 `harness/run_utils.py`（对应函数改自由函数：`ask_planner_with_retry`/`parse_plan_response`/`to_tasks`/`apply_goals_edit`/`history_lines`/`goals_lines`，外加从 `reflect()` 里顺带抽出的 `goal_retries_exhausted`）。原来给 episode 用的 `harness/utils.py` 顺带改名成 `episode_utils.py`（`episode_harness.py` 里的 `harness_utils` 别名同步改成 `episode_utils`，22 处调用点），两个工具文件按局内图/run 级图分清楚、互不依赖。冒烟验证：`run_utils` 纯函数/`ask_planner_with_retry` 独立测过一遍，外加一次假端口跑通整张图（`begin→plan→dispatch→reflect→review→plan→END`）确认拆分后行为不变；`ruff --select F401,F821,F841` 干净（`run_harness.py` 里那个 `HarnessPort` 未用导入是拆之前就有的老债，按约定没动） |
| ✅ 补 `RUN_START`/`RUN_END`，judge/verify_steps 的 `attempt` 字段 | 对应第 4 条 a) 和原第 4 条：新增 `EventType.RUN_START`/`RUN_END` + `trace_utils.run_start`/`run_end`/`run_error`（`episode_id` 位置放 `run_id`、`step` 恒为 0，跟 `Source.PLAN` 是同一个约定），`RunHarness.run()` 现在开局写 `RUN_START`，正常/异常收尾都写 `RUN_END`（异常带 `why`），模式照抄 `EpisodeHarness.run()` 的 `episode_start`/`episode_end`/`episode_error` 三段式。另外 `Brain.judge()`/`Brain.verify_steps()` 四处 `ModelCall` 构造（各自的成功/异常路径）都补上了 `"attempt": "1"`——两条链目前都不重试，以前是漏记不是没有第二次。冒烟验证：假端口把 `RunHarness.run()` 正常路径和异常路径各跑一遍，确认首尾事件分别是 `RUN_START`/`RUN_END` 且异常路径带 `why`；`@initialize` 包一层后真调一次 `Brain.judge()`，确认返回的 `ModelCall.payload` 带 `attempt`。第 4 条 b)（进程层 INTERRUPTED 兜底）和 c)（plan 调用次数复核）还没做，见第 4 条 |
| ✅ `RunDataCenter`：前后端交互统一（goals 槽 + review 槽，含真阻塞轮询） | 对应第 1 条：新模块 `pokemon_agent/harness/run_data_center.py`（`RunDataCenter` + `DataCenterReviewer`），goals 槽原样搬自 `RunHarness` 的旧内部字段，review 槽新增（`publish_review_request`/`pending_review`/`submit_review_response`/`await_review_response(timeout, poll_interval)`——`timeout<=0` 立即返回 `None`，`>0` 真阻塞轮询直到超时或有答复）。`RunHarness.review()` 现在把 `episode_trace`（`run_utils.episode_trace_events` 按 `episode_id` 过滤出的单局完整 trace）塞进`HumanReviewReqFromHarness` 一起发布。`api.py` 新增 `GET/POST /runs/{id}/review`，`GET /runs/{id}` 响应体补 `review_pending` 字段；`REVIEW_TIMEOUT` 默认 0（审查面板还没做，先不真阻塞，等价于原来的 `AutoContinueReviewer`）。前端补数据层：`types.ts`（`HumanDecision`/`PendingReview`/`ReviewSubmitReq`/`ReviewSubmitResp`）、`api.ts`（`getPendingReview`/`submitReview`）、新文件 `useReview.ts`（2s 轮询，同 `useRunGoals` 模式）；审查面板 UI 组件本身留作后续任务。冒烟验证覆盖 goals/review 槽单测、`DataCenterReviewer` 超时与真答复两条路径、`RunHarness` 全链路集成（`episode_trace` 非空且只含当局事件、槽位生命周期对）、`api.py` 端点全流程（`TestClient` 走一次 202→review_pending=True→GET 详情→POST 决策→409 复查）；既有测试套件跑过一遍无回归。**已知连带回归**：`tests/test_api.py::test_review_endpoint_removed` 断言端点不存在，现在端点真实存在，等测试解冻信号再改 |
| ✅ `verify_steps` 改检索增强验证 + 节点拆分 + `verify_llm` 独立可配置 | 对应第 9 条：`step_verify.md` 重写（写死的领域规则全删，改成读 `$knowledge` 占位符，覆盖不到时兜底 `reliable=false`）；`StepVerifyReq` 加 `knowledge` 字段；新增 `episode_utils.build_verify_knowledge_query`（整局 entries 的 scene/overlay/action 并集 + goal 拼查询，同 `build_knowledge_query` 的教训）；新增独立 `Source.VERIFY`（原来跟 `judge` 共用 `Source.JUDGE`，token/延迟分不开）；新增 `trace_utils.verify_call`，结构化 `verdicts`（`index`/`reliable`/`why`）落 trace 而不是只留 `reliable` 集合。**落地时按用户要求做了架构修正**：初版实现把检索+校验揉进一个节点，违反 `EpisodeHarnessPort` 的"每个节点只改状态里一处"接口约束——改成三个独立节点 `retrieve_verify_step_memory`（只改 `verify_step_entries`）→ `retrieve_verify_knowledge`（只改 `verify_knowledge`）→ `verify_steps`（只改 `verified_steps`，读 state 已查好的两项，不自己查库），`retrieve_verify_step_memory` 后按有无 step 记忆路由分流，空则直接跳 `summarize`；图从 17 节点变 19 节点，`EpisodeHarnessPort` 文档/ASCII 图同步更新。`Brain.__init__` 加 `verify_llm`（缺省回退 `judge_llm`，向后兼容），`build.py` 的 `build_real()` 加 `verify_model` 参数。冒烟验证：7 段测试覆盖三个节点各自只改一处状态、query 带 entries 的场景/动作特征、空 entries 时路由结果、`verify_steps` 读 state 而不重新查库、`verify_llm` 真的独立于 `judge_llm`（含不传时回退、传了用自己两条路径）；既有测试套件 53/53 相关用例通过，无回归。**还没做**：真实数据 ground truth 核对，跟第 3 条测评体系一起做，见第 9 条 |
| ✅ 审查面板 UI + `REVIEW_TIMEOUT` 真启用 | 对应第 1 条：`REVIEW_TIMEOUT` 默认 0→5，`RunDataCenter` 补 `review_deadline()`，`GET /runs/{id}/review` 响应体加 `deadline_ts`；`web/src/App.tsx` 新增 `ReviewPanel`（outcomes/last_task 展示 + continue/stop/retry/push 四按钮 + 倒计时 + 超时自动兜底提示）；`useReview.ts` 轮询间隔 2000ms→500ms（配 5s 超时，原间隔太粗会吃掉近一半的可反应窗口）。`tsc --noEmit` 无报错；后端 `RunDataCenter`/`DataCenterReviewer` 的 deadline 逻辑单独脚本验证过（5s/0.2s 超时、清空归零、超时兜底成 CONTINUE 三种场景）；`tests/test_api.py` 端到端跑不了（这个精简 device VM 环境装不上 `agent_permission`，同 evaluation 那次 ruff/pytest 限制），只到单元级别 |
| ✅ `eval_report.py` 补充审计失效率统计 | 对应本次可观测/审计全项目扫描：`Source.VERIFY` 的 `payload.verdicts` 之前只落 trace 没人解析，`SourceMetrics` 新增 `verify_total`/`verify_unreliable`/`verify_unreliable_rate`/`verify_parse_errors`，报表按链路多一行"审计失效率"明细，见 `evaluation/SPEC.md` 10.4a；3 个新测试（可信/不可信混合、`verdicts` 解析失败、无 `verdicts` 字段的普通链路不受影响），`evaluation/tests/` 共 17 个用例全过。对应 P2 可审计从 📋 推进到 🚧 |
| ⏪ 删除死代码 `tests/test_step_audit.py` | 这个测试文件引用的 `Brain.audit_steps`/`Brain._parse_audit`/`pokemon_agent.schemas.communication.step_audit`（`StepAuditReq`/`StepAuditResp`/`StepAuditVerdict`）在当前代码里根本不存在——某次重构把这套机制改名成 `verify_steps`/`step_verify.py`（`StepVerifyReq`/`StepVerifyVerdict`），测试文件没跟着改名，`import` 那行直接 `ModuleNotFoundError`，整个文件在 collection 阶段就挂了，从未真正跑起来验证过"审计器永远返回不抛异常""解析失败全部标不可靠"这两条核心契约。0902 全项目扫描发现，用户确认"删掉test"，已删除；真实机制（`Brain.verify_steps`）继续由 `EpisodeHarness` 的图节点覆盖，没有独立单测这件事本身是个遗留缺口，但不在本次范围内 |
| ✅ 观测台事件流断线提示 + 四栏性能优化 | 对应本次可观测扫描发现：`useRunStream.ts` 之前只监听 `trace`/`done`/`error` 三个具名 SSE 消息，从没注册 `onerror`（对比 `useFrameStream.ts` 有），断线时前端没有任何视觉提示，只能靠"事件列表很久没变"猜。改成返回 `{events, connected}`，`onerror` 时 `connected=false`，`App.tsx` 加一条"事件流已断开，浏览器正在自动重连…"的提示条（不影响浏览器自身的自动重连，纯展示）。顺带给 think/act/observe/其他 四个 `filter` 加 `useMemo`（原来每次渲染都全量重新过滤+反转，长 run 几千条事件会有实打实的性能问题）。用户对前端这块要求是"能用就行，你想干嘛干嘛"，按最低成本方案做，没上虚拟滚动/rotation |
| ✅ `map_hint.md` + `decide_action.md` 修正 trace#20 归因 | **0903 用户指出我最初诊断错了**：以为"已知地图41是初心镇宝可梦中心"是模型训练时记住的攻略，实际重新查了 `read_knowledge` 的 `refs` 才发现——这条是**如实检索到的项目知识**（`pokemon_agent/memory/semantic/knowledge/pokemon_center.md`，运营维护、只读，内容属实），不是模型编的。真正的问题在下游：模型把"知识说这个方向最终能到宝可梦中心"（跨地图关系，长期为真）和"屏幕边缘的下一格就是门"（这一帧还没加载出来，`walk_map`/`neighbors` 里根本没有）混成了一件事，并且把这个预测提前写成"因为……满足'站在门前台阶上'判据"存进 `StepMemory.rationale`——而 `rationale` 是决策时的原始说法，写入后不会再核对（`step_memory.py` 文档本身就写明"不是已经验证过的结论"），执行后的 `after` 状态其实四邻全是 `.`，没有任何门的证据，但已经晚了。改了两处 prompt：`map_hint.md` 把"训练时地图攻略不是证据"改成准确的说法（检索知识说的是"地图之间的关系"，不是"这一屏此刻有什么"）；`decide_action.md` 的 `rationale` 要求里加两条硬规则——只写"现在已经看到的"不写"这么走了之后会看到什么"，以及 rationale 不许对目标判据下结论（那是 judge 的职责）。`load(...)` 渲染验证过两个文件都正常；**效果仍要等下一次真实 run 观察**
| ✅ prompt 装配架构重排：统一入口 + 按用途分目录 + 组装逻辑收进单文件 + Brain 全部改收单一 req | 0904 一次连续重构，起因是"prompt 该怎么组织"的讨论。**目录**：`pokemon_agent/prompts/` 下按"谁只服务谁"分区——`calls/` 平铺五个没有复用片段的独立模板（`judge_success`/`run_plan`/`step_verify`/`episode_summary`/`perceive_screen`），`decide_action` 带四个只服务它自己的片段（`button_help`/`map_hint`/`repeat_hint`/`retry_note`），单独挪进子目录 `calls/decide_action/`——查过这四份没有任何一份被别的模板复用。**读取**：`load(name)` 改成整棵 `prompts/` 目录树递归找 `<name>.md`，调用方不用关心某份 prompt 在哪层子目录，两处重名当场 `assert`。**组装**：以前分散在 `game_hints.py`/`brain_hints.py`/`Brain._build_prompt()` 三处的 `decide_action` 拼装逻辑收进一个新文件 `prompts/decide_action.py`，`game_hints.py`/`brain_hints.py` 已删除；`judge_success.py`/`step_verify.py` 同理新增，把原来分别嵌在 `Brain.judge()`/`Brain.verify_steps()` 方法体里的渲染逻辑搬出来。**Brain 边界**：`Brain` 现在完全不认识 `pokemon_agent.prompts` 这个包——`choose_once`/`judge`/`verify_steps`/`reflect` 四个方法全部只收一个 req 参数，不再有"prompt 字符串"和"其余参数"分开传的情况；`judge`/`verify_steps` 原来"渲染也在 try 里"以维持"永不抛异常"契约的写法，改成渲染搬到调用方（`EpisodeHarness`）后，由调用方自己包一层等价 try/except 接住 `build_prompt()` 可能抛的 `KeyError`，`Brain` 内部 try/except 收窄到只包模型调用这一步。**req 复用**：`BrainDecisionReq`/`BrainVerdictReq`/`StepVerifyReq` 都加了 `prompt: str = ""` 字段，跟对应的 `build_prompt()` 共享同一个对象——先拿其余字段拼 prompt，`req.model_copy(update={"prompt": ...})` 回填，再整个交给 `Brain`，`EpisodeHarness` 里原来同一批字段构造两遍（一遍给 req、一遍给 `build_prompt` 位置参数）的重复消掉了；新增 `ReflectReq`（`before`/`action`/`after`）同理收进 `Brain.reflect()`，统一"模块间调用只认一个 req"这条规则。**验证方式的限制**：这个 device VM 的 `python3` 装不上 `pydantic`/`agent_permission`（长期已知的环境限制，见下方基础设施缺口），没法跑真实 import/pytest，验证靠 `ast.parse`（语法）+ 手写的 unused-import 扫描——11 个改动文件全部通过，代码里搜不到任何残留的旧签名调用点，但**没有一次真正跑起来的端到端验证**，跟下面 `tests/test_episode_stall.py` 的遗留问题是同一类风险。**已知遗留**：`tests/test_episode_stall.py` 的 `FakeBrain.build_decision_prompt`/`choose_once_async` 等桩方法现在对不上新签名，按约定等测试解冻信号再改；`button_help.md` 与 `knowledge/battle_actions.md` 重复写"战斗菜单是 2×2"这条（0903 审计发现）还没修，同样等信号 |
| ✅ 修掉 `button_help.md` 与 `knowledge/battle_actions.md` 重复写"战斗菜单是 2×2"这条 | 0903 审计发现的遗留项：`button_help.md` 的 choice/left、choice/right 两行硬写死了"只有 2×2 排布的选择框（战斗行动菜单）用得上"，跟 `knowledge/battle_actions.md` 的内容完全重复，且两者在 battle 场景下的同一次 `decide_action.md` 调用里会同时被渲染进去。改成泛指"只在选择框是横向多列排布时才有效果"，把"具体哪些场合是"这个领域知识留给 `$knowledge` 占位符检索，不再硬编码进这份常驻加载的模板。`perceive_screen.md` 里同一条知识（指令框是 2×2）**没有改**——那是结构性例外：这份 prompt 的职责就是从像素判断 `scene` 本身，判断出来之前无法先按 `scene=battle` 去检索"战斗知识"再喂给它，检索的前提在这一步还不成立；在 `pyboy_world.py::perceive_once()` 的方法文档里补了这条例外的书面说明，供以后审计时对照。|
| ✅ `_render_human_note()` 硬编码提示词搬进 `human_note.md` | 用户 0905 明确要求"所有关于 prompt 渲染的问题全部交给 prompt"，全项目扫描后发现的唯一违规点：`decide_action.py::_render_human_note()` 把"人类刚刚插的话（最高优先级）"这整段指令性文字（标题+最高优先级声明+格式要求）硬编码成 Python 字符串字面量，只有 `note` 本身是变量，跟 `button_help.md`/`map_hint.md`/`repeat_hint.md`/`retry_note.md` 那套"内容在 `.md`、Python 只管数据/开关逻辑"的既定模式不一致，也就绕开了 `PromptTemplate.sha` 的版本追踪。改法完全照 `retry_note.md`/`_RETRY_TEMPLATE` 的先例：新建 `calls/decide_action/human_note.md`（原文一字不改，只把 `f"> {note}"` 换成占位符 `$note`），模块顶部加 `_HUMAN_NOTE_TEMPLATE = load("human_note")`，`_render_human_note()` 收缩成"空串不渲染，否则 `_HUMAN_NOTE_TEMPLATE.render(note=note)`"两行。**验证比前几轮更扎实**：`pokemon_agent.prompts` 这个子包本身不依赖 `pydantic`，这台 device VM 上真的能直接 `import`/`load()`/`.render()` 跑通（不只是 `ast.parse`），拿一句测试插话跑了一遍，逐字节比对渲染结果和原硬编码版本完全一致（含空行位置——`.md` 文件末尾多余的换行符一度会在 `$human_note_block` 和后面 `## 目标` 之间多插一个空行，已 `rstrip` 掉），`sha=f5a1d5b5e448`。|
| ✅ trace 落盘感知帧：每一次感知的原始画面挂到对应的 OBSERVE/VIEW 事件上 | 用户提出的新需求：想在回看 trace 时能看到模型当时实际看到的那张画面，不只是解析出来的 `facts`。**第一版做法（同一天内被用户否决）**：`WorldPerceptionResp` 新增 `frame_png: bytes`，`TracePort.save_frame()` 另存成独立 PNG 文件、`payload` 里塞一个 `frame_path` 字符串引用——用户明确要求改掉："请保存到现有的 trace 类型里，只是多保存一个字段，并且我希望保存的是二进制字段，能直接读的"。**改后的做法**：`TraceEvent` 直接新增 `frame_png: bytes | None` 字段（不再是路径），配 `model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")`——pydantic v2 对 `bytes` 字段的默认 JSON 序列化按 UTF-8 解码，PNG 字节不是合法 UTF-8，不显式声明 base64 编解码会导致 `model_dump_json()` 落盘时报错/损坏。`TracePort.append()`/`LocalTrace.append()` 新增关键字参数 `frame_png`，直接传给 `TraceEvent` 构造；`payload: dict[str, str]` 的形状完全不动。`TracePort.save_frame()`/`LocalTrace._frames_dir` 整个删掉，`WorldPerceptionResp.frame_png`（`pyboy_world.py::perceive_once()` 里截好的 PNG）改为原样一路传：`episode_utils.perceive_with_retry()` 返回 `(观测, 帧字节)`（不再落盘），经 `EpisodeRunState.pending_frame_png: bytes | None`（新字段，跟 `pending_observation` 同生共死）传到下一轮 `look()`，那里调 `trace.append(*trace_utils.observe(...), frame_png=state.pending_frame_png)` 直接落进那一条事件；`trace_utils.observe()` 恢复成不认识帧这件事——二进制字段完全绕开它，由调用方在 `append()` 时另传。`look_after_action` 的轻量摘要事件仍不挂帧，理由不变：同一帧马上在下一轮 `look()` 里连着完整 `facts` 一起记一次。**已知取舍**：`trace_data/` 本来就没有 rotation/归档（工程基础设施缺口表已经记了这条），帧字节现在直接嵌进 JSONL 每一行，比独立文件更省一次目录管理，但也让单条 JSONL 行本身变大、`episodes/*.jsonl` 从纯文本变成夹带 base64 大字符串，行内容不再适合直接人眼扫读；长期高频跑量时这条缺口的优先级应该提前，这次没有顺带做 rotation。**验证方式的限制**：同上几轮，这台 device VM 装不上 pydantic/agent_permission，靠 ast.parse + unused-import 扫描验证，没有端到端真实跑过一局确认 `model_dump_json()`/`model_validate_json()` 真的能在这个 bytes 字段上正确来回转换。|

| ✅ trace#20 修复第二拍：`map_note`/`map_guide` 结构性拆分 + prompt 精简 | 用户明确要求"结构性重写"，不只是加规则。改了三处代码 + 两份 prompt：**a) `ActionSpaceForBrain` 新增 `map_note` 字段**，跟原来的 `note`（连按用法）分开——以前 `MAP_HINT`（怎么读地图/判断证据）和 `REPEAT_HINT`（按键链用法）拼在一起塞进 `note`，被挂在 prompt 的"可用按键"标题下面，语义和位置对不上。**b) `game_tools.py::_mask()`** 把两者分开赋值（`note=REPEAT_HINT`, `map_note=MAP_HINT`）。**c) `Brain._build_prompt()`** 新增 `map_guide=space.map_note` 参数，紧跟在 `facts` 后面渲染。**d) `decide_action.md`** 新增 `## 怎么读这些事实、判断证据够不够` 一节，`$map_guide` 紧接在 `已知事实` 之后（模型刚看完这一帧数据就读到判断证据的规则，不用等读完一大段按键说明），`rationale` 字段要求重排：两条硬规则（只写"现在已经看到的"+ 不许对判据下结论）提到最前面，并新增"自证"要求——断言某格是门/某个 landmark 必须写得出具体坐标，写不出就是在猜。**e) `map_hint.md`** 合并三处重复的"都来自模拟器内存/都不会错"表述成一处，新增"`neighbors` 没有旧缓存"规则（直接对应模型真实用过的托辞"neighbors可能是错误或旧缓存"），"检索知识说的是地图关系"一节挪到文件最前面，跟地图/坐标基本规则放在一起。验证：`ast.parse` 三个改动的 `.py` 文件干净；`ActionSpaceForBrain` 新旧字段默认值/赋值单测过；完整 render 一遍新版 `decide_action.md`（含真实 trace 数据）确认 `$map_guide` 落在 `已知事实` 正下方、`note`/`map_note` 分流正确；`evaluation/tests/` 17 个用例无回归。`tests/test_episode_stall.py` 等依赖 `agent_permission` 的用例这台 device VM 仍然装不上，老问题，非本次引入

| ✅ trace#20 修复第三拍：`knowledge`/`episode_memories` 从 `obs.facts` 里独立出来 | 用户进一步指出结构问题：总 prompt 要分清楚"固定存在的规则描述"和"按需检索的内容"，检索出来的东西要标明怎么塞、怎么信。查代码发现 `enrich_observation` 一直把知识库检索结果（`knowledge`）和跨局摘要（`episode_memories`）跟 `known_objects` 一起折进 `obs.facts`——三者混在"已知事实"里对模型来说长得一模一样，没有可信度区分（`known_objects` 坐标锚定、跟 `walk_map` 同级可信，另外两个是检索结果，可信度低得多）。改动：**a) `BrainDecisionReq`** 新增 `knowledge`/`episode_memories` 两个字符串字段。**b) `episode_harness.py`**：`enrich_observation` 不再把这两项折进 `obs.facts`（`known_objects` 因为坐标锚定、可信度同级，继续留着），`think_action` 直接从 `state.knowledge_semantic_memory`/`state.global_episode_memories` 现算文本拼进 `BrainDecisionReq`。**c) `Brain._build_prompt`** 新增两个参数，`decide_action.md` 新增"## 检索到的相关知识"（`$knowledge`，说明"检索覆盖不到当前场景是常态，不代表没有先例；检索到的是跨地图/跨局规律，不能替代已知事实"）和"## 跨局摘要记忆"（`$episode_memories`，说明"是之前几局自己总结的，可能带偏差，可信度低于本局内相关记忆"）两节，各自独立于"已知事实"和"相关记忆"。**d) `map_hint.md`** 里"站在D上怎么按"、"隔着柜台怎么和NPC互动"这两段操作细节挪进了知识库（`doors_and_warps.md`/`dialogue_interaction.md`，按场景检索，不用每次都塞进总 prompt），`map_hint.md` 留一句指针"这类细节按需检索时看'检索到的相关知识'"。`step_memory.py::SNAPSHOT_BLIND` 和 `episode_harness_port.py` 里对应的过时文档一并同步。验证：7 个改动文件 `ast.parse` 干净；完整 render 一遍新版 `decide_action.md`（`$knowledge` 用真实的 `pokemon_center.md` 内容）确认三类数据（已知事实/检索知识/相关记忆/跨局摘要）四节各自独立、顺序符合可信度从高到低；`evaluation/tests/` 17 个用例无回归。**这一拍改的是"总 prompt 的骨架"，不是某一句话的措辞**——效果仍要等真实 run 观察
| ✅ 全部 prompt 文件逐个复核并按"一个一个改"改完（quote 风格/JSON 围栏/共享内容去重/自相矛盾） | 用户要求"每个看看，格式是否有冲突，是否有改进的地方，是否清晰"，逐份读完 `pokemon_agent/prompts/*.md` 后按用户"一个一个改"的要求依次修：**1) `decide_action.md`**——统一引号为 `「」`、删掉 `rationale` 要求里和新加硬规则重复的旧段落、修正"已知事实"引言里把 `known_objects`（检索结果但同级可信）误描述成"不含任何检索结果"的自相矛盾。**2) `map_hint.md`**——统一引号，把嵌在别处、读起来突兀的"站在D上/隔着柜台"过渡句独立成一节 `## 有些操作细节按需检索，不是每次都写在这里`。**3) `perceive_screen.md`**——地形图例改用 `$terrain_legend`（原来手抄一份跟 `map_hint.md` 用的 `terrain_legend()` 措辞不一致，`@` 那行两边写法都不同），对应改了 `pyboy_world.py::perceive_once()` 传参和 import；修掉结尾"不要有```json包裹"跟第七节例子全带围栏的自相矛盾，统一成"不要有其他文字"；顺手修了一处引号混用（`"主角正上方"「左下角」`）和一处标题重复渲染（`## 七、每一类的输出样例` 打印了两遍）。**4) `episode_summary.md`**——输出格式补上 ```json``` 围栏，字段示例从类型占位符（`"str"`/`"float"`）换成具体内容（能直接 `json.loads`）。改 `TERRAIN_MEANING`/`MAP_CHARS` 之前 `grep` 过 `pokemon_agent/world/ram.py` 确认它被用来做每帧 `walk_map` 字符合法性校验，**没有**动这个共享源头，只改了消费方怎么引用它。验证：`ast.parse` 检查 `pyboy_world.py`；`load()`/`render()` 逐份跑通 `decide_action`/`map_hint`(`MAP_HINT`)/`perceive_screen`/`episode_summary`；`episode_summary.md` 新例子额外过了 `json.loads` 确认合法；`evaluation/tests/` 17 个用例无回归。复核沉淀的通用注意事项写进了第 3 条"prompt 更新注意事项"，供以后改 prompt 参考 |
| ✅ run 级 plan 入栈顺序诊断（第一版判断错了，已撤回）+ `run_plan.md` 措辞修正 + 补 plan 决策的 trace 缺口 | 用户贴了一张观测台截图：栈顶（当前正在执行）是"与宝可梦中心前台护士对话"，栈里更深处躺着还没做过的"走到宝可梦中心，画面中出现宝可梦中心"——**后者明显应该先做**，用户怀疑"planner 不理解子目标该怎么分解，反而给了一个更难实现的目标"。**第一版诊断（错的，已撤回）**：以为 `run_plan.md` 里"先压的先做"是"`push_goals` 列表第一项该最先执行"的意思，而代码 `state.goals + pushes` 原序 append 让列表最后一项变栈顶最先派发，跟这条承诺相反，于是把三处入栈代码（`plan()`/`review()`/`apply_goals_edit`）都改成了 `list(reversed(pushes))`。**用户当场纠正**：目标栈的真实规则是纯 LIFO——"不是先压的先做，是……压到栈顶，然后就会直接执行栈顶任务"，也就是**后压的先做**（列表最后一项变新栈顶、最先派发）——这正是撤回前的原始代码行为，代码从来没有 bug，是我误读了"先压的先做"这句话反而把正确的行为改错了。**撤回**：三处入栈代码改回原序 append，三处字段文档（`RunPlanResp`/`GoalsEdit`/`HumanReviewRespFromFrontend` 的 `push_goals`）也改回准确描述 LIFO 的说法。**真正需要改的是 `run_plan.md` 本身的措辞**：原文"按优先级从前到后（先压的先做）"确实是在误导模型——如果模型真信了这句话、按"先做的排前面"给列表，实际执行顺序会被系统倒过来，这次案例很可能就是这么发生的。改成明确告诉模型这是一个栈、列表最后一项最先执行，且用户补充了一条独立要求："任务之间应该有递进关系"——排在后面（更晚执行）的目标要建立在前面目标已经达成的基础上，一步步接近最终目的，不能跳过前置条件直接给更难更远的目标，这条也写进了 `run_plan.md` 的规则里。**顺带补的可观测缺口**（用户追问"trace 里到底有没有记 plan 给出新 plan 的时候"，答案是没有——一并修，这部分不受上述诊断反复影响）：`Source.PLAN` 的 `MODEL_CALL` 之前只有 token 账单，没有任何字段记 `push_goals` 具体内容或 `why`，新增 `trace_utils.plan_verdict()`（`EventType.LLM_OUTCOME`，`Source.PLAN`，`kind=verdict`，记 `done`/`pushed_goals`/`why`），跟 `judge_verdict`/`verify_result` 是同一个"账单记花费、LLM_OUTCOME 记结论"模式，`RunHarness.plan()` 三条非 `plan_failed` 出口（done / 压栈 / 都不做）各补一次调用。**验证方式的限制**：同上几轮，这台 device VM 装不上 pydantic/agent_permission，靠 ast.parse + unused-import 扫描验证改动的 `.py` 文件，没有真实跑一次 run 确认 `run_plan.md` 措辞修正后模型给出的 `push_goals` 顺序确实符合预期。 |
| ✅ `run_plan.md` 补"目标粒度"约束——之前压出来的目标细到单格移动 | 上一条 LIFO 顺序修正落地、用户重新跑了一段之后又贴了一张截图：栈顶（执行中）是"向上走一格"（判据"玩家角色 Y 坐标减少 1"），下面压着"向右走一格"——两个都是**单次移动**级别的原子动作，不是任务级目标。用户明确指出"目标有点太细了，应该是那种任务导向的，如果没有必要提供新 goal 可以直接 skip"。`run_plan.md` 原来只要求"具体、可判定"，没有下限约束，模型把"具体"理解成了"精确到每一格怎么走"。改了两条规则：**a)** 明确要求目标"任务导向"——是一段有实际意义的任务片段（通常要好几步到十几步），不是单次按键/单格移动这种原子动作，具体往哪个方向摸索、按几次键留给 episode 内决策代理自己处理；**b)** 新增一条独立规则，明确"如果栈顶目标已经足够明确、能直接让 episode 自己摸索完成，`push_goals` 应该留空"——这个 skip 选项代码层面（`resp.push_goals` 允许空列表）本来就支持，缺的是 prompt 没有明确鼓励模型用它，导致模型倾向于"每次都压点什么"而不是判断"这次到底需不需要压"。**跟上一条 LIFO 顺序修正是独立的两个问题**：顺序修正解决的是"给出的目标谁先谁后"，这条解决的是"给出的目标本身粒度对不对"——同一个 `run_plan.md`，同一次用户观察 run 的过程里连着发现了两处，按发现顺序分开记。**验证方式的限制**：这是纯 prompt 文案改动，没有代码变更，靠 `load()`/render 一遍确认模板本身语法没问题；措辞是否真的让模型输出更合适粒度的目标，要等下一次真实 run 观察。 |
| ✅ 诊断"judge 判不出成功"：根因是 `pokemon_center_enter` 的 `success_criteria` 写得太松（已发现未修） | 用户观察同一个 run：ep2 判 `done=true` 进了宝可梦中心之后，ep3~ep5 用几乎一样的目标反而连续 8 次判 `false`，问"为何现在的 judge 判断不出来成功了"。查 trace 逐步核对后发现根因不在 judge 本身，而在**判据写得太松**：ep2 的目标来自 `tasks.py` 固定任务 `pokemon_center_enter`，其 `success_criteria` 是"scene 是 indoor，且 map_id 和历史里门外那几步不同（已经换过一次图）"——这条只要求"进了随便一栋建筑"，没有要求任何宝可梦中心特有证据，`map_id=41` 那个小房间（一桌一椅一人）满足字面判据，judge 照判据"正确地"判了成功；而 `plan()` 看到这条成功记录后又 push 了一个同名新目标，这次 `plan()` 自己生成的 `success_criteria` 明显更严格（要求护士乔伊/治疗台等证据），ep3~ep5 连续判 `false` 因此也是"正确"的——因为按这条更严的判据，agent 确实还没到真正的宝可梦中心。**用户随后纠正了这个诊断的前提**：指出 ep2 进的那个房间"根本就不是大木博士，就是宝可梦中心"——也就是说 `map_id=41` 那个房间本身可能真的是宝可梦中心，而后续几步 VLM 把里面的 NPC / 对话来源误标成"大木博士"是**感知（VLM）本身的幻觉**，不是"criteria 太松导致的巧合误判"这一个原因就能完全解释的；真实情况更可能是两个问题**同时存在**——criteria 确实写得过松（不该只靠"换了张图"就判定宝可梦中心），VLM 对室内场景/NPC 身份的识别也不可靠（`overview`/对话来源标注可能张冠李戴）。**这条目前只是诊断，没有修**：`tasks.py::pokemon_center_enter` 的 criteria 没有改紧，VLM 感知可靠性问题也还没有独立排查方案，都记在这里等下一步决定怎么改（criteria 往严格改到什么程度、VLM 那边要不要单独起一个"感知可靠性"排查任务，见新增的第 21 条）。|
| ✅ episode 内新增"人类实时插话"通道，`decide_action.md` 里最高优先级注入 | 用户新需求："human in view 中我们可以输入我们的观测和指令，这个是最高优先级"，追问澄清后确认要插的位置是 **episode 内实时**（`decide_action`，而不是 run 级 episode 之间的 `review()`）——人类边看 watch 画面边打字，下一次决策就要读到。**复用现成的 `RunDataCenter` 模式**（前后端交互统一层，见第 1 条），新增第三个槽——human_note 槽：非阻塞、单槽、覆盖式、**一次性**（`take_human_note()` 取走即清空，只对下一次 `think_action` 生效，没人写过恒为空串），跟 goals 槽同一套约定，不同于 review 槽（那个是阻塞轮询）。**改动**：`RunDataCenter` 新增 `submit_human_note`/`take_human_note`；`EpisodeHarness.__init__` 新增 `data_center` 参数（`None` 时行为完全不变，等价于没接前端）；`think_action()` 每步开头取一次，取到非空才记一条 `LIFECYCLE`/`kind=human_note` 的轻量 trace 事件（`trace_utils.human_note_injected`，没插话不留痕迹）；`BrainDecisionReq` 新增 `human_note` 字段；`decide_action.py::build_prompt()` 新增 `_render_human_note()`，空串时整段不渲染（不是每步都塞一句"没人插话"的噪音），非空时渲染成独立小节 `## 人类刚刚插的话（最高优先级）`，插在 `decide_action.md` 开头引言之后、`## 目标` 之前——**放在最前面**，模型先读到这条"压过下面所有规则"的声明，再读目标/已知事实/rationale 硬规则，冲突时按提示改听人类的并在 `rationale` 里如实写"人类指示：……，因此改为……"。`RunHarness` 补一个薄委托 `submit_human_note()`；`build.py` 改成先落实一个共享 `RunDataCenter` 实例（不传就自己建一个），同时注入 `EpisodeHarness`（human_note 槽）和 `RunHarness`（goals/review 两槽），不再各自新建互不相干的两份；`api.py` 新增 `POST /runs/{id}/note`（`HumanNoteReq`，run 已结束 409，同 `edit_goals` 的约定）。**验证**：`ast.parse` 8 个改动文件全干净；`string.Template` 真实渲染过 `decide_action.md`（空 `human_note_block` 和非空两种情形），确认空时无残留占位符、非空时新小节正确插在目标前面；unused-import 扫描两处误报（`HarnessPort`/`TraceEvent`）经核对是改动前就有的旧债，非本次引入。**还没做**：前端 UI（输入框 + 调用 `POST /runs/{id}/note`）留给后续，这次只做了后端通道；一次性 vs 持续粘着的语义选了"一次性"（更贴近"实时纠偏"），如果用户实际用起来发现想要的是"持续到我明确取消/goal 变化"那种粘性语义，需要另开一次改。|
| ✅ `plan` 自动压栈临时关闭开关 + `REVIEW_TIMEOUT` 默认拉长到 60s | 用户"暂时有个想法"：把 `plan()` 自动压栈关掉，改用人工审查（`review()` 的 `PUSH`）手动加目标，同时把 review 超时从 5s 延到 60s 给人足够时间看完结果再决定。**没有删代码，做成开关**：`RunHarness.__init__` 新增 `auto_push_goals: bool = True`，`plan()` 里 `resp.done` 照常生效（run 该不该整体结束不受影响），只是 `auto_push_goals=False` 时强制丢弃 `resp.push_goals`（改成 `[]`）——模型的 prompt/schema 完全没动，仍然照常被问、照常解析，只是这里不采纳，最省事也最容易改回去。`build.py::build_real()` 透传同名参数给 `RunHarness`；`api.py` 新增环境变量 `POKEMON_AUTO_PUSH_GOALS`（**默认 `false`**——这是本次唯一一处新开关默认改变行为而不是默认兼容旧行为，因为用户明确要求"现在就关掉"，想改回自动压栈设 `POKEMON_AUTO_PUSH_GOALS=true` 即可）。`REVIEW_TIMEOUT`（`POKEMON_REVIEW_TIMEOUT`）默认从 `"5"` 改成 `"60"`。**没受影响的两条人工加目标通道**：`review()` 的 `PUSH` 决策、`POST /runs/{id}/goals`（`apply_goals_edit`）——两者的压栈逻辑（LIFO append）各自独立于 `plan()`，这个开关只管 `plan()` 那一条自动通道。**验证**：`ast.parse` 三个改动文件干净；手动过一遍 `plan()` 的三条出口（done / push / 都不做）确认 `pushes=[]` 时 `if pushes:` 分支正确跳过、`if resp.done or (not state.goals and not pushes)` 逻辑不受影响。**没做**：没有验证过真实 run（这台 device VM 装不上 pydantic，跟以前几轮同样的限制）；用户同一轮追问的"human_note 置信度能不能保证最高"单独在对话里如实答复（结论：不能，见对话记录），没有对应的代码改动。| 用户紧接着追问一句"同时也不会自己结束，现在 plan 的工作全部交给 review"——追加了第二个开关 `auto_decide_done`（同样默认 `false`，同样走环境变量 `POKEMON_AUTO_DECIDE_DONE`）：关掉后 `plan()` 完全不能自主让 run 结束——`resp.done` 被忽略，**目标栈自然清空**这个原来会让 `plan()` 直接判 `done`（栈空还不算模型自己拍板，但原代码把这个"没活干了"跟"模型主动喊停"揉在同一个条件里判 `done`）的情形，现在也不再直接判——改成落到"什么都不做"分支，让 `_compile()` 的图路由处理：`plan` 的条件边新增一条 `else "review" if not s.goals`（在 `dispatch`/`END` 之前判），栈空时改路由去 `review()`，只有人类的 `STOP` 决策才能真的结束 run（`CONTINUE`/超时兜底成 `CONTINUE` 时，栈还空的话会再绕回来问一次，不会不问人就自己停，但也因此**不会自己终止**——长时间没人应答、栈又空，会一直在 `plan⇄review` 之间用 60s 周期空转）。两个开关（`auto_push_goals`/`auto_decide_done`）各自独立，互不依赖。**验证**：`ast.parse` 三个改动文件干净；手动过一遍新增的路由分支——`plan_failed`/`done`/`not s.goals`/其余 四种情形对应的目标节点都对得上，`dispatch` 的"非空栈"前置断言不会再被空栈撞到。**没做**：真实 run 验证（同上，环境限制）；也没有另外提醒用户"长时间无人应答时 run 会空转不停"这件事在代码里落成告警/超时上限，只在这条记录和对话里提了。|
| ✅ 观测台前端：目标栈改造成纯前端草稿，`push` 时整栈原子同步到后端（`sync` 边） | 用户提出新设计（"goals 自己本身变成纯前端操作。plan 的时候从后端获取数据更新前端，push 的时候才会把栈推到后端"），澄清后确认三条：整栈同步（不是增量）；前端正在编辑时后端目标栈变了就以后端为准覆盖本地（用户当前只在人工 review 阶段编辑，这个冲突窗口基本不会撞上）；可以完整编辑所有栈**包括栈顶**，只有 review/plan 两个时间点前端栈会变。**动机**：原来的 `GoalsEditReq`（push/remove/replace）是单槽覆盖式——前端如果为了同步一次多处编辑连发好几个增量请求，早发的会在下一次 `plan()` 消费前被后发的悄悄覆盖丢掉，不适合"整栈一次性同步"这种用法。**后端**：`GoalsEdit`/`GoalsEditReq` 新增 `kind="sync"`，携带完整新目标栈 `goals`（栈顶=最后一项），`apply_goals_edit` 新增分支——不锁栈顶（用户已确认接受这个风险），原子整体替换 `state.goals`，`attempts` 按 `task_id` 找回旧计数、新目标记 0；`api.py::edit_goals` 透传 `goals` 字段（`goal_to_task`前缀 `sync-`，已有 `task_id` 的项保留原样）。**前端**：`App.tsx` 里目标栈从"`useRunGoals` 直接渲染的只读列表 + 逐条 `editGoals` 调用"改成本地 `draft` 状态（新增/编辑/删除全部只改 `draft`，不打后端）；用 `wasReviewActiveRef` 识别"review 刚从不 pending 变成 pending"这个瞬间，只在这个时刻用 `backendGoals` 整体覆盖 `draft`（避免例行 2s 轮询把正在编辑的东西冲掉）；`GoalRow` 去掉了"栈顶只读"分支，栈顶现在跟其他行一样可编辑/删除，只保留一个"执行中"标记；原来的"追加目标"表单改成只 append 进本地 `draft`；新增"同步目标栈到后端"按钮调用新的 `syncGoals()`（一次 POST，`kind: "sync"`）。`types.ts`/`api.ts` 同步新增 `DraftGoal`/`syncGoals`。**验证**：后端三个改动文件 `ast.parse` 干净；前端 `tsc --noEmit` 无错、`vite build`（因这台 device VM 对挂载目录默认没有删除权限，`web/dist/` 有历史残留文件导致 `EPERM`，改用 `--outDir /tmp/dist-check2` 验证）构建成功。**没做**：真实 run 端到端验证（这台 device VM 装不上 pydantic/agent_permission，同上几轮的环境限制）；`review()` 自身的 `PUSH` 决策（另一条独立通道，直接原子 append 且会解决当前 review 请求）跟这条新的 `sync` 通道是否要进一步统一/简化，用户在上一轮"追加目标表单还有什么用"的追问里提出过、还没最终拍板，留待下次。|
| ✅ `GoalsEdit` 删掉 `push`/`remove`/`replace`，只留 `sync` | 用户确认"我们已经不需要 remove 和 push 和 replace"——上一条把目标栈改造成纯前端草稿之后，这三个按 `task_id` 定位的增量 kind 在前端已经没有调用点了（`editGoals()` 整个函数都没人调），只有 `sync` 在用。**改动**：`GoalsEdit`（`goals_edit.py`）简化成只有 `kind: Literal["sync"] = "sync"` + `goals` 一个字段；`apply_goals_edit`（`run_utils.py`）去掉按 `kind` 分支判断，只剩整栈替换那一段逻辑；`api.py` 的 `GoalsEditReq` 同步简化成只有 `goals` 字段，`edit_goals()` 端点相应精简。前端 `types.ts` 的 `GoalsEditReq`/`GoalsEditKind` 同步简化，`DraftGoal` 保留；`api.ts` 删掉整个 `editGoals()` 函数，只留 `syncGoals()`。**没受影响**：review 决策里那个同名但完全独立的 `push`（`HumanDecision` 的 `continue`/`stop`/`retry`/`push`，走 `POST /runs/{id}/review`，`ReviewPanel` 还在用）——这是不同的机制，不在这次清理范围内。**验证**：后端三个改动文件 `ast.parse` 干净；前端 `tsc --noEmit` 无错、`vite build`（`--outDir /tmp` 规避这台 device VM 对 `web/dist/` 历史残留文件的 `EPERM` 删除限制）构建成功；全项目 `grep` 确认 `push`/`remove`/`replace` 三个 kind 字符串在 `GoalsEdit` 相关文件里已无残留（唯一命中的 `"push"` 是上面说的 `HumanDecision`，不相关）。|
| ✅ 删掉 review 的 `PUSH` 决策，加目标只保留"goal 的 push + goals 的 read"两个通道 | 用户进一步简化："只保留两个，一个是 goal 的 push，一个是 goals 的 read，去掉 review 的 push"。**"goal 的 push"= 上一条的 `sync` 改名**：`GoalsEdit.kind` 从 `"sync"` 改成 `"push"`（行为完全不变，仍是整栈原子替换、不锁栈顶），前端 `syncGoals()` 同步改名 `pushGoals()`。**"goals 的 read"= 沿用现成 `GET /runs/{id}`**（已经带 `goals` 字段，`useRunGoals` 一直在用），没有新开端点。**删 review 的 `PUSH`**：`HumanDecision` 枚举去掉 `PUSH`，`HumanReviewRespFromFrontend` 去掉 `push_goals` 字段；`RunHarness.review()` 去掉 `PUSH` 分支；`api.py` 的 `ReviewDecisionReq` 的 `decision` 收窄成 `continue`/`stop`/`retry`，去掉 `push_goals` 字段，`submit_review()` 端点相应精简。前端 `types.ts` 的 `HumanDecision`/`ReviewSubmitReq` 同步收窄；`ReviewPanel` 去掉"插入新目标"按钮 + 展开表单（`pushOpen` 状态、`handlePushSubmit`），现在只剩继续/停止/重试上一层三个按钮——加/改/删目标统一走目标栈那个框（本地草稿 + 推送到后端），不再跟"这一轮 episode 怎么办"混在一个决策里。顺带清理了 `run_harness.py`/`build.py`/`human_reviewer.py` 里几处提到"review 的 PUSH 决策"的过时注释/文档。**验证**：8 个改动的后端文件 `ast.parse` 全干净；全项目 `grep HumanDecision\.`/`push_goals`/`PUSH` 确认无残留引用（`RunPlanResp.push_goals`/`auto_push_goals` 是 plan 自己的字段，跟这次删的 review PUSH 是两回事，不受影响）；前端 `tsc --noEmit` 无错、`vite build` 构建成功。|
| ✅ 目标栈"读"单独拿出一个后端接口 + 前端刷新时机改成监听 plan verdict trace 事件（不再靠 review 状态猜） | 用户对"现在 goals 是怎么同步的"追问后进一步要求："这个 goals 还是单独拿出来吧"——澄清后确认两点：① 不是要解除 review 门控（编辑仍然只在 review 激活时开放），而是要**给 goals 的读单独开一个后端接口**，不再complain 混在 `GET /runs/{id}` 那个大而全的状态接口里；② "plan 编辑完 goals 的时候"里的 "plan" 指后端 `plan()` 节点（模型自动规划），不是前端用户编辑——也就是要求把"本地草稿刷新的时机"从"review 变 pending"这个粗糙信号，改成"plan() 刚跑完一轮"这个精确信号（两者之间隔着一整个 episode 的 dispatch/reflect 循环，用 review 当信号会晚一整个 episode 才刷新）。**后端**：`api.py` 新增独立端点 `GET /runs/{id}/goals`（跟 `POST /runs/{id}/goals` 的 push 配对），把原来内嵌在 `get_run()` 里的目标栈视图逻辑抽成共享 helper `goals_view()`，两个端点共用，避免两处分叉。**前端**：`api.ts` 新增 `getGoals()`；`App.tsx` 去掉 `useRunGoals` 轮询 hook 和"review 从不激活变激活"这个刷新触发条件，改成用 `useMemo` 从 `useRunStream` 已经在订阅的 SSE trace 事件里找最新一条 `Source.PLAN`/`kind="verdict"` 的事件（`trace_utils.plan_verdict()`，已有的既存事件，这次没新增），用一个 ref 记上次处理过的 `event_id`，出现新的就调 `getGoals()` 整份覆盖本地 `draft`；另加一个"进入/换 run 时先拉一次打底"的初始化 effect，覆盖"页面刚打开、还没出现过 plan 事件"这个冷启动窗口。`useRunGoals.ts` 文件本身没删（这台 device VM 默认没有删除权限），但已经没有任何地方 import 它，`vite build` 的模块数从 37 降到 36 确认它已经被摇树排除。**验证**：`ast.parse` 干净；前端 `tsc --noEmit` 无错、`vite build` 构建成功。**没做**：真实 run 端到端验证（这台 device VM 装不上 pydantic/agent_permission，同上几轮的环境限制），没有真实观察过"push 之后下一次 plan verdict 事件到达时草稿确实被正确刷新"这条链路。|
| ✅ `facts` 里删掉 `stalled`/`cursor_said`/`perception_warning` 三个纯诊断字段 | 用户逐条审过 `observation.facts` 里的四个候选删除项后拍板：**`stalled`/`cursor_said`/`perception_warning` 直接删，`neighbors` 保留**（`neighbors` 是唯一以主角为原点、能跨步骤直接比较可通行性的地形字段，`walk_map` 原点跟人走没法这么用，删了会让 `StepMemory` 失去这类判断依据）。**`stalled`**：`episode_harness.py::judge()` 不再往 `facts` 写这一项——它原来只在 `obs.done=True` 时才出现，而 `decide_action.py` 送 prompt 前先 `assert not obs.done`，从没被模型读到过，纯粹是摆设。**顺带发现一个真依赖**：`episode_utils.py::derive_episode_reason()` 原来靠 `obs.facts.get("stalled")` 判 `EPISODE_END` 的 `reason` 是不是 `"stalled"`，删字段会顺带打断这条——改成 `derive_episode_reason(obs, max_steps, *, stalled: bool)`，调用方直接传 `state.stall_count >= STALL_LIMIT`（`trace_utils.judge_verdict()` 已经在记这个同一个布尔值，行为完全不变，只是不再绕道 `facts`）。**`cursor_said`/`perception_warning`**：两者的文档/注释都写着"不是给大脑读的，只进 trace/观测台"，但 `decide_action.py::build_prompt()` 对 `facts` 是全量转发、没有像 judge 那样的 `JUDGE_BLIND`，两者一旦出现分歧/警告就会真的漏进决策 prompt——属于设计意图和实现不一致，删掉顺带堵上这个漏洞。连带清理：`ScreenState.cursor_said` 字段（原本只有 `facts["cursor_said"]` 一个消费者，没人读了就是死代码，一并删除，`_derive_cursor_from_lines()` 的赋值也删掉）、`SNAPSHOT_BLIND` 去掉 `cursor_said`（已经从源头不产生，不用再单独挡）、`brain.py`/`trace/utils.py` 几处过时注释同步改。**验证**：改动的 7 个文件 `ast.parse` 全干净；全项目 `grep` 确认三个字段名在 `.py` 里已无残留引用（`step_memory.py` 里一处提到 `cursor_said` 的是新加的说明性注释，非残留代码）。这台 device VM 仍装不上 pydantic/agent_permission，没有真实跑一局验证。|
| ⏪ 讨论过给 `ObservationFromWorld` 加一份截图字段，最终否决 | 用户问"截图现在放到哪个数据结构里了"，追问到"observation 里应不应该也带一份截图 base64"。查代码后指出两个冲突点：**a)** `ObservationFromWorld` 的 class docstring 明确写着"原始画面…不进这里，那些属于 harness，大脑看不到也不该看到"——现在图片唯一的落点是 `TraceEvent.frame_png`，只挂在感知那次的 `MODEL_CALL` 事件上，`decide_action`/`judge`全程只读文字 `facts`；真要让大脑"看图"决策，两个 prompt 模板得从 `.complete()` 换成 `.describe()` 那套多模态路径，不是加个字段这么简单。**b)** 即使只是想让 `obs` 带着图走（不进 prompt），也绕不开 `StepMemory` 每一步都把 `obs` 存两份（`before`/`after`）落进 `episode_store`——截图字段如果不进 `SNAPSHOT_BLIND`，等于每步在情景记忆库里多存两份完整 PNG，而且跟 trace 里 `MODEL_CALL.frame_png` 那份完全重复。用户确认这正是顾虑所在（"存 observation 的 trace 就不用落盘了"），拍板**不加**——现状（截图只挂 `TraceEvent.frame_png`，`obs` 不带图）维持不变，这条只是把讨论过程和否决理由记下来，避免以后又有人重新提这个方案时要从头查一遍。|
| ✅ `done`/`success` 从 `ObservationFromWorld` 搬到 `EpisodeRunState` | 用户追问"为什么 done 和 success 要放进 observation？直接 look 的时候 judge 完了就结束了"，查代码确认这个批评站得住：`ObservationFromWorld.done` 原本身兼两职——**世界层自己的信号**（唯一来源是 `pyboy_world.py` 模拟器窗口被关闭）和 **harness 的终止裁决**（`judge()` 综合三类机械条件+模型判定后的结论）共用同一个字段名，`judge()` 一跑就用 `obs.model_copy()` 把前者覆写成后者，事后没法分清"这次是世界说的还是我们判的"；`success` 更彻底——世界压根没有"任务完不完成"这个概念，这个字段唯一的写入者一直是 `judge()`自己。**改法**：`ObservationFromWorld` 删掉 `success` 字段，`done` 缩窄成"世界层只读信号"（docstring 明确写"这里只读不写"）；`EpisodeRunState`照 `stall_key`/`stall_count` 的先例新增顶层 `done: bool`/`success: bool`两个字段，专门给 harness 的终止裁决用。`judge()` 不再对 `obs` 做任何`model_copy`（观测全程不被这一格改动），本地算出 `done`/`success` 两个局部变量，返回 `{"done": done, "success": success}` 作为独立状态增量。**连带改的调用点**：`_compile()` 的路由 lambda（`state.observation.done` → `state.done`）；`run()` 收尾的 outcome 组装（`obs.success` → `final_state.success`）；`retrieve_verify_step_memory`/`verify_steps`/`summarize` 三处前置断言（同样的替换）；`summarize()` 里喂给蒸馏器的 outcome 字典；`episode_utils.py::derive_episode_reason()` 签名从 `(obs, max_steps, *, stalled)` 简化成 `(success, step, max_steps, *, stalled)`，不再假装自己需要一份完整观测；`brain.py::Brain._blind()` 去掉 `success=obs.success`（字段已经不存在）；`pyboy_world.py` 构造 `obs` 时去掉占位的 `success=False`。**没动的地方**：`decide_action.py` 的 `assert not obs.done` 保留原样——它检查的是世界层的原始信号（现在语义更干净了：单纯"世界还在不在"，不是"这一局该不该结束"），graph 的路由结构本来就保证走到这里时 `state.done` 必为 False，这条断言继续有效，不用改成读 `state`。**验证**：这次这台 device VM 的 `python3` 突然能 `import pydantic` 了（环境变化，原因不明），`ObservationFromWorld`/`EpisodeRunState` 两个 schema 真实构造过一遍确认 `success` 字段已经从 `model_dump()` 里消失、`done`/`success` 已经在 `EpisodeRunState.model_fields` 里；`derive_episode_reason()` 新签名靠 `ast.parse` 验证（`episode_utils.py` 仍然卡在 `agent_permission` 缺失，没法真 import）；全项目 `grep obs\.success\b`/`observation\.success` 确认零残留，`grep obs\.done\b` 逐条核对过，剩下的引用全部是世界层原始信号的合法用法（`_begin()`/`look_after_action()`/`decide_action.py` 的断言、`judge()` 内部读取），没有遗漏该改成 `state.done` 的地方。`tests/`（`conftest.py`/`test_episode_stall.py`/`test_memory_tool.py`）里搜到的几处 `success=` 都是 `EpisodeMemory(...)` 的字段，跟这次改的 `ObservationFromWorld`/`EpisodeRunState` 无关，不受影响。|
| ✅ `StepMemory` 挂截图引用，`judge`/`verify_steps` 改成多模态调用（带图问，凑不齐图退化成纯文本） | 用户在"截图放到哪个数据结构里"（上一条否决方案）之后回来重提，明确要求"存引用不存字节"+"judge 也按 episode 一样去重"+"修掉截图编号 bug"+"prompt 里加图片说明"。**a) 先修了一个真实 bug**：`screenshot/` 文件名 `{run_id}_{episode_id}_{step}.png` 里的 `step` 号，`_begin()` 和第 0 轮 `look_after_action()` 都用 `before.step=0`，两次写同一个文件名——不是覆盖（`_save_screenshot` 撞名会追加 `(1)` 后缀，不覆盖），但会让"按 step 号算文件名"这个公式在这两帧上失真（算出来是 `_0.png`，实际这一步的画面在 `_0(1).png`）。改法：`LocalTrace.append()`/`episode_utils.perceive_with_retry()` 新增 `screenshot_step` 参数，把"截图该编几号"和"这条 `MODEL_CALL` 该记在哪个 step 的账上"解耦——`look_after_action()` 感知到的其实是下一步的开局画面，传 `screenshot_step=before.step+1`，`_begin()` 不变（缺省等于 `step=0`）。改完之后 `_{n}.png` 对任意 `n`（含 0）都唯一对应"第 n 步的开局画面"，不再有正常运行下的撞名。**b) `StepMemory` 新增 `before_frame`/`after_frame: str | None`**——只存 `screenshot_filename()` 算出来的文件名（不是字节），由 `store_step_episode_memory()` 在盖 `episode_id` 的同一次 `model_copy` 里顺带盖上，跟 `Brain.reflect()` 本身不知道 run_id/存储约定的原则一致。新增 `frame_sequence(entries)`——跟 `render_sequence()` 同一件事的图片版，按文件名字符串去重相邻重复（`entries[i].after_frame == entries[i+1].before_frame` 本来就是同一个物理文件）。**c) `VisionCompletionReq.image_png: bytes` 泛化成 `images: list[bytes]`**（`min_length=1`），`_MultimodalMixin.describe()` 相应改成拼多张 `image_url` block（图在前、文字 prompt 固定殿后），`ImageNotDelivered` 的判定阈值按张数等比放大（`self._floor * len(images)`）——`QwenProvider` 本来就"语言+视觉两用"，`.complete()`/`.describe()` 都有，不用新增供应商类。**d) `judge_llm`/`verify_llm` 类型从 `LLMProvider` 改成新增的 `JudgeProvider`**（`LLMProvider`+`VisionProvider` 的合并 Protocol，`QwenProvider` 不改代码就满足）。`Brain.judge()`/`verify_steps()` 新增私有 `_ask()`：`images` 非空走 `describe()` 多模态问一次，空的话退化成 `complete()` 纯文本——一张便利副本缺失（`StepMemory` 没留下文件名，或文件确实不在磁盘上）不该让"永远不抛异常"的判定链路直接失败。`ModelCall.payload` 新增 `n_images` 字段（带没带图直接影响判定看到了什么，回头分不清"没带图判错"还是"带了图还判错"）。**e) Harness 侧组装**：`judge()` 用 `frame_sequence(history)` 去重 + 当前帧自己的文件名（跟 history 最后一条去重）拼成 `images`；`verify_steps()` 同理用 `frame_sequence(entries)`（全量，没有"当前帧"这一说，校验的是已结束的一局）。两处都用 `read_screenshot()` 读，读不到的文件（`None`）直接跳过，不让一张缺失的便利副本拖垮整条链路。**f) `judge_success.py::build_prompt()` 改用 `render_sequence`**（原来是手写 `"\n\n".join(m.render(...))`，没有跟 `step_verify` 一样去重——`JUDGE_HISTORY` 虽然只是小窗口，但只要窗口里有连续两步，重复就存在，这次一并对齐两条链路）。**g) 两份 prompt（`judge_success.md`/`step_verify.md`）新增"除了文字，你还会看到几张截图"一节**：讲清楚顺序（history 在前、当前帧殿后，去重规则跟文字一致）、用途（核对文字有没有抽错，不是用来重新推算坐标——位置证据仍然只认 `where`，这条规矩跟"你手里没有地图"是同一条，不受这次改动影响）、冲突时的优先级（截图上实际看到的文字为准，文字是抽取结果可能有误）。**验证**：这台 device VM 这次全程能 `import pydantic`（延续上一条的环境变化），做了比之前几轮更扎实的真实验证——`frame_sequence`/`render_sequence` 对含 gap 的真实 `StepMemory` 序列跑过一遍确认去重正确；`VisionCompletionReq` 空列表正确触发 `ValidationError`；`judge_success.build_prompt()`/`step_verify.build_prompt()` 真实渲染过（含新截图说明段落），无 `KeyError`；`QwenProvider.describe()` 打桩 `_post`/`_unpack` 验证过多图 content block 顺序（N 张图+1 段文字）和按张数等比放大的 `ImageNotDelivered` 阈值（正常/触发两条路径都走过）；`Brain.judge()`/`Brain.verify_steps()` 用假 `agent_permission` 桩模块 + 假 provider，真实跑过"有图→`describe()`"和"无图→`complete()`兜底"两条分支，`ModelCall.payload["n_images"]` 数值也对上了。**没做/已知缺口**：`episode_harness.py` 本身仍卡在 `agent_permission`/`langgraph` 缺失，没法端到端真实 import 一次（`judge()`/`verify_steps()` 节点里新加的 `frame_sequence`+`read_screenshot()` 组装代码只过了 `ast.parse`，逻辑靠人工核对，没有真实跑一局验证）；没有真实调过一次 DashScope API 确认多图请求真的按预期送达（这台设备网络出不去，同以前几轮）；`verify_steps` 的图片数量跟局长线性增长这件事本身（用户之前已经提过"history 存的 stepmemory 太多了"）这次没有额外限流，是个已知的、跟这次改动同源的风险点，留给以后决定要不要在 `frame_sequence` 之外再加一层"最多带 N 张"的截断。|
| ✅ 上一条改主意：`StepMemory` 直接存 base64（不再是文件名引用），配套四处跟着改 | 用户看完上一条后追问"这个 token 数是你刚刚测的吗"（答案：不是，是按 `IMAGE_TOKEN_FLOOR=100` 这个项目已有的实测阈值 + 查到的 Qwen3-VL 缩放规则推出来的，没有真实调过 API），紧接着改主意："StepMemory 你完全可以直接存字节，但是按 base64，即 vlm 模型要求的 rest api 格式存"——推翻了上一条"只存引用不存像素"的设计。**改动**：`StepMemory.before_frame`/`after_frame` 语义从"`screenshot/` 下的文件名"改成"base64 编码后的 PNG 字符串"（直接是 `image_url` 要拼的那段内容），`store_step_episode_memory()` 从"算文件名"改成"读盘一次、编码一次"（新增私有方法 `EpisodeHarness._frame_b64()`）。**顺带把整条链路都改成了 base64 字符串，不再有 bytes↔base64 的来回转换**：`VisionCompletionReq.images` 从 `list[bytes]` 改成 `list[str]`（四次改版，紧接着上一条的三次改版），`_MultimodalMixin.describe()` 不再自己 `base64.b64encode`，直接拼 `req.images[i]` 进 URL；`PyBoyWorld` 感知那条路径（唯一还产出原始字节的地方）在构造请求前自己编码一次；`_dump()`（调试落盘工具）改成先解码再写文件，不然存下来的就是纯文本不是图。**连带简化**：`verify_steps()` 组装 `images` 不再需要 `read_screenshot()`——`frame_sequence(entries)` 直接返回的就是可以塞进 `VisionCompletionReq` 的字符串；`judge()` 里 history 部分同理简化，只有"当前这一帧"（还没被反思成 `StepMemory`）仍然需要 `_frame_b64()` 现读现编。`frame_sequence()` 的去重逻辑完全不变（原来比较文件名字符串，现在比较 base64 字符串，两种情况下"同一帧→字符串相等"这个前提都成立）。**这次拿掉的东西**：`StepMemory` 不再"只存引用不重复存像素"，`before`/`after` 图片字节现在跟文字字段一样有相邻重叠——用户明确认识到这个代价并选择接受，换来的是 `judge`/`verify_steps` 组装请求时完全不用碰磁盘、不用担心截图文件是否存在/被撞名改后缀。**验证**：延续上一条的实测方式重新跑了一遍——`frame_sequence` 对含 `None`（缺图）条目的序列去重正确；`VisionCompletionReq` 空列表校验、多字符串顺序正确；`QwenProvider.describe()` 打桩验证 base64 字符串直接进 URL、没有二次编码；`Brain.judge()` 用假 provider 验证 `req.images` 原样透传到 `describe()` 调用；额外新增了 `_frame_b64()`/`read_screenshot()`/`screenshot_filename()` 三者拼起来的真实读盘+编码回环测试（写一个假 PNG 到 `screenshot/`，读出来编码、再删除确认缺图返回 `None`）。**已知缺口不变**：`episode_harness.py` 仍然装不上 `agent_permission`，`judge()`/`verify_steps()`/`store_step_episode_memory()` 里这次改的组装代码只过了语法检查，没有端到端真实跑一局。|
| ✅ judge/verify 换供应商到火山方舟豆包旗舰，感知升级到 qwen3.8-max | 用户拍板"之前可能是模型不行，现在我们换最强的豆包模型"。**先纠了一个我自己的错**：中途把"observation 用 qwen3max"理解成 `qwen3-vl-max`，查了 DashScope 官方文档才发现**没有这个型号**——VL 专用系列（`qwen3-vl-plus`/`qwen3-vl-flash`）plus 已经是最高档，没有更高的 max；`qwen3.8-max` 才是通用多模态旗舰（本来就是 `QwenProvider` 类自己的默认型号）。当场用 `AskUserQuestion` 核实，用户确认是 `qwen3.8-max`，没有沿着错的猜测往下改。**改动**：`build_real()` 的 `judge_llm`/`verify_llm` 构造从 `QwenProvider` 换成 `ArkProvider`（该类之前已经实现好、只是从没被真正用起来），`model` 默认值改成 `doubao-seed-2-1-pro-260628`（查证：这是 2026-06 发布的豆包 Seed 2.1 Pro 旗舰，火山方舟原生多模态，日期后缀是接入点强制要求，缺了会 404）；`verify_llm` 的 fallback 链从三级 `verify_model or judge_model or text_model` 收窄成两级 `verify_model or judge_model`——**这不是随手删的，是必须删**：`text_model` 是 Qwen 型号名，一旦 `judge_model`/`verify_model` 都留空，旧代码会把 Qwen 的型号字符串传给 `ArkProvider`，直接在火山方舟接入点上 404，不是"退化成纯文本"那种优雅失败。`vision_model` 默认值从 `qwen3-vl-plus` 升到 `qwen3.8-max`，两个独立的实验入口（`run_episode.py::build_session()` 硬编码的 `vision_model="qwen3-vl-plus"`/`judge_model="qwen-plus"`，后者整行删除、改用 `build_real()` 的新默认值；`run_experiment.py` 手写 manifest 里的 `vision`/`judge` 两行）同步跟着改，没有漏掉旁路入口。`judge_llm`/`verify_llm` 换成 `JudgeProvider` 类型后本来就要求 `.describe()`/`.complete()` 都有，`ArkProvider` 跟 `QwenProvider` 一样是 `_MultimodalMixin` 子类，两个方法都有，类型上不用再改。**已知需要用户自己做的事**：`ARK_API_KEY` 环境变量——`ArkProvider.API_KEY_ENVS = ("ARK_API_KEY",)`，跟 `DASHSCOPE_API_KEY` 是两个不同的密钥，没设的话 `ArkProvider.__init__` 会在装配阶段直接抛 `RuntimeError`（同 `QwenProvider` 没设 key 时的行为），这一步我没法替用户做，只能提醒。**验证**：`ArkProvider(model="doubao-seed-2-1-pro-260628", ...)` 真实构造过一遍（设 `ARK_API_KEY=fake`），`isinstance(p, JudgeProvider)` 为真，`.config()` 输出的 `base_url` 确认指向火山方舟接入点而不是 DashScope；三个改动的 `.py` 文件 `ast.parse` 全干净。**没做**：真实调用（这台设备没有真的 `ARK_API_KEY`，也没网络，没法验证豆包那边真的按预期收图/出结果）；`docs/spec/providers/SPEC.md` 里只写了 `DASHSCOPE_API_KEY` 的鉴权说明，没同步补 `ARK_API_KEY`，按"spec 等解冻信号再改"的既定约定没有动它，只在这条记录里写清楚。|
| ✅ `verify_steps` 与 `summarize` 合并成一次调用 + `decide_action.md` 的 rationale 补"依据→结论"硬规则 | 用户要求"直接融合verify和summary"，但先要求说清楚之前 memory 遇到过什么情况、StepMemory 中间步骤被当正确步骤的问题怎么办、rationale 有没有更好的模板——这条把三件事一起记。**历史问题回顾（用户要求先说清楚的部分）**：a) `verify_steps` 当初从 `summarize` 里独立出来，直接原因是战斗菜单里 `down×3` 被模型自己记成"逃跑"、实际是打开了道具袋这次事故（第 9 条）——step 记忆是模型自述、没有验证，直接喂蒸馏会把错误操作固化成经验、跨局传播；b) "把中间步骤当成已验证事实"这条更精确的说法是 trace#20 系列三次事故（`map_hint.md`/`decide_action.md` 两次改版那几条）——模型把"知识说这个方向最终能到宝可梦中心"（跨地图关系，长期为真）和"屏幕边缘的下一格就是门"（这一帧根本没加载出来）混成一件事，写进 `StepMemory.rationale` 之后不会再被核对（`step_memory.py` 文档原话："写入后不会再被核对"），执行后四邻全是 `.`，没有任何门的证据，但已经晚了；c) 这两类问题的共同根子是"自述先被信、后被查"——`verify_steps` 是"后被查"那一半，`decide_action.md` 的硬规则是"少让它先被错信"那一半，两者本来就不是同一层防线，合并调用改的是"后被查"怎么问，不动"少让它先被错信"。**合并方案（用户拍板"合并成一次调用、两段结构化输出"）**：新 `VerifyAndSummarizeReq`/`VerifyAndSummarizeResp`（`schemas/communication/verify_and_summarize.py`）取代原 `StepVerifyReq`/`StepVerifyResp`（`StepVerifyVerdict` 留用，两处复用：合并响应的 `verdicts` 字段、`trace_utils.verify_call()` 落 trace）；新模板 `verify_and_summarize.md` 把 `step_verify.md` 的判定规则和 `episode_summary.md` 的摘要要求拼进一份 prompt，**"先判可信、再只用可信的写摘要"这条安全性质原样保留在 prompt 里**（明确要求 `reliable: false` 的记录不能在 `summary`/`reusable_patterns`/`critical_decisions` 里被当成事实引用）；`Brain.verify_and_summarize()` 取代 `Brain.verify_steps()`，一次 `_ask()` 问完，解析成 `(verdicts, summary)` 两段，`summary` 段解析失败不影响 `verdicts` 段（互不连坐）；`EpisodeMemoryGenerator` 新增 `build_from_response()` 静态方法（`_create_episode_memory` 的字段搬运逻辑复用，不重写一份）；`MemoryTool` 新增 `store_precomputed_episode_summary()`，跳过 `generate_summary()` 那次会重新问模型的调用，只做落盘 + 更新检索向量缓存；`EpisodeHarness` 新节点 `verify_and_summarize` 取代原 `verify_steps`+`summarize` 两格串联（图仍是 19 个节点，`verify_steps` 一进一出、`verify_and_summarize` 一进一出，净数不变），没有 step 记忆的边缘分支仍走原 `summarize` 节点（全量喂、没有可信过滤这回事，谈不上合并收益，也没有理由动它）。**用户明确要的取舍，不是遗漏**：原来两次独立调用能各自失败——`verify_steps` 调用坏了，`summarize` 仍能单独把全量记忆蒸馏一遍；合并成一次之后，这次调用一旦失败/解析不出来，可信过滤和跨局摘要**都**拿不到，只退化成"这一局不写摘要、多一条错误事件"，不再有"至少还能拿到一份未经校验的摘要"这条后备路径。合并调用的账仍记 `Source.VERIFY`（校验器失效率报表沿用旧口径），代价是这条账单现在也混进了写摘要那部分的 token，不再是纯校验成本。**`decide_action.md` 的 rationale 改法**：用户明确"这次修改rationale的目的不是为了减字段，而是为了给出更有用的论据"——没有拆 `StepMemory.rationale` 的 schema（仍是 `list[str]`），改的是这个字段里每一条字符串必须满足的形状：新增第三条硬规则，要求每条 rationale 必须是「依据 → 结论」两半都在，只有结论没依据（"这样比较好"）或只有依据没结论（复述已知事实、不说支持了什么）都不合格；配了一条正例和一条直接取自 trace#20 事故的反例，反例里重申"任何跨地图/跨局知识只能指导怎么做，不能替代已知事实里这一帧真正看到的依据"。**验证**：这台 device VM 这次装上了 `pydantic`/`rank_bm25`/`langgraph`（之前几轮的环境限制这次解除了一部分，`agent_permission` 仍要靠 stub），做了比前几轮更扎实的真实验证——`Brain._parse_verify_and_summarize()` 三种场景（正常解析、外层 JSON 畸形整体兜底、`summary` 段畸形但 `verdicts` 段不受影响）、`EpisodeMemoryGenerator.build_from_response()`/`MemoryTool.store_precomputed_episode_summary()` 端到端落盘+重启重建索引、`prompts.verify_and_summarize.build_prompt()` 真实渲染、`decide_action.md` 补丁后仍能正常渲染（新示例没有引入 `$` 占位符冲突），以及**图真的编译成功**（`EpisodeHarness._compile()` 用假协作者跑通，确认 `verify_and_summarize` 在节点里、`verify_steps` 不在、`summarize` 仍在、总节点数 19 不变）。**已知遗留（沿用本项目一贯做法，等信号再改）**：`tests/test_episode_stall.py` 的 `FakeBrain` 仍引用旧 `StepVerifyResp`，这个文件本来就因为 `agent_permission` 装不上而跑不起来，非本次引入、不在本次范围内；`schemas/datastore/__init__.py`/`providers/openai_compatible.py`/`vision_completion.py`/`trace/store.py`/`schemas/datastore/step_memory.py`/`judge_success.py` 里若干处提到"`verify_steps`"的注释/文档字符串是泛指这条校验链路，字面没有跟着改名，留着不算错但不够精确，同样等下次touch这些文件时顺手改。 |
| ✅ 真机验证发现并修复三处回归：`LocalTrace` 两个方法被误缝进 `read_screenshot()`、`run_episode.py` 丢了入口守卫、`build_session()` 解包还停在旧的 3 元组 | 用户配好 `DASHSCOPE_API_KEY`/`ARK_API_KEY` 后要求"全部过一遍"——这台 device VM 这次用 `uv` 装了 Python 3.11 + 真实 `agent-permission`/`pyboy` 全套依赖，第一次能真的跑 `python -m pokemon_agent.experiment.run_episode` 而不是靠 stub。跑的过程中连续暴露三个此前从没被真实执行验证过的回归，全部在真机上修复：**a) `trace/store.py`——`screenshot_filename()`/`read_screenshot()` 这两个"0905 新增的模块级函数"当初被插进了 `LocalTrace` 类体中间（`_save_screenshot` 方法之后），Python 因为它们是顶格 `def`，会终止类体；紧跟着的 `events()`/`_episode_is_complete()` 虽然缩进仍是 4 格，实际已经变成嵌套在 `read_screenshot()` 函数体内的死代码，既不是 `LocalTrace` 的方法也从未被调用——第一次真实 `LocalTrace.append()` 调用（`RunHarness.run()` 开局写 `RUN_START`）就用 `self._episode_is_complete(...)` 撞上 `AttributeError`。这是本 session 更早"0905 二次改版：trace 落盘感知帧"那次改动引入的，之前所有验证都是 `ast.parse` + 手工 unused-import 扫描，扫不出"缩进对、但作用域不对"这类问题，只有真的实例化+调用才能测出来。修法：把两个模块级函数整体移到类定义之后，`events()`/`_episode_is_complete()` 恢复成 `LocalTrace` 的真方法（纯挪位置，`git diff` 确认零内容改动）。**b) `run_episode.py` 缺 `if __name__ == "__main__": main()` 入口守卫**——`git log -p` 能看到更早版本有过这段，不知道哪次改动弄丢的；模块自己的 docstring 明明白白写着 `python -m pokemon_agent.experiment.run_episode 12 "..."` 的用法，但 `python -m` 运行时 `main()` 从未被调用，import 成功、静默 exit 0，表现为"什么都没发生"而不是报错——比前两处更隐蔽，靠读代码根本发现不了，只有真的按文档说的方式跑一次才会注意到"怎么什么输出都没有"。**c) `build_session()`/`main()` 还在按旧的 `harness, trace, world = build_real(...)` 三元组解包**——`build_real()` 早些时候（更早一次会话，API 层接 `RunDataCenter`/`GameTools` 那次重构）已经改成返回四元组 `(harness, trace, world, tools)`，`api.py` 当时同步改了，但单发入口 `run_episode.py`（以及它间接调用的 `run_experiment.py`）没有跟着改——`ValueError: too many values to unpack`。三处修复都不属于这次"合并 verify_steps/summarize"改动引入的问题，是更早几次改动遗留、从未被真实执行路径测过的债；这次因为用户主动要求"全部过一遍"、环境也第一次具备条件，才被真机验证挖出来，顺手全部修掉。**最终受限于网络**：这台 device VM 和这次会话的云端容器，出站网络都经过组织级 allowlist 代理，`dashscope.aliyuncs.com`/`ark.cn-beijing.volces.com` 都被代理拒绝（`403 Forbidden`/`connect_rejected`，连 `google.com` 都一样被拒，是整体策略不是这两个域名特有），到这一步之前的全部代码路径（图编译、`RunHarness.run()`、`plan()` 节点真的构造出 prompt 并发起 HTTP 调用）都验证通过，卡在"发真实网络请求"这一步——这是环境的出站策略限制，不是代码问题，也不应该被绕过；真正的"模型真的回答对不对"这一层验证需要用户在有出站权限的机器上自己跑。 |
| ✅ 装配/成本一轮扫描：真跳过 `plan`、单独 `plan_model`、`cached_tokens` 记账 | 用户看完真机跑出来的第一份 trace 后追问两件事：`plan` 明明关了自动压栈/自动收尾为什么还有 token 消耗、judge/perception 的 input token 为什么这么大。查 trace 实锤：`plan` 那次调用确实花了 709 input token，但 `llm_outcome.pushed_count=0`——`auto_push_goals`/`auto_decide_done` 关闭时代码原来只是"问了但丢弃"（`resp.push_goals` 强制清空、`resp.done` 不采信），不是真跳过。**改法**：`RunHarness.plan()` 消费完观测台编辑指令后立即判断两个开关是否都关，都关就直接返回等价于"问完但没压栈/没判 done"的返回形状（图路由不变），不再实际调模型。同一轮用户还要求"给 plan 单独设置 provider"——`build_real()` 新增独立 `plan_model` 参数（默认同样是 `doubao-seed-2-1-pro-260628`），run 级规划器不再借用 `memory_model`，有自己的 `ArkProvider` 实例，回退链落 `judge_model`。**judge/perception token 大**的诊断：perception 是 399 行静态 `perceive_screen.md`（硬编码场景判定规则/地形图例，文档里写明这是"领域知识不该硬编码进常驻 prompt"这条规则唯一的例外）+ 一张截图，5300+ input token 是这份静态 prompt 体量本身决定的；judge 的 input token 随 `n_images` 线性涨（1→2 张图涨了约 1800 token），GB 原生分辨率只有 160×144，涨幅明显是供应商侧按固定 tile/patch 网格算 token、不因原图小而打折。**缓存命中率**：查证 DashScope（Qwen）和火山方舟（doubao-seed-2.x 起）都有"隐式缓存"，默认开、不可关，命中的 token 只按标准输入价的 20% 计费，字段名两家一致：`usage.prompt_tokens_details.cached_tokens`。但**火山方舟的隐式缓存明确不保证命中、不保证命中最长前缀**，而且我们现在的多模态请求是"图片在前、静态文字在后"（`_MultimodalMixin.describe()` 的既有顺序）——对我们这种"图片每次都不同、静态文字每次相同"的场景，这个顺序恰恰是不利于命中的（前缀被易变的图片占住，后面重复的静态文字够不上"前缀"），跟 Aliyun 文档"多模态内容放前面提高命中率"针对的是"图片本身会重复"的场景不是一回事——**这是一个待验证的优化方向，这次没有改内容顺序，只做了记账**：`_unpack()`/`TextCompletionResp`/`VisionCompletionResp` 新增 `cached_tokens` 字段，一路穿透 `Brain._ask()`/`choose_once()`/`judge()`/`verify_and_summarize()`/`run_utils.ask_planner_with_retry()`/`episode_store.py::generate_summary()`/`pyboy_world.py::perceive_once()` 六个 `ModelCall.payload` 构造点，全部补上 `"cached_tokens"` 键，取不到就是 `"0"`（老响应没这字段，不是异常）。前端 `ModelCallPanel` 本来就整包 dump payload 的 JSON，不用改代码就能看到这个新字段；要看聚合命中率，可以离线按 `source` 分组 `sum(cached_tokens)/sum(input_tokens)`（trace JSONL 已经落盘，`episodes/*.jsonl` 每条 `model_call` 事件的 payload 里都有）。**验证**：`source /tmp/pa_venv/bin/activate` 后跑通了 `_unpack()` 的手工回归（带/不带 `prompt_tokens_details` 两种响应体都测了取值正确）、`tests/` 全量重跑（71/73，跟改动前完全一样，两个失败仍是已知跟本次无关的 `HumanDecision.PUSH` 旧债）。**已知遗留，留给下一步**：图片/文字顺序要不要为了命中率反过来（静态文字放前面、图片放后面）没有动，这会改变 vision 模型实际读到的 token 顺序，属于会影响识别效果的改动，需要先跟用户确认再动；聚合命中率目前只能离线算，没有做成 `MetricsPanel` 里的实时数字，需要的话再加。 |
