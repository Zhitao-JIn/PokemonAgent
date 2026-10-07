"""脚本 MCP 能力装配：每个场合注册显式函数签名。"""

from mcp.server.fastmcp import FastMCP

from .bag import register as register_bag
from .battle import register as register_battle
from .field_interaction import register as register_field_interaction
from .field_menu import register as register_field_menu
from .field_movement import register as register_field_movement
from .field_places import register as register_field_places
from .learn import register as register_learn
from .naming import register as register_naming
from .party import register as register_party
from .pc_items import register as register_pc_items
from .pc_pokemon import register as register_pc_pokemon
from .shop import register as register_shop
from .types import ScriptExecutor


def register(mcp: FastMCP, execute: ScriptExecutor) -> None:
    """注册 14 条地图流程和 23 条接管流程；买卖由 buy_item / sell_item 组合调用。"""
    register_shop(mcp, execute)
    register_battle(mcp, execute)
    register_bag(mcp, execute)
    register_party(mcp, execute)
    register_pc_items(mcp, execute)
    register_pc_pokemon(mcp, execute)
    register_learn(mcp, execute)
    register_field_movement(mcp, execute)
    register_field_interaction(mcp, execute)
    register_field_places(mcp, execute)
    register_field_menu(mcp, execute)
    register_naming(mcp, execute)
