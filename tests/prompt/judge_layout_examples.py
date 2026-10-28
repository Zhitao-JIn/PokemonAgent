"""判定三层的离线原料和固定 v8 的临时注册表。"""

from pokemon_agent.direct.judge_prompt_params import judge_prompt_params
from pokemon_agent.prompt import JudgeParams
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from pokemon_agent.schemas.harness.domain.ram_observation import RamObservation
from tests.prompt.layout_examples import (
    details_data,
    examples,
    observation_data,
    run_index_data,
    task_data,
)


def reading(sequence: int) -> RamObservation:
    """完整读数及每条独立来源标识。"""
    return RamObservation(
        event_id=f"ram-event-{sequence}",
        source="run.sense",
        episode_id="e",
        task_id="t",
        step=sequence,
        observed_at=100.0 + sequence,
        sequence=sequence,
        ram={
            "in_battle": False,
            "covered": True,
            "text_source": "decode",
            "menu": {"current_item": 0, "max_item": 0, "top_x": 0},
            "money": 100 + sequence,
            "bag": [],
            "party": [{"species": 1, "level": 7, "hp": 25, "max_hp": 25, "status": "ok"}],
            "decoded": {"dialog_text": "", "options": [], "cursor": ""},
        },
    )


def requests() -> dict[str, FromHarnessToBrainToolJudgeReq]:
    """真实请求契约造三层素材，不调用模型、模拟器或检索服务。"""
    plans = examples()
    choose = plans["decide_action"].model_dump(mode="json")
    episode = plans["decompose"].model_dump(mode="json")
    run = plans["run_plan"].model_dump(mode="json")
    base = {"goal": choose["goals"][-1], "knowledge": choose["knowledge"]}
    data = {
        "task": dict(
            base, history=choose["memories"], task_index=[task_data()], allow_interrupt=True
        ),
        "episode": dict(
            base,
            task_memories=[task_data()],
            task_table=episode["task_table"],
            episode_index=details_data(),
            observation=observation_data(),
        ),
        "run": dict(
            base,
            episode_memories=details_data(),
            goal_table=run["plan"],
            run_index=run_index_data(),
            observation=observation_data(),
        ),
    }
    return {name: _request(name, values) for name, values in data.items()}


def _request(name: str, data: dict) -> FromHarnessToBrainToolJudgeReq:
    """两层规划保留全部四组字段；三层均显式填写 RAM 窗口。"""
    data["ram_observations"] = []
    if name == "task":
        data["history"] = [
            {**entry, "observations": [], "outcome": None} for entry in data["history"]
        ]
    if name != "task":
        data.update(
            latest_planning={
                "new_items": [
                    {
                        "goal": "读取完整结果",
                        "success_criteria": "取得完整原文",
                        "budget": {"limit": 2, "unit": "actions" if name == "episode" else "tasks"},
                    }
                ],
                "updates": [{"index": 0, "status": "pending", "note": "规划更新全文"}],
                "execution_order": ["existing:0", "new:0"],
                "why": "最新规划理由全文",
            },
            trigger="after_child",
            planning_round=2,
        )
    if name == "run":
        data["ram_observations"] = [reading(i).model_dump(mode="json") for i in range(1, 6)]
    return FromHarnessToBrainToolJudgeReq.model_validate(data)


def params() -> dict[str, JudgeParams]:
    """经生产 tool 边界转成 prompt 的独立参数。"""
    return {name: judge_prompt_params(request) for name, request in requests().items()}
