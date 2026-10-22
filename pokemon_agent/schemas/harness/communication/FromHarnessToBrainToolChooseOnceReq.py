"""`FromHarnessToBrainToolChooseOnceReq`：harness → `BrainTool` 的决策请求。

**只装素材**（观测、动作空间、记忆）——harness 依赖 world/memory 是允许的，
而这些正是拼 prompt 需要的素材。`BrainTool` 自己调 `build_prompt(req)` 拼 prompt、
渲染裸字段，再交给 brain。harness 不碰 prompt（0913 定案）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.memory import ActMemory, ObjectFactEvent, TaskMemory
from pokemon_agent.world import ActionSpace, TaskObservation


class FromHarnessToBrainToolChooseOnceReq(BaseModel):
    """harness 侧组装（`harness/episode/decide/think_action.py`，纯参数拼接）、
    交给 `BrainTool` 的决策请求。

    goals：整个目标栈，栈顶（最后一个）是这一轮要完成的。
    obs：当前观测（`facts` 只装这一帧从模拟器内存读出来的东西）。
    space：当前可用动作空间——`BrainTool` 从它提取 `keys` 传给大脑，
        说明文字则渲进 prompt。
    memories：本局内情景记忆（`ActMemory`）。
    last_result：上一步脚本的结果一句话（调用 → 结局码：摘要或原因），渲染在观测之后；
        上一步不是脚本时为空。
    knowledge/task_index/human_note：分开放，各自在 prompt 里有独立
        占位符与可信度说明（混在一起模型没法区分对待）。

    `human_note` 由 `build_prompt()` 拼在**整个 prompt 的最末尾**（0914 控制台
    改造：它是覆盖指令，不是又一节背景说明——理由见
    `direct/prompts/__init__.py::append_human_note`）。**模板里没有它的占位符**
    ——它是"渲染完之后再追加"，所以不在 `decide_action.md` 的那些 `$` 变量里。

    **`prompt` 不是本模型的字段**（0913 删）：`BrainTool.choose()` 入口处调
    `prompts.decide_action.build_prompt(req)` 拼它，只活在那一次调用的局部
    ——"先拼 prompt 再回填进同一个 req"那个中间态不再外露。

    **决策的截图也不进信封**（0915 129）：`memories` 里每条 `ActMemory` 自带
    `before_frame`/`after_frame`，`BrainTool.choose()` 用 `dedup_snapshots()`
    把它们拼装成随请求发出的 images——与 prompt 的 `$memories` 段落
    （`render_sequence()` 的文字版）**同一批帧、逐帧对应**。不另开素材通道的
    理由：两条通道迟早漂移，"模型读到的文字步骤"和"看到的画面"必须严格同源。
    """

    goals: list[Goal]
    obs: TaskObservation
    space: ActionSpace
    memories: list[ActMemory]
    last_result: str = ""
    knowledge: str = ""
    task_index: list[TaskMemory] = Field(
        default_factory=list,
        description="本 episode 内、goal 与本 task 相同的此前 task，已去掉两张帧",
    )
    human_note: str = ""

    known_objects: list[ObjectFactEvent] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def serialize_incremental(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """历史请求未提供原始事件时保留原信封形状。"""
        data = handler(self)
        if "known_objects" not in self.model_fields_set:
            data.pop("known_objects", None)
        return data
