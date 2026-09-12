"""`EpisodeHarnessPort`：跑一局的子 agent 接口——**接口里就有图**。

一局（one episode）是 run 的子 agent：run 级主 agent（`HarnessPort`）按任务计划
反复调它。本接口除了顶层入口 `run()`，还显式声明**图的二十一个节点**与它们的
形状（`(EpisodeRunState) -> 状态增量`），图拓扑写在模块 docstring 里——**每个
节点只改状态里的一处**（或紧密绑在一起的一小组，如 `stall_key`/`stall_count`）：

    record_observation → judge ──(state.done ?)──→ retrieve_verify_step_memory
                       ├─(无 step 记忆)────────────────────→ close_episode
                       └─(有 step 记忆)→ retrieve_verify_knowledge
                                          → verify_and_summarize
                                          → close_episode → END
      └─(else)→ get_action_space
        → retrieve_step_episode_memory → retrieve_global_episode_memory
          → retrieve_knowledge_semantic_memory → retrieve_object_semantic_memory
        → merge_retrieval
        → think_action〔产出 plan + pending_presses〕
        → act〔弹队首一键〕 → perceive_after_action〔取帧 + 判读 + 写 AFTER_ACTION〕
        → apply_stop〔按 stop 截队 + 只在真丢键时写 ACTION_TRUNCATED〕
        → detect_stall → store_step_episode_memory → store_object_semantic_memory
        → close_step〔扶正当前帧 + 步号加一〕
             ├─(pending_presses 非空)→ act            ← 链内小循环：一个键一步
             └─(队列空)→ save_checkpoint〔写 CHECKPOINT_SAVE〕 → record_observation

**`step` 是一个小 action。** 一次决策交出的 `sequence` 被展开成
`pending_presses`，链内每按一个键就走完一圈（`act` 起头、`close_step` 收尾），
每圈各写一条 `StepMemory`、各判一次中止；队列空了才回到链首重新决策。

**账写在它的宿主里**（v7）：每个节点自己落自己那条账，三个 `*_utils` 只交回尝试
材料。于是观察账（`perceive_after_action` 的 `AFTER_ACTION`，链内每键一条）与处置账
（`apply_stop` 的 `ACTION_TRUNCATED`，**只在真的丢了键时**一条）分得清清楚楚——
"看到什么"与"据此处置了什么"是两笔账。拆法的唯一性（中止补感知要用 `stop`）、
"中止 ≠ 截断"的判据与取舍见 `docs/spec/harness/PLAN_graph_readability.md` §3.6/§3.7。

链内小循环不改节点集合，只加一条从 `close_step` 回到 `act` 的条件边——
`save_checkpoint` 因此仍然只落在链边界上（每键一份含模拟器快照的存档会让存档量
乘上链长，而链内执行是纯 RAM 确定的，从链首存档重放能逐帧复现）。

**节点职责对照表（21 格，行序 = 图的执行顺序）**——一页看完"它改哪一处 state、
写哪条账、一句话干什么"。这是"读图"缺的那一页：**"每个节点只改一处"是接口对实现方
的硬约束，约束看不见就没法检查。**

| # | 节点 | 改的 state 字段 | 写的 trace 事件 | 一句话 |
|---|---|---|---|---|
| 1 | `save_checkpoint` | —（写盘） | `CHECKPOINT_SAVE` | 链边界存档（快照 + state + 游标 + 帧账） |
| 2 | `record_observation` | —（只读；**不扶正**） | `OBSERVE`（**带本链开局帧**） | 把本链开局这一帧登记入账——**它不感知** |
| 3 | `judge` | `done`、`success` | `JUDGE_CALL`、`JUDGE_VERDICT` | 四类终止一次判完 |
| 4 | `get_action_space` | `action_space` | `ACTION_SPACE` | 算这一步能用的按键 |
| 5 | `retrieve_step_episode_memory` | `step_episode_memories` | `RETRIEVE_NODE` | 查本局单步情景 |
| 6 | `retrieve_global_episode_memory` | `global_episode_memories` | `RETRIEVE_NODE` | 查跨局摘要 |
| 7 | `retrieve_knowledge_semantic_memory` | `knowledge_semantic_memory` | `RETRIEVE_NODE` | 查知识库 |
| 8 | `retrieve_object_semantic_memory` | `object_semantic_memory` | `RETRIEVE_NODE` | 查这张地图上的 object |
| 9 | `merge_retrieval` | `observation`（折 object） | `MEMORY_READ` | 四路汇聚 + 记合并账 |
| 10 | `think_action` | `plan`、`pending_presses`、`plan_step_start` | `THINK`（+human_note、+决策账） | 决策出一条链 |
| 11 | `act` | `action`、`pending_presses` | `ACT` | 弹队首一键、推进世界（**只有它推世界**） |
| 12 | `perceive_after_action` | `pending_observation`、`pending_stop` | `AFTER_ACTION`（带帧）+ `MODEL_CALL(PERCEPTION)`（链尾/中止键） | 取新帧、判读结局（含中止补感知），**并留观察账** |
| 13 | `apply_stop` | `pending_presses` | `ACTION_TRUNCATED`（**只在真的丢了键时**） | **只落实**：按 `stop` 的作废范围截队 |
| 14 | `detect_stall` | `stall_key`、`stall_count` | `STALL_CHECK` | 算停摆（L2 护栏） |
| 15 | `store_step_episode_memory` | —（落库） | `MEMORY_WRITE` | 反思成一条情景记忆 |
| 16 | `store_object_semantic_memory` | —（落库） | `OBJECT_NOTE` | 判 object 事件并落库 |
| 17 | `close_step` | `observation`、`step` | `STEP_ADVANCE` | **扶正当前帧 + 步号加一**；链内小循环的分叉出口 |
| 18 | `retrieve_verify_step_memory` | `verify_step_entries` | `RETRIEVE_NODE` | 查本局全部 step |
| 19 | `retrieve_verify_knowledge` | `verify_knowledge` | `MEMORY_READ` | 查校验用知识 |
| 20 | `verify_and_summarize` | `verified_steps` | `VERIFY_CALL`、`VERIFY_RESULT`、`EPISODE_MEMORY_WRITE` | 一次调用：先判可信、再只用可信的写摘要 |
| 21 | `close_episode` | `outcome` | `EPISODE_END` | **本局收尾**：算结算，收尾分支都汇到它 |

改图要同时改三处：`episode/graph.py` 的 `add_node`（装配）、本表、`web/src/App.tsx` 的
`CHAIN_PHASES`。**前两者与相位表的一致性由 `scripts/check_graph_phases.py` 机械核对**
（`ast` 抽 `add_node` 的字面量，与相位表的 `key` 逐条比对）；本表与它们同为人工维护，
改图时一并跟着改。

四个 `retrieve_*` 节点各自独立（互不依赖彼此的输出，都只读 `observation`），
写进四个不同的字段；`merge_retrieval` 只做合并，把其中三类折进
`observation.facts`，交给 `think_action`。收尾分支的 `retrieve_verify_step_memory`/
`retrieve_verify_knowledge` 是同一个模式在收尾路径的落地——检索单独成节点、
结果单独落一个 state 字段，`verify_and_summarize`（一次调用问完"哪些可信"
和"蒸馏摘要"两件事，见 `docs/ROADMAP.md`"verify_steps 与 summarize 合并"
一条）本身不兼职查库——检索单独成节点，和主循环的 `retrieve_*` 同一模式，
不把查库缝进校验节点。`verify_step_entries` 为空时跳过校验与蒸馏这两格，
**但收尾链并不提前结束**——两条分支都汇到 `close_episode`（本局结算必须由图内的
节点写出，理由见该方法的文档）；没有"不经校验全量蒸馏"的第二条路径。

`EpisodeRunState` 是这一局在图上流转的全部可序列化状态——**已搬到 `episode/state.py`**
（步 0：状态不是能力，`interface/` 只回答"harness 需要外面给什么"；本文件 re-export
它，旧 import 路径不破）。它与节点签名互为契约——节点读它、写它的增量，
`run()` 用它的最终形态结算。

原来放在顶层 `pokemon_agent/interfaces/harness/`；跟着"协议物理挨着它自己的实现"这条
原则搬到了这里，`pokemon_agent/interfaces/` 这个集中注册表这次整个撤销，消费方直接
`from pokemon_agent.harness import EpisodeHarnessPort, EpisodeRunState`。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pokemon_agent.brain import TaskForBrain
from pokemon_agent.harness.deps import HarnessDeps
from pokemon_agent.harness.episode.state import EpisodeRunState
from pokemon_agent.schemas.harness import (
    FromRunHarnessToEpisodeHarnessRunReq,
    FromRunHarnessToEpisodeHarnessRunResp,
)


@runtime_checkable
class EpisodeHarnessPort(Protocol):
    """**跑一局的子 agent**：开局、跑图、收尾，一局一个回合。

    接口即图：二十个节点方法就是图的二十个节点——两个出口分叉：`judge` 出口的
    done 分支决定是继续循环还是进收尾分支（有 step 记忆时进 `verify_and_summarize`
    一格问完校验+蒸馏，没有则直接结束收尾链）；`close_step` 出口按
    `pending_presses` 是否为空决定是回到 `act` 再按一键，还是回 `save_checkpoint`
    重新决策。每个节点只改
    `EpisodeRunState` 里的一处——这是接口对实现方的约束，不只是风格建议：
    一个节点改了几处、改坏了哪处不好定位。实现方把这份契约翻译成自己的
    图引擎（当前是 LangGraph），但图有哪些节点、什么形状，由接口定死。
    """

    # ---- 上下文（步 2 新增）----

    @property
    def deps(self) -> HarnessDeps:
        """**全图唯一的 context**（`PLAN_graph_composition.md` §4 D3/F10）。

        为什么它属于接口：它是**两侧共用的同一个对象**——`RunHarness.dispatch`
        往 `deps.run_state_snapshot` 写、`save_checkpoint` 从同一份里读；将来
        `RunHarness.run()` 还要用它当 `invoke(context=…)` 的入参。实现方各自
        造一份就会"各看各的而且不报错"（F1 那类静默错）。所以端口把它亮出来，
        装配点（`build.py`）据此把同一份递给两侧。
        """
        ...

    # ---- 顶层入口 ----

    def run(
        self, req: FromRunHarnessToEpisodeHarnessRunReq
    ) -> FromRunHarnessToEpisodeHarnessRunResp:
        """跑完一局：解决栈顶这一个目标。

        req.episode_id：这一局的标识。
        req.task：栈顶目标（执行单元，含判据/步数上限）。
        req.stack：**整个目标栈（全局信息）**——投影成 `EpisodeRunState.episode_goals`：
            判只判栈顶（`episode_goals[-1]` = task.goal），其余层给大脑全局视野。
        req.run_state：RunState 的 model_dump（图状态重建/透传）。
        前置条件：episode_id 非空、task.max_steps > 0、stack 非空且栈顶 == task。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END；
            返回的 outcome 与事件流对同一局给出同一份结论。
        """
        ...

    def resume(
        self,
        episode_id: str,
        task: TaskForBrain,
        stack: list[TaskForBrain],
        step: int,
        run_state: dict[str, Any],
    ) -> FromRunHarnessToEpisodeHarnessRunResp:
        """从本局第 `step` 步开局的 checkpoint 恢复并跑完（`PLAN_checkpoint` §5）。

        **它是图外的第二个入口，不是一个节点**：前六步准备的产物（废弃截断、
        世界快照回载、状态重建、帧账回载）就是"进图的完整初始状态"，而
        `void_after` 的前提是"图还没开始跑"、`load_state_bytes` 是世界层动作
        ——做成节点会同时破坏恢复时序与 replay 的可重放性（三条理由见
        `episode/entry.py` 的模块 docstring）。

        前置条件：实现方注入了 checkpoint 工具；`(episode_id, step)` 的存档成对存在。
        后置条件：trace 里恰好多一条 `CHECKPOINT_RESTORE`、一条 EPISODE_END；
            废弃时间线（该步之后的事件/记忆/截图）已归档截断。
        """
        ...

    # ---- 图的二十一个节点（每个：(state) -> 状态增量，只改一处）----

    def save_checkpoint(self, state: EpisodeRunState) -> dict[str, Any]:
        """图边界节点：每一圈边界（含 step0）写一份 checkpoint。**只写存档与接缝账，
        不改状态。**

        同时补一条 `CHECKPOINT_SAVE`（`LIFECYCLE`）——与 `resume()` 的
        `CHECKPOINT_RESTORE` 对称，存档端在事件流里也要可见（没有它，replay 只能反推
        存档文件的 step 来切段）。量级是**链边界一条**，不是每键一条。checkpoint 工具
        未注入（测试、单局直跑）时空转，那时**不写账**（没有存档就没有接缝可标）。
        """
        ...

    def record_observation(self, state: EpisodeRunState) -> dict[str, Any]:
        """把当前帧记成一条 `OBSERVE`——**这一链的决策输入**。只记账，不改状态。

        它不扶正、不盖步号（那些是 `close_step`/`_begin` 的事）：只把
        `state.observation` 连同 `goals`、以及**这一帧的画面**记成一条链级事件。
        `OBSERVE` 每链一条——链内每个键都没有它（那些键只读 RAM、没有模型调用可挂，
        痕迹留在那一键自己的 `AFTER_ACTION` 上）。

        **它带的那一帧有两个来源**：第 0 步那一帧来自 `_begin`（没有前驱按键，只能
        挂这里）；之后每一步的开局画面由 `_frame_b64` **按 event_id 读回**上一条链链尾
        键那一帧（v7 取代 v5 的"多带一份"——链尾键自己那份挂在它的 `AFTER_ACTION` 上，
        这里读回逐字节相同的一份，见 `PLAN_graph_readability.md` §3.7.3）。
        """
        ...

    def judge(self, state: EpisodeRunState) -> dict[str, Any]:
        """这一局该不该停，在这一格一次性判完——世界结束/步数用尽/停摆/目标
        达成四类来源都在这合并，不分给别的节点。"""
        ...

    def get_action_space(self, state: EpisodeRunState) -> dict[str, Any]:
        """按这一帧观测算这一步能用的动作空间。仅在没终止的分支上跑。"""
        ...

    def retrieve_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局单步情景记忆（全量），交给 `think_action`。不折进观测。"""
        ...

    def retrieve_global_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查跨局摘要记忆（按场景 + 任务目标），交给 `merge_retrieval` 折进观测。"""
        ...

    def retrieve_knowledge_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查知识库（按 observation 特征 + goal 拼的 query），交给 `merge_retrieval`。"""
        ...

    def retrieve_object_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查语义记忆（object：这张地图上互动过的东西），交给 `merge_retrieval`。"""
        ...

    def merge_retrieval(self, state: EpisodeRunState) -> dict[str, Any]:
        """把四路检索结果合成这一帧观测：本局单步记忆之外的三类折进 `observation.facts`。"""
        ...

    def think_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """决策：从动作空间里选一个动作（一次 `choose()` = 一轮 Thought → Action）。

        只改 `plan`/`pending_presses` 两处——它们是**同一次决策的两个表示**
        （原样的链 / 展开成单键的执行队列），必须一起写：只写一个，
        另一个就会带着上一条链的残留进下一圈。
        """
        ...

    def act(self, state: EpisodeRunState) -> dict[str, Any]:
        """弹出队首一键、执行，推进世界。**唯一推进世界的节点。**

        改 `action`/`pending_presses` 两处——"弹队首"这一个动作的两面：派生的
        单键 `ActionFromBrain` 交给世界、队列里剩下的留给链内小循环。

        **不扶正当前帧**（那是 `close_step` 的活）：`observation` 在本圈里的语义是
        "这次按键之前的那一帧"——两个 store 拿它当 `before`、`perceive_after_action`
        拿它当判中止的基准——它在**上一步的终点**就已经就位，本格只读不算。

        **`settle` 由"这是不是队列里最后一个键"决定**——链中间的键不等过场走完。
        """
        ...

    def perceive_after_action(self, state: EpisodeRunState) -> dict[str, Any]:
        """感知按键后的新一帧，**判读这一键的结局**，并写这一键的 `AFTER_ACTION`。

        改 `pending_observation`/`pending_stop` 两处——"看到了什么"与"为什么没有
        继续"是同一次感知的解读，两个面。链内的键只做 RAM 感知；链尾与中止的那
        一键才做完整视觉感知（成本不变量见 `PLAN_action_step_granularity.md` §9）。

        **账在这里写（v7，账写在它的宿主里）**：本格是帧的产出格，帧归本格那条
        `AFTER_ACTION`（观察摘要 `status`/`done`，链内每键一条）。`stop` 是**处置**，
        不进观察账——它归 `apply_stop` 只在真丢键时写的那条 `ACTION_TRUNCATED`。
        接缝为什么只能在这里——中止补感知的触发条件就是 `stop`——见
        `docs/spec/harness/PLAN_graph_readability.md` §3.6/§3.7。
        """
        ...

    def apply_stop(self, state: EpisodeRunState) -> dict[str, Any]:
        """按 `stop` 的作废范围截队；**只在真的丢了键时**留一条 `ACTION_TRUNCATED`。

        改 `pending_presses` 一处；写一条账（可选的）——"截断了没有、丢了哪些键"是
        执行层处置自己的动作，与"这一键看到了什么"（上一格 `perceive_after_action`
        的 `AFTER_ACTION`）是两笔账：后者链内每键一条，前者**只在真丢键时**一条。

        **中止 ≠ 截断**：`up×1 -> down×2` 里第一下撞墙时本段剩余为零，一个键都不用
        丢，链照常往下走——那时**不写这条账**。"这一局被截断了几次"于是可以直接数
        `ACTION_TRUNCATED` 的条数，不必重算。`stop` 挂在 `ACT` 系（处置账）而不是
        `AFTER_ACTION`（观察账），正是为了让这个判断不需要读者自己做。

        **帧不归这一格**（v7）：帧由 `perceive_after_action` 挂在自己的
        `AFTER_ACTION` 上。取舍见 `docs/spec/harness/PLAN_graph_readability.md` §3.7。
        """
        ...

    def detect_stall(self, state: EpisodeRunState) -> dict[str, Any]:
        """算这一步的停摆键与连续计数（L2 护栏，只算数不改观测）。"""
        ...

    def store_step_episode_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把这一步整理成一条可检索的经验，写进情景记忆。"""
        ...

    def store_object_semantic_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """把这一步涉及的语义记忆（object：那一格本身）写进库。"""
        ...

    def close_step(self, state: EpisodeRunState) -> dict[str, Any]:
        """**把这一步关上**：当前帧前进到刚感知的那一帧、步号加一。
        **改 `observation`/`step` 两处**——"一步结束了"的两面。

        扶正排在这里的理由：它是"这一步"的终点，且必须发生在两个 store 读完
        `before`/`after` 之后（谁先扶正都会把 `before` 冲掉）。出口条件边也从这
        一格分叉（回 `act` / 回 `save_checkpoint`）。
        """
        ...

    def retrieve_verify_step_memory(self, state: EpisodeRunState) -> dict[str, Any]:
        """查本局全部 step 记忆，交给 `retrieve_verify_knowledge`/`verify_and_summarize`。
        只在判完成的收尾分支上跑一次（不是每步），仅改 `verify_step_entries`。"""
        ...

    def retrieve_verify_knowledge(self, state: EpisodeRunState) -> dict[str, Any]:
        """整局一次检索领域知识（query 由本局 step 记忆的场景/动作特征拼），
        交给 `verify_and_summarize` 判领域合理性。只在 `verify_step_entries`
        非空时才跑，仅改 `verify_knowledge`。"""
        ...

    def verify_and_summarize(self, state: EpisodeRunState) -> dict[str, Any]:
        """拿 `verify_step_entries`/`verify_knowledge` 问独立判定器，一次调用
        问完两件事：只把可信的过滤出来（改 `verified_steps`），并用它们蒸馏出
        一条跨局摘要记忆、落库。**图上单独一格，收尾链的最后一格**（见
        `docs/ROADMAP.md`"verify_steps 与 summarize 合并"一条——只在
        `verify_step_entries` 非空时才会跑到这一格，为空时收尾链直接结束，
        没有"全量蒸馏"的兜底路径）。"""
        ...
