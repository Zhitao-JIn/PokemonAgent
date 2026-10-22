"""把逐场景与逐重规划审阅笔记绑定到每条请求的证据。"""

from evals.dataset.brain_calls.dataset_contract import Criterion, InputCase

from .contract import Annotation
from .evidence import collect
from .planning_notes import DECOMPOSE_RETRY, INITIAL, PLAN_RETRY


def review(case: InputCase) -> Annotation:
    """每个已知请求给具体要求；上下文冲突不硬造可执行计划答案。"""
    sample, _, _, index = case.case_id.split(".")
    scenario, number = sample.removeprefix("knowledge_"), int(index)
    evidence = collect(case)
    base = dict(
        case_id=case.case_id,
        family=case.family,
        request_sha256=case.source.request_canonical_sha256,
        method="codex_history_review",
        evidence=evidence,
    )
    if scenario == "battle_action_menu" and number == 2:
        return Annotation(
            **base,
            status="invalid_task",
            rationale=(
                "当前已逃跑/不在原战斗主菜单，但原 L1 明确只准方向键且禁"
                "止逃跑、离开后重新遇敌。现有输入不能同时满足目标和限制；"
                "恢复同一可用战斗现场或修订用户目标后才能作为生成任务计分"
                "。"
            ),
        )
    progress, boundary = notes_for(case, scenario, number)
    pointers = [item.pointer for item in evidence]
    criteria = [
        Criterion(name="case_progress", instruction=progress, evidence=pointers),
        Criterion(name="case_boundary", instruction=boundary, evidence=pointers),
    ]
    criteria.append(dispatch_criterion(case.family, pointers))
    return Annotation(
        **base, status="labelled", rationale=progress + " " + boundary, criteria=criteria
    )


def notes_for(case: InputCase, scenario: str, number: int) -> tuple[str, str]:
    """返回本次场景及可见重规划历史的具体要求。"""
    progress, boundary = INITIAL[scenario]
    if case.family == "decompose":
        progress, boundary = DECOMPOSE_RETRY.get((scenario, number), (progress, boundary))
    elif number > 1:
        progress = PLAN_RETRY[(scenario, number)]
        boundary = "仅依据本次请求可见的表、状态与历史调整；不导入其他 L1 的详细对话或未见地图。"
        if scenario == "battle_action_menu":
            boundary = INITIAL[scenario][1]
    if case.family == "plan":
        progress = (
            "以下是语义边界，不要求把操作细节重述为新目标；原 pending"
            " 目标仍适用时允许不更新、不新增："
        ) + progress
    return progress, boundary


def dispatch_criterion(family: str, pointers: list[str]) -> Criterion:
    """按调用契约保留可派遣目标/子任务与预算约束。"""
    return Criterion(
        name="dispatch_and_history",
        instruction=(
            (
                "可保留本次仍有效的 pending 原目标且不新增；失败/放弃目标"
                "需恢复 pending 或以有依据的等价目标替换。completed 不重"
                "复派遣，不能伪造表索引或已完成事实；新增不超过 max_push"
                "。"
            )
            if family == "plan"
            else (
                "任务要从当前观测/已结算表继续，按必要前置顺序推进，不重"
                "复已完成项；每项给明确目标/可核验 criterion/正预算，总数"
                "不超过 max_tasks。"
            )
        ),
        evidence=pointers,
    )
