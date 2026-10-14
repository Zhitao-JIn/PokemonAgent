"""P5 统一能力掩码选动作：脚本条目进掩码、chooser 解析、act 分流与 act_call 两形。

**对得上谁**：PLAN_mcp_servers P5 验证清单——
- chooser 解析：动作名解析 / 越权（掩码外）拒绝 / 脚本 args 校验；
- act_call 两形 content（key / script）；
- 掩码：`compute_action_space` 按场合给脚本条目（walk 全量 / dialog 两条 / 其余零）；
- e2e：模型选脚本 → MCP 通道 `WorldMcpTool.execute` → server 脚本 tool → 终态报告
  （in-memory transport 直连 server 实例，不起端口）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from _doubles.world_console import StubConsole

from pokemon_agent.brain.brain import Brain
from pokemon_agent.brain.errors import IllegalAction, ParseFailure
from pokemon_agent.brain.interface import (
    Action,
    ActionSegment,
    ScriptArg,
    ScriptCall,
    ScriptSignature,
)
from pokemon_agent.direct.brain_tool import Chooser
from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.action_space import compute_action_space
from pokemon_agent.world.scripts.catalog import SCRIPT_SPECS, run_script_by_name, script_entries
from pokemon_agent.world.scripts.scenes import SCRIPT_DEFINITIONS

FIELD_SCRIPTS = set(SCRIPT_SPECS) - set(SCRIPT_DEFINITIONS) - {"buy_item", "sell_item"}

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


def _obs(scene: TaskScene) -> TaskObservation:
    return TaskObservation(
        step=0, status="s", scene=scene, place=PlaceInWorld(map_id=12, x=13, y=8)
    )


# ---- 1. 目录与场合可用性 ----


def test_catalog_has_fourteen_regular_scripts_plus_takeover_scripts() -> None:
    assert len(SCRIPT_SPECS) == 14 + len(SCRIPT_DEFINITIONS)


def test_walk_scene_gets_every_field_script() -> None:
    assert {e.name for e in script_entries("walk")} == FIELD_SCRIPTS


def test_shop_scene_gets_checked_buy_sell_and_quit() -> None:
    assert {e.name for e in script_entries("shop_items")} == {"buy_item", "sell_item", "shop_quit"}


def test_dialog_scene_gets_only_dialog_scripts() -> None:
    assert {e.name for e in script_entries("dialog")} == {
        "advance_dialog",
        "wait_until_scene",
    }


def test_battle_scene_gets_no_scripts() -> None:
    assert script_entries("battle") == []


# ---- 2. 掩码：脚本条目进 mask/entries ----


def test_action_space_walk_includes_scripts_in_mask() -> None:
    space = compute_action_space(_obs(TaskScene.WALK), ALL_BUTTONS)
    for name in FIELD_SCRIPTS:
        assert space.enabled(name), f"{name} 应在 walk 场合可用"
        entry = space.entry(name)
        assert entry is not None and entry.kind == "script"
    assert space.enabled("a")  # 键照常


def test_action_space_takeover_scene_keeps_directions_with_its_takeover_scripts() -> None:
    space = compute_action_space(_obs(TaskScene.PARTY), ALL_BUTTONS)
    assert set(space.names) == {"up", "down", "left", "right", "a", "b"}
    scripts = [entry for entry in space.entries if entry.kind == "script"]
    assert scripts
    assert all(entry.name.startswith("party_") and space.enabled(entry.name) for entry in scripts)
    assert space.enabled("a") and space.enabled("b")
    assert not space.enabled("start") and not space.enabled("select")


# ---- 3. chooser 解析：脚本名 + args ----

_SCRIPT_SIGS = [
    ScriptSignature(
        name="walk_to",
        params=[
            ScriptArg(name="x", type="int", required=True),
            ScriptArg(name="y", type="int", required=True),
        ],
    )
]


def _brain() -> Brain:
    return Brain.__new__(Brain)  # _parse 不碰 provider，绕过 __init__


def test_parse_script_action_with_args() -> None:
    action = _brain()._parse(
        '{"action": "walk_to", "args": {"x": 5, "y": 2}}', ["a", "up"], _SCRIPT_SIGS
    )
    assert action.script is not None and action.script.name == "walk_to"
    assert action.script.args == {"x": 5, "y": 2}
    assert action.describe() == "script:walk_to(x=5, y=2)"


def test_choose_accepts_flat_script_parameters_through_the_public_brain_port() -> None:
    from pokemon_agent.brain.schemas import LlmCompleteReq, LlmCompleteResp

    class FlatScriptProvider:
        """固定回答的文本 provider，不调用外部模型。"""

        def complete(self, request: LlmCompleteReq) -> LlmCompleteResp:
            return LlmCompleteResp(text='{"action": "walk_to", "x": 5, "y": 2}')

    brain = Brain(decide_llm=FlatScriptProvider())

    result = brain.choose(prompt="选择一条允许的脚本", keys=[], scripts=_SCRIPT_SIGS)

    assert result.action.script is not None
    assert result.action.script.name == "walk_to"
    assert result.action.script.args == {"x": 5, "y": 2}
    assert len(result.calls) == 1


def test_parse_script_missing_required_arg_is_parse_failure() -> None:
    with pytest.raises(ParseFailure):
        _brain()._parse('{"action": "walk_to", "args": {"x": 5}}', ["a", "up"], _SCRIPT_SIGS)


def test_parse_unknown_name_lists_scripts_in_illegal() -> None:
    with pytest.raises(IllegalAction) as exc:
        _brain()._parse('{"action": "nope"}', ["a", "up"], _SCRIPT_SIGS)
    assert "walk_to" in exc.value.allowed  # 脚本名在"当时允许"清单里


def test_parse_still_prefers_keys_over_scripts() -> None:
    action = _brain()._parse('{"action": "up"}', ["a", "up"], _SCRIPT_SIGS)
    assert action.sequence and action.script is None


# ---- 4. chooser normalize：脚本原样放行 ----


def test_normalize_passes_script_through() -> None:
    chooser = Chooser(None)  # type: ignore[arg-type] — _normalize 不碰 brain
    action = Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2}))
    assert chooser._normalize(action) is action


# ---- 5. act_call 渲染两形 ----


def _trace_req(action: Action, report: dict[str, Any] | None = None):
    from pokemon_agent.direct.trace import render
    from pokemon_agent.schemas.harness import (
        FromHarnessToTraceToolAppendReq,
        TraceKind,
    )

    return render, FromHarnessToTraceToolAppendReq(
        kind=TraceKind.ACT_CALL,
        meta={
            "run_id": "r",
            "branch": "main",
            "source": "act",
            "episode_id": "ep",
            "task_id": "t",
            "step": 1,
        },
        action=action,
        report=report,
    )


def test_act_call_script_form_carries_report() -> None:
    from pokemon_agent.brain.interface import ScriptCall

    render, req = _trace_req(
        Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2})),
        report={
            "ok": True,
            "code": "ok",
            "data": {"final_pos": {"x": 5, "y": 2}},
            "events": [],
            "calls": [],
        },
    )
    rendered = render.act_call(req)
    assert rendered.kind == "act_call"
    assert rendered.content["script"] == "walk_to"
    assert rendered.content["args"] == {"x": 5, "y": 2}
    assert rendered.content["ok"] == "true"  # 账本布尔 = 小写字符串
    assert rendered.content["code"] == "ok"
    assert "sequence" not in rendered.content


def test_act_call_key_form_unchanged() -> None:
    render, req = _trace_req(Action(sequence=[ActionSegment(name="up")]))
    rendered = render.act_call(req)
    assert rendered.content["sequence"] == [{"name": "up", "times": 1}]
    assert "script" not in rendered.content


# ---- 6. 决策 prompt：脚本条目进 $actions ----


def test_decide_prompt_lists_script_entries() -> None:
    from pokemon_agent.brain.interface import Goal
    from pokemon_agent.direct.prompts.decide_action import build_prompt
    from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
    from pokemon_agent.world import ActionEntry, ActionSpace

    space = ActionSpace(
        names=["up"],
        mask={"up": True, "walk_to": True},
        entries=[
            ActionEntry(kind="key", name="up"),
            ActionEntry(
                kind="script",
                name="walk_to",
                params=[
                    __import__("pokemon_agent.world", fromlist=["ScriptParam"]).ScriptParam(
                        name="x", type="int"
                    ),
                    __import__("pokemon_agent.world", fromlist=["ScriptParam"]).ScriptParam(
                        name="y", type="int"
                    ),
                ],
                description="走到本图坐标 (x, y)。",
            ),
        ],
        descriptions={"up": "向上走"},
    )
    prompt = build_prompt(
        FromHarnessToBrainToolChooseOnceReq(
            goals=[Goal(goal="g", criteria="c")],
            obs=_obs(TaskScene.WALK),
            space=space,
            memories=[],
        )
    )
    assert "机械脚本" in prompt
    assert "walk_to(x: int, y: int)" in prompt
    assert "走到本图坐标" in prompt
    assert '{"action": "walk_to", "args"' in prompt  # 输出格式示例


# ---- 7. run_script_by_name 分发 ----


def test_run_script_by_name_dispatches_and_reports() -> None:

    console = StubConsole()
    result = run_script_by_name(console, "face_direction", {"direction": "north"})
    assert result.ok and console.facing() == "north"


# ---- 8. e2e：脚本动作经 WorldMcpTool.execute → server 脚本 tool ----


class _InlineClient:
    """in-memory 版 `McpClient.call_tool_sync`：直连 server 实例，不起端口。"""

    def __init__(self, server: Any) -> None:
        self._server = server

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mcp.shared.memory import create_connected_server_and_client_session

        async def run() -> dict[str, Any]:
            async with create_connected_server_and_client_session(
                self._server.mcp._mcp_server
            ) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                assert not result.isError
                return dict(json.loads(result.content[0].text))

        return asyncio.run(run())


class _NoWorld:
    """脚本 tool 不经原子层——给个可辨识的占位即可。"""

    def get_action_space(self) -> None:
        raise AssertionError("脚本通道不应触碰原子层")


def test_world_mcp_tool_executes_script_over_mcp() -> None:
    from pokemon_agent.brain.interface import ScriptCall
    from pokemon_agent.mcp_servers import world_server
    from pokemon_agent.mcpclient.world_tool import WorldMcpTool
    from pokemon_agent.schemas.harness import FromHarnessToGameToolExecuteReq

    console = StubConsole()
    world_server.start(_NoWorld(), rom="fake.rom")
    world_server._lease_owner = None
    world_server.set_console_factory(lambda: console)

    tool = WorldMcpTool(_InlineClient(world_server), client_id="t")
    resp = tool.execute(
        FromHarnessToGameToolExecuteReq(
            action=Action(script=ScriptCall(name="face_direction", args={"direction": "west"})),
            observation=_obs(TaskScene.WALK),
        )
    )
    assert resp.report is not None and resp.report["ok"] is True
    assert resp.report["code"] == "ok"
    assert console.facing() == "west"
