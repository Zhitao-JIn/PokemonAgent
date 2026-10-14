"""world server 原子层：7 条 tool 的形状、单实例租约、health。

**不起真模拟器**（.venv 无 pyboy，且真机起跑交回用户本机）：`_FakeWorld` 实现
`WorldPort` 的那几个方法，只验 server 这一层的直译与闸门——"按下去世界里
發生什么"是真机冒烟的事，不进 pytest。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.testclient import TestClient

from pokemon_agent.mcp_servers import world_server
from pokemon_agent.mcpclient import McpClient
from pokemon_agent.world import ActionSpace, PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.action_space import compute_action_space
from pokemon_agent.world.errors import PerceptionAttemptFailed

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


class _FakeWorld:
    """`WorldPort` 的最小实现：只记下被调用过什么，位置按脚本走。"""

    def __init__(self, *, moves: bool = True) -> None:
        self.reset_calls: list[dict[str, Any]] = []
        self.steps: list[list[tuple[str, int]]] = []
        self.loaded: list[bytes] = []
        self._pos = (12, 13, 8)
        self._moves = moves
        self._fail_perceive = False

    # ---- WorldPort ----

    def reset(self, **kwargs: Any) -> None:
        self.reset_calls.append(kwargs)

    def all_actions(self) -> list[str]:
        return list(ALL_BUTTONS)

    def get_action_space(self) -> ActionSpace:
        observation = self.perceive_task().observation
        return compute_action_space(observation, list(ALL_BUTTONS))

    def perceive_task(self) -> Any:
        observation = TaskObservation(
            step=0,
            status="你在野外。",
            scene=TaskScene.WALK,
            place=PlaceInWorld(map_id=self._pos[0], x=self._pos[1], y=self._pos[2]),
        )
        return type(
            "TaskPerceived", (), {"observation": observation, "frame_png": "", "ram": None}
        )()

    def perceive_once(self) -> Any:
        if self._fail_perceive:
            raise PerceptionAttemptFailed({"error": "VisionParseFailure: 读不出"})
        observation = TaskObservation(step=0, status="你在野外。", scene=TaskScene.WALK)
        return type(
            "Perceived",
            (),
            {
                "observation": observation,
                "calls": [{"model": "fake"}],
                "frame_png": "",
                "ram": None,
            },
        )()

    def step(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        self.steps.append(list(segments))
        if self._moves:
            self._pos = (self._pos[0], self._pos[1] + 1, self._pos[2])

    def save_state(self) -> bytes:
        return b"STATE"

    def load_state(self, data: bytes) -> None:
        self.loaded.append(data)


@pytest.fixture()
def server():  # noqa: ANN201
    """每个用例一个干净的世界与租约。"""
    world = _FakeWorld()
    world_server.start(world, rom="fake.rom")
    world_server._lease_owner = None
    yield world
    world_server._lease_owner = None


# ---- 一、直译形状 ----


def test_step_is_the_only_key_execution_gate_and_reports_moved(server: _FakeWorld) -> None:
    """`step` 是唯一按键口：段按序交给 world，`moved` 由位置变化机械判定。"""
    body = world_server.step([["up", 1]], True, "c1")

    assert body["ok"] is True
    assert server.steps == [[("up", 1)]], "MCP 的二元数组还原成 world 的 (键名, 次数) 元组"
    assert body["data"]["moved"] is True
    assert body["data"]["event"] is None, "event 字段形状先定，判定前移是 P6"


def test_step_reports_not_moved_when_the_world_did_not_move() -> None:
    """撞墙没动 → moved=False（blocked 的机械依据，不需要 world 额外报告）。"""
    world_server.start(_FakeWorld(moves=False), rom="fake.rom")
    world_server._lease_owner = None
    assert world_server.step([["up", 1]], True, "c1")["data"]["moved"] is False


def test_get_action_space_exposes_one_flat_namespace() -> None:
    """键与脚本在**同一个** mask 里；不可用的显式 False（不是缺席）。"""
    world_server.start(_FakeWorld(), rom="fake.rom")
    body = world_server.get_action_space()

    mask = body["data"]["mask"]
    assert "up" in mask and "a" in mask, "原子键在掩码里"
    assert mask["up"] is True
    assert False in mask.values(), "掩码覆盖整个命名空间（含此刻不可用的）"
    assert {e["name"] for e in body["data"]["entries"]} == {n for n, on in mask.items() if on}


def test_perceive_task_never_fails_and_perceive_once_reports_failure() -> None:
    """task 档不会失败；视觉档失败走 `perception_failed` 信封（不抛、不重试）。"""
    world = _FakeWorld()
    world_server.start(world, rom="fake.rom")
    assert world_server.perceive_task()["data"]["observation"]["scene"] == "walk"

    ok = world_server.perceive_once()
    assert ok["ok"] is True and ok["data"]["calls"] == [{"model": "fake"}]

    world._fail_perceive = True
    bad = world_server.perceive_once()
    assert bad["ok"] is False and bad["code"] == "perception_failed"


def test_state_roundtrip_is_base64(server: _FakeWorld) -> None:
    """存档走 base64（JSON 装不了 bytes），回读逐字节相同。"""
    saved = world_server.save_state()["data"]["state_base64"]
    assert saved == "U1RBVEU="

    assert world_server.load_state(saved, "c1")["ok"] is True
    assert server.loaded == [b"STATE"]


# ---- 二、单实例租约 ----


def test_first_client_takes_the_lease_and_the_second_is_rejected(server: _FakeWorld) -> None:
    """同一时刻只允许一个推进者——两个模拟器并存是这台机器的硬红线。"""
    assert world_server.reset("t1", "g", "c", 10, "", "c1")["ok"] is True
    assert world_server.step([["up", 1]], True, "c1")["ok"] is True

    denied = world_server.step([["up", 1]], True, "c2")
    assert denied["ok"] is False and denied["code"] == "rejected"
    assert "c1" in denied["error"]


def test_read_only_tools_do_not_take_the_lease(server: _FakeWorld) -> None:
    """看一眼不该抢锁：只读 tool 不占租约（否则旁观者会把推进者锁在外面）。"""
    world_server.get_action_space()
    world_server.perceive_task()
    world_server.save_state()

    assert world_server._lease_owner is None
    assert world_server.step([["up", 1]], True, "c2")["ok"] is True, "租约还没人拿"


def test_only_the_holder_can_release_the_lease(server: _FakeWorld) -> None:
    world_server.reset("t1", "g", "c", 10, "", "c1")
    assert world_server.release_lease("c2")["ok"] is False

    assert world_server.release_lease("c1")["ok"] is True
    assert world_server.step([["up", 1]], True, "c2")["ok"] is True, "还了就能换人"


# ---- 三、health 与注册表 ----


def test_health_reports_ready_and_lease_holder() -> None:
    world_server.start(_FakeWorld(), rom="fake.rom")
    world_server._lease_owner = None
    app = world_server.mcp.streamable_http_app()
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["service"] == "pokemon-world"
        assert body["ready"] is True
        assert body["lease_owner"] is None

        world_server.reset("t1", "g", "c", 10, "", "c1")
        assert client.get("/health").json()["lease_owner"] == "c1"


def test_registry_lists_the_atomic_layer() -> None:
    """注册表 = 能力面：7 条原子 + 租约归还 + 37 条脚本（§7 一脚本一 API）。"""
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    world_server.start(_FakeWorld(), rom="fake.rom")

    async def list_tools() -> set[str]:
        async with create_connected_server_and_client_session(
            world_server.mcp._mcp_server
        ) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {t.name for t in tools.tools}

    names = asyncio.run(list_tools())
    assert names == {
        "reset",
        "get_action_space",
        "perceive_task",
        "perceive_once",
        "step",
        "save_state",
        "load_state",
        "release_lease",
        # 脚本层（§7，一脚本一 API）
        "face_direction",
        "walk_to_adjacent",
        "walk_to",
        "circle_walk",
        "bounce_in_tall_grass",
        "talk_to_adjacent_npc",
        "buy_item",
        "sell_item",
        "interact_facing",
        "advance_dialog",
        "wait_until_scene",
        "exit_map",
        "heal_at_center",
        "open_menu_to",
        "shop_quit",
        "naming_enter_name",
        "battle_fight",
        "battle_switch",
        "battle_use_item",
        "battle_run",
        "switch_send_out",
        "bag_use",
        "bag_toss",
        "bag_close",
        "party_switch",
        "party_field_move",
        "party_stats",
        "party_close",
        "pc_withdraw_item",
        "pc_deposit_item",
        "pc_toss_item",
        "pc_withdraw_pokemon",
        "pc_deposit_pokemon",
        "pc_change_box",
        "pc_log_off",
        "learn_forget",
        "learn_skip",
    }, names


def test_client_roundtrip_over_mcp_transport() -> None:
    """经 MCP 调一次 `get_action_space`：信封能过网络、能被 client 解回 dict。"""
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    world_server.start(_FakeWorld(), rom="fake.rom")

    async def call() -> dict[str, Any]:
        async with create_connected_server_and_client_session(
            world_server.mcp._mcp_server
        ) as session:
            await session.initialize()
            result = await session.call_tool("get_action_space", {})
            return json.loads(result.content[0].text)

    body = asyncio.run(call())
    assert body["ok"] is True and body["data"]["mask"]["up"] is True
    assert McpClient is not None  # client 侧在 P5 接线，这里只确认形状可解
