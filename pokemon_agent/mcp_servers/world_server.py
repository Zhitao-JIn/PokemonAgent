"""world server：MCP 注册表暴露世界的**原子层**（7 条）+ 健康检查。

**这一层没有领域逻辑**：每条 tool = `WorldPort` 同名方法的直译（bytes 走 base64），
信封组装归 mcpclient、脚本与判定归 server 进程内的脚本层（P4 起）。

**单实例租约**（防两模拟器并存，0924 口径的硬红线）：`PyBoyWorld` 是强状态单
实例，两个客户端同时推进会互相踩帧。MCP 是无身份的（同一个 HTTP 端点谁都能
连），所以租约**由调用方显式报 `client_id`**——第一个调用变更类 tool 的
client 拿到租约，其余人的变更调用一律 `rejected`，直到租约被释放。
只读 tool（感知 / 掩码 / 存档导出）不占租约：看一眼不该抢锁。

起跑（用户本机，0924 口径）：

    python -m pokemon_agent.mcp_servers.world_server --rom <rom> [--state-file <path>]
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from pokemon_agent.mcp_servers.common import (
    HEALTH_PATH,
    MCP_PATH,
    envelope,
    fail,
    health_payload,
)

if TYPE_CHECKING:  # 只为类型标注：world 的协议是零依赖的纯 Protocol
    from pokemon_agent.world import WorldPort

mcp = FastMCP("pokemon-world")

SERVICE_NAME = "pokemon-world"

_world: WorldPort | None = None
_rom: str | None = None
_lease_owner: str | None = None
_console_factory: Callable[[], Any] | None = None


def start(world: WorldPort, rom: str | None = None) -> None:
    """注入世界实现（构造期一次）。tool 函数体全部经它委托。"""
    global _world, _rom
    _world = world
    _rom = rom


def set_console_factory(factory: Callable[[], Any] | None) -> None:
    """注入脚本层的 `WorldConsole` 工厂（测试用）；缺省 = `WorldConsoleAdapter(_w)`。"""
    global _console_factory
    _console_factory = factory


def _console() -> Any:  # noqa: ANN401
    """脚本层的 console：真机 = `WorldConsoleAdapter` 包 `PyBoyWorld`。"""
    if _console_factory is not None:
        return _console_factory()
    from pokemon_agent.world.pyboy_world import PyBoyWorld
    from pokemon_agent.world.scripts.console_adapter import WorldConsoleAdapter

    assert isinstance(_world, PyBoyWorld), "脚本 tool 需要真机 world（PyBoyWorld）"
    return WorldConsoleAdapter(_world)


def _w() -> WorldPort:
    assert _world is not None, "world server world not injected — call start() before serving"
    return _world


def _pos(observation: Any) -> tuple[int, int, int] | None:  # noqa: ANN401
    """观测里的位置三元组（`Observation.place` 是全项目唯一的位置表示）。"""
    place = observation.place
    return None if place is None else (place.map_id, place.x, place.y)


def _take_lease(client_id: str | None) -> dict[str, Any] | None:
    """变更类 tool 的租约闸：返回 None = 放行；否则返回失败信封。

    `client_id` 不传 = 不参与租约（单客户端场景的简写，只读调用方本来就不传）。
    判据只有一条：**同一时刻只允许一个推进者**。
    """
    global _lease_owner
    if client_id is None:
        return None
    if _lease_owner is None:
        _lease_owner = client_id
        return None
    if _lease_owner != client_id:
        return fail(
            "rejected",
            f"world 单实例租约被 {_lease_owner!r} 持有，{client_id!r} 不能推进世界",
        )
    return None


# ---- 只读面 ----


@mcp.tool()
def get_action_space() -> dict[str, Any]:
    """此刻能干什么：**统一能力掩码**（原子键与宏在同一命名空间，`名字 → 是否可用`）。

    不需要指定类型——拿到的 `mask` 里键和宏混在一起，挑一个 enabled 的即可；
    `entries` 给每个条目的参数签名与说明（宏有参数，键没有）。
    """
    space = _w().get_action_space()
    # 整份 dump 交出去：`names` / `macros` 是 prompt 渲染要用的形状，
    # `mask` / `entries` 是统一掩码的形状——它们是同一份 ActionSpace 的两个视图，
    # 只在 server 这一处产出，client 侧验回即可，不做二次组装。
    return envelope(data=space.model_dump(mode="json"))


@mcp.tool()
def perceive_task() -> dict[str, Any]:
    """读当前这一帧（**不调模型**）：场合、屏幕文本或走位图、坐标。

    便宜、不会失败——它是"现在在哪、画面上有什么"的机械读数。
    """
    perceived = _w().perceive_task()
    return envelope(
        data={
            "observation": perceived.observation.model_dump(mode="json"),
            "frame_png": perceived.frame_png,
            "ram": perceived.ram,
        }
    )


@mcp.tool()
def perceive_once() -> dict[str, Any]:
    """读当前这一帧的**视觉档**（调一次视觉模型，不重试；重试预算归调用方）。"""
    try:
        perceived = _w().perceive_once()
    except Exception as exc:  # noqa: BLE001 —— world 的词汇不该跨进程泄漏
        return fail("perception_failed", f"{type(exc).__name__}: {exc}")
    return envelope(
        data={
            "observation": perceived.observation.model_dump(mode="json")
            if perceived.observation is not None
            else None,
            "calls": perceived.calls,
            "ram": perceived.ram,
        }
    )


@mcp.tool()
def save_state() -> dict[str, Any]:
    """导出模拟器完整状态（base64）。**不推进世界**——存档点即此刻。"""
    return envelope(data={"state_base64": base64.b64encode(_w().save_state()).decode("ascii")})


# ---- 变更面（占租约）----


@mcp.tool()
def reset(
    task_id: str,
    goal: str,
    success_criteria: str,
    max_steps: int,
    initial_state_hint: str = "",
    client_id: str | None = None,
) -> dict[str, Any]:
    """开新一局：按任务重置到初始状态。**不感知**——第一帧由调用方另取。"""
    denied = _take_lease(client_id)
    if denied is not None:
        return denied
    _w().reset(
        task_id=task_id,
        goal=goal,
        success_criteria=success_criteria,
        max_steps=max_steps,
        initial_state_hint=initial_state_hint,
    )
    return envelope()


@mcp.tool()
def step(
    segments: list[list[Any]],
    settle: bool = True,
    client_id: str | None = None,
) -> dict[str, Any]:
    """**唯一按键执行口**：按一段键推进世界。

    `segments`：`[[按键名, 连按次数], ...]`（MCP 的 JSON 没有元组，用二元数组）。
    返回 `{moved, event}`——`event` 是本键的裸对象事件（P6 起 world 侧判定，
    与脚本报告 `events[]` 同一裁判同一形状；普通移动 / blocked 为 `null`）。
    """
    denied = _take_lease(client_id)
    if denied is not None:
        return denied
    pairs = [(str(name), int(times)) for name, times in segments]
    from pokemon_agent.world.object_events import observe_step

    moved, event = observe_step(_w(), pairs, settle=settle)
    return envelope(data={"moved": moved, "event": event})


@mcp.tool()
def load_state(state_base64: str, client_id: str | None = None) -> dict[str, Any]:
    """用 `save_state` 的产物把模拟器原样恢复到那一刻。**不 tick**。"""
    denied = _take_lease(client_id)
    if denied is not None:
        return denied
    _w().load_state(base64.b64decode(state_base64))
    return envelope()


@mcp.tool()
def release_lease(client_id: str) -> dict[str, Any]:
    """归还单实例租约（只有持有者能还）。换客户端跑之前先调它。"""
    global _lease_owner
    if _lease_owner is not None and _lease_owner != client_id:
        return fail("rejected", f"租约在 {_lease_owner!r} 手里，{client_id!r} 不能释放")
    _lease_owner = None
    return envelope()


# ---- 脚本层（§7，一脚本一 API；实现住 world/scripts，随 world 拷走）----


def _run_script(  # noqa: ANN401 —— 脚本入参形状各异，tool 壳逐个显式声明
    fn: Callable[..., Any],
    client_id: str | None,
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """脚本 tool 统一通道：租约 → 执行 → 终态报告进信封（events 裸事件化）。

    `data.ok` 是**脚本语义成败**（bounce 的 `battle_started` 也算成功），
    信封顶层的 ok 只反映 `code == "ok"`——两者分工见 SPEC §3.1。
    """
    denied = _take_lease(client_id)
    if denied is not None:
        return denied
    result = fn(_console(), **kwargs)
    return envelope(
        data={"ok": result.ok, "code": result.code, **result.data, "calls": result.calls},
        code=result.code,
        events=list(result.events),
    )


@mcp.tool()
def face_direction(direction: str, client_id: str | None = None) -> dict[str, Any]:
    """脚本 face_direction：转向指定方向（已面向则原地不动）。"""
    from pokemon_agent.world.scripts.movement import face_direction as _fn

    return _run_script(_fn, client_id, direction=direction)


@mcp.tool()
def walk_to_adjacent(direction: str, client_id: str | None = None) -> dict[str, Any]:
    """脚本 walk_to_adjacent：向相邻格走一步；被挡 → blocked，落草丛 → entered_grass。"""
    from pokemon_agent.world.scripts.movement import walk_to_adjacent as _fn

    return _run_script(_fn, client_id, direction=direction)


@mcp.tool()
def walk_to(x: int, y: int, max_steps: int = 200, client_id: str | None = None) -> dict[str, Any]:
    """脚本 walk_to：走到目标格（固定轴序贪心，被挡换轴，5 步收敛校验；不做 BFS）。"""
    from pokemon_agent.world.scripts.movement import walk_to as _fn

    return _run_script(_fn, client_id, x=x, y=y, max_steps=max_steps)


@mcp.tool()
def circle_walk(laps: int, extent: int = 1, client_id: str | None = None) -> dict[str, Any]:
    """脚本 circle_walk：绕圈走 laps 圈（每步断言位移、圈末回起点）。"""
    from pokemon_agent.world.scripts.movement import circle_walk as _fn

    return _run_script(_fn, client_id, laps=laps, extent=extent)


@mcp.tool()
def bounce_in_tall_grass(steps: int = 30, client_id: str | None = None) -> dict[str, Any]:
    """脚本 bounce_in_tall_grass：草丛里来回走撞怪；遇怪=battle_started（目的达成），
    步数用完=no_encounter（合法）。"""
    from pokemon_agent.world.scripts.movement import bounce_in_tall_grass as _fn

    return _run_script(_fn, client_id, steps=steps)


@mcp.tool()
def talk_to_adjacent_npc(
    direction: str = "", client_id: str | None = None
) -> dict[str, Any]:
    """脚本 talk_to_adjacent_npc：跟面前 NPC 说话；对话增量在 events[]，
    出选项 → choice_presented（绝不代选），训练家 → battle_started。"""
    from pokemon_agent.world.scripts.interact import talk_to_adjacent_npc as _fn

    return _run_script(_fn, client_id, direction=direction or None)


@mcp.tool()
def buy_item(item: str, count: int, client_id: str | None = None) -> dict[str, Any]:
    """脚本 buy_item：按 tables 在售表买道具；终态对账（扣款/入库）→ verify_failed 兜底。"""
    from pokemon_agent.world.scripts.shop import buy_item as _fn

    return _run_script(_fn, client_id, item=item, count=count)


@mcp.tool()
def sell_item(item: str, count: int, client_id: str | None = None) -> dict[str, Any]:
    """脚本 sell_item：把背包道具卖给店（卖价=买价一半）；终态对账 → verify_failed 兜底。"""
    from pokemon_agent.world.scripts.shop import sell_item as _fn

    return _run_script(_fn, client_id, item=item, count=count)


@mcp.tool()
def interact_facing(client_id: str | None = None) -> dict[str, Any]:
    """脚本 interact_facing：跟面前物体交互（招牌/石头/NPC 通用）；有对话→ok，
    无变化→no_response，出选项→choice_presented（绝不代选）。"""
    from pokemon_agent.world.scripts.interact import interact_facing as _fn

    return _run_script(_fn, client_id)


@mcp.tool()
def advance_dialog(max_presses: int = 30, client_id: str | None = None) -> dict[str, Any]:
    """脚本 advance_dialog：把当前对话框推进到底（反复按 a 直到回野外）；
    推不完→still_talking，中途出选项→choice_presented（冻结）。"""
    from pokemon_agent.world.scripts.flow import advance_dialog as _fn

    return _run_script(_fn, client_id, max_presses=max_presses)


@mcp.tool()
def wait_until_scene(
    scene: str, timeout_s: float = 10.0, client_id: str | None = None
) -> dict[str, Any]:
    """脚本 wait_until_scene：不按键只 tick，逐帧等场合变成 `scene`；超时→timeout
    （过场/淡入/回血白闪这类"等它自己变"的窗口）。"""
    from pokemon_agent.world.scripts.flow import wait_until_scene as _fn

    return _run_script(_fn, client_id, scene=scene, timeout_s=timeout_s)


@mcp.tool()
def exit_map(target_warp: int = -1, client_id: str | None = None) -> dict[str, Any]:
    """脚本 exit_map：查 tables/warps[map_id] 的出口换图；踩到出口→ok（新图），
    按了不换图（表过期）→warp_failed，去门口被挡→透传 blocked，map 非白名单→unsupported_map。"""
    from pokemon_agent.world.scripts.navigation import exit_map as _fn

    return _run_script(_fn, client_id, target_warp=target_warp)


@mcp.tool()
def heal_at_center(max_steps: int = 60, client_id: str | None = None) -> dict[str, Any]:
    """脚本 heal_at_center：宝可梦中心回满血（走到护士前→面朝护士→对话→机械确认
    YES→回满校验）；map 非白名单→unsupported_map，队伍未全满→verify_failed。"""
    from pokemon_agent.world.scripts.navigation import heal_at_center as _fn

    return _run_script(_fn, client_id, max_steps=max_steps)


@mcp.tool()
def open_menu_to(target: str, client_id: str | None = None) -> dict[str, Any]:
    """脚本 open_menu_to：开 start 菜单并进指定子菜单（如 POKéMON→party）；
    target 非法→rejected，选中后仍在 start 菜单→wrong_scene。"""
    from pokemon_agent.world.scripts.menu import open_menu_to as _fn

    return _run_script(_fn, client_id, target=target)


# ---- 运维面 ----


@mcp.custom_route(HEALTH_PATH, methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """健康检查（普通 HTTP）：服务名 / 能力是否注入 / 租约在谁手里。"""
    return JSONResponse(
        health_payload(
            SERVICE_NAME,
            ready=_world is not None,
            root=_rom,
            lease_owner=_lease_owner,
            transport=MCP_PATH,
        )
    )


def main() -> None:
    """命令行入口：解析参数 → 造真实世界 → 起 Streamable HTTP 服务。"""
    parser = argparse.ArgumentParser(description="pokemon world MCP server")
    parser.add_argument("--rom", required=True, help="ROM 路径")
    parser.add_argument("--state-file", default=None, help="起点存档（不给 = 从开机起跑）")
    parser.add_argument("--vision-model", default="qwen3.8-max")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()

    from pokemon_agent.brain.vision_factory import build_vision_provider
    from pokemon_agent.world import PyBoyWorld

    world = PyBoyWorld(
        args.rom,
        build_vision_provider(model=args.vision_model, temperature=0.0),
        state_path=args.state_file,
    )
    start(world, rom=args.rom)
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    assert mcp.settings.streamable_http_path == MCP_PATH
    print(f"{SERVICE_NAME} listening on http://{args.host}:{args.port}{MCP_PATH}")
    print(f"health: http://{args.host}:{args.port}{HEALTH_PATH}")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
