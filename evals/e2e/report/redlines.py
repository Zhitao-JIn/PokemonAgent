"""红线（`docs/eval/spec.md` §七，S4）：命中任一条样本即判负，不参与加权。

- R1 出错：run 以 `termination=error` 收尾，或出现 `run_error` / `episode_error`。停摆不算。
- R2 刹车失灵：一局里连续失败的 task 已达 `EPISODE_STALL_LIMIT` 却还在派 task；run 层同理
  （连续失败的局已达 `RUN_STALL_LIMIT` 却还在开局）。成功清零；被打断（`interrupted`）不计入连击。
- R3 谎报成功：run 以 `goal_done` 收尾，但样本目标的机械判据为 fail。
"""

from __future__ import annotations

from evals.e2e.checks import RunStream
from evals.e2e.schemas import CheckVerdict, RedLineHit
from pokemon_agent.config import EPISODE_STALL_LIMIT, RUN_STALL_LIMIT
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.tools.trace import ParsedEvent
from pokemon_agent.tools.trace.content import EpisodeEndContent, TaskEndContent

_DONE = "goal_done"
_NOT_COUNTED = "interrupted"


def red_lines(stream: RunStream, verdict: CheckVerdict) -> list[RedLineHit]:
    """三条红线逐条核，返回命中的。"""
    hits = [_r1(stream), _r2_episode(stream), _r2_run(stream), _r3(stream, verdict)]
    return [h for h in hits if h is not None]


def _r1(stream: RunStream) -> RedLineHit | None:
    """出错。"""
    errors = stream.of_kind(TraceKind.RUN_ERROR, TraceKind.EPISODE_ERROR)
    end = stream.run_end()
    if errors:
        return RedLineHit(
            line_id="R1", evidence=[e.uuid for e in errors], reason="出现了异常收尾账"
        )
    if end is not None and end.termination == "error":
        return RedLineHit(line_id="R1", reason="run 以 error 收尾")
    return None


def _r2_episode(stream: RunStream) -> RedLineHit | None:
    """episode 层刹车失灵：连击达上限后同一局里又开了 task。"""
    streak: dict[str, int] = {}
    for e in stream.of_kind(TraceKind.TASK_START, TraceKind.TASK_END):
        episode = e.meta.episode_id
        if e.kind == TraceKind.TASK_START:
            if streak.get(episode, 0) >= EPISODE_STALL_LIMIT:
                return RedLineHit(
                    line_id="R2",
                    evidence=[e.uuid],
                    reason=f"{episode} 连续失败 {streak[episode]} 个 task 后仍在派 task",
                )
            continue
        streak[episode] = _next_streak(streak.get(episode, 0), e)
    return None


def _r2_run(stream: RunStream) -> RedLineHit | None:
    """run 层刹车失灵：连续失败的局达上限后又开了局。"""
    streak = 0
    for e in stream.of_kind(TraceKind.EPISODE_START, TraceKind.EPISODE_END):
        if e.kind == TraceKind.EPISODE_START:
            if streak >= RUN_STALL_LIMIT:
                return RedLineHit(
                    line_id="R2", evidence=[e.uuid], reason=f"连续失败 {streak} 局后仍在开局"
                )
            continue
        assert isinstance(e.content, EpisodeEndContent)
        streak = 0 if e.content.termination == _DONE else streak + 1
    return None


def _next_streak(current: int, end: ParsedEvent) -> int:
    """一个 task 收尾后的失败连击。"""
    assert isinstance(end.content, TaskEndContent)
    if end.content.termination == _DONE:
        return 0
    if end.content.termination == _NOT_COUNTED:
        return current
    return current + 1


def _r3(stream: RunStream, verdict: CheckVerdict) -> RedLineHit | None:
    """谎报成功。"""
    end = stream.run_end()
    if end is not None and end.termination == _DONE and verdict.outcome == "fail":
        return RedLineHit(
            line_id="R3", evidence=verdict.evidence, reason=f"run 判成，机械判负：{verdict.reason}"
        )
    return None


__all__ = ["red_lines"]
