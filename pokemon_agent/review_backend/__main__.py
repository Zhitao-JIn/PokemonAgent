"""`python -m pokemon_agent.review_backend`：起后端，常驻到 Ctrl+C。

端口被占时报错退出，不自动换端口——run 与网页都靠这个端口找后端。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .backend import ReviewBackend

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


async def _serve_forever(host: str, port: int) -> None:
    """起服务并一直挂着。"""
    async with ReviewBackend().serve(host, port) as server:
        print(f"[review-backend] 已启动：浏览器打开 http://{host}:{port}", flush=True)
        await server.serve_forever()


def main() -> None:
    """解析参数、起服务；端口被占时打印原因并以 1 退出。"""
    parser = argparse.ArgumentParser(description="Pokemon Agent 人在环后端")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    try:
        asyncio.run(_serve_forever(args.host, args.port))
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
