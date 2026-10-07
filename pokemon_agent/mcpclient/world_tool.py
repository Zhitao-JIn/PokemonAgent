"""`GameToolPort` 的 MCP 远程门面：世界住在另一个进程时，harness 侧拿到的还是
同一张口。

**信封翻译在这里，判定不在**：`Task` → 裸字段、`Perceived` → 信封、存档的
base64 ↔ 文件、感知的重试循环——全是原 `mcpclient/game_tools.py` 的职责，随迁到
这一层（mcpclient 带逻辑属性，2026-09-29 定案）。server 只做 `WorldPort` 的
直译，一点领域判断都没有。

**已知缺口**（刻意不在这里打补丁）：
- **`evolve`**：无输入推进。当前全仓零调用方（只有 `GameTools.evolve` 自己），
  7 条原子里没有它，故 MCP 面不提供。
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from pokemon_agent.backoff import backoff_seconds
from pokemon_agent.config import PERCEPTION_MAX_RETRIES
from pokemon_agent.mcpclient.client import McpClient, McpToolError
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolExecuteResp,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolPerceiveOnceResp,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSaveStateResp,
    ModelCall,
    ModelCallLog,
)
from pokemon_agent.world import ActionSpace


def _last_error(calls: list[ModelCall]) -> str:
    """最后一次尝试的失败信息折成一句话（与 `game_tools._last_error` 同形）。"""
    if not calls:
        return "no attempts recorded"
    last = calls[-1]
    return f"{last.error_kind}: {last.error}"


class WorldMcpTool:
    """经 MCP 调 world server 的世界门面（`GameToolPort` 的远程实现）。

    `client_id`：单实例租约的身份。MCP 是无身份的（同一个端点谁都能连），
    所以推进者必须自报是谁——**一个进程一个 id**（缺省 `harness-<pid>`），
    同一时刻只允许一个推进者。
    """

    def __init__(self, client: McpClient, client_id: str | None = None) -> None:
        self._client = client
        self._client_id = client_id or f"harness-{__import__('os').getpid()}"

    @property
    def client_id(self) -> str:
        """租约身份（换客户端跑之前要 `release_lease()`）。"""
        return self._client_id

    def release_lease(self) -> None:
        """归还租约，让另一个客户端能接管这个世界。"""
        self._client.call_tool_sync("release_lease", {"client_id": self._client_id})

    # ---- GameToolPort ----

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """开新一局：`Task` 拆成裸字段（world 不认识 brain 的类型）。"""
        task = req.task
        self._client.call_tool_sync(
            "reset",
            {
                "task_id": task.task_id,
                "goal": task.goal,
                "success_criteria": task.success_criteria,
                "max_steps": task.max_steps,
                "initial_state_hint": task.initial_state_hint,
                "client_id": self._client_id,
            },
        )

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """取能力掩码——**由 server 按它自己那一帧算**（tool 层在另一个进程，
        没有帧）。

        `req.observation` 在这里只作**一致性前提**：调用方交出它据以决策的那份
        观测，两次调用之间没有 step（server 同步单 client），所以两边算出的掩码
        必然是同一份；server 那一份是真相。
        """
        assert req.observation is not None, "get_action_space() needs the observation in question"
        body = self._client.call_tool_sync("get_action_space", {})
        return FromHarnessToGameToolGetActionSpaceResp(
            action_space=ActionSpace.model_validate(body["data"])
        )

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        """task 层一帧（不调模型）。观测是 Pydantic，跨进程走 JSON 再验回。"""
        body = self._client.call_tool_sync("perceive_task", {})
        from pokemon_agent.world import TaskObservation

        return FromHarnessToGameToolPerceiveTaskResp(
            observation=TaskObservation.model_validate(body["data"]["observation"]),
            frame_png=body["data"].get("frame_png", ""),
            ram=body["data"].get("ram"),
        )

    def perceive_with_retry(self) -> tuple[FromHarnessToGameToolPerceiveOnceResp, ModelCallLog]:
        """视觉档感知：**重试循环在 client 这一侧**（与 `GameTools` 同预算、
        同退避、同翻译）。

        为什么循环在这：只有循环控制者知道试了几次、还剩几次预算、耗尽之后
        这个节点怎么收场——这与 brain 六链路把循环收在 tool 层是同一条判据。
        server 只负责"问一次、不问成就报 `perception_failed`"。
        """
        from pokemon_agent.errors import MaxRetriesExceeded

        log: ModelCallLog = []
        for nth in range(1, PERCEPTION_MAX_RETRIES + 1):
            body = self._client.call_tool_sync("perceive_once", {})
            if not body["ok"]:
                payload: dict[str, Any] = {"error": body.get("error") or body["code"]}
                # server 侧的世界词汇不跨进程，这里只认得出"这次没读出"与
                # 4xx（重试注定无用）——与 `game_tools` 从异常名前缀还原同判据。
                text = str(body.get("error", ""))
                kind = text.split(":", 1)[0].strip() or "PerceptionParseFailure"
                log.append(ModelCall(payload=payload, error_kind=kind, error=text))
                if kind == "ProviderRejected":
                    raise MaxRetriesExceeded(len(log), _last_error(log), log, source="sense")
                if nth < PERCEPTION_MAX_RETRIES:
                    timeouts = sum(c.error_kind == "ToolTimeout" for c in log)
                    time.sleep(backoff_seconds(kind == "ToolTimeout", timeouts))
                continue

            calls = body["data"].get("calls") or []
            log.extend(ModelCall(payload=call) for call in calls)
            from pokemon_agent.world import Observation

            observation = body["data"].get("observation")
            return (
                FromHarnessToGameToolPerceiveOnceResp(
                    observation=Observation.model_validate(observation)
                    if observation is not None
                    else None,
                    calls=calls,
                    frame_png=body["data"].get("frame_png", ""),
                    ram=body["data"].get("ram"),
                ),
                log,
            )

        raise MaxRetriesExceeded(PERCEPTION_MAX_RETRIES, _last_error(log), log, source="sense")

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> FromHarnessToGameToolExecuteResp:
        """执行**一个键或一条脚本**：键走 `step`（唯一按键执行口），脚本走同名 tool。

        脚本动作 = `call_tool_sync(脚本名, args + client_id)`——脚本 tool 的返回
        形状就是终态报告（`{ok, code, data, events, calls}`），原样进 `resp.report`
        （与进程内 `_run_script_report` 的折法逐字段一致）。

        所有公开脚本走同名 tool；内部 shop_buy/shop_sell 由买卖脚本组合调用。
        """
        action = req.action
        if action.script is not None:
            body = self._client.call_tool_sync(
                action.script.name,
                {**action.script.args, "client_id": self._client_id},
            )
            return FromHarnessToGameToolExecuteResp(
                report={**body["data"], "events": body.get("events", [])}
            )
        assert len(action.sequence) == 1, "execute() 只接受单键动作"
        segment = action.sequence[0]
        self._client.call_tool_sync(
            "step",
            {
                "segments": [[segment.name, segment.times]],
                "settle": req.settle,
                "client_id": self._client_id,
            },
        )
        return FromHarnessToGameToolExecuteResp()

    def save_state(
        self, req: FromHarnessToGameToolSaveStateReq
    ) -> FromHarnessToGameToolSaveStateResp:
        """server 给 base64，**落盘在 client 这一侧**（路径是 client 的盘）。"""
        body = self._client.call_tool_sync("save_state", {})
        data = base64.b64decode(body["data"]["state_base64"])
        path = Path(req.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        assert path.stat().st_size == len(data) > 0
        return FromHarnessToGameToolSaveStateResp(path=str(path), size=len(data))

    def load_state(self, req: FromHarnessToGameToolLoadStateReq) -> None:
        """读盘在 client，字节过 MCP 交给 server 恢复。"""
        self._client.call_tool_sync(
            "load_state",
            {
                "state_base64": base64.b64encode(Path(req.path).read_bytes()).decode("ascii"),
                "client_id": self._client_id,
            },
        )

    def evolve(self, req: Any) -> None:  # noqa: ANN401
        """无输入推进：MCP 面不提供（7 条原子里没有它，当前零调用方）。"""
        raise McpToolError("MCP 模式下不提供 evolve（无输入推进）：当前全仓零调用方")
