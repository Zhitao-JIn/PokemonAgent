"""`BrainTool` → `Brain` 这一跳的判定请求协议：
`FromBrainToolToBrainJudgeReq`。"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from pokemon_agent.schemas.datastore import StepMemory
from pokemon_agent.schemas.domain import GoalForBrain


class FromBrainToolToBrainJudgeReq(BaseModel):
    """**递给判定链路的请求**：要判的目标、本局最近几步历史，加上这次问模型用的
    prompt。**模块间调用只认一个输入参数**——这一份 req 同时是
    `pokemon_agent.prompts.judge_success.build_prompt()` 的输入（读 `prompt` 之外
    的字段拼出 prompt）和 `Brain.judge()` 的输入（只读 `prompt`），两边共享同一个
    对象。

    goal：要判的目标。
    history：本局最近几步（不含 rationale），默认空。给 `build_prompt()` 渲
        `$history`（`render_sequence()`）用的——这是"发生过的事"的叙述文本。
        **"当前观测"不再单独传**：`history` 非空时（judge 第 0 步不问模型，
        走到这里 `history` 保证非空），最近一条的"之后变成"就是当前这一帧，
        `build_prompt()` 直接复用 `render_sequence()` 渲出来的最后一条，
        不再从旧的 `snapshots[-1]` 另起一份重复渲染同一份观测（0909 拍板，
        见 CHANGELOG）。
    images：由 `pokemon_agent.schemas.datastore.step_memory.
        dedup_snapshots(history)` 算出来的去重截图（PNG 字节），这次问模型
        要带的图。不是 `build_prompt()` 算的——跟 `prompt` 一样由 Harness
        （`episode_harness.py` 的 `judge()`）在拼完文字 prompt 之后一并填
        进来，因为只有 Harness 知道截图文件存在哪个 run/episode 下、读不读
        得到。空列表表示这次判定退化成纯文本（见 `Brain.judge()` 的兜底
        逻辑），不是"这次没有历史"的信号——那个信息在 `history` 里。
    prompt：这次问模型用的完整 prompt。**构造时留空**——先拿其余字段调
        `build_prompt(req)` 拼出字符串，再 `req.model_copy(update={"prompt": ...})`
        回填，才交给 `Brain.judge(req)`。
    """

    goal: GoalForBrain
    history: Sequence[StepMemory] = ()
    images: Sequence[bytes] = ()
    prompt: str = ""
