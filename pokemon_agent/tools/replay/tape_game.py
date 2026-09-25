"""`TapeGame`：回放段里顶替游戏门面——观测取自磁带，按键不动模拟器。

模拟器只在切换那一刻读目标 task 的开局世界快照（由恢复路径的切换钩子做），回放段里不重演：
世界里有随机事件，重演不可靠（intent C8）。按键对不对，由 `TapeTrace` 核 `press_key` 那笔账。

动作空间照常由真件算：它是观测的纯函数（按 overlay 掩码、配上静态的按键说明与读图提示，
不碰模拟器），账上只记了按键名——算出来之后核一遍名字与录下的相同。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolPerceiveOnceResp,
    ModelCallLog,
)
from pokemon_agent.tools.interface import GameToolPort
from pokemon_agent.world import Observation

from .tape import Tape, event_content

_SENSE_LINK = "sense"


class TapeGame:
    """`GameToolPort` 的回放版。切换前取磁带、切换后原样转给真件；其余方法一律转给真件。"""

    def __init__(self, real: GameToolPort, tape: Tape) -> None:
        self._real = real
        self._tape = tape

    def perceive_with_retry(
        self, *, ram_only: bool = False
    ) -> tuple[FromHarnessToGameToolPerceiveOnceResp, ModelCallLog]:
        """切换前：下一条 `sense_frame` 还原成观测；录下的是感知耗尽就照样抛出。"""
        if self._tape.switched:
            return self._real.perceive_with_retry(ram_only=ram_only)
        event = self._tape.peek({"sense_frame", "call_exhausted"})
        calls = self._tape.perception_calls_before(event)
        body = event_content(event)
        if event.kind == "call_exhausted":
            assert body.get("link") == _SENSE_LINK, f"磁带上下一条是 {body} 的耗尽，不是感知"
            raise MaxRetriesExceeded(len(calls), "录下的感知耗尽", calls, source=_SENSE_LINK)
        observation = Observation.model_validate(
            {
                "step": 0,
                "status": body["status"],
                "facts": body["facts"],
                "done": body["done"] == "true",
                "perceived": body["perceived"] == "true",
                "place": body.get("place"),
            }
        )
        resp = FromHarnessToGameToolPerceiveOnceResp(
            observation=observation,
            calls=[dict(c.payload) for c in calls],
            frame_png=body.get("frame", ""),
        )
        return resp, calls

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """由真件按观测算（纯函数），切换前再核按键名与下一条 `get_action_space` 账相同。"""
        resp = self._real.get_action_space(req)
        if not self._tape.switched:
            recorded = event_content(self._tape.peek({"get_action_space"}))["names"]
            if resp.action_space.names != recorded:
                raise self._tape.diverge(
                    f"回放分叉：动作空间应为 {recorded}，实为 {resp.action_space.names}"
                )
        return resp

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> None:
        """切换前：不动模拟器（这一键对不对由 `press_key` 那笔账核）。"""
        if self._tape.switched:
            self._real.execute(req)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 —— reset / 存读档等照转真件
        return getattr(self._real, name)


__all__ = ["TapeGame"]
