"""脚本定义与统一生命周期：签名、业务步骤和恢复规则均由脚本声明。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..interface import ActionEntry, TaskScene
from .control_flow import Abort, Halt, ScriptResult
from .engine import ScriptRun
from .execution_types import ScriptReason, ScriptStatus
from .interface import WorldConsole
from .policies import ScriptPolicy

Check = Callable[[ScriptRun, dict[str, str | int]], tuple[ScriptReason, str] | None]
Execute = Callable[[ScriptRun, dict[str, str | int]], str]


@dataclass(frozen=True)
class ScriptDefinition:
    """签名、适用场合、前置校验、业务步骤与生命周期策略。

    scene 是主入口；entry_scenes 显式声明同一业务可接受的其他入口，保留实际起始场合。
    """

    spec: ActionEntry
    scene: TaskScene
    check: Check
    execute: Execute
    policy: ScriptPolicy = field(default_factory=ScriptPolicy)
    entry_scenes: tuple[TaskScene, ...] = ()


def bad_args(spec: ActionEntry, args: dict[str, str | int]) -> str:
    """参数与签名不符返回原因；外部输入失败不是 assert 契约。"""
    extra = sorted(set(args) - {p.name for p in spec.params})
    if extra:
        return f"{spec.name} 没有参数 {extra}"
    for param in spec.params:
        if param.name not in args:
            if param.default is None:
                return f"{spec.name} 缺参数 {param.name}"
            continue
        value = args[param.name]
        if param.type == "int" and (isinstance(value, bool) or not isinstance(value, int)):
            return f"{param.name} 要整数，给的是 {value!r}"
        if param.type == "str" and not isinstance(value, str):
            return f"{param.name} 要字符串，给的是 {value!r}"
    return ""


def result_for(
    run: ScriptRun, status: ScriptStatus, code: str, reason: str = "", summary: str = ""
) -> ScriptResult:
    """保留具名结局与步骤明细，返回共用的报告。"""
    return run.finish(
        ok=status is ScriptStatus.DONE,
        code=code,
        extra={
            "scene": run.scene.value,
            "status": status.value,
            "reason": reason,
            "summary": summary,
            "steps": [step.model_dump() for step in run.steps],
        },
    )


def run_definition(
    console: WorldConsole, definition: ScriptDefinition, args: dict[str, str | int]
) -> ScriptResult:
    """按定义执行；预期拒绝与中止返回报告，未预期异常向上传播。"""
    run = ScriptRun(
        console,
        budget=0,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
        policy=definition.policy,
    )
    invalid = bad_args(definition.spec, args)
    accepted = run.scene in (definition.scene, *definition.entry_scenes)
    if not accepted:
        invalid = f"{run.scene.value} 场合没有脚本 {definition.spec.name}"
    if invalid:
        code = ScriptReason.UNKNOWN_SCRIPT if not accepted else ScriptReason.BAD_ARGS
        return result_for(run, ScriptStatus.REJECTED, code.value, invalid)
    filled = dict(args)
    for param in definition.spec.params:
        if param.name not in filled and param.default is not None:
            filled[param.name] = param.default
    return execute_definition(run, definition, filled)


def execute_definition(
    run: ScriptRun, definition: ScriptDefinition, args: dict[str, str | int]
) -> ScriptResult:
    """先准备再校验；业务中止才调用 on_error，成功才调用 after。"""
    try:
        if run.policy.before:
            run.policy.before(run)
    except Abort as exc:
        return result_for(run, ScriptStatus.ABORTED, exc.code.value, exc.reason)
    except Halt as exc:
        status = ScriptStatus.LEFT_SCENE if exc.code == "left_scene" else ScriptStatus.ABORTED
        return result_for(run, status, exc.code, str(exc.extra.get("reason", "")))
    rejected = definition.check(run, args)
    if rejected:
        return result_for(run, ScriptStatus.REJECTED, rejected[0].value, rejected[1])
    try:
        summary = definition.execute(run, args)
    except Abort as exc:
        if run.policy.on_error:
            run.policy.on_error(run)
        return result_for(run, ScriptStatus.ABORTED, exc.code.value, exc.reason)
    except Halt as exc:
        if run.policy.on_error:
            run.policy.on_error(run)
        return run.finish(ok=exc.ok, code=exc.code, extra=exc.extra)
    if run.policy.after:
        run.policy.after(run)
    return result_for(run, ScriptStatus.DONE, "ok", summary=summary)
