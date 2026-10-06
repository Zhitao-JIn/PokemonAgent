"""scripts 测评的 solver：存档起 world → 开跑前的键 → 读一帧 → 直接调脚本 → 再读一帧。

只证明"脚本在真模拟器上跑得对"，所以不经 GameTools 门面与掩码，直接走脚本层的分发
（`run_script_by_name` + `WorldConsoleAdapter`）。产物整份进 sample store，不做任何判定。
"""

from __future__ import annotations

import asyncio
import time

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import concurrency, store_as
from pydantic import TypeAdapter

from evals.core.world_case import read_frame, start_world, stop_world
from pokemon_agent.world.scripts.catalog import run_script_by_name
from pokemon_agent.world.scripts.console_adapter import WorldConsoleAdapter

from .schemas import ScriptCase, ScriptReport, ScriptRun, ScriptRunRecord
from .takeover_samples import case_for

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
        case = case_for(state.metadata)
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
