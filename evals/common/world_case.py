"""world_script_execute 与冻结帧采集共用的世界装配，只经 MCP。"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from evals.paths import REPO_ROOT
from pokemon_agent.brain import Task
from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.mcpclient import McpTransportError, assert_mcp_server_ready
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.schemas.harness import FromHarnessToGameToolResetReq
from pokemon_agent.world import RamReadout, TaskObservation

ROM = REPO_ROOT / "assets" / "rom"


def world_url() -> str:
    """读 MCP_WORLD_SERVER_URL 并探活 world server，返回地址。

    失败：未配地址或地址不可达时抛 McpTransportError；评测 solver 会自动启动服务，
    若 `MCP_WORLD_SERVER_URL` 已设置则复用它（调试用）。
    """
    load_env_file()
    url = env_str("MCP_WORLD_SERVER_URL")
    if not url:
        raise McpTransportError(
            "评测脚本会启动 world server；若 MCP_WORLD_SERVER_URL 已设置则复用该服务"
        )
    assert_mcp_server_ready(url, "world")
    return url


def start_world(state: Path, pre: Sequence[str], *, case_id: str) -> WorldMcpTool:
    """从调用方给定的完整存档路径起 world，并按完开跑前的键。

    前置条件：存档存在（缺了 use_start_state 读文件时当场炸——基础设施故障，交 inspect 记
    sample error，不进分母）。
    后置条件：返回的 world 已 reset，调用方用完负责 stop_world。
    """
    os.environ.setdefault("MCP_WORLD_CLIENT_ID", "eval")
    world = WorldMcpTool.build(world_server_url=world_url())
    world.use_start_state(state)
    world.reset(
        FromHarnessToGameToolResetReq(
            task=Task(task_id=case_id, goal="world 用例测评", success_criteria="-", max_steps=1)
        )
    )
    for key in pre:
        world.press([(key, 1)], settle=True)
    return world


def read_frame(world: WorldMcpTool) -> tuple[TaskObservation, RamReadout]:
    """读一帧 task 档观测与内存读数（不调模型）。

    后置条件：内存读数非空（task 档感知恒读内存）。
    """
    perceived = world.perceive_task()
    assert perceived.ram is not None, "task 档感知必带内存读数"
    return perceived.observation, perceived.ram


def stop_world(world: WorldMcpTool) -> None:
    """归还租约，让下一个用例能继续推进同一个 world server。"""
    world.release_lease()


__all__ = ["ROM", "read_frame", "start_world", "stop_world", "world_url"]
