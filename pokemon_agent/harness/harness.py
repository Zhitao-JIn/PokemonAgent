"""Harness —— **控制一局怎么跑**。它就是以前那张图。

改名的理由：以前叫 harness 的那个类其实是工具层（大脑怎么碰环境），
而真正在控制循环的是 `graph/build.py`。名字盖住了这个事实，
于是"一步"这个概念没有主人——world 在数 step，harness 在猜边界，
图在决定什么时候算一轮，三家各有一份，才需要按步去重来对账。

现在只有一个主人：

    LoopState 拥有"这一局跑到哪了"。step 在这里盖章，别人只读。
    Harness   拥有生死判断与记账。**它自己没有任何字段**，是无状态的。

**Harness 是唯一调 `trace.append()` 的人**，但组装 payload 不是它的活——
"发生了一次 observe 该记哪些字段"是 `trace/utils.py` 里一堆纯函数的事，
这里只管"这一步该不该记、记成哪个 `EventType`"，然后把纯函数吐出来的
`(episode_id, step, type, source, payload)` 原样转给 `trace.append(*...)`。
大脑把账（`ModelCall`）连同结果一起交出来，由这里翻译成事件；
判定器碰不到自己的账不是特权设计，而是所有大脑调用的共同处境。

## 一轮循环长什么样

    look             obs = self._observe(state)    -> MODEL_CALL(感知，通常 0 条，账已在上一步记过)
                                                      + OBSERVE + MODEL_CALL(判定) + GOAL_POP(完成时)
                     space = game.get_action_space()
    retrieve_memory  memories = memory.query_episodic(...)
                     obs 折进 known_objects/knowledge（语义记忆的读）  -> MEMORY_READ
    think            d = brain.choose(goals, obs, space, memories)
                                                   -> MODEL_CALL(决策)×N + ERROR×失败次数 + THINK
    press            tools.execute                 -> MODEL_CALL(感知，通常 0 条) + ACT
    remember         reflect → memory.write_episodic → memory.note_step
                                                   -> MEMORY_WRITE + OBJECT_NOTE×N
                                                      step += 1，回到 look

    look 判出终止时改走：
    summarize        memory.store_episode_summary  -> MODEL_CALL(蒸馏) + EPISODE_MEMORY_WRITE
    （回到 run()）    EPISODE_END

`retrieve_memory`/`remember`/`summarize` 是**显式的图节点**，不是藏在别处的几行代码——
"每一步先查记忆再决策""只有推进世界那一步才写记忆""一局只在结束时蒸馏一次"
这三条规则因此是图结构本身，一眼能看见（见 `_compile` 的完整说明）。

**收尾（`EPISODE_END`）不在图里，在 `run()`。** `END` 是 LangGraph 的哨兵、
挂不上动作；更要紧的是正常结束和异常终止都得写这条事件，
写在 `run()` 里两条路径才共用同一个出口。

**这一版只有一类动作。** 以前 `think` 出口按 `Action.intent` 分三岔
（press / push_goal / inspect），现在是一条直线——intent 连同它的枚举一起删了，
拆子目标的机制会在别处重写。

**观测只在 `look` 里产生，一步一次。** `_observe()` 是全项目唯一给
`step` / `done` / `success` 赋值的地方，而它只有 `_look` 一个调用方。
所以"一步一次观测"不需要任何去重来保证——它是调用图的形状本身。

`press` 里的顺序不能换：`ACT` 和 `MEMORY_WRITE` 都属于第 n 步，
`step + 1` 在最后才发生，下一轮 `look` 记的 `OBSERVE` 才是第 n+1 步。

## 目标栈

`goals` 这个栈的形状留着，但**这一版它恒为一层**：栈底是任务目标，
而压栈的唯一途径 `push_goal` 已经删了。**当前目标永远是栈顶**（`goals[-1]`），
判定只判它，完成就出栈；栈空 = 任务完成，只有这一条路径写 `success`。

`if not remaining` 在只有一层时永远成立，留着不是为了当下分支，
而是把"只有任务目标本身完成才算成功"写成代码——子目标回来之后，
agent 自己压的那些完成了只该弹栈，不该给自己发奖状。

这里曾经有一套「每层各判一次、并发发出、最深的那条完成连同上面的全部出栈」的机制
（`_judge_all` + `reason=superseded`）。前提是栈会长起来，现在不会，
所以退回最简形态：一个线程池、一段并发写 trace 的注意事项、一个恒为 0 的 `depth`，
全都不必要。当时那份权衡（判定之间的隔离与可标定性 vs 省 token）记在 CHANGELOG 里，
**不留在代码里占位**——占位的抽象会把下一版往旧形状上带，而拆解机制在别处重写时，
多层判定要不要回来、以什么形状回来，是那时的决定。

## 状态为什么全在 LoopState 里

判据是**"它会不会影响下一个 prompt"**，不是"它活多久"。

早先我按"活多久"分：单步流转的进 `LoopState`，`episode_id` / `task` / `step` /
`succeeded` 当成实例字段。理由是"图状态会被复制、合并、快照"——那句话只对活对象
（world / tools / brain / trace）成立，它们确实序列化不了。但 episode 的身份是
**纯数据**，而且恰恰是 checkpoint 唯一需要的那部分。放在实例字段里，
等于把"跑到哪了"存在了一个 checkpointer 看不见的地方：
接上 LangGraph 的 checkpointer 也恢复不出第几步、在跑哪个任务。

## 光有 LoopState 还复现不了，这一点要写明

目标是「恢复 state + 恢复模拟器存档 = 接着往下跑」。按上面那条判据数，还差两样：

- **记忆库**（`GameTools._memories`）。它进 prompt，但既不在 state 也不在存档里。
  恢复出来记忆是空的，下一个 prompt 就不一样。
- **`world._facing`**。朝向是从**我们自己的动作历史**推的，不是从 RAM 读的，
  所以 pyboy 的 save state 里没有它——而它进 `facts`、进 prompt。这个洞更隐蔽。

补法是阶段 2 的 `Checkpoint`：`LoopState` + 记忆库 + 模拟器存档 + world 的推导状态
+ manifest（模型型号与 prompt sha——prompt 改了，同一个 state 也复现不出来）。

顺带分清两件事：**replay** 是不调模型、从 trace 里按顺序取 `raw` 重新解析
（用途：改了解析器之后离线重算，不花钱），只需要 trace；
**resume** 才是接着跑，那才需要完整 checkpoint。

## 为什么还是 LangGraph 而不是 while

三段之间的转移条件是显式的边，将来往中间插节点（状态归并、值回填、
权限确认、成本熔断）不需要改循环体。LangGraph 只承担循环调度与状态传递，
记忆和状态表全部是自己实现的。

## 还没做的

**六件套只有 trace 一件**：缺权限确认、沙箱、成本上限、checkpoint、replay。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_permission import initialize
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.interfaces.brain import BrainPort
from pokemon_agent.interfaces.tools import GameToolPort, MemoryToolPort
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.schemas.action import Action, ActionSpace, Goal
from pokemon_agent.schemas.memory_episode import EpisodeMemory
from pokemon_agent.schemas.memory_episodic import MemoryEntry, Snapshot
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.task import Task
from pokemon_agent.schemas.trace import EpisodeOutcome, ModelCall, Source, Verdict
from pokemon_agent.trace import utils as trace_utils


MEMORY_RECALL_LIMIT = 5
"""每次决策检索几条情景记忆。原来是 `Brain` 构造时的 `memory_limit` 参数——
大脑不再持有检索通道之后，"查几条"变成了循环控制的事，搬到这里来。
"""

EPISODE_MEMORY_RECALL_LIMIT = 3
"""每次决策检索几条跨局摘要记忆。比 `MEMORY_RECALL_LIMIT` 小：这是"别的局
蒸馏出的经验"，本来就该比"这一局刚发生的事"占更少的 prompt 篇幅。
"""

JUDGE_HISTORY = 3
"""判定器能看到本局最近几步。

不是 0：证据可能在三步以前那一帧的对话框里，而**一条第 10 步才压进来的子目标，
前 9 步根本没人问过它**——那几帧的证据就这么丢了。原来那版靠"每步都问一次"兜底，
兜不住这个洞。

也不是"全部"：判定是每步 × 每层各一次，历史进的是**共享前缀**，
条数一多，一局的判定成本就跟着步数平方增长。三条够覆盖"刚刚发生了什么"。

历史里**不含 `rationale`**（`MemoryEntry.render(reason=False)`）——
发生过的事给判定器看，决策者对那件事的主张不给。
"""

class LoopState(BaseModel):
    """一局的**全部**可序列化状态。

    分两组，但两组都在这里——分组只是为了读的人知道哪些跨步、哪些不跨：

        身份    episode_id / task / step / succeeded / why   跨步，checkpoint 要的就是它
        流转    observation / space / action                  单步内，从一个节点传到下一个

    **`outcome` 不在这里。** 它是这一局的最终结论，由 `run()` 在图跑完之后
    从 `observation` 直接算出来——放进 state 就得有个节点负责填它，
    而"下结论"不该是任何一个循环节点的副业（详见 `run()` 里的说明）。

    **活对象一个都不进来**（world / tools / brain / trace）：它们序列化不了，
    进来就把整个状态变成不可存的。它们是 Harness 的构造参数，由装配处注入。
    """

    episode_id: str = Field(description="这一局的标识，全局唯一。trace 按它分组")
    task: Task = Field(description="在跑哪个任务。目标、判据、步数上限都在里面")
    step: int = Field(
        default=0,
        description="跑到第几步。**全项目只有这一个 step**。"
        "拆子目标和细看**也算一步**——它们同样烧一次决策调用，"
        "混进同一个数里意味着 max_steps 是一道『总共允许它折腾多少轮』的闸",
    )
    goals: list[Goal] = Field(
        default_factory=list,
        description="目标栈。**`goals[0]` 恒为任务目标，只有它决定 episode 成败**；"
        "上面几层是 agent 自己拆的子目标，完成只弹栈，不写 success",
    )
    succeeded: bool = Field(
        default=False,
        description="判定器说过达成了没有。**一旦为真就不再问**——"
        "结论不会反悔，'已经和母亲说过话了'不会因为多走一步就变回没说过",
    )
    why: str = Field(
        default="", description="判成功时的依据。成功率是要报的数字，每个 True 都得说得出依据"
    )

    observation: Observation | None = None
    space: ActionSpace | None = None
    memories: list[MemoryEntry] = Field(
        default_factory=list,
        description="`retrieve_memory` 查出来的、给这一步 `think` 用的情景记忆。"
        "**图上单独一格**——查什么、查几条是循环控制的决策，不该藏在 `think` 内部",
    )
    action: Action | None = None
    press_result: Observation | None = None
    """`press` 执行动作之后的新观测，交给紧跟着的 `remember` 去写记忆。

    只在 `press → remember` 这一段之间有意义，
    `remember` 结束后被下一轮 `look` 写的新 `observation` 盖过去，不跨步存活。
    """


class Harness:
    """一局的控制器。**它自己没有状态**——状态全在 `LoopState` 里流。"""

    def __init__(
        self, game: GameToolPort, memory: MemoryToolPort,
        brain: BrainPort, trace: TracePort, run_id: str = "local",
        episode_state_dir: Path | None = None,
    ) -> None:
        self._game = game
        self._memory = memory
        """情景记忆 + 语义记忆（object）都走这一个端口。**和 `game` 是两个不相关的
        对象**——`GameToolPort` 只碰 world，`MemoryToolPort` 只碰记忆，
        见 `interfaces/tools.py` 的模块说明。
        """
        self._brain = brain
        self._trace = trace
        """裸的 `TracePort`。`Harness` 自己调 `append()`，但从不自己拼
        `dict[str, str]`——payload 全部由 `trace_utils` 里的纯函数组装好，
        这里只负责在正确的时机把它们的输出转给 `self._trace.append(*...)`。
        """
        self._run_id = run_id
        self._episode_state_dir = episode_state_dir
        """蒸馏跨局摘要记忆（`MemoryTool.summarize_episode`）时要标在
        `EpisodeMemory.run_id` 上——`TracePort` 的实现自己持有一份同样的
        `run_id`（见 `interfaces/trace.py`），但那个不对调用方暴露 getter，
        `Harness` 只能自己另外持有一份。默认值和 `LocalTrace(run_id="local")`
        的默认值保持一致，避免两处默认值打架。
        """
        self._graph = self._compile()

    # ---- 对外只有这一个入口 ----

    @initialize
    def run(self, episode_id: str, task: Task) -> EpisodeOutcome:
        """跑完一局，返回结果。

        前置条件：episode_id 非空、task.max_steps > 0。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。
        """
        assert episode_id, "run() got an empty episode_id"
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        # **`_begin()` 也在 try 里面。** 它会 `reset()` 世界、`save_state()` 存档，
        # 而 `execute:game:save_state` 是配置里唯一 `approval_required` 的权限——
        # 人类拒批/审批超时抛出来的异常要是从这里逃走，这一局连 `EPISODE_END`
        # 都没有，正是下面那段注释要防的"从分母上消失"。
        try:
            state = self._begin(episode_id, task)
            # 一步走五个节点（look / retrieve_memory / think / press / remember），
            # 外加收尾的 summarize。留一倍余量：递归上限撞上去的症状是
            # 一局无声截断，宁可给宽。
            final = self._graph.invoke(state, {"recursion_limit": task.max_steps * 6 + 20})
        except Exception as exc:
            # **异常逃出去之前必须把 EPISODE_END 补上。** 不补的话这一局在事件流里
            # 永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，
            # **直接从分母上消失**——而 `MaxRetriesExceeded`（决策模型连着几次
            # 吐不出合法动作）恰恰是最该被记成失败的那一类。
            #
            # 记完照常往外抛：这一局确实跑不下去了，吞掉只会让调用方拿到一个
            # 语义不明的空结果。
            #
            # **权限失败不单开一个 `except` 分支。** 曾经有一个，函数体和这里
            # 逐字相同——删掉它程序行为一个字节不变，它只是让人误以为权限失败
            # 已经被单独处理过了，于是这件事不会再有人回来做。将来真要按权限名
            # 聚合（"哪一项权限最常拦住 agent"），改的地方是 `episode_error()`
            # 内部：那是"把异常翻译成事件"的纯函数的职责，不是控制流的。
            self._trace.append(*trace_utils.episode_error(episode_id, task.task_id, exc))
            raise

        final_state = LoopState.model_validate(final)
        obs = final_state.observation
        # **收尾只有这一个地方**，而且 `outcome` 就在这里算。
        #
        # 它以前是 `_look` 里调的一个 `_outcome()` 方法，算完塞进 `LoopState.outcome`
        # 带过来。两个问题：一个叫"看一眼"的节点顺手把这一局的结论下了；
        # 而 `outcome` 和下面那条 `EPISODE_END` 的 payload 本来就是**同一份信息的
        # 两个形态**（success / steps / reason 逐字段对应），算在两个地方，
        # 迟早不一致——而不一致时没有任何东西会报错，返回值说成功、事件流说失败，
        # 离线统计和调用方各信一半。
        #
        # 不包成方法是因为它只有这一个调用方，而且是三行纯翻译：
        # 包起来只会让"这个数是怎么来的"多隔一跳。
        reason = ("success" if obs.success
                  else "max_steps_exceeded" if obs.step >= task.max_steps
                  else "world_ended")
        outcome = EpisodeOutcome(
            episode_id=episode_id, task_id=task.task_id,
            success=obs.success, steps=obs.step, reason=reason,
        )

        # 正常结束写在这里，异常终止写在上面的 except 里，两条路径共用同一条
        # `EPISODE_END` —— 图内图外各写一次的话，迟早有一条路径漏掉，
        # 而漏掉的那些局会直接从成功率的分母上消失。
        self._trace.append(
            *trace_utils.episode_end(episode_id, outcome, final_state.why)
        )
        return outcome

    def _begin(self, episode_id: str, task: Task) -> LoopState:
        """开一局：重置世界，写下边界，造出初始状态。

        **这里不观测**——观测是 `look` 的事，而 `look` 是图的入口。
        记忆**不清空**——跨任务复用经验正是要验证的东西。
        """
        # **`EPISODE_START` 在做任何事之前就写。**
        #
        # 以前它写在 `reset()` / `save_state()` 之后，注释却说"episode 的边界应该是
        # 这一局在事件流里看到的第一条事件"——那句话只在**这两步都成功**时才成立。
        # `reset()` 要调模拟器和视觉模型，`save_state()` 挂着唯一那条
        # `approval_required` 的权限，两者都可能抛。抛在这一行之前的话，
        # `run()` 的兜底只会补一条 `EPISODE_END`，事件流里出现一个没有开头的结尾，
        # 比彻底没有记录更难读。
        #
        # 写在前面的代价是"这一局可能一步没跑就结束了"，但那本来就是事实，
        # 而且 `EPISODE_END` 会把原因说清楚。
        self._trace.append(
            *trace_utils.episode_start(episode_id, task, self._memory.episode_step_count)
        )

        reset = self._game.reset(task)
        if self._episode_state_dir is not None:
            self._game.save_state(str(self._episode_state_dir / f"{episode_id}.start.state"))

        # reset() 里那次真实感知产生的调用记录紧跟其后——当场记账，
        # 不留到下一次 `_observe()` 才补记。
        for call in reset.calls:
            failed = call.get("ok") != "True"
            for args in trace_utils.model_call(
                episode_id, 0, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            ):
                self._trace.append(*args)
        # 栈底是任务目标本身。**它永远在，也永远是成败的唯一依据。**
        return LoopState(
            episode_id=episode_id, task=task,
            goals=[Goal(goal=task.goal, criteria=task.success_criteria)],
        )

    # ---- 图 ----

    def _compile(self) -> CompiledStateGraph:
        """look → retrieve_memory → think → press → remember → look
                └─(done)→ summarize → END

        **一条直线，没有分派。** 以前 `think` 出口按 `Action.intent` 分三岔
        （press / push_goal / inspect），现在只剩按键一类动作——intent 连同它的
        枚举一起删了，拆子目标的机制会在别处重写。分派的边留着也没有第二个去处，
        留着只会让人以为图上还有分支。

        `retrieve_memory` / `remember` / `summarize` 都是**显式的图节点**，
        不是藏在别的节点里的几行代码。这样三条规则**是图结构本身**，
        不用读代码也看得出来：

            每一步先查记忆再决策        retrieve_memory 在 think 前面
            推进世界那一步才写记忆      remember 只跟在 press 后面
            一局只在结束时蒸馏一次经验  summarize 只在 look 的终止分支上

        `summarize` 是这一版新加的。以前蒸馏藏在收尾逻辑里，
        跟着 `EPISODE_END` 一起发生——图上看不到"这一局结束时还额外调了一次模型"，
        而那是一次真金白银的调用。摆成一格之后它有了自己的位置：
        **`look` 判出终止 → 蒸馏 → 才算走完**。

        **收尾（`EPISODE_END`）不在图里，在 `run()`。** `END` 是 LangGraph 的
        哨兵，不是节点，挂不上动作；更要紧的是正常结束和异常终止都得写这条事件，
        写在 `run()` 里两条路径才共用同一个出口——分散到图内图外各写一次，
        迟早有一条路径漏掉，而漏掉的那些局会直接从成功率的分母上消失。
        """
        graph = StateGraph(LoopState)
        graph.add_node("look", self._look)
        graph.add_node("retrieve_memory", self._retrieve_memory)
        graph.add_node("think", self._think)
        graph.add_node("press", self._press)
        graph.add_node("remember", self._remember)
        graph.add_node("summarize", self._summarize)

        graph.set_entry_point("look")
        # **唯一的终止分支在 look 出口**：看完才知道这一局还要不要继续。
        # 放在动作节点出口的话，"步数用尽"和"目标达成"要在两个地方各判一次。
        graph.add_conditional_edges(
            "look",
            lambda state : "summarize" if state.observation.done else "retrieve_memory",
            {"retrieve_memory": "retrieve_memory", "summarize": "summarize"},
        )
        graph.add_edge("retrieve_memory", "think")
        graph.add_edge("think", "press")
        graph.add_edge("press", "remember")
        graph.add_edge("remember", "look")
        graph.add_edge("summarize", END)
        return graph.compile()

    def _look(self, state: LoopState) -> dict[str, Any]:
        """看一眼，然后决定要不要接着走。**每一步都从这里开始。**

        开局那一帧也走这里——它是图的入口。所以"起点存档就已经满足判据"
        这种 episode 会在第 0 步就被判出来，一步都不用走。
        不这样的话这类局会白跑满步数，而成功率里少掉的正是最容易达成的那些。

        ## 返回值是**状态增量**，不是"结果"

        这是 LangGraph 的节点约定（CLAUDE.md 第五节）：节点返回一个 dict，
        里面只放**这一步改了哪些字段**，由 LangGraph 合并进 `LoopState`；
        没写进去的字段保持原样。所以下面 return 的不是"look 算出了什么"，
        而是"look 要求把 state 的这几个字段改成这些值"。

        只有"接着跑"那条分支多带一个 `space`（`think` 节点要用）；
        终止那条什么都不多给——**这一局的结论由 `run()` 算**，
        `_look` 只负责看一眼、判一次、把结果写回 state。
        """
        obs, goals, succeeded, why = self._observe(state)

        update: dict[str, Any] = {
            "observation": obs,
            "goals": goals,
            "succeeded": succeeded,
            "why": why,
        }

        if not obs.done:
            # 按键由工具层给。`intents` 那一层没有了——能做哪几类事曾经是循环的账，
            # 现在只有一类，`ActionSpace` 里连这个字段都删了。
            update["space"] = self._game.get_action_space()

        return update

    def _look_route(self, state: LoopState) -> str:
        """终止就去蒸馏，否则接着跑。**不直接连 END**——见 `_compile`。"""
        assert state.observation is not None, "routing before any observation"



    def _retrieve_memory(self, state: LoopState) -> dict[str, Any]:
        """查这一步要用的**全部**记忆，交给 `think`。**图上单独一格。**

        查什么、查几条本身就是循环控制的决策（用哪种检索、限几条），
        不该藏在 `think()` 内部的一行代码里——独立成节点之后，以后想换策略
        （比如从字符重叠换成 embedding），改的是这一个节点，
        `think()`/`brain.choose()` 的签名都不用动。

        用当前快照的渲染文本去查，不用 `obs.summary`：记忆里存的是快照
        （位置/概况/地标/通行图），summary 是"你在野外"这种一句话，
        两边词汇几乎不重叠，字符打分会一条都选不中。

        ## `known_objects`/`knowledge`/`episode_memories` 也在这里查，**不在 `_observe()` 里**

        三者都是记忆的读，不是"看一眼"：`known_here()` 按坐标查这张地图互动过的东西
        （语义记忆·object），`knowledge_base()` 查和坐标无关的通用先验（语义记忆·
        knowledge），`query_episode_memories()` 查和当前任务相关的、别的局蒸馏出的
        经验（跨局摘要记忆，见 `schemas/memory_episode.py`）。放进 `_observe()`
        （`look` 节点）的话，"每一步先查记忆再决策"这条规则就又变回散在多个节点里、
        图上看不出来，而这正是当初把 `retrieve_memory` 拆成独立节点要解决的问题。

        代价是它们**发生在 judge 之后**（`_observe()`/`look` 已经判过这一步）——
        这其实是好事，不是坏事：`knowledge` 之前放在 `_observe()` 里时，
        `judge()` 每一层每一步都会看到这段和"这一帧是否达成目标"完全无关的
        游戏机制说明（`known_objects` 因为在 `JUDGE_BLIND` 里躲过了，`knowledge`
        没有），纯粹是浪费判定器的 token。挪到这里之后判定器天然看不到，
        不需要再靠黑名单去挡。

        折算进 `state.observation.facts`（而不是单独一个新字段）是为了不动
        `decide_action.md` 的 `$facts` 渲染逻辑——对 `think()` 而言，这两样东西
        看起来和 `walk_map`/`landmarks` 一样，都是"当前状态的一部分"。
        """
        assert state.observation is not None, "retrieve_memory before look"
        obs, ep, step = state.observation, state.episode_id, state.observation.step
        memories = self._memory.query_episode_steps(ep)

        known = self._memory.query_objects(obs)
        if known:
            obs = obs.model_copy(update={"facts": {**obs.facts, "known_objects": known}})
        knowledge_result = self._memory.query_knowledge(
            query=state.task.goal, limit=MEMORY_RECALL_LIMIT
        )
        knowledge = "\n\n".join(knowledge_result.contents)
        if knowledge_result.contents:
            obs = obs.model_copy(update={"facts": {**obs.facts, "knowledge": knowledge}})

        # 跨局摘要记忆：查"和当前任务相关的、别的局蒸馏出的经验"，不是"这一帧长什么样"，
        # 所以查询词用 `state.task.goal`，不是 `Snapshot.of(obs).render()`——
        # `EpisodeMemory.render()` 里压根没有位置/地标这些字段，拿快照去比只会一条都选不中。
        # 场景过滤需要一个具体地图；`obs.place` 为 None（刚重置、过场动画里）时没有场景可过滤，
        # 这一步直接跳过，和 `known_here()` 处理 `obs.place is None` 的方式一致。
        episode_memories: list[EpisodeMemory] = []
        if obs.place is not None:
            scene_key = "|".join(filter(None, (
                f"map:{obs.place.map_id}",
                f"scene:{obs.facts.get('scene', '')}",
                f"overlay:{obs.facts.get('overlay', '')}",
            )))
            episode_memories = self._memory.query_episode_summaries(
                scene=scene_key, query=state.task.goal,
                limit=EPISODE_MEMORY_RECALL_LIMIT,
            )
            if episode_memories:
                rendered = "\n\n".join(m.render() for m in episode_memories)
                obs = obs.model_copy(
                    update={"facts": {**obs.facts, "episode_memories": rendered}}
                )

        # 检索发生在决策模型调用之前，事件顺序照实写——**因果顺序**，不是排版偏好。
        self._trace.append(
            *trace_utils.memory_read(
                ep, step, memories, known, knowledge, episode_memories,
                knowledge_sources=knowledge_result.sources,
            )
        )
        return {"observation": obs, "memories": memories}

    def _think(self, state: LoopState) -> dict[str, Any]:
        """大脑推理，然后**把它交回来的账翻译成事件**。

        大脑一次 `choose()` 里可能调好几次模型（解析失败要重试），
        所以这里写出来的是一组事件而不是一条。三类分开写，因为它们回答不同的问题：

            MODEL_CALL    每次尝试花了多少 —— 失败的那几次同样烧了钱
            ERROR         每次为什么失败   —— 按 kind 聚合就是失败模式分布
            THINK         最终选了什么     —— 决策内容本身

        `MEMORY_READ` **不在这里写**——查记忆这件事本身已经挪到了图上单独一格
        `retrieve_memory`，那条事件也跟着挪过去了（见该方法）。`state.memories`
        就是那一格交出来的结果，这里直接用，不重新查一遍。

        失败：重试用尽时抛 `MaxRetriesExceeded`。**抛异常的是这里，不是大脑**——
        大脑只汇报"一次都没解析出合法动作"，而"这一局是否因此终止"是循环的判断。
        """
        assert state.observation is not None, "think before look"
        assert state.space is not None, "think without an action space"
        ep, step = state.episode_id, state.observation.step

        decision = self._brain.choose(
            state.goals, state.observation, state.space, state.memories
        )
        assert decision.calls, "choose() must report at least one model call"

        for call in decision.calls:
            for args in trace_utils.model_call(ep, step, Source.DECISION, call):
                self._trace.append(*args)

        if decision.action is None:
            last = decision.calls[-1]
            self._trace.append(*trace_utils.decision_failed(ep, step, last))
            raise MaxRetriesExceeded(len(decision.calls), last.error)

        self._trace.append(*trace_utils.think(ep, step, decision.action, attempt=len(decision.calls)))
        return {"action": decision.action}

    # ---- 唯一的动作节点。**只有 press 推进世界。** ----

    def _press(self, state: LoopState) -> dict[str, Any]:
        """按键，推进世界。**只管执行和账，不写记忆。**

        记忆写入挪到了紧跟着的 `_remember()`——图上能直接看出
        "press 之后必然跟着 remember"，不用再靠读代码才知道这一步顺手把
        记忆也写了。`step` 也不在这里加：`press → remember` 是一个整体，
        加一次的地方在链路末尾（`_remember`），这样 `ACT`/`MEMORY_WRITE`
        才会落在同一个（第 n）步上。
        """
        assert state.observation is not None, "press before look"
        assert state.action is not None, "press without an action"
        ep, before, action = state.episode_id, state.observation, state.action

        result = self._game.execute(action)
        assert result.observation is not None, "execute() must return the new observation"

        # `result.calls` 是推进这一步期间（通常是执行后重新感知那一次）产生的
        # 模型调用记录，**这一步的账当场记，不再拖到下一步 `_observe()` 才补记**——
        # calls 现在跟着 `execute()` 的返回值一起交出来，不用再靠 `drain_calls()`
        # 那种"下次谁来取谁就顺手把上一步的账也记了"的隐式时机。
        for call in result.calls:
            failed = call.get("ok") != "True"
            for args in trace_utils.model_call(
                ep, before.step, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            ):
                self._trace.append(*args)

        self._trace.append(*trace_utils.act(ep, before.step, action, result.message))

        # 新观测交给 `_remember()`：它没盖过章（step 恒 0），
        # 但记忆只取 `Snapshot`——那里面全是 facts，和步号无关。
        return {"press_result": result.observation}

    def _remember(self, state: LoopState) -> dict[str, Any]:
        """把 `press` 刚推进的这一步写进记忆。**图上单独一格，只跟在 press 后面。**

        从 `_press()` 里拆出来，是为了让"记忆写在哪个节点"在图上看得见——
        以前一个 `press` 方框里塞了按键、情景记忆落库、语义记忆建档三件事，
        图上读不出这三件事的先后关系。这一版只有 `press` 一类动作，所以
        "只有推进世界那一步才写记忆"这条规则暂时没有反例；它仍然值得摆成独立一格，
        因为不推进世界的动作回来时（`after` 和 `before` 是同一帧，
        写进去就是一堆"结果：什么都没发生"，会把检索结果稀释掉），
        要改的是这条边接不接，而不是去 `_press()` 里加 if。

        `ACT`（在 `press` 里）和 `MEMORY_WRITE`（这里）都属于第 n 步；
        `step + 1` 放在这里、这条链路的末尾，下一轮 `look` 写的 `OBSERVE`
        才落在第 n+1 步上。提前加一的话事件流的步号会往回跳，
        读日志的人会把这条记忆读成下一步的。
        """
        assert state.observation is not None, "remember before look"
        assert state.action is not None, "remember without an action"
        assert state.press_result is not None, "remember before press"
        ep, before, action, after = (
            state.episode_id, state.observation, state.action, state.press_result
        )

        # `episode_id` 在这里盖：大脑不知道自己在哪一局。
        entry = self._brain.reflect(before, action, after).model_copy(
            update={"episode_id": ep}
        )
        self._memory.store_episode_step(entry)
        self._trace.append(*trace_utils.memory_write(ep, before.step, entry))

        # **语义记忆和情景记忆是两回事，分开写。**
        # 情景记忆记"我在那种画面里选了什么"，作用域是一次经过；
        # 这一条记"地图39 x=2 y=3 那个人会说什么"，作用域是那一格，域内恒真、域会再现。
        # 它不需要模型判断——面朝哪一格是 `place + facing` 算出来的，两个输入都确定。
        for note in self._memory.store_objects_interactions(before, action, after):
            self._trace.append(*trace_utils.object_note(ep, before.step, note))

        return {"step": state.step + 1}
    # ---- 观测：全项目唯一产出 Observation 的地方 ----

    def _observe(self, state: LoopState) -> tuple[Observation, list[Goal], bool, str]:
        """读一帧，盖上步号与终止判断，判一次成败，记进 trace。

        返回 `(观测, 弹栈之后的目标栈, 是否已达成, 达成的依据)` —— 后三项要写回 state。

        只有 `_look` 调它，所以**一步恰好一次**。这一版之所以不需要
        `_traced_step` / `_judged_step` 那两个去重字段，原因就是这一句。

        `game.perceive()` 是纯读且按帧缓存：`act` 里 `execute()` 刚感知过的那一帧，
        这里命中缓存，**不产生任何额外的模型调用**——`result.calls` 那时是空列表，
        这一步就没有 MODEL_CALL(perception) 事件，因为确实没有调用发生
        （执行阶段真正产生的那些调用，已经在 `_press()` 里当场记过账了）。

        终止有三个来源，这里全判了：

        - **步数用尽** —— 只有这一层知道走了几步。
        - **世界不可用**（窗口被关）—— world 自己置 `done`，这里保留。
        - **栈底那条目标达成** —— 问大脑，见 `_judge`。

        事件顺序是**因果顺序**：先记产生这一帧观测的那几次感知调用，
        再记观测本身，最后才是基于它的判定。反过来记的话，拿事件流做 replay
        的人会先看到结果、再看到产生它的原因。控制台上排版不好看是**显示层的问题**，
        在显示层解决——不能为了排版去改事件流，trace 是唯一的事实来源。

        ## `known_objects`/`knowledge` **不在**这里拼

        它们是语义记忆的读，属于"查记忆"，不属于"看一眼"——放在 `_retrieve_memory()`
        里（图上单独一格），不放在这里。`_observe()` 只产出**这一帧模拟器/视觉模型
        实际给出的东西**，见该方法的完整说明。
        """
        perceived = self._game.perceive()
        raw = perceived.observation
        obs = raw.model_copy(update={
            "step": state.step,
            "done": raw.done or state.step >= state.task.max_steps,
        })

        # **看到的都建档**，没互动过的也建——"这里有一扇门，我见过 7 次一次没进过"
        # 正是这份档案最有用的一类条目。放在这里是因为 `_observe()` 是全项目
        # 唯一一步产出一次观测的地方，而 `seen` 必须一步只加一次。
        for call in perceived.calls:
            # **`ok=False` 的那几次要带上 error_kind**，`trace_utils.model_call()`
            # 才会吐出那条 ERROR。漏掉的话「视觉模型输出解析失败」这一类**永远不出现在失败模式
            # 分布里**，只能回头去解析 payload 里的 `ok` 字符串——而那正是
            # 把 kind 单独拎出来要避免的事。
            failed = call.get("ok") != "True"
            for args in trace_utils.model_call(
                state.episode_id, obs.step, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            ):
                self._trace.append(*args)
        # **`goals` 记的是这一帧被看到时的栈**（judge 弹栈之前），因为 OBSERVE
        # 必须先于本步的判定事件（因果顺序，见上）——判完之后的栈会在随后的
        # GOAL_POP 里体现。往 payload 里塞什么字段是 `trace_utils.observe()`
        # 自己的事，这里只交出发生了什么。
        self._trace.append(
            *trace_utils.observe(state.episode_id, obs, state.goals, self._game.last_frame_sha)
        )
        return self._judge(state, obs)

    def _judge(
        self, state: LoopState, obs: Observation
    ) -> tuple[Observation, list[Goal], bool, str]:
        """**判栈顶那一条。完成就出栈。**

        ## 只判栈顶，不再每层各判一次

        以前每层各判一次、并发发出（`_judge_all`），为的是"中间层完成时，
        上面那些当初为它拆出来的一起作废"。那套机制的前提是**栈会长起来**，
        而压栈的唯一途径 `push_goal` 已经删了——栈恒为一层。
        对一层的栈来说，"每层各判一次"和"判栈顶"是同一件事，
        只是前者还额外背着一个线程池、一段并发写 trace 的注意事项，
        以及一个恒等于 0 的 `depth`。

        所以这里退回最简形态。拆解机制在别处重写时，多层判定要不要回来、
        以什么形状回来（并发 / 合成一次 / 只判栈顶）是**那时**的决定——
        当时那份权衡（隔离与可标定性 vs token）记在 CHANGELOG 里，不留在代码里
        占位，因为占位的抽象会把下一版往旧形状上带。

        ## 栈顶完成才写 success

        栈恒为一层，所以栈顶就是栈底、就是任务目标。这条 `if not remaining`
        在只有一层时永远成立——留着它不是为了当下分支，是为了**把"只有任务目标
        本身完成才算成功"这句话写成代码**：子目标回来之后，agent 自己压的那些
        完成了只该弹栈，不该给自己发奖状。

        **`obs.done` 不是跳过判定的理由**（那里的 `done` 是"步数用尽"，
        而任务完全可能恰好在最后一步达成）；**判过成功之后不再问**
        （结论不会反悔——"已经和母亲说过话了"不会因为多走一步就变回没说过）。
        """
        if state.succeeded:
            # **早退也要把 done/success 打上。** 当前图里走不到这个分支
            # （判成成功的那一步同时置了 `obs.done`，`_look_route` 直接去 summarize），
            # 但 resume 会：从一个 `succeeded=True` 的 checkpoint 恢复时，
            # 不打标记的话 `_look_route` 不去 summarize，转而进 `think`，
            # 而那时 `goals` 已经是空的（成功那一步清空了）——`brain.choose`
            # 的 `assert goals` 当场崩掉。
            return (
                obs.model_copy(update={"done": True, "success": True}),
                state.goals, True, state.why,
            )

        goals = list(state.goals)
        assert goals, "the goal stack must never be empty"

        # **同一份历史给判定器。** 证据可能在三步以前那一帧的对话框里。
        history = self._memory.query_recent_steps(state.episode_id, JUDGE_HISTORY)
        verdict = self._brain.judge(goals[-1], obs, history)

        # **判定的账单单独记**（`Source.JUDGE`）。它和决策各自烧 token，混在一起
        # 就说不清"成功率这个数字本身花了多少钱"，也算不出判定器自己的失效率。
        # 判定失败会顺带补一条 ERROR —— "判了没完成"和"根本没判出来"必须分得开，
        # 否则判定器坏掉的时候，表现就是成功率悄悄变成 0，而没人知道为什么。
        depth = len(goals) - 1
        for args in trace_utils.judge_call(state.episode_id, obs.step, depth, verdict.call):
            self._trace.append(*args)

        if not verdict.done:
            return obs, goals, False, ""

        self._trace.append(*trace_utils.goal_pop(
            state.episode_id, obs.step, depth, goals[-1], "done", verdict.why
        ))
        remaining = goals[:-1]
        if not remaining:
            # 栈空 = 任务完成。**只有这一条路径写 success。**
            return (
                obs.model_copy(update={"done": True, "success": True}),
                remaining, True, verdict.why,
            )
        return obs, remaining, False, ""

    # ---- 收尾 ----

    def _summarize(self, state: LoopState) -> dict[str, Any]:
        """**图上的最后一格**：把这一局蒸馏成一条跨局摘要记忆。

        摆成节点而不是藏在收尾逻辑里，是因为它**要调一次模型**。
        图上看得见的东西才会被算进成本：藏起来的那次调用不出现在任何方框里，
        读图的人会以为一局的开销就是 `steps × (感知 + 决策 + 判定)`。

        `success` / `steps` **直接从 `observation` 读**，不经过 `EpisodeOutcome`。
        以前这里收一个 `result: EpisodeOutcome` 参数，而那个对象是 `_look` 算好、
        塞进 state 带过来的——绕这一圈的唯一收益是少写两个字段名，
        代价是这一局的结论必须提前算出来、并且在 state 里多占一个字段。
        现在 `outcome` 只在 `run()` 的出口构造一次。

        `EPISODE_END` **不在这里写**——它在 `run()`，和异常路径共用一个出口。

        ## 为什么是这里、而不是每一步

        单步情景记忆（`MemoryEntry`）和语义记忆（object）才是每步在 `_remember()`
        里落盘的那两类；跨局摘要记忆的**检索单元是一整局**，自然也只在一整局
        跑完之后蒸馏一次，见 `schemas/memory_episode.py` 顶部对两类记忆的区分。

        ## 只吞 `ValueError` 这一种失败

        蒸馏依赖一次额外的 LLM 调用，会失败（`EpisodeMemoryGenerator.generate_summary`
        解析不出合法 JSON 时抛 `ValueError`，且已经在内部留了一条 `ERROR` trace 事件，
        见 `memory/episode/episode_summarizer.py`）。**单据齐全**才吞：那条 ERROR
        事件是它出现在失败模式统计里的凭证，没有凭证的静默吞掉就是在丢数据。

        吞掉是因为蒸馏失败不该拖累这一局本该正常记的 `EPISODE_END`——
        这一局确实跑完了，只是没能力提炼经验，这是两件事。
        别的异常照常往上抛，由 `run()` 的兜底记成一局失败。
        """
        obs = state.observation
        assert obs is not None and obs.done, "summarize before the episode finished"
        try:
            self._memory.store_episode_summary(
                state.episode_id, self._run_id, state.task.goal,
                {"success": obs.success, "steps": obs.step,
                 "max_steps": state.task.max_steps},
            )
        except ValueError:
            pass
        return {}
