"""从完整请求与独立世界规则构建参考；不读取旧模型输出。"""

from collections import Counter
from pathlib import Path

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer import mechanical_scorer
from evals.agent_short_goal_run.scorer.stream import RunStream
from pokemon_agent.direct.trace import ParsedEvent

from .choose_labels import acceptable_actions
from .dataset_contract import InputCase, ReferenceCase
from .milestones import MILESTONES
from .rubrics import criteria_for
from .visible_judge import visible_judge


def base_reference(case: InputCase, constraints: dict[str, object]) -> ReferenceCase:
    """初始值仅有评分约束，不预填真假标签。"""
    criteria = criteria_for(case.family, case.layer)
    return ReferenceCase(
        case_id=case.case_id,
        evaluation="source_grounded_rubric",
        criteria=criteria,
        constraints=constraints,
        evidence=list(
            dict.fromkeys(f"request.{path}" for item in criteria for path in item.evidence)
        ),
    )


def judge_reference(
    case: InputCase, sample: EvalSample, events: list[ParsedEvent]
) -> ReferenceCase:
    """显式可见状态与精确匹配的原始机械判据分开处理；未知不猜。"""
    request = case.request
    result = base_reference(case, {"goal": request.goal.model_dump(mode="json")})
    if request.goal.criteria.strip() == sample.success_criteria.strip() and case.source.trace_uuids:
        _registered_truth(case, sample, events, result)
    visible = visible_judge(request)
    if visible is not None:
        result.evaluation, result.label_source = "mechanical", "mechanical"
        result.achieved, rule, locator = visible
        result.check_id = "visible_state." + rule
        result.mechanical_reason = "显式判据严格匹配；仅读当前请求可见状态"
        result.evidence = [locator]
    return result


def _registered_truth(
    case: InputCase, sample: EvalSample, events: list[ParsedEvent], result: ReferenceCase
) -> None:
    """原规则读取调用前截断流；子单元再按 episode/task 隔离。"""
    position = next(
        index for index, event in enumerate(events) if event.uuid == case.source.trace_uuids[0]
    )
    call, before = events[position], events[:position]
    if case.layer != "run":
        before = [event for event in before if event.meta.episode_id == call.meta.episode_id]
    if case.layer == "task":
        before = [
            event
            for event in before
            if event.kind == "episode_start" or event.meta.task_id == call.meta.task_id
        ]
    score = mechanical_scorer()(RunStream(before), sample.model_copy(update={"granularity": "run"}))
    if score.outcome in ("pass", "fail"):
        result.evaluation, result.label_source = "mechanical", "mechanical"
        result.achieved, result.check_id = score.outcome == "pass", sample.check_id
        result.mechanical_reason = score.reason
        work = Path(case.source.request_file).parents[3]
        result.evidence = [(work / "trace" / f"{uuid}.json").as_posix() for uuid in score.evidence]


def planning_reference(case: InputCase, sample: EvalSample) -> ReferenceCase:
    """原场景里程碑仅作有条件参考，新目标以当前请求为准。"""
    request = case.request
    if case.family == "plan":
        constraints = {"max_push": request.max_push, "goal_table": request.plan}
    else:
        constraints = {"max_tasks": request.max_tasks, "goal": request.goal}
    constraints["scenario_milestones_if_required_and_not_satisfied"] = MILESTONES.get(
        sample.sample_id.removeprefix("knowledge_"), []
    )
    constraints["milestone_applicability"] = (
        "仅当当前目标仍是该场景原始目标时适用；重规划的新目标以当前请求为准。"
    )
    return base_reference(case, constraints)


def choose_reference(case: InputCase) -> ReferenceCase:
    """不把旧选择或不完备规则候选当唯一答案；允许等价合法行动。"""
    actions, reason = acceptable_actions(case)
    result = base_reference(
        case,
        {
            "goals": case.request.goals,
            "action_space": case.request.space,
            "equivalent_actions_allowed": True,
            "acceptable": [action.model_dump(mode="json") for action in actions],
            "label_reason": reason,
        },
    )
    if actions:
        result.evaluation = "action_set"
        result.label_source = "mechanical"
        result.check_id = (
            "visible_menu.cursor_first_keys"
            if case.request.obs.facts.overlay == "choice"
            else "visible_walk_map.shortest_first_keys"
        )
    return result


def summary_reference(case: InputCase) -> ReferenceCase:
    """全部下级输入是事实参照，正负标注保留，不提供伪造的参考摘要。"""
    request = case.request
    memories = request.episode_memories if case.layer == "run" else request.entries
    source_fields = (
        "run_id",
        "episode_id",
        "task_id",
        "goal_id",
        "goal",
        "run_goal",
        "termination",
        "steps",
        "steps_used",
        "acts_used",
        "episodes",
        "succeeded",
    )
    chapter = {key: getattr(request, key) for key in source_fields if hasattr(request, key)}
    counts = Counter(
        "positive" if verdict.positive else "negative"
        for verdict in getattr(request, "verdicts", [])
    )
    return base_reference(
        case,
        {
            "source_chapter": chapter,
            "source_records": len(memories),
            "verify_distribution": dict(counts),
            "reference_summary": None,
        },
    )
