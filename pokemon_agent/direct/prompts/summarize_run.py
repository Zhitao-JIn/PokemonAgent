"""run 蒸馏的素材渲染：最终目标表与全部局记忆。"""

from pokemon_agent.schemas.harness import FromHarnessToBrainToolSummarizeRunReq

from . import load

_TEMPLATE = load("summarize_run")


def history_blocks(req: FromHarnessToBrainToolSummarizeRunReq) -> list[str]:
    """按执行序渲染每局完整记忆；代表帧不进入文本。"""
    return [memory.render() for memory in req.episode_memories]


def build_prompt(req: FromHarnessToBrainToolSummarizeRunReq) -> str:
    """以最终目标表定案为准拼出 run 复盘请求；调用方保证局记忆非空。"""
    assert req.episode_memories, "run summary needs episode memories"
    goals = "\n".join(
        f"- {entry.task.task_id}｜{entry.task.goal}｜{entry.status.value}｜"
        f"note={entry.note}｜overturned={str(entry.overturned).lower()}"
        for entry in req.goals
    )
    return _TEMPLATE.render(
        run_goal=req.run_goal,
        termination=req.termination.value,
        judge_reason=req.judge_reason or "（无）",
        episodes=req.episodes,
        succeeded=req.succeeded,
        acts_used=req.acts_used,
        max_episodes=req.max_episodes,
        goals=goals or "（无目标条目）",
        episodes_text="\n\n".join(history_blocks(req)),
    )
