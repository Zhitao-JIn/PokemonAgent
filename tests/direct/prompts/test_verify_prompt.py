"""verify 两级标记（0923 192）的信封与 prompt 契约。

verify 是标记器不是审判官：entries 收 ActMemory（task 层）或 TaskMemory
（episode 层），判定字段是 `positive`（正/负样本），不是"可信度"。
"""

from __future__ import annotations

from pokemon_agent.brain import VerifyVerdict
from pokemon_agent.direct.prompts import verify as verify_prompt
from pokemon_agent.schemas.harness import FromHarnessToBrainToolVerifyReq
from pokemon_agent.schemas.memory import ActMemory, TaskMemory


def _task_memory(i: int) -> TaskMemory:
    return TaskMemory(
        run_id="r1",
        episode_id="r1-ep1",
        task_id=f"t{i}",
        goal="向北走一步",
        termination="goal_done",
        reason="chain_done",
        steps_used=2,
        total_acts=i * 2,
        summary="按了 up，位置北移一格",
        quality_score=0.9,
        quality_rationale="前后帧一致",
    )


def test_verify_req_accepts_task_memories() -> None:
    """episode 层：TaskMemory 装进同一个信封（一次只装一种素材）。"""
    req = FromHarnessToBrainToolVerifyReq(
        entries=[_task_memory(0), _task_memory(1)], goal="走到地图北端"
    )
    assert len(req.entries) == 2
    assert all(isinstance(e, TaskMemory) for e in req.entries)


def test_verify_verdict_marks_positive_not_reliability() -> None:
    """判定值对象：`positive` 布尔位 + `why`。"""
    v = VerifyVerdict(index=0, positive=False, why="方向背离目标")
    assert v.positive is False


def test_build_prompt_renders_task_memories_with_indices() -> None:
    """episode 层 prompt：TaskMemory 逐条渲 `## 第 i 条`，goal 原样进模板。"""
    req = FromHarnessToBrainToolVerifyReq(entries=[_task_memory(0)], goal="走到地图北端")
    prompt = verify_prompt.build_prompt(req)
    assert "## 第 0 条" in prompt
    assert "task `t0`" in prompt
    assert "走到地图北端" in prompt
    assert "positive" in prompt  # 输出格式要求正/负样本位
    assert "reliable" not in prompt


def test_build_prompt_still_renders_act_memories_via_sequence() -> None:
    """task 层 prompt：ActMemory 走 render_sequence（相邻快照去重），编号对齐。"""
    act = ActMemory(
        run_id="r1",
        episode_id="r1-ep1",
        step=0,
        action="up",
        before={"step": 0, "status": "站立", "map_id": 12},
        after={"step": 1, "status": "站立", "map_id": 12},
    )
    req = FromHarnessToBrainToolVerifyReq(entries=[act], goal="向北走一步")
    prompt = verify_prompt.build_prompt(req)
    assert "## 第 0 条" in prompt
    assert "up" in prompt
    assert "positive" in prompt
