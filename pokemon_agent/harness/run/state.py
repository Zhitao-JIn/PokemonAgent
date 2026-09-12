"""run 图的唯一状态载体：`RunState` + 恢复分派的定位 `ResumeEpisode`。

从 `harness/interface/harness_port.py` 搬来（`PLAN_graph_composition.md` §6 步 0）——
**状态不是能力**，`interface/` 只回答"harness 需要外面给什么"。旧路径
`harness_port.py` 仍 re-export 这两个名字，既有 import 不用改。

步 0 的三处内容变更（其余一字未动，全部为 D2 那张父子交界键表服务）：

1. `last_task` → **`task`**（D2-③）：父子图交界靠**键名逐字对上**传递（F1），
   子侧叫 `task`，父侧就得叫 `task`——没有别名机制。这个名字本身也更准：
   它装的就是"刚派发出去的那一层目标"。
2. 新增 **`episode_goals`**（D2-②）：父侧 `goals` 是"目标栈"这个领域概念，不动；
   子侧要的是**投影视图**（`list[GoalForBrain]`，判只判栈顶），由 `dispatch` 每局
   投影写入这个新键。同名不同型会在子图入口当场 `ValidationError`（F2），
   所以两者必须分开。
3. `outcome` 的**读者**多了一个：子图从 `close_episode` 写出同名键合并回来（D2-④），
   不是父子两张图各写一次。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import GoalForBrain, TaskForBrain
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp


class ResumeEpisode(BaseModel):
    """恢复分派的定位：`dispatch` 据此走 `episode.resume(step)` 而不是 `run`
    （PLAN_checkpoint §4）。由 `RunHarness.resume_run()` 置入，分派完成后清空。
    """

    episode_id: str = Field(description="要恢复的局")
    step: int = Field(ge=0, description="恢复到该局第几步开局（0 = 本局从头重跑）")


class RunState(BaseModel):
    """一个 run 的**全部**可序列化状态。

        身份    run_id / goals / attempts / outcomes   跨轮，checkpoint 要的就是它
        交接    episode_goals / task                    每次派发前由 `dispatch` 写，
                                                        **键名与 episode 图逐字对上**
        流转    episode_id / outcome / plan_note        单轮内，节点间传递

    **`goals` 是目标栈，栈顶 = `goals[-1]`**——每次派发给子 agent 的栈顶目标；
    其余层是全局信息（子 agent 的 `episode_goals` 投影看到全栈，判只判栈顶）。
    **`attempts` 与 `goals` 平行**（`attempts[i]` = 第 i 层目标已被派发的次数），
    invariant `len(attempts) == len(goals)`——弹栈/压栈时两者必须同步增减。
    弹栈/压栈都在这里发生（`reflect`/`review`），子 agent 不碰。

    **`episode_goals` 是投影，不是第二份目标栈**：它是 `goals` 映射成
    `GoalForBrain` 之后的形态（子图要的形状），每局由 `dispatch` 重写一次。
    两者是**不同的东西**，所以是两个键——领域概念一份、给子图的投影一份。

    **活对象一个都不进来**（episode harness / trace / memory / llm）：它们
    序列化不了，是 `HarnessDeps` 的字段，由装配处注入。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话），trace 按它分组")
    goals: list[TaskForBrain] = Field(
        description="目标栈，**栈顶 = goals[-1]**（下一个要解决的）；"
        "其余层是给子 agent 的全局信息（投影成它的 `episode_goals`）",
    )
    attempts: list[int] = Field(
        default_factory=list,
        description="与 goals 平行的派发计数，attempts[i] = 第 i 层已被派发几次。"
        "invariant：len(attempts) == len(goals)。reflect 拿栈顶计数判断重试预算",
    )
    outcomes: list[FromRunHarnessToEpisodeHarnessRunResp] = Field(
        default_factory=list,
        description="已完成的 episode 结算（含重试的失败局），按执行顺序——`RunResp` 的汇总源",
    )

    episode_goals: list[GoalForBrain] = Field(
        default_factory=list,
        description="**给子图的投影**：目标栈（`goals`）映射成 `GoalForBrain` 的形态。"
        "每局由 `dispatch` 重写，键名与 `EpisodeRunState.episode_goals` 逐字相同"
        "（父子图交界按同名键传递，F1）",
    )
    task: TaskForBrain | None = Field(
        default=None,
        description="刚派发的那一层目标（review 的 RETRY 压回栈顶用；也是交界键 `task`）。"
        "`None` = 还没派发过",
    )

    episode_id: str | None = Field(default=None, description="本轮派发的 episode 标识")
    outcome: FromRunHarnessToEpisodeHarnessRunResp | None = Field(
        default=None, description="本轮刚收的结算（`reflect` 弹栈/重试的依据）"
    )
    plan_note: str = Field(
        default="",
        description="plan 本轮组装的决策上下文（trace 历史 + 目标栈渲染成 prompt）——"
        "LLM 决策器的完整输入；进 state 是为了可观测",
    )
    plan_failed: bool = Field(
        default=False,
        description="plan 的 LLM 决策连续 `PLAN_MAX_ATTEMPTS` 次失败——路由到 review "
        "交人工（机器没主意了，问人）；review 后回到 plan 会重新尝试",
    )

    resume_episode: ResumeEpisode | None = Field(
        default=None,
        description="恢复分派定位；仅 `resume_run()` 置入，dispatch 消费后清空。None = 正常流程",
    )
    done: bool = Field(default=False, description="run 是否结束（栈空且无新目标 / 人类停止）")
    why: str = Field(default="", description="结束原因（全部目标解决 / 重试耗尽 / 人类停止）")
