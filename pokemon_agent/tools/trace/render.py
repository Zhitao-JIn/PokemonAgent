"""把 req 里的领域对象渲染成 trace 事件的**封套 + 正文**——**纯函数，不碰 trace**。

每个渲染函数对应一种 `TraceKind`，收 `FromHarnessToTraceToolAppendReq`，
吐出 `(EventType, kind, content)` 三元组：

```
type     事件粗类（EventType 的常量）
kind     账名——**就是 req.kind**（0914 去翻译表之后没有第二种写法）
content  这笔账的正文（可 JSON 化的对象；`store` 负责序列化成字符串落盘）
```

`meta`（`run_id` / `source` / `episode_id` / `step`）**不由本文件拼**：前两个归
落盘层与信封，后两个直接来自 `req` 的公共字段，`TraceTool.append()` 统一组装。

会连带产生第二条事件的几个（`model_call` / `judge_call` / `verify_call`——
某次尝试失败时补一条 `call_failed`）吐出三元组的 list，由 `TraceTool.append()`
展开逐条落盘。

**`content` 的字段名是跨模块契约**：观测台前端按字段名渲染
（`cached_tokens` / `verdicts` / `success` / `input`……），harness 改字段名/删
字段会让面板**静默**缺失——本文件的字段变更是 tool 与前端的跨模块变更，
改字段必须同步前端的读取逻辑。

**字符串值一律保持字符串**（`"1"` / `"true"`）——`content` 是 JSON 对象，
但里面的标量值沿用"写进账时 `str()`"这条规矩，**布尔一律小写**
（`str(x).lower()`，不要裸 `str(x)`）。生产者不止本文件：
`brain/brain.py`（十二处）与 `world/pyboy_world.py` 的账单 `ok` 也是**直接写进
同一份 content** 的，同样受这一条约束。核对侧由
`experiment/real_check/node_io.py::BOOLEAN_FIELDS` 一份扁平名单统一执行。

**例外是"本身就是结构化数据"的那几处**（`facts` / `sequence` / `verdicts` /
`refs` / `names` / `dropped` / `goals` / `success_criteria` / `pushed_goals` /
三本写账的正文）：它们**直接放对象/数组、不再自己 `json.dumps` 一次**——封套
改造之后 `content` 本身就是 JSON，里面再嵌一个"装着 JSON 的字符串"是双重编码，
读的人得多解一层。核对侧由 `node_io._check_structured_content` 与
`_check_read_accounts` 守着（`facts` 得是对象、两条 `sequence` 得是数组、
六条读口的 `refs` 得是字符串数组）。

**还有一条 0914 跟进的总规矩：同笔账之内能从兄弟字段推出来的不写**——
`goal_count`（= len(goals)）、`success_rate`（= succeeded/total）、
`count`（= len(refs/names)）、`dropped_count`、`pushed_count`、
`segment_count`/`press_count`（= sequence 的长度与次数和）、`observe` 顶层的
`scene`/`overlay`（= facts 里的同名字段）、`episode_error` 的恒定
`success`/`steps`，全都因此退场；能推的那一维随兄弟字段一起**改成数组**，
让"数出来"变成可靠操作而不是分词。

各 kind 必填的 req 字段用每个函数入口的 assert 表达（precondition），
与 `FromHarnessToTraceToolAppendReq` 的 docstring 一一对应。

**记忆写口只有一种形状**：`(MEMORY_IO, TraceKind.WRITE_*, <记录正文>)`
——三本账逐字相同，正文是**源记录去掉坐标与章**之后的那份（见 `_body` 与
各家 `drop`）。`meta` 与封套的形状由 `TraceTool`/`store` 保证，
**本文件不再自己拼 `{kind, source, meta, content}` 那个信封**（0914 之前是那样，
`source` 与 `meta` 都住在 payload 里）。

章（成没成、几步、是不是空章）在 `episode_start` / `episode_end` 两条边界账上，
**不进写账的 content**。
"""

from __future__ import annotations

from typing import Any, NamedTuple

from pydantic import BaseModel

from pokemon_agent.brain import (
    Action,
    Goal,
    StepVerifyVerdict,
    Task,
)
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    RunResp,
    TraceKind,
)
from pokemon_agent.schemas.memory import (
    EpisodeMemory,
    ObjectFactEvent,
    StepMemory,
)
from pokemon_agent.trace import EventType
from pokemon_agent.world import Observation


class Rendered(NamedTuple):
    """一条渲染结果：「这条记录是什么粗类、叫什么账、正文是什么」。

    `content` 是**对象**（dict / list），落盘时由 `store.LocalTrace.append` 序列化
    成 JSON 字符串——序列化只在一处做。
    """

    type: str
    kind: str
    content: Any


RenderedEvent = Rendered | list[Rendered]
"""渲染函数的返回值：一条，或（一拆多时）一串。"""


def run_start(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**run 的边界必须进事件流**，跟 `episode_start` 是同一个理由：没有它，
    replay/统计分不出一个 run 从哪开始，也看不出初始目标栈的目标文字和判据
    长什么样（`success_criteria` 只有当时的判据原文，判定逻辑不在这里）。

    run 级账沿用项目约定（`meta.episode_id` 位放 run_id、`step` 恒 0）——run 级
    事件不挂在任何一局上，跟 `plan` 的模型调用账是同一个约定。

    **`goals` / `success_criteria` 是两条平行的数组**（按栈序，栈顶在最后）——
    与每帧 `observe` 的 `goals` 同一个形状（`Task` 与 `Goal` 两个类型在这一列上
    同形，两处的差别只有"哪一份列表"）。**不另记 `goal_count`**：它是
    `len(goals)`，数组自己数得出来。

    前置条件：`req.meta.source` 非空（`RunHarness.new_run` 自报）。
    """
    goals: list[Task] = req.run_goals or []
    return Rendered(
        EventType.LIFECYCLE,
        TraceKind.RUN_START,
        {
            "goals": [g.goal for g in goals],
            "success_criteria": [g.success_criteria for g in goals],
        },
    )


def run_end(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**run 的收尾必须进事件流。** 不记的话，光看 trace 分不出这个 run 是
    正常跑完（目标栈清空 / 人工喊停）还是半路死掉（撞
    `GraphRecursionError`、进程被杀……）。异常路径走 `run_error`，不是这里。

    **不记 `success_rate`**（0914 跟进）：它是 `succeeded / total`，同一笔账里
    两个兄弟字段就能推出来——留一份迟早会有一份不对。

    前置条件：req.outcome_run 非 None。
    """
    outcome: RunResp = req.outcome_run
    return Rendered(
        EventType.LIFECYCLE,
        TraceKind.RUN_END,
        {
            "total": str(outcome.total),
            "succeeded": str(outcome.succeeded),
        },
    )


def run_error(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """异常逃出 `RunHarness.run()` 之前**补一条收尾事件**——跟 `episode_error`
    是同一个理由：不补的话这个 run 在事件流里永远"没有结束"，离线统计时
    既不在成功里也不在失败里，直接从分母上消失。

    **它只带 `error`**（0914 跟进）：此前还照抄 `run_end` 那三件
    （`total` / `succeeded` / `success_rate`），填的却是写死的 `0` / `0` / `0.0`
    ——而这条账恰恰是在"结算还没算出来"的时候写的（异常从 `run()` 里逃出去，
    `RunResp` 根本没生成）。于是那三个数不是"还没算"，是**声称这个 run 一局
    都没跑**：崩在第 5 局的 run 也被写成 `total=0`，**是假信息**，比缺字段更坏。
    两型（`run_end` / `run_error`）共有字段的便利，抵不过"报一个错的数"。

    前置条件：req.error 非 None（异常的字符串快照）。
    """
    return Rendered(
        EventType.LIFECYCLE,
        TraceKind.RUN_ERROR,
        {
            # **异常快照叫 `error`，不叫 `why`**（0914 对齐审计）：`why` 在
            # `judge_verdict`/`plan_verdict`/判定账单上是"**模型给出的理由**"，
            # 两个语义共用一个字段名。这里连同 `episode_error` 一起——错误族
            # 一律说 `error`。
            "error": req.error,
        },
    )


# ---- episode 边界 ----


def episode_start(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**episode 的边界必须进事件流。** 没有它，光看日志分不出一次尝试从哪开始。

    任务本体快照进正文（`goal`/`success_criteria`/`max_steps`）；**`task_id`
    不进**——那是实验层的分组键，实验层自己知道在跑哪个任务。

    **`success_criteria` 必须逐局快照**：run_start 只记初始目标栈的判据；
    而且 plan 压栈后每一局的判据可以和初始栈不同，"这一局实际用的判据"的权威
    落点在这里。

    前置条件：req.task 非 None。
    """
    task: Task = req.task
    return Rendered(
        EventType.LIFECYCLE,
        TraceKind.EPISODE_START,
        {
            "goal": task.goal,
            "success_criteria": task.success_criteria,
            "max_steps": str(task.max_steps),
        },
    )


def episode_end(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**成功与否必须落进事件流。** 不记的话，光看日志算不出成功率——
    而那是这个项目唯一的一组硬数字。

    **判定依据不进这里**——它随最后一次判定的账单留档（`judge_call` 的
    `why`），不重复存。

    前置条件：req.outcome_episode 非 None。
    """
    outcome = req.outcome_episode
    return Rendered(
        EventType.LIFECYCLE,
        TraceKind.EPISODE_END,
        {
            "success": str(outcome.success).lower(),
            "steps": str(outcome.steps),
            "reason": outcome.reason,
        },
    )


def episode_error(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**异常逃出去之前必须补一条收尾事件。** 不补的话这一局在事件流里
    永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，
    **直接从分母上消失**——而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那类。

    **它只带 `error`**（0914 跟进，与 `run_error` 同一口径）：此前还带
    `success="false"` 与 `steps="-1"`——前者恒等于「kind 是 episode_error」这个
    事实本身，后者是一个"未知"哨兵，两个都能从封套的 `kind` 推出来，留着只会
    多两个能与真相对不上的地方。"两型同形"的便利抵不过它们不携带信息。

    前置条件：req.error 非 None。
    """
    return Rendered(
        EventType.LIFECYCLE,
        TraceKind.EPISODE_ERROR,
        {"error": req.error},
    )


# ---- 账：每一次模型调用共用同一条翻译规则 ----

_CALL_LINK: dict[str, str] = {
    TraceKind.PERCEPTION_CALL: "perception",
    TraceKind.DECIDE_CALL: "decide",
    TraceKind.PLAN_CALL: "plan",
    TraceKind.JUDGE_CALL: "judge",
    TraceKind.VERIFY_CALL: "verify",
    TraceKind.SUMMARIZE_CALL: "summarize",
    TraceKind.EXTRACT_CALL: "extract",
}
"""`TraceKind` 的七个调用类 → **链路名**，那个维度唯一的真源。

链路名必须与 `BrainTool._attempt_loop("…")` 的实参、以及 `*AttemptFailed`
的默认 `source` 逐字相同——它们是同一个东西（`MaxRetriesExceeded.source`），
**分两处写就会静默漂移**。落点只有一处：错误账（`call_failed` /
`call_exhausted`）的 `content.link`。**调用账本身不带链路名**——它的 `kind`
（`decide_call`）已经说明了是哪条链。

0913 晚之前这里从 `Source` 派生（那时链路名还另占一个顶层 `source` 字段）；
`Source` 删除后本表就是链路名唯一的家。

`extract`（0914 S4）与 `summarize` 并列而不是并入它：两条链路吃同一份素材
（这一局的可信记录）但产出不同的东西（知识属于世界、摘要属于那一局），
**分开记才看得出"哪条链路在烧钱、烧出了什么"**。
"""


def model_call(req: FromHarnessToTraceToolAppendReq) -> list[Rendered]:
    """一笔账里的**每一条**模型调用 → 一条调用账，失败的那次再补一条 `call_failed`。

    **账单和失败模式是两件事**：前者回答"花了多少钱"，后者回答"为什么没
    拿到东西"。混进一条里，按失败类型聚合的时候就得去解析正文里的字符串。

    `req.calls` 是整条重试链（每次尝试一条）——重试过的调用在这里展开成多条
    调用账。**没有 `attempt` 戳**（0914 跟进删）："第几次"由账在链上的位置回答，
    再盖一枚戳就是给同一个数留第二个能对不上的地方。

    前置条件：req.calls 非空，且 req.kind 是 `_CALL_LINK` 认得的七个调用类之一。
    """
    assert req.calls, "model_call rendered without any calls"
    link = _CALL_LINK[req.kind]
    events: list[Rendered] = []
    for call in req.calls:
        events.append(Rendered(EventType.MODEL_CALL, req.kind, dict(call.payload)))
        if call.error_kind:
            events.append(
                Rendered(
                    EventType.ERROR,
                    TraceKind.CALL_FAILED,
                    {
                        "link": link,
                        "exception": call.error_kind,
                        "reason": call.error,
                    },
                )
            )
    return events


def judge_call(req: FromHarnessToTraceToolAppendReq) -> list[Rendered]:
    """判定的账单，比别的链路多一份**判定依据（`why`）**：成功率是要报的数字，
    每一个 True 都得说得出依据。依据跟着账单走，episode_end 不再重复存。

    前置条件：req.calls、req.why 非 None。
    """
    return [event._replace(content={**event.content, "why": req.why}) for event in model_call(req)]


def verify_call(req: FromHarnessToTraceToolAppendReq) -> list[Rendered]:
    """校验器（`Brain.verify()`）的账单，多记一份结构化 `verdicts`。

    `verdicts` **直接放对象**（`[{index, reliable, why}, …]`）——0914 之前它是
    `json.dumps` 出来的一串字符塞在正文里，而正文当时本身就是 JSON 串，等于
    双重编码；现在正文就是 JSON，里面的结构化数据不必再自己 encode 一次。

    前置条件：req.calls、req.verdicts 非 None。
    """
    verdicts: list[StepVerifyVerdict] = req.verdicts
    rendered = [v.model_dump() for v in verdicts]
    return [
        event._replace(content={**event.content, "verdicts": rendered}) for event in model_call(req)
    ]


def call_failed(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**某条链的某一次尝试失败**（`model_call` 会为带 `error_kind` 的那次自动补）。

    单独渲染一个函数是为了让 `_RENDERERS` 的表看着完整——`TraceTool.append`
    直接收 `req.kind` 的那些账不会走它。

    前置条件：req.link、req.error 非 None。
    """
    assert req.link, "call_failed 没报 link——这条错误账属于哪条链没写"
    return Rendered(
        EventType.ERROR,
        TraceKind.CALL_FAILED,
        {"link": req.link, "exception": "", "reason": req.error or ""},
    )


def call_exhausted(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**某条链重试预算耗尽**——节点失败了、为什么。

    **只回答"这个节点完了、为什么"，不带账。**（0913 拍板）

    账与失败态是两件不同的事：前者回答"花了多少钱、每次模型吐了什么"，重试几次
    就有几条；后者回答"这个节点放弃了"。以前 `decision_failed` 用 `calls=[last]`
    把账的尾巴塞进失败事件里，只为渲染出 `last: "ParseFailure: …"` 一行——
    而那句话本就从异常上取得到（`exc.last_reason`），绕道又搬一条账进来。

    0914 封套改造：此前五个派发键（`DECISION_FAILED` / `JUDGE_FAILED` /
    `VERIFY_FAILED` / `SUMMARIZE_FAILED` / `EXTRACT_FAILED`）统统渲染成
    `kind="MaxRetriesExceeded"`、链路落在 `payload.link`——**五个成员说的是同一件
    事**，合并成一个 `CALL_EXHAUSTED`，链路改由调用方在 `req.link` 里自报
    （`render._link_failed` 那个把链路名写死在函数里的写法随之删除）。

    **不带 `reason`**（0914 跟进）："耗尽"由 `kind` 自己说；最后一次尝试为什么
    失败，答案在同链最后一条 `call_failed` 的 `reason` 上——账已逐条落过，这里
    再抄一份就是同一件事说两遍，而两处迟早有一处不同步。

    前置条件：req.link 非空。
    """
    assert req.link, "call_exhausted 没报 link——这条错误账属于哪条链没写"
    return Rendered(
        EventType.ERROR,
        TraceKind.CALL_EXHAUSTED,
        {"link": req.link},
    )


def plan_failed(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**已废**（0914 控制台改造）。`plan` 位置没有"重试预算耗尽"这个事件了：
    `Planner` 的失败契约是抛异常（原样上抛，走 `RUN_ERROR`），人不满意由插话
    循环处理且不设上限。这里留一个会炸的墓碑——万一还有调用方按老路发这笔账，
    就地爆炸比静默渲染出一条假账好。
    """
    raise AssertionError(
        "plan_failed 渲染器已删除：plan 位置没有重试预算耗尽这条账（见 TraceKind）"
    )


# ---- 一步之内的各类事件 ----


def observe(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**facts 必须进正文。** 它才是观测的实质内容。只记 summary 的话，
    replay 出来只剩「你在野外」这种废话。**`scene` / `overlay` 不另记**——
    它们就是 `facts` 里的两个字段，抄到顶层是同一件事说两遍。

    **`goals` 也要跟着这一帧一起记**（数组，栈序）——读日志的人拿得到
    "这一帧、这个决策，当时的目标栈长什么样"。

    `facts` **直接放对象**（`obs.facts.model_dump()`）：0914 之前它是
    `model_dump_json()` 出来的一串字符塞在正文里，等于双重编码。

    这一帧的原始画面**跟着这条账走**（`req.frame`，base64 PNG；0914 曾删、同日跟进
    请回——replay 只看 trace 就该看得到画面）。调用方从帧槽现取，槽空（跨进程）时
    不交、正文里也就没有这个键。

    前置条件：req.obs 非 None。
    """
    obs: Observation = req.obs
    goals: list[Goal] = req.goals or []
    content: dict[str, Any] = {
        "status": obs.status,
        "facts": obs.facts.model_dump(),
        "goals": [g.goal for g in goals],
    }
    if req.frame:
        content["frame"] = req.frame
    return Rendered(
        EventType.VIEW,
        TraceKind.OBSERVE,
        content,
    )


def action_sequence(action: Action) -> list[dict[str, Any]]:
    """动作在正文里的形状：**只有结构化的 `sequence`**（`think` 与 `do_action`
    共用这一个函数——两者的关系是 **1:N**，`think` 一次决策一条、记整条链；
    `do_action` 每按一个键一条、记那一个键，形状一致才比对得上）。

    **结构化的 `sequence` 必须记，不能只记 `describe()` 那行渲染文本**：
    "链平均多长、多少步用到了链"这类聚合要按段/按次统计，去解析渲染文本就得
    反向分词，而分词一旦和措辞漂移，统计会**静默地**错。段级 rationale 跟着
    `sequence` 一起记（`model_dump()` 带它）：它没有第二个落点——`think` 的
    正文不再有顶层 rationale，而无记忆基线组不写记忆，那时它就只剩这一处。

    **`action` / `segment_count` / `press_count` 不进正文**（0914 跟进）：三个
    都能从 `sequence` 推出来（`describe()` 是它的渲染文本、两个计数是它的
    长度与次数和）——`do_action` 那条上后两个还恒等于 1。
    """
    return [segment.model_dump() for segment in action.segments()]


def human_note_injected(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**已删**（0914 控制台改造）——插话不再是一个独立事件。

    新语义：插话是**那一次决策的输入的一部分**（人说了话 → 当场带着它重问
    模型），所以它挂在 `THINK` 的 `human_note` 字段上，而不是另起一条事件。

    本函数保留成一个**显式的墓碑**，避免有人按旧名字回头找渲染器时以为
    只是注册漏了——真正想找的东西在 `think()` 的正文里。
    """
    raise AssertionError(
        "human_note_injected 渲染器已删——插话现在挂在 THINK 的 `human_note` 字段上"
    )


def think(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """把这一步选出的动作拼成事件（`LLM_OUTCOME`）。

    **链原文在这里，一次决策一份**：`sequence` 记的就是整条链（每段自带
    rationale），这条事件占用的 step 区间由后面 N 条 `DO_ACTION` 的 step 号
    标出——将来"按链读"要分组时，join 键是 `(episode_id, step)`。

    **正文里没有顶层 `rationale`**（v3 起）：理由的粒度是段，就写在段里。

    **`human_note` 只在非空时进正文**。

    **`input` / `output` 是那次成功的请求与原文**（结论账自带"问了什么、模型吐了
    什么"，不必跳到调用账对读）。**没有 `attempt`**（0914 跟进删）：这条链是第几次
    问出来的，由同一步的 `decide_call` 账条数与顺序回答，插话轮次一混它就数不干净
    ——索性不给它一个能错的位子。

    前置条件：req.action、req.input、req.output 非 None。
    """
    action: Action = req.action
    assert req.input is not None and req.output is not None, (
        "think 结论账要带上那次成功的请求与原文（input/output）"
    )
    content: dict[str, Any] = {
        "sequence": action_sequence(action),
        "thought": action.thought,
        "input": req.input,
        "output": req.output,
    }
    if req.human_note:
        content["human_note"] = req.human_note
    return Rendered(EventType.LLM_OUTCOME, TraceKind.THINK, content)


def do_action(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """把这一次按键拼成事件。

    **和 `think` 共用 `action_sequence`，但关系是 1:N**：`think` 落在链首那一步、
    记整条链；这里**每按一个键记一条**、记的就是那一个键（单段、`times=1`）。

    **不记"结果"。** 按完之后世界变成什么样，答案是下一条 `OBSERVE` 事件里
    那份完整观测。这一键的结局（`stop`）也不在这里——它按下去的那一刻还不存在，
    落在同一步的 `AFTER_ACTION` 上。

    前置条件：req.action 非 None。
    """
    action: Action = req.action
    return Rendered(EventType.ACT, TraceKind.DO_ACTION, {"sequence": action_sequence(action)})


# ---- 记忆写：四本账**一个形状**（content 就是记录正文）----
#
# 与六条读口 `{query, refs}` 对偶——**读 = 问什么·是谁，
# 写 = 这条是谁·写到哪·写了什么**。0914 封套改造之后，"谁发的 / 落在哪一步 /
# 哪本账"三件事分别由 `meta.source` / `meta.episode_id`+`meta.step` / 封套
# `kind` 承担，所以 `content` **只剩正文**：
#
#   content  记录本体的 JSON 对象
#
# ⚠️ 判据是"存在反函数"：能否从这份对象无损还原出源记录的字段。
# `StepMemory.render()` 那种渲染文本（`… 做了 up 之后变成：…`）人能读，
# 但想拿 `action` / `stop` 只能写正则去切——分词一旦和措辞漂移，统计会
# **静默地**错。散文还有一个更硬的毛病：`write_object` 原先把 `button` /
# `map_id` 压进 `x=13 y=8 按 a` 里，账上那份就不再是记录的副本、而是一句
# **转述**（真源被丢）。


def _body(model: BaseModel, *, drop: frozenset[str]) -> dict[str, Any]:
    """源记录 → `content` 里那份正文：**去掉封套/标签已有的身份、机械判定的章、
    以及不属于正文的东西**（各家 `drop` 见模块级常量）。

    `mode="json"` 一次到位：嵌套模型落成 dict——不再有第二处手写的字段映射。

    **键名照抄模型字段**（0914 99 撤了 97 加的那次改名）：账与模型逐字可比，
    读的人查一个键只需要看一个地方。库里那一面叫 `text` 是存储实现的名字
    （`store.put(text=…)`），**不是账要跟着改的理由**。
    """
    return model.model_dump(mode="json", exclude=set(drop))


_STEP_BODY_DROP = frozenset({"episode_id", "step", "run_id", "before_frame", "after_frame"})
"""`StepMemory` 里**不进 `content`** 的字段：

- `episode_id` / `step` / `run_id`：坐标——`meta` 上有（`meta` 是这条记录的签名
  信息，由封套字段与调用方自报拼成）；
- `before_frame` / `after_frame`：**base64 PNG，不是正文**——图片的真源是
  `memory/step_memory/*.json` 本身（0914 封套改造后 trace 里已经没有帧了），
  账里再存一份 base64 会把一条写账顶到几百 KB。

其余一律照录（含 `before`/`after` 两份完整观测快照）：链内那些帧走 `ram_only`，
`after_action` 只记 `status`/`done`，**这条账是每键观测全量唯一的落点**。"""

_OBJECT_BODY_DROP = frozenset({"episode_id", "step", "run_id"})
"""`ObjectFactEvent` 里不进 `content` 的字段——同 `_STEP_BODY_DROP` 的头三个。

事件本体（`place` / `actor_place` / `kind` / `button` / `text`|`map_id`）全在；
物体格的检索键 `place.key` 是 `place` 的派生物，读的人从 `content.place` 现算即可。"""

_EPISODE_BODY_DROP = frozenset({"episode_id", "run_id", "goal", "success", "steps"})
"""`EpisodeMemory` 里不进 `content` 的字段——**坐标 + 来源章**。

`episode_id` / `run_id` 是坐标（`meta` 上有）；`goal` / `success` / `steps` 是
**机械判定的章**，真源在 `episode_start` / `episode_end` 两条边界账上，
抄进写账就是同一件事的第三份拷贝。**正文与章分家**：`content` 装正文，
成不成败去 join 边界账。

空章也不必靠标记认：`content` 里的正文全空就是空章。"""


def memory_write(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """把新写入的那条单步情景记忆拼成事件。

    `meta` 由调用方在 `req.meta` 里一次交齐——这条记忆的坐标与 `meta` 上的
    同源（调用方从 `entry` 现取，见
    `harness/episode/store/store_step_episode_memory.py`）。

    前置条件：req.entry 非 None。
    """
    entry: StepMemory = req.entry
    return Rendered(EventType.MEMORY_IO, TraceKind.WRITE_STEP, _body(entry, drop=_STEP_BODY_DROP))


def stall_check(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """`detect_stall`（L2 护栏）每一步算出的停摆键/连续计数快照。

    这条把每一步停摆判定的构成过程记下来：哪一步开始连续不动、涨到第几次
    才触发，不用重放整局重新算一遍就能看见。**没有 token 花费**。

    前置条件：req.stall_key、req.stall_count 非 None。
    """
    return Rendered(
        EventType.ACT,
        TraceKind.STALL_CHECK,
        {"stall_key": req.stall_key, "stall_count": str(req.stall_count)},
    )


def object_note(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """语义记忆和情景记忆是两回事，分开写——见 `memory_write`。

    **`content` 是事件本体的那份对象**（`type` / `kind` / `button` /
    `actor_place` / `place`，按子类再带 `text` 或 `map_id`）——事件就是存储的
    真源，trace 里这份副本让 replay 不必回读事件库。

    **物体格不单记**：它是 `content.place` 的派生物（`map_id:x:y`），
    同一条账里存两份就是"同一件事写两遍"。

    **原先这里是一段散文 + 三个顶层键**（`key` / `landmark_kind` / `actor`），
    散文里 `button`、`actor_place` 的坐标、`warp` 的目标地图都只剩几个互相
    挨着的词——取回来要正则切，**真源（记录）在账上被丢掉了**。

    前置条件：req.event 非 None。
    """
    event: ObjectFactEvent = req.event
    return Rendered(
        EventType.MEMORY_IO, TraceKind.WRITE_OBJECT, _body(event, drop=_OBJECT_BODY_DROP)
    )


def episode_memory_write(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """跨局摘要记忆写入（蒸馏成功）拼成事件。`memory` 层——这条链的
    token 花费和决策链分开记账；**账本身在 `*_call` 里**。

    **`content` 是这条记忆的正文面**：本局可信 step 记忆蒸馏出来的那些字段
    （`summary` / `reusable_patterns` / `critical_decisions` / `failure_points` /
    `quality_score` / `quality_rationale` / `applicable_scenes` / `tags`）
    **加上 `markdown`**——就是落进 `memory/episode_memory/<uuid>.md` 的那段正文
    本身，键名跟模型字段逐字一致。留全的代价是一局一条账，换来的是"重启后能
    从 trace 重建经验、run 级读账不必查记忆库"。

    **章不进 `content`**（`goal`/`success`/`steps`，见 `_EPISODE_BODY_DROP`）：
    成败是机械判定，真源在 `episode_start` / `episode_end` 上。**正文与章分家**
    之后，"两个产出者形状逐字相同、只能靠 `summary` 是不是空串猜"这个二义
    也一并消失——空章看 `content` 里的正文全空。

    前置条件：req.memory 非 None。
    """
    memory: EpisodeMemory = req.memory
    return Rendered(
        EventType.MEMORY_IO,
        TraceKind.WRITE_EPISODE,
        _body(memory, drop=_EPISODE_BODY_DROP),
    )


def episode_summary_error(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """蒸馏解析失败拼成事件。

    **`link` 与另外两条错误账对齐**：错误族一律带 `link`——没有它的那条，
    读账的人看不出"这是哪条链路的错误"。这一格属于 `summarize` 链路。

    前置条件：req.reason 非空。
    """
    return Rendered(
        EventType.ERROR,
        TraceKind.SUMMARY_PARSE_ERROR,
        {"link": "summarize", "reason": req.reason},
    )


# ---- "节点活动"轻量事件：给链式观测台补全节点痕迹，都不经模型 ----
#
# 这批事件是零成本记账（无模型调用、正文轻量）。**它们的链路归属由
# `(type, kind)` 自己带出来**：掩码/步进/图控制挂 ACT/LIFECYCLE 的
# get_action_space/stall_check/step_advance，检索挂
# MEMORY_IO 的 read_*，判定与校验挂 LLM_OUTCOME 的 judge_verdict/verify_verdict，
# 动作后观察挂 VIEW 的 after_action。**唯一的撞名是两条结论类**
# （judge 与 plan 都产出 LLM_OUTCOME），所以 plan 那条的 kind 独立成
# `plan_verdict`——见 `plan_verdict` 的说明。


def judge_verdict(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """judge 的判定结论（非账单）。

    **不重复存模型 raw**：调用账归列后链上 judge 的可见内容靠这条。
    `why` 与调用账正文里的同源，这里记一份便于不翻账单就能看结论。

    **判的是哪条目标，不在这条里记**：判定对象恒为活跃投影的末位
    （`judge` 判 `goals[-1]`），而同局的 `episode_start.goal` 已经逐字记着它。

    `input` / `output` 是那次成功的请求与原文（同 `think`）。

    前置条件：req.done/success/stalled/why/input/output 非 None。
    """
    return Rendered(
        EventType.LLM_OUTCOME,
        TraceKind.JUDGE_VERDICT,
        {
            "done": str(req.done).lower(),
            "success": str(req.success).lower(),
            "stalled": str(req.stalled).lower(),
            "why": req.why,
            "input": req.input,
            "output": req.output,
        },
    )


def action_space(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """get_action_space 的输出：这一步允许的动作名（掩码结果），**数组**。

    **不另记 `count`**（0914 跟进）：它是 `len(names)`，数组自己数得出来。
    `harness` 层——掩码是图控制做的零成本账，不是世界/模型的产出。

    前置条件：req.names 非 None。
    """
    names: list[str] = req.names
    return Rendered(
        EventType.ACT,
        TraceKind.GET_ACTION_SPACE,
        {"names": names},
    )


def retrieve_node(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """**每一次检索的唯一形状**：`{query, refs}`——问了什么、命中是谁。

    六条读口全走这一个渲染函数，形状**逐字相同**；**账名由 `req.kind` 定**
    （`READ_STEP` … `READ_VERIFY_KNOWLEDGE` 六个成员，0914 起各占一个 kind）：

    | `kind` | `query` 里是什么 | `refs` 里一条是什么 |
    |---|---|---|
    | `read_step` | `episode_id=…`（本局全量，无其他条件） | `"(episode_id, step)"` 坐标 |
    | `read_global` | `run_id=…`（本 run 全量） | 跨局摘要的 `episode_id` |
    | `read_knowledge` | **BM25 检索词原文** | 命中记录的 `source` 文件名 |
    | `read_object` | `map_id=… before_step=…` | 对象事件的 `place.key` |
    | `read_verify_step` | `episode_id=…` | 同 `read_step` |
    | `read_verify_knowledge` | **BM25 检索词原文** | 同 `read_knowledge` |

    **`query` 记的是真正交给记忆读口的东西，不加包装**：四条按等值条件查的写
    `k=v`；两条 BM25 的记那串检索词原文（它本来就带空格，包一层反而失真）。

    **为什么只有一种形状**：`refs` 答"读到的是哪几条"、`query` 答"按什么查的"
    ——这两件事就是检索的全部产出，**正文一个字节都不落这里**：单步记忆按坐标回
    `memory/step_memory/`；对象档案与知识正文在决策账单的 `prompt` 里；跨局摘要在
    `write_episode` 那条账上。

    **`refs` 是数组、没有 `count`**（0914 跟进）：清单压成一行字符串时，读的人要
    自己猜分词规则（`(ep, step)` 里带空格、文件名不带），判据侧还得维护一张
    "哪条读口按什么数条数"的表；而命中条数**恒等于 `refs` 的长度**，单列一个
    `count` 就是给"同一个数"留第二个能和真相对不上的地方。

    `memory` 层——检索不花模型的钱。

    前置条件：req.query 非 None、req.refs 非 None（空清单交 `[]`，不是省略）。
    """
    assert req.query is not None, "retrieve_node rendered without a query"
    assert req.refs is not None, "retrieve_node rendered without refs"
    return Rendered(
        EventType.MEMORY_IO,
        req.kind,
        {"query": req.query, "refs": list(req.refs)},
    )


def step_advance(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """close_step 节点：步数推进的结果。`harness` 层——图控制的记账。

    前置条件：req.next_step 非 None。
    """
    return Rendered(EventType.LIFECYCLE, TraceKind.STEP_ADVANCE, {"next_step": str(req.next_step)})


def after_action(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """`perceive_after_action` 的观察摘要（非账单）——**这一键之后世界长什么样**。

    **正文 = 这一帧观测里 RAM 免费的那一半，结构化地放**（0914 跟进改形；此前只有
    `status` 一行渲染串，把"能从 RAM 拿到什么"答成了散文）：

    - `place`：主角格的结构化坐标（`map_id/x/y`）——RAM 读得出，`None`（世界没了
      等情形）时**省略这个键**，不写 `null`；
    - `facts`：整份事实快照（RAM 档天然只有 `where`/`facing`/`neighbors`/
      `landmarks`/`walk_map`/`map_id`；完整档才多出 `scene`/`overlay`/对话那几样）；
    - `done` / `perceived`：世界还在不在、这一帧问没问过视觉模型——**用 `perceived`
      分开"没读过"和"读到是空"**（与 `Facts` 的约定同一条）。

    **`status` 不再记**：它是 `facts` 那几个字段渲染出来的一行串，抄一份是同一件事
    说两遍。**结局判读已删**（0914 用户定调）：撞没撞墙不再判、也不再截队列——
    预算由 `close_step` 的纯步数闸执行。**这一帧的原始画面跟着账走**（`req.frame`，链中间的键也
    有——RAM 档照截帧，与"有没有人看过它"无关）；跨进程槽空时不交、键不出现。

    前置条件：req.obs 非 None。
    """
    obs: Observation = req.obs
    content: dict[str, Any] = {
        "facts": obs.facts.model_dump(),
        "done": str(obs.done).lower(),
        "perceived": str(obs.perceived).lower(),
    }
    if obs.place is not None:
        content["place"] = obs.place.model_dump()
    if req.frame:
        content["frame"] = req.frame
    return Rendered(EventType.VIEW, TraceKind.AFTER_ACTION, content)


def verify_verdict(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """verify_steps 的校验结论摘要。

    逐条 verdicts 仍在调用账的正文里（报表按它解析失效率）；
    这里补轻量汇总当链上内容。

    `input` / `output` 是那次成功的请求与原文（同 `think`）。

    前置条件：req.checked、req.unreliable、req.input、req.output 非 None。
    """
    assert req.input is not None and req.output is not None, (
        "verify_verdict 要带上那次成功的请求与原文（input/output）"
    )
    return Rendered(
        EventType.LLM_OUTCOME,
        TraceKind.VERIFY_VERDICT,
        {
            "checked": str(req.checked),
            "unreliable": str(req.unreliable),
            "input": req.input,
            "output": req.output,
        },
    )


def plan_verdict(req: FromHarnessToTraceToolAppendReq) -> Rendered:
    """run 级 `plan` 节点的决策结论（非账单）。

    `pushed_goals`：压入的新目标描述**数组**，按 `push_goals` 原始列表顺序
    （**调用方注意**：这是模型提出的优先级顺序——"先做"在前，不是最终真正
    入栈的顺序）。**不另记 `pushed_count`**：数组自己数得出来。

    **`kind=plan_verdict` 与 `judge_verdict` 并列**：删掉顶层 `source` 之后，
    "这一步判完了"（judge）与"这一轮规划判完了"（plan）都产出 LLM_OUTCOME，
    只有 `kind` 分得开它们。

    前置条件：req.done、req.pushed、req.why 非 None。
    """
    pushed: list[str] = req.pushed
    content: dict[str, Any] = {
        "done": str(req.done).lower(),
        "pushed_goals": pushed,
        "why": req.why,
    }
    # `input` / `output` 可选：`auto_push_goals=False` 或控制台 planner 路径
    # 根本没有模型调用，那时交 `None`、键不出现。
    if req.input is not None:
        content["input"] = req.input
    if req.output is not None:
        content["output"] = req.output
    return Rendered(EventType.LLM_OUTCOME, TraceKind.PLAN_VERDICT, content)
