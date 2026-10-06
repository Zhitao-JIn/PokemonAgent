"""`python -m pokemon_agent.review_backend`：起后端，常驻到 Ctrl+C。

端口被占时报错退出，不自动换端口——run 与网页都靠这个端口找后端。
可选 `--no-agent`：不起 AI 复核席，回到纯人模式（前端无提案；`WebReviewer` 仍按
`--review` 走 `timeout=None`，由人决定何时答）。`AGENT_REVIEWER_URL`（`.env`）缺失时
自动降级为无 agent，不崩。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pokemon_agent.env import env_str, load_env_file

from .agent_client import AgentClient
from .backend import ReviewBackend

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_DEFAULT_AGENT_URL = "ws://127.0.0.1:8770"


async def _serve_forever(host: str, port: int, agent_client: AgentClient | None) -> None:
    """起服务并一直挂着；可选先连 agent 进程。"""
    backend = ReviewBackend(agent_client=agent_client)
    async with backend.serve(host, port) as server:
        print(f"[review-backend] 已启动：浏览器打开 http://{host}:{port}", flush=True)
        await backend.start_agent()
        await server.serve_forever()


def main() -> None:
    """解析参数、读 env、构造 agent 客户端（可选）、起服务。"""
    parser = argparse.ArgumentParser(description="Pokemon Agent 人在环后端")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-agent", action="store_true", help="不起 AI 复核席，回到纯人模式")
    args = parser.parse_args()

    agent_client: AgentClient | None = None
    if not args.no_agent:
        load_env_file()
        url = env_str("AGENT_REVIEWER_URL", _DEFAULT_AGENT_URL) or _DEFAULT_AGENT_URL
        agent_client = AgentClient(url)

    try:
        asyncio.run(_serve_forever(args.host, args.port, agent_client))
    except OSError as exc:
        print(
            f"[review-backend] 起不来：{exc}（端口 {args.port} 被占？上次的后端可能还在跑）",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("[review-backend] 已停止", flush=True)


if __name__ == "__main__":
    main()
