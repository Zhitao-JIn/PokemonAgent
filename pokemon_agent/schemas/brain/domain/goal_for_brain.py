"""喂给大脑的一个目标：想达成什么，以及怎么算达成。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GoalForBrain(BaseModel):
    """**喂给大脑的目标**：想达成什么，以及**怎么算达成**。

    两样一起给，不能只给前者：判定器的输入就是这两项，没有判据它无从判断，
    只能凭"看起来差不多了"回答——而那正是成功率会被污染的地方。

    本阶段一局只有一个目标，由任务给定（`goals` 栈里恒为一层，见
    `EpisodeRunState.goals`（`interfaces/harness/episode_harness_port.py`））。目标栈这个形状留着，是因为拆子目标要回来——
    但**拆的机制会在别处重写**，不是现在这个 intent 分派。
    """

    goal: str = Field(min_length=1, description="想达成什么，一句话")
    criteria: str = Field(
        min_length=1, description="画面上出现什么才算达成。**要能只看一帧就判断**"
    )
