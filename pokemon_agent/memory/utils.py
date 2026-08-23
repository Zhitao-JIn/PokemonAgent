from typing import List, Dict, Any

from pokemon_agent.schemas.memory_episode_summary import EpisodeStep
from pokemon_agent.schemas.memory_episodic import MemoryEntry


def _get_episode_memories(
    memory_entries: List[MemoryEntry],
    episode_id: str
) -> List[MemoryEntry]:
    """获取特定episode的所有基础记忆条目"""
    return [m for m in memory_entries if m.episode_id == episode_id]


def _memory_entry_to_episode_steps(
    entries: List[MemoryEntry]
) -> List[EpisodeStep]:
    """将MemoryEntry列表转换为EpisodeStep结构"""
    steps = []
    for i, entry in enumerate(entries, 1):
        # 从MemoryEntry中提取关键信息
        # 这里应该是更复杂的解析逻辑，但作为基础实现
        content_lines = entry.content.split('\n')
        thought = ""
        action = ""
        result_summary = ""
        scene = "unknown"

        for line in content_lines:
            if "**思考**" in line:
                thought = line.split(":", 1)[1].strip()
            elif "**动作**" in line:
                action = line.split(":", 1)[1].strip().split(" ×")[0]
            elif "**结果**" in line:
                result_summary = line.split(":", 1)[1].strip()
            elif "**场景**" in line:
                scene = line.split(":", 1)[1].strip()

        steps.append(EpisodeStep(
            thought=thought or "无思考过程",
            action=action or "UNKNOWN",
            action_times=1,
            result_summary=result_summary or "无结果",
            scene=scene,
            step_number=i
        ))
    return steps


def _create_memory_entry(
    episode_id: str,
    run_id: str,
    goal: str,
    outcome: Dict[str, Any],
    response: Dict[str, Any]
) -> MemoryEntry:
    """从LLM响应创建MemoryEntry对象"""
    content = f"""# 情景记忆: {goal}

**总结**
{response.get('summary', '')}

**可重用经验**
{'- ' + '\n- '.join(response.get('reusable_patterns', [])) if response.get('reusable_patterns') else '暂无'}

**关键决策**
{'- ' + '\n- '.join(response.get('critical_decisions', [])) if response.get('critical_decisions') else '暂无'}

**潜在问题**
{'- ' + '\n- '.join(response.get('failure_points', [])) if response.get('failure_points') else '暂无'}"""

    quality_score = response.get('quality', {}).get('score', 0.5)
    quality_score = max(0.0, min(1.0, quality_score))

    return MemoryEntry(
        id=f"epsum-{episode_id}",
        episode_id=episode_id,
        timestamp="2026-08-23T15:30:00",  # 实际应为 datetime.now().isoformat()
        content=content,
        tags=response.get('tags', []),
        rationale=response.get('rationale', '情景记忆生成'),
        quality=quality_score,
        metadata={
            "run_id": run_id,
            "goal": goal,
            "success": outcome.get("success", False),
            "steps": outcome.get("steps", 0),
            "max_steps": outcome.get("max_steps", 0),
            "applicable_scenes": response.get('applicable_scenes', []),
            "memory_quality": _get_quality_level(quality_score)
        }
    )


def _get_quality_level(score: float) -> str:
    """根据评分获取质量等级"""
    if score >= 0.85:
        return "EXCELLENT"
    elif score >= 0.7:
        return "GOOD"
    elif score >= 0.5:
        return "FAIR"
    elif score >= 0.3:
        return "POOR"
    else:
        return "UNRELIABLE"