"""判定请求的 RAM 模型在 tool 边界转成 prompt 自有的文字契约。"""

from pokemon_agent.prompt import JudgeParams, RamObservationRecord
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq


def judge_prompt_params(request: FromHarnessToBrainToolJudgeReq) -> JudgeParams:
    """保留原判定素材，RAM 只序列化一次；空表不虚构任何观测。"""
    data = request.model_dump(mode="json")
    data["ram_observations"] = [
        RamObservationRecord(
            event_id=entry.event_id,
            source=entry.source,
            episode_id=entry.episode_id,
            task_id=entry.task_id,
            step=entry.step,
            observed_at=entry.observed_at,
            sequence=entry.sequence,
            ram_json=entry.ram.model_dump_json(),
        )
        for entry in request.ram_observations
    ]
    return JudgeParams.model_validate(data)
