"""`python -m pokemon_agent.agent_reviewer`：起 agent 进程，常驻到 Ctrl+C。

读 `.env`（`pokemon_agent.env.load_env_file`）的 `AGENT_REVIEWER_URL` 解析 host/port 起 WS server；
CLI `--host`/`--port` 可覆盖。`DEEPSEEK_API_KEY` 缺失即 `RuntimeError` 当场停（提示先配 key）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from urllib.parse import urlparse

from pokemon_agent.agent_reviewer.agent import AgentReviewer
from pokemon_agent.agent_reviewer.server import serve_agent
from pokemon_agent.env import env_str, load_env_file

logger = logging.getLogger(__name__)

_DEFAULT_URL = "ws://127.0.0.1:8770"


def _host_port(url: str) -> tuple[str, int]:
    """从 `ws://host:port` 解析 host/port；缺省端口回退 8770。"""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8770
    return host, port


def main() -> None:
    """解析参数、读 env、起服务；端口被占 / key 缺失时打印原因并以 1 退出。"""
    parser = argparse.ArgumentParser(description="Pokemon Agent · AI 复核席进程")
    parser.add_argument("--host", default=None, help="覆盖 .env 里的绑定地址")
    parser.add_argument("--port", type=int, default=None, help="覆盖 .env 里的绑定端口")
    args = parser.parse_args()

    load_env_file()
    url = env_str("AGENT_REVIEWER_URL", _DEFAULT_URL) or _DEFAULT_URL
    host, port = _host_port(url)
    host = args.host or host
    port = args.port or port

    try:
        # 构造即校验 key：缺失当场停（`build_deepseek` 内 `RuntimeError`）。
        AgentReviewer()
    except RuntimeError as exc:
        print(f"[agent] 起不来：{exc}（先在 .env 配 DEEPSEEK_API_KEY）", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(serve_agent(AgentReviewer(), host, port))
    except OSError as exc:
        print(
            f"[agent] 起不来：{exc}（端口 {port} 被占？上次的后端 / agent 可能还在跑）",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("[agent] 已停止")


if __name__ == "__main__":
    main()
