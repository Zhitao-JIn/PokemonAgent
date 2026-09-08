"""`BrainTool` → `Brain` 这一跳的判定请求协议：
`FromBrainToolToBrainJudgeReq`。"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from pokemon_agent.schemas.datastore import StepMemory
from pokemon_agent.schemas.domain import GoalForBrain, ObservationFromWorld


class FromBrainToolToBrainJudgeReq(BaseModel):
    """**递给判定链路的请求**：要判的目标、本局最近几步历史，加上这次问模型用的
    prompt。**模块间调用只认一个输入参数**——这一份 req 同时是
    `pokemon_agent.prompts.judge_success.build_prompt()` 的输入（读 `prompt` 之外
    的字段拼出 prompt）和 `Brain.judge()` 的输入（只读 `prompt`），两边共享同一个
    对象。

    goal：要判的目标。
    history：本局最近几步（不含 rationale），默认空。给 `build_prompt()` 渲
        `$history`（`render_sequence()`）用的——这是"发生过的事"的叙述文本，
        跟下面 `images`/`snapshots` 是同一份 `history` 摊出来的另一半。
    images / snapshots：都由 `pokemon_agent.schemas.datastore.step_memory.
        dedup_snapshots(history)` **一次遍历、一并**算出来，长度、顺序严格
        一一对应——`images[i]` 那张截图对应的观测就是 `snapshots[i]`。
        `images`（PNG 字节，去重后的顺序）是这次问模型要带的截图；`snapshots`
        （`ObservationFromWorld` 列表）给 `build_prompt()` 转文字用，取
        `snapshots[-1]` 就是"当前观测"（不单独传 `obs` 字段——
        `history` 非空时最后一份观测就是当前观测，从同一次去重遍历里直接
        取 `snapshots[-1]`，构造上保证对得上号）。两者都不是 `build_prompt()`
        算的——跟 `prompt` 一样由 Harness（`episode_harness.py` 的 `judge()`）
        在拼完文字 prompt 之后一并填进来，因为只有 Harness 知道截图文件存在
        哪个 run/episode 下、读不读得到。都为空列表表示这次判定退化成纯文本
        （见 `Brain.judge()` 的兜底逻辑），不是"这次没有历史"的信号——那个
        信息在 `history` 里。
    prompt：这次问模型用的完整 prompt。**构造时留空**——先拿其余字段调
        `build_prompt(req)` 拼出字符串，再 `req.model_copy(update={"prompt": ...})`
        回填，才交给 `Brain.judge(req)`。
    """

    goal: GoalForBrain
    history: Sequence[StepMemory] = ()
    images: Sequence[bytes] = ()
    snapshots: Sequence[ObservationFromWorld] = ()
    prompt: str = ""
