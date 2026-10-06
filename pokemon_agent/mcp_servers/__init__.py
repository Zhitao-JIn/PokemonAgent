"""mcp_servers：两个 MCP server（memory / world）——注册表对外暴露能力面。

- `memory_server`：能力面 `recall` / `memorize`（分族分流与落族实现在
  `memory/recall.py`，一份实现两模式共用）；
- `world_server`：原子层 + 脚本层（P2+ 落码）。

server 由用户本机起跑（0924 口径）；测试走 in-memory transport。
"""
