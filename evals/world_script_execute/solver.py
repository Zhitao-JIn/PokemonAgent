"""脚本执行 solver 与运行记录；数据样本由 dataset 提供，裁决由 scorer 产出。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.common.world_case import read_frame, start_world, stop_world
from evals.world_script_execute.dataset import ScriptCase
from evals.world_script_execute.dataset.loader import state_path
from evals.world_script_execute.dataset.schemas import EventOutcome
from pokemon_agent.world import RamReadout, TaskObservation

logger = logging.getLogger(__name__)


class ScriptEvent(BaseModel):
    """脚本报告里的一条裸事件（mcp SPEC §3.4）；只钉判定要用的字段，其余原样保留。"""

    model_config = ConfigDict(extra="allow")

    outcome: EventOutcome
    object_kind: str | None = None
    text: str | None = None
    map_id: int | None = None


class ScriptReport(BaseModel):
    """脚本终态报告（`ScriptResult` 的 JSON 形状，calls 不进测评）。"""

    ok: bool
    code: str
    data: dict[str, Any] = Field(default_factory=dict)
    events: list[ScriptEvent] = Field(default_factory=list)


class ScriptRun(BaseModel):
    """solver 跑完一条用例的全部产物。

    契约：`report` 与 `crash` 恰好一个有值——脚本中途抛异常时没有报告，异常摘要进 `crash`。
    """

    report: ScriptReport | None = None
    crash: str = ""
    before_observation: TaskObservation
    before_ram: RamReadout
    after_observation: TaskObservation
    after_ram: RamReadout
    seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def _report_xor_crash(self) -> ScriptRun:
        """报告与异常二选一。"""
        assert (self.report is None) != (not self.crash), "report 与 crash 必须恰好一个有值"
        return self


def run_case(case: ScriptCase, version: str = "v1", *, checkpoint: Path | None = None) -> ScriptRun:
    """在 MCP world server 上跑一条用例（同步，solver 放进线程里调）。

    步骤 1：起 world、按开跑前的键、读开跑帧。
    步骤 2：调脚本；脚本异常与 server 侧异常记为 crash。
    步骤 3：读收尾帧，归还租约。
    """
    # 步骤 1。
    world = start_world(state_path(case.state, version), case.pre, case_id=case.case_id)
    try:
        before_observation, before_ram = read_frame(world)
        if checkpoint is not None:
            _save_before(checkpoint, before_observation, before_ram)

        # 步骤 2。
        report, crash = None, ""
        started = time.monotonic()
        try:
            body = world.call_script(case.script, dict(case.args))
            report = ScriptReport(
                ok=body["data"]["ok"],
                code=body["data"]["code"],
                data={k: v for k, v in body["data"].items() if k not in {"ok", "code", "calls"}},
                events=body["events"],
            )
        except Exception as exc:  # noqa: BLE001 —— 脚本的任何异常都是被测结论，留痕后判负
            crash = f"{type(exc).__name__}: {exc}"
        seconds = round(time.monotonic() - started, 2)

        # 步骤 3。
        after_observation, after_ram = read_frame(world)
    finally:
        try:
            stop_world(world)
        except Exception:  # noqa: BLE001 —— 归还租约失败不得掩盖步骤 2/3 已有的结论
            logger.warning("归还 world 租约失败", exc_info=True)
    return ScriptRun(
        report=report,
        crash=crash,
        before_observation=before_observation,
        before_ram=before_ram,
        after_observation=after_observation,
        after_ram=after_ram,
        seconds=seconds,
    )


def _save_before(path: Path, observation: TaskObservation, ram: RamReadout) -> None:
    """原子保存开跑帧；超时未取到收尾帧时只保留最后已知观测。"""
    provisional = ScriptRun(
        crash="超时",
        before_observation=observation,
        before_ram=ram,
        after_observation=observation,
        after_ram=ram,
        seconds=300.0,
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(provisional.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


__all__ = ["ScriptRun", "ScriptReport", "run_case"]
