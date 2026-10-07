"""视觉测评的产物与字段判定；机械 RAM 字段归 decode。"""

from __future__ import annotations

import asyncio
import base64

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import BaseModel, Field, model_validator

from evals.data.frames.schemas import ScreenSample
from pokemon_agent.brain.vision_factory import build_vision_provider
from pokemon_agent.world import Facts, VisionProvider
from pokemon_agent.world.errors import PerceptionAttemptFailed
from pokemon_agent.world.prompts import load as load_prompt
from pokemon_agent.world.visual_perception import perceive_visual

VISION_FIELDS: tuple[str, ...] = ("scene", "overlay", "dialog_text", "options", "cursor")
SCORE_KEYS: tuple[str, ...] = (*VISION_FIELDS, "parsed")
"""Score 的列：视觉五项各一列，外加"这次尝试解析出来没有"。"""


class PerceiveRun(BaseModel):
    """一次感知尝试的产物。

    契约：`facts` 与 `failure` 恰好一个有值——尝试失败（`PerceptionAttemptFailed`）时没有观测。
    """

    facts: Facts | None = None
    failure: str = ""
    raw: str = Field(default="", description="视觉模型原文（失败时排查用）")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _facts_xor_failure(self) -> PerceiveRun:
        """观测与失败二选一。"""
        assert (self.facts is None) != (not self.failure), "facts 与 failure 必须恰好一个有值"
        return self


class PerceiveRunRecord(StoreModel):
    """solver 写、scorer 读的唯一交接面。"""

    run: PerceiveRun | None = None


class ProviderUnreachable(RuntimeError):
    """视觉调用本身没成（网络 / 密钥 / 网关）：基础设施故障，上抛成 sample error、不进分母。

    生产里 `perceive_frame` 把这类失败与"读出来了但解析不了"都包成 `PerceptionAttemptFailed`
    （对重试循环两者一样）；测评要分开——只有后者是模型读屏的错。区分依据是账里有没有 `error`。
    """


PROMPT_NAME = "perceive_screen"
"""与 `PyBoyWorld` 缺省 `prompt_name` 同一份模板。"""


@solver
def perceive_solver(vision_model: str) -> Solver:
    """被测对象槽位：一条样本 = 一次截图视觉感知。

    前置条件：`state.metadata["sample"]` 是 `ScreenSample` 的 JSON 形状（task 装配时写入）。
    失败：型号名不认识时构造当场炸；读出来却解析不了记进 `PerceiveRun.failure`、交 scorer 判负；
    视觉调用不通（网络、密钥）抛 `ProviderUnreachable`，inspect 记 sample error、不进分母。
    """
    vision = build_vision_provider(model=vision_model, temperature=0.0)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sample = ScreenSample.model_validate(state.metadata["sample"])
        store_as(PerceiveRunRecord).run = await asyncio.to_thread(perceive_sample, sample, vision)
        return state

    return solve


def perceive_sample(sample: ScreenSample, vision: VisionProvider) -> PerceiveRun:
    """对一帧样本跑一次生产感知节点（同步，solver 放进线程里调）。"""
    png = base64.b64decode(sample.frame_png.removeprefix("data:image/png;base64,"))
    try:
        perceived = perceive_visual(
            png,
            prompt=load_prompt(PROMPT_NAME).render(
                known_map="（仅提供截图，无内存地形输入）", terrain_legend=""
            ),
            vision=vision,
        )
    except PerceptionAttemptFailed as exc:
        if exc.call.get("error"):
            raise ProviderUnreachable(str(exc.call["error"])) from exc
        return PerceiveRun(
            failure=str(exc.call.get("error") or "解析不出 ScreenState"),
            raw=str(exc.call.get("raw", "")),
            input_tokens=int(str(exc.call.get("input_tokens", 0))),
            output_tokens=int(str(exc.call.get("output_tokens", 0))),
        )
    call = perceived.call
    screen = perceived.screen
    return PerceiveRun(
        facts=Facts(
            scene=screen.scene,
            overlay=screen.overlay,
            dialog_text=screen.dialog_text,
            options=screen.options,
            cursor=screen.cursor,
            overview=screen.overview,
            **screen.fields,
        ),
        raw=str(call.get("raw", "")),
        input_tokens=int(str(call.get("input_tokens", 0))),
        output_tokens=int(str(call.get("output_tokens", 0))),
    )


__all__ = ["ProviderUnreachable", "perceive_sample", "perceive_solver"]
