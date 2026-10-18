"""独立 reviewer 的唯一装配入口；只造读端口、终端和链路，不启动游戏或大脑。"""

import argparse
import asyncio
import itertools
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from langfuse.api.core.api_error import ApiError

from pokemon_agent.config import DEFAULT_REVIEW_LINK_URL, REVIEW_LINK_URL, TRACE_BACKEND
from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.mcpclient.client import McpClient, mcp_endpoint
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.memory_tool import MemoryMcpTool
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.reviewer.interaction import ReviewSeats
from pokemon_agent.trace import LocalTrace, TracePort
from pokemon_agent.trace.langfuse_support import (
    PAGE_SIZE,
    LangfuseClientPort,
    build_client_from_environment,
    decode_observation_event,
    json_decode_meta,
    matches_meta,
    observation_time_bounds,
    response_cursor,
    sequence,
    value_of,
)

from .app import ReviewerApp
from .hub import Commands, Hub
from .link.server import ReviewLinkServer
from .seats.human import HumanSeat
from .seats.terminal_io import StdinLines
from .view import ViewReaders

logger = logging.getLogger(__name__)


class ConfiguredTraceReader:
    """本地读共享目录，Langfuse 跨 trace 查询后按完整 meta 筛选，包含恢复分支。"""

    def __init__(
        self, *, local: TracePort | None = None, client: LangfuseClientPort | None = None
    ) -> None:
        self._local, self._client = local, client

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """仅调用查询 API，不创建观察；可见性沿后端语义，Langfuse 不保证立即可见。"""
        if self._local is not None:
            return [
                TraceEvent.model_validate(event.model_dump())
                for event in self._local.read_events(meta)
            ]
        try:
            return self._langfuse_events(meta or {})
        except (ApiError, httpx.HTTPError) as exc:
            raise RuntimeError(f"Langfuse 查询失败：{type(exc).__name__}") from exc

    def _langfuse_events(self, meta: dict[str, Any]) -> list[TraceEvent]:
        """分页解码兼容的账本封套，再以完整 meta 筛选，不绑定 run 或 branch 的 trace_id。"""
        if self._client is None:
            raise RuntimeError("读端口未接入")
        events: list[TraceEvent] = []
        cursor: str | None = None
        seen: set[str] = set()
        lower, upper = observation_time_bounds()
        for _ in itertools.count():
            response = self._client.api.observations.get_many(
                fields="core,basic,io,metadata,usage",
                limit=PAGE_SIZE,
                cursor=cursor,
                from_start_time=lower,
                to_start_time=upper,
            )
            for observation in sequence(value_of(response, "data", [])):
                event = decode_observation_event(observation)
                if event is None:
                    continue
                tags = json_decode_meta(event.meta)
                if tags is not None and matches_meta(tags, meta):
                    events.append(TraceEvent.model_validate(event.model_dump()))
            cursor = response_cursor(response)
            if not cursor:
                break
            if cursor in seen:
                raise RuntimeError("Langfuse 分页游标重复，不能保证结果完整")
            seen.add(cursor)
        return sorted(events, key=lambda event: (event.ended_at, event.seq))


def argument_parser() -> argparse.ArgumentParser:
    """地址与共享存储可显式指定；席位必须由人指定，R6b 仍仅支持 human。"""
    parser = argparse.ArgumentParser(description="Pokemon Agent 独立复核席")
    parser.add_argument("--seats", required=True, choices=["human", "ai", "both"])
    parser.add_argument("--url")
    parser.add_argument("--trace-backend", choices=["local", "langfuse"], default=TRACE_BACKEND)
    parser.add_argument("--trace-root", type=Path)
    parser.add_argument("--memory-server-url")
    parser.add_argument(
        "--image-root", type=Path, default=Path(tempfile.gettempdir()) / "pokemon-review"
    )
    parser.add_argument("--env-file", type=Path)
    return parser


async def run(args: argparse.Namespace) -> None:
    """装配完整 human 路径；无记忆地址时查询返回未接入，不阻止启动。"""
    load_env_file(args.env_file)
    url = args.url or env_str("REVIEW_LINK_URL") or REVIEW_LINK_URL or DEFAULT_REVIEW_LINK_URL
    parsed = urlsplit(url)
    if parsed.scheme != "ws" or not parsed.hostname:
        raise ValueError("本地 reviewer 监听地址必须是 ws://host:port")
    if args.seats != "human":
        raise ValueError("AI 席尚未接入，请使用 --seats human")
    if args.trace_backend == "langfuse" and args.trace_root is not None:
        raise ValueError("--trace-root 仅适用于 local 后端")
    trace, client = _trace(args)
    memory_client, memory = _memory(args.memory_server_url)
    lines = StdinLines(sys.stdin.readline)
    human = HumanSeat(lines, _write, image_root=args.image_root)
    readers = ViewReaders(trace, memory, trace_delayed=args.trace_backend == "langfuse")
    hub = Hub(readers, on_activity=human.activity)
    app = ReviewerApp(
        ReviewSeats(human=True, ai=False), hub=hub, commands=Commands(hub), human=human
    )
    link = ReviewLinkServer(app, mode="human")
    try:
        port = parsed.port if parsed.port is not None else 80
        async with await link.serve(parsed.hostname, port) as listener:
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            address = f"ws://{host}:{listener.sockets[0].getsockname()[1]}{parsed.path}"
            _write(f"[reviewer] 已启动：{address}；共享 trace={args.trace_backend}，Ctrl-C 退出")
            await app.serve()
    finally:
        app.close()
        lines.close()
        await link.shutdown()
        if memory_client is not None:
            memory_client.stop()
        if client is not None:
            client.shutdown()


def _trace(
    args: argparse.Namespace,
) -> tuple[ConfiguredTraceReader | None, LangfuseClientPort | None]:
    """Langfuse 缺配置时保留查询未接入，不静默改读本地账，也不阻止终端启动。"""
    if args.trace_backend == "local":
        return ConfiguredTraceReader(local=LocalTrace(root=args.trace_root)), None
    try:
        client = build_client_from_environment()
    except (RuntimeError, ValueError) as exc:
        logger.warning("Langfuse 读端口未接入：%s", exc)
        return None, None
    return ConfiguredTraceReader(client=client), client


def _memory(url: str | None) -> tuple[McpClient | None, MemoryTool | None]:
    """只用普通 MCP 查询能力；保留客户端句柄以便服务退出时停止线程。"""
    address = url or env_str("MCP_MEMORY_SERVER_URL")
    if not address:
        return None, None
    client = McpClient(mcp_endpoint(address))
    client.start()
    memory = MemoryTool(
        MemoryMcpTool(client, snapshot_root=Path(tempfile.gettempdir()) / "pokemon-review-memory")
    )
    return client, memory


def _write(text: str) -> None:
    """终端统一立即刷新，不能把提示滞留在重定向缓冲区。"""
    print(text, flush=True)


def main() -> None:
    """启动失败明确报地址或配置问题，不自动换端口或启动 run。"""
    args = argument_parser().parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[reviewer] 启动失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        _write("[reviewer] 已停止")


if __name__ == "__main__":
    main()
