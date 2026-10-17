"""`GameToolPort` 的 MCP 远程门面：世界住在另一个进程时，harness 侧拿到的还是
同一张口。

**信封翻译在这里，判定不在**：`Task` → 裸字段、`TaskPerceived` → 信封、存档的
base64 ↔ 文件——由门面负责。server 只做 `WorldPort` 的
直译，一点领域判断都没有。

**已知缺口**（刻意不在这里打补丁）：
- **`evolve`**：无输入推进。当前全仓零调用方，
  7 条原子里没有它，故 MCP 面不提供。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from pokemon_agent.mcpclient.action_space import action_space_for, with_prompt_text
from pokemon_agent.mcpclient.client import McpClient, McpToolError
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolExecuteResp,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSaveStateResp,
)
from pokemon_agent.world import ActionSpace
from pokemon_agent.world.action_space import ALL_BUTTONS


class WorldMcpTool:
    """经 MCP 调 world server 的世界门面（`GameToolPort` 的远程实现）。

    `client_id`：单实例租约的身份。MCP 是无身份的（同一个端点谁都能连），
    所以推进者必须自报是谁——**一个进程一个 id**（缺省 `harness-<pid>`），
    同一时刻只允许一个推进者。
    """

    def __init__(self, client: McpClient, client_id: str | None = None) -> None:
        self._client = client
        self._client_id = client_id or f"harness-{__import__('os').getpid()}"

    @classmethod
    def build(cls, *, world_server_url: str, client_id: str | None = None) -> WorldMcpTool:
        """连接 world server；空地址抛 ValueError，传输失败向上传递。

        调用方提供非空地址；启动客户端并保留租约身份，不探活。
        /health 由装配点在 run 开始前检查。
        """
        if not world_server_url.strip():
            raise ValueError("world 只经 MCP：请设置 MCP_WORLD_SERVER_URL")

        from pokemon_agent.mcpclient.client import McpClient, mcp_endpoint

        client = McpClient(mcp_endpoint(world_server_url))
        client.start()
        return cls(client, client_id=client_id)

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

        `req.observation` 是调用方据以决策的观测，也用于补充静态 prompt 文案。
        两次调用之间没有 step（server 同步单 client），两边掩码一致；server 那份是真相。
        返回值保留 server 掩码，只补按键说明、连按用法与地图规则。
        """
        assert req.observation is not None, "get_action_space() needs the observation in question"
        body = self._client.call_tool_sync("get_action_space", {})
        return FromHarnessToGameToolGetActionSpaceResp(
            action_space=with_prompt_text(ActionSpace.model_validate(body["data"]), req.observation)
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

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> FromHarnessToGameToolExecuteResp:
        """执行单键或脚本，键走 step、脚本走同名 tool。

        前置条件：动作在 req.observation 的空间内；键为单键，脚本条目 enabled。
        违约在任何 MCP 调用前断言失败；传输错误向上传递。
        后置条件：键响应保留本键裸事件（缺失或 null 为 None），脚本响应保留终态报告。
        所有公开脚本走同名 tool；内部 shop_buy/shop_sell 由买卖脚本组合调用。
        """
        action = req.action
        space = action_space_for(req.observation, list(ALL_BUTTONS))
        if action.script is not None:
            script_names = [e.name for e in space.entries if e.kind == "script"]
            entry = space.entry(action.script.name)
            assert entry is not None and entry.kind == "script" and space.enabled(entry.name), (
                f"execute() got script {action.script.name!r} outside {script_names}"
            )
            body = self._client.call_tool_sync(
                action.script.name,
                {**action.script.args, "client_id": self._client_id},
            )
            return FromHarnessToGameToolExecuteResp(
                report={**body["data"], "events": body.get("events", [])}
            )
        assert len(action.sequence) == 1, (
            "execute() 只接受单键动作；连按应由 Harness 的循环展开成多步"
        )
        segment = action.sequence[0]
        assert space.contains(segment.name), f"execute() got {segment.name!r} outside {space.names}"
        body = self._client.call_tool_sync(
            "step",
            {
                "segments": [[segment.name, segment.times]],
                "settle": req.settle,
                "client_id": self._client_id,
            },
        )
        return FromHarnessToGameToolExecuteResp(event=body["data"].get("event"))

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
