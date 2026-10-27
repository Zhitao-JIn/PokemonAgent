"""world server：MCP 注册表暴露 7 条原子操作、租约归还与 37 条脚本，另有健康检查。

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
    """此刻能干什么：**统一能力掩码**（原子键与脚本在同一命名空间，`名字 → 是否可用`）。

    不需要指定类型——拿到的 `mask` 里键和脚本混在一起，挑一个 enabled 的即可；
    `entries` 给每个条目的参数签名与说明（脚本有参数，键没有）。
    """
    space = _w().get_action_space()
    # 整份 dump 交出去：`names` 是 prompt 渲染按键说明要用的形状，
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
def save_state() -> dict[str, Any]:
    """导出模拟器完整状态（base64）。**不推进世界**——存档点即此刻。"""
    return envelope(data={"state_base64": base64.b64encode(_w().save_state()).decode("ascii")})


@mcp.tool()
def read_wram() -> dict[str, Any]:
    """数据集冻结用的只读 WRAM 导出（8192 字节 base64），不占租约、不推进世界。"""
    return envelope(data={"wram_base64": base64.b64encode(_w().read_wram()).decode("ascii")})


# ---- 变更面（占租约）----


@mcp.tool()
def reset(
    task_id: str,
    goal: str,
    success_criteria: str,
    max_steps: int,
    initial_state_hint: str = "",
    state_base64: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """开新一局：按任务重置到初始状态，不感知，第一帧由调用方另取。

    state_base64 非 None 时解码为本次 reset 的字节起点，优先于服务端默认起点。
    """
    denied = _take_lease(client_id)
    if denied is not None:
        return denied
    start_arguments = (
        {"start_state": base64.b64decode(state_base64)} if state_base64 is not None else {}
    )
    _w().reset(
        task_id=task_id,
        goal=goal,
        success_criteria=success_criteria,
        max_steps=max_steps,
        initial_state_hint=initial_state_hint,
        **start_arguments,
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

    `dialog` 排在展开 `result.data` **之后**：`advance_dialog` 往 `data["dialog"]`
    放过一份按段的旧值，这里用报告顶层的按行列表覆盖它（D9 同名冲突）。
    """
    denied = _take_lease(client_id)
    if denied is not None:
        return denied
    result = fn(_console(), **kwargs)
    return envelope(
        data={
            "ok": result.ok,
            "code": result.code,
            **result.data,
            "calls": result.calls,
            "dialog": result.dialog,
        },
        code=result.code,
        events=list(result.events),
    )


# ---- 运维面 ----


def _run_named_script(
    name: str, client_id: str | None, arguments: dict[str, str | int | float | None]
) -> dict[str, Any]:
    """公开脚本共用现有租约、执行和终态信封通道。"""
    from pokemon_agent.world.scripts.catalog import SCRIPT_FUNCS

    assert name in SCRIPT_FUNCS, f"unregistered script {name!r}"
    return _run_script(SCRIPT_FUNCS[name], client_id, **arguments)


from .world_script_tools import register as register_script_tools  # noqa: E402

register_script_tools(mcp, _run_named_script)


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
    """委托命令行装配与服务启动。"""
    from .world_server_cli import main as run_server

    run_server(mcp, start, SERVICE_NAME)


if __name__ == "__main__":
    main()
