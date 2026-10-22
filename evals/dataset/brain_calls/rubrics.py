"""五类来源约束量表；只引用当时生产输入，不提供被采集模型的答案。"""

from .dataset_contract import Criterion

SPECS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "judge": (
        ("goal_satisfaction", "严格满足 goal.criteria 才判达成，不以接近目标替代完成。", ("goal",)),
        (
            "current_unit_evidence",
            "以本单元证据判断；背景不是当前单元完成的证据。",
            ("history", "task_memories", "episode_memories", "observation"),
        ),
        (
            "no_false_early_stop",
            "菜单打开、光标移动或成功叙述不能替代实际达成。",
            ("goal", "observation", "history"),
        ),
    ),
    "plan": (
        (
            "preserve_goal_identity",
            "按目标表身份调整，不因文字相同合并不同目标。",
            ("plan", "last_judge"),
        ),
        (
            "progress_relevance",
            "新增或修改目标应推进当前未完成目的，避免无关目标。",
            ("plan", "observation", "details", "human_note"),
        ),
        (
            "avoid_repeating_failure",
            "利用本 run 详情和判定，避免重复已证伪路线。",
            ("details", "last_judge", "objects"),
        ),
        ("valid_plan", "输出结构、索引和新增数量符合请求约束。", ("plan", "max_push")),
    ),
    "decompose": (
        (
            "necessary_steps",
            "包含尚未满足的必要前置步骤；已满足步骤可省略。",
            ("goal", "observation", "task_memories", "task_table"),
        ),
        (
            "dependency_order",
            "步骤按前置依赖排序，不循环、不颠倒准备与确认。",
            ("goal", "observation"),
        ),
        (
            "executable_tasks",
            "task 目标具体、判据可检验、步数为正，不虚构状态。",
            ("observation", "knowledge", "goal"),
        ),
        (
            "scope_and_feedback",
            "区分本局证据与背景，响应失败反馈和明确插话。",
            ("task_memories", "episode_index", "last_judge", "human_note"),
        ),
        ("decomposition_limit", "任务数量遵守本次 max_tasks 输出要求。", ("max_tasks",)),
    ),
    "choose": (
        ("parsed_action", "输出能解析成原 Action 契约。", ("space",)),
        ("legal_action", "每段按键或脚本符合原 mask，参数符合原签名。", ("space",)),
        (
            "goal_progress",
            "行动应依据当时状态推进当前目标；等价行动均可接受。",
            ("goals", "obs", "memories"),
        ),
        (
            "use_history",
            "若有历史或反馈，避免已证伪的重复尝试并正确使用。",
            ("memories", "last_result", "task_index", "human_note"),
        ),
    ),
    "summary": (
        ("factual_fidelity", "事实可追溯到下级输入，禁止虚构因果、动作或结果。", ("$records",)),
        (
            "outcome_fidelity",
            "来源章的终止类别、数量和最终定案优先于叙述。",
            ("termination", "judge_reason", "$verdicts"),
        ),
        ("negative_evidence", "保留重要失败和负标注，不蒸馏成全程成功。", ("$records",)),
        ("useful_compression", "总结关键决策、失败条件和经验，避免无关复述。", ("$records",)),
    ),
}


def criteria_for(family: str, layer: str) -> list[Criterion]:
    """每次创建独立值对象，按层替换源记录和判定表的字段名。"""
    substitutions = {
        "$records": "episode_memories" if layer == "run" else "entries",
        "$verdicts": "goals" if layer == "run" else "verdicts",
    }
    return [
        Criterion(
            name=name,
            instruction=instruction,
            evidence=[substitutions.get(path, path) for path in evidence],
        )
        for name, instruction, evidence in SPECS[family]
    ]
