"""从实际调用身份核对三层详情、背景和蒸馏原料；不猜测缺失来源。"""

from pokemon_agent.direct.trace import ParsedEvent

from .dataset_contract import InputCase


def verify_scope(case: InputCase, events: list[ParsedEvent]) -> list[str]:
    """返回不能核对的事项；已知身份不一致直接失败，不静默删记录。"""
    episode_goals = {
        event.meta.episode_id: event.content.goal_id
        for event in events
        if event.kind == "episode_start"
    }
    if case.family == "summary":
        _summary_scope(case, episode_goals)
        return []
    if not case.source.meta:
        return ["no_completed_attempt_for_trace_binding"]
    if case.layer == "run":
        _run_scope(case)
    elif case.layer == "episode":
        _episode_scope(case, episode_goals)
    else:
        _task_scope(case)
    return []


def _run_scope(case: InputCase) -> None:
    """L0 详情只属本 run，背景只属其他 run。"""
    request, meta = case.request, case.source.meta
    details = request.details if case.family == "plan" else request.episode_memories
    if any(memory.run_id != meta["run_id"] for memory in details):
        raise ValueError(f"{case.case_id}: foreign run details")
    if any(memory.run_id == meta["run_id"] for memory in request.run_index):
        raise ValueError(f"{case.case_id}: current run in background")


def _episode_scope(case: InputCase, episode_goals: dict[str, str]) -> None:
    """L1 背景必须同 run、同 L1 goal 身份，排除本局。"""
    request, meta = case.request, case.source.meta
    goal_id = episode_goals[meta["episode_id"]]
    if any(
        memory.episode_id != meta["episode_id"] or memory.run_id != meta["run_id"]
        for memory in request.task_memories
    ):
        raise ValueError(f"{case.case_id}: foreign episode details")
    if any(
        memory.run_id != meta["run_id"]
        or memory.goal_id != goal_id
        or memory.episode_id == meta["episode_id"]
        for memory in request.episode_index
    ):
        raise ValueError(f"{case.case_id}: invalid L1 background")


def _task_scope(case: InputCase) -> None:
    """L2 详情只属本 task；背景只属本 episode 内同目标文本的此前 task。"""
    request, meta = case.request, case.source.meta
    memories = request.memories if case.family == "choose" else request.history
    if any(
        memory.task_id != meta["task_id"]
        or memory.episode_id != meta["episode_id"]
        or memory.run_id != meta["run_id"]
        for memory in memories
    ):
        raise ValueError(f"{case.case_id}: foreign task details")
    goal = request.goals[-1].goal if case.family == "choose" else request.goal.goal
    if any(
        memory.episode_id != meta["episode_id"]
        or memory.task_id == meta["task_id"]
        or memory.goal != goal
        for memory in request.task_index
    ):
        raise ValueError(f"{case.case_id}: invalid L2 background")


def _summary_scope(case: InputCase, episode_goals: dict[str, str]) -> None:
    """summary 按 task、episode、run 分别只蒸馏本单元全部下级原料。"""
    request = case.request
    entries = request.episode_memories if case.layer == "run" else request.entries
    if any(memory.run_id != request.run_id for memory in entries):
        raise ValueError(f"{case.case_id}: foreign run in summary")
    if case.layer in ("episode", "task") and any(
        memory.episode_id != request.episode_id for memory in entries
    ):
        raise ValueError(f"{case.case_id}: foreign episode in summary")
    if case.layer == "task" and any(memory.task_id != request.task_id for memory in entries):
        raise ValueError(f"{case.case_id}: foreign task in summary")
    if (
        case.layer == "episode"
        and request.episode_id in episode_goals
        and request.goal_id != episode_goals[request.episode_id]
    ):
        raise ValueError(f"{case.case_id}: summary goal identity mismatch")
