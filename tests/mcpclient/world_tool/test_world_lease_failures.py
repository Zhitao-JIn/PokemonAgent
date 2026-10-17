"""租约拒绝必须报错；持有者释放后另一个客户端才能推进世界。"""

from pathlib import Path
from typing import Any

import pytest

from pokemon_agent.brain.interface import Action, ActionSegment, Task
from pokemon_agent.mcpclient.client import McpToolError
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolResetReq,
)


@pytest.mark.parametrize("operation", ["reset", "load_state", "press", "execute", "release_lease"])
def test_other_client_cannot_silently_succeed_while_world_is_leased(
    tool: WorldMcpTool, client: Any, world: Any, tmp_path: Path, operation: str
) -> None:
    request = FromHarnessToGameToolResetReq(
        task=Task(task_id="t1", goal="g", success_criteria="c", max_steps=10)
    )
    tool.reset(request)
    other = WorldMcpTool(client, client_id="other-process")
    path = tmp_path / "start.state"
    path.write_bytes(b"OTHER")
    calls_before = list(world.calls)

    with pytest.raises(McpToolError, match="rejected"):
        if operation == "reset":
            other.reset(request)
        elif operation == "load_state":
            other.load_state(FromHarnessToGameToolLoadStateReq(path=str(path)))
        elif operation == "press":
            other.press([("up", 1)])
        elif operation == "execute":
            other.execute(
                FromHarnessToGameToolExecuteReq(
                    action=Action(sequence=[ActionSegment(name="up", times=1)]),
                    observation=world.perceive_task().observation,
                )
            )
        else:
            other.release_lease()

    assert world.calls == calls_before
    tool.release_lease()
    other.reset(request)
    assert world.calls[-1][0] == "reset"
