"""scripts 测评的契约：用例（`ScriptCase` / `ScriptExpect`）、solver→scorer 交接面
（`ScriptRun` / `ScriptRunRecord`）与判定结论（`ScriptVerdict`）。

期望是纯数据（进 `Sample.metadata` 与 `.eval` 日志，Inspect View 里直接可读），分两面：

- **自报面**（`ok` / `code` / `data` / `events`）：核脚本的终态报告；
- **真值面**（`after` / `delta`）：核前后两帧 RAM 档观测，按 `PROBE_KEYS` 词表取值
  （`bag:<道具名>` 另算），不信脚本自述。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, concurrency, store_as
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from evals.solvers.world_case import read_frame, start_world, stop_world
from pokemon_agent.world import RamReadout, TaskObservation
from pokemon_agent.world.scripts.catalog import run_script_by_name
from pokemon_agent.world.scripts.console_adapter import WorldConsoleAdapter

PROBE_KEYS: tuple[str, ...] = (
    "map_id",
    "x",
    "y",
    "facing",
    "scene",
    "money",
    "party_hp_missing",
)
"""真值面可引用的键；另有 `bag:<道具名>`（背包里该道具的数量，无则 0）。"""
BAG_PREFIX = "bag:"
EventOutcome = Literal["dialog", "warp", "still"]


def is_probe_key(key: str) -> bool:
    """`key` 是否在真值词表里。"""
    return key in PROBE_KEYS or (key.startswith(BAG_PREFIX) and len(key) > len(BAG_PREFIX))


class ScriptExpect(BaseModel):
    """一条用例的期望。

    `data` 对报告 `data` 做子集匹配（只写标量）；`events` 是报告事件 outcome 序列里
    必须**按序出现**的子序列；`dialog` 是对话事件文字（按序拼起来）里必须出现的片段；
    `after` 是收尾帧的取值，`delta` 是收尾帧减开跑帧的整数差。
    契约：真值面至少写一项（只核自报的用例等于让脚本给自己打分）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    code: str
    data: dict[str, str | int | bool] = Field(default_factory=dict)
    events: list[EventOutcome] = Field(default_factory=list)
    dialog: list[str] = Field(default_factory=list)
    after: dict[str, str | int] = Field(default_factory=dict)
    delta: dict[str, int] = Field(default_factory=dict)
    takeover_id: str | None = None

    @model_validator(mode="after")
    def _truth_declared(self) -> ScriptExpect:
        """真值面非空、键都在词表里。"""
        if not (self.after or self.delta or self.takeover_id):
            raise ValueError("用例必须声明至少一项真值期望（after / delta）")
        bad = [k for k in [*self.after, *self.delta] if not is_probe_key(k)]
        if bad:
            raise ValueError(f"真值键不在词表里：{bad}")
        return self


class ScriptCase(BaseModel):
    """一条用例：存档 + 开跑前的键 + 一次脚本调用 + 期望。

    `state` 相对 `experiment/experiment_states/`；`matrix_row` 是 PLAN_mcp_servers 附录 A
    的行号（覆盖表按它聚合）；`basis` 写期望的依据（地图 / 规则出处），给审用例的人看。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    matrix_row: int | None = Field(default=None, ge=2, le=15)
    script: str
    args: dict[str, str | int] = Field(default_factory=dict)
    state: str
    pre: tuple[str, ...] = ()
    expect: ScriptExpect
    basis: str


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


class ScriptRunRecord(StoreModel):
    """solver 写、scorer 读的唯一交接面（inspect 的 sample store）。"""

    run: ScriptRun | None = None


_JSON = TypeAdapter(dict)
PYBOY_SLOT = "pyboy"
"""进程内模拟器的并发槽名（与其它 world 用例测评共用同一个槽）。"""


@solver
def script_solver() -> Solver:
    """被测对象槽位：一条样本 = 一次脚本调用。

    前置条件：`state.metadata["case"]` 是 `ScriptCase` 的 JSON 形状（task 装配时写入）。
    失败：存档起不来 / world 崩溃直接上抛（inspect 记 sample error、可重试、不进分母）；
    脚本自己抛异常不上抛——记进 `ScriptRun.crash`，交 scorer 判负。
    同一进程里同一时刻只跑一个模拟器（`concurrency("pyboy", 1)`）：并行起多个 PyBoy
    实测会读空内存（`PyBoyAssertException: No data`）。
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case = ScriptCase.model_validate(state.metadata["case"])
        async with concurrency(PYBOY_SLOT, 1):
            run = await asyncio.to_thread(run_case, case)
        store_as(ScriptRunRecord).run = run
        return state

    return solve


def run_case(case: ScriptCase) -> ScriptRun:
    """在真模拟器上跑一条用例（同步，solver 放进线程里调）。

    步骤 1：起 world、按开跑前的键、读开跑帧。
    步骤 2：调脚本；脚本抛异常记为 crash。
    步骤 3：读收尾帧，关模拟器。
    """
    # 步骤 1。
    world = start_world(case.state, case.pre, case_id=case.case_id)
    try:
        before_observation, before_ram = read_frame(world)

        # 步骤 2。
        report, crash = None, ""
        started = time.monotonic()
        try:
            result = run_script_by_name(WorldConsoleAdapter(world), case.script, dict(case.args))
            report = ScriptReport(
                ok=result.ok,
                code=result.code,
                data=_JSON.dump_python(result.data, mode="json"),
                events=list(result.events),
            )
        except Exception as exc:  # noqa: BLE001 —— 脚本的任何异常都是被测结论，留痕后判负
            crash = f"{type(exc).__name__}: {exc}"
        seconds = round(time.monotonic() - started, 2)

        # 步骤 3。
        after_observation, after_ram = read_frame(world)
    finally:
        stop_world(world)
    return ScriptRun(
        report=report,
        crash=crash,
        before_observation=before_observation,
        before_ram=before_ram,
        after_observation=after_observation,
        after_ram=after_ram,
        seconds=seconds,
    )


__all__ = ["run_case", "script_solver"]
