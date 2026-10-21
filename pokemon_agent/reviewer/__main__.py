"""独立 reviewer 的唯一装配入口；只造读端口、终端和链路，不启动游戏或大脑。"""

import argparse
import asyncio
import itertools
import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from langfuse.api.core.api_error import ApiError

from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.mcpclient.client import McpClient, mcp_endpoint
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.memory_tool import MemoryMcpTool
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.reviewer.interaction import ReviewSeats
from pokemon_agent.settings import AppConfig, load_config, resolve_path
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
from .ports import AiReviewer
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
    """席位、监听地址、共享 trace 与记忆地址全部来自配置；命令行只收覆盖文件。"""
    parser = argparse.ArgumentParser(description="Pokemon Agent 独立复核席")
    parser.add_argument(
        "--config",
        action="append",
        type=Path,
        help="覆盖 default.json 的配置文件，可重复，后者胜；与 harness 用同一份",
    )
    parser.add_argument(
        "--image-root", type=Path, default=Path(tempfile.gettempdir()) / "pokemon-review"
    )
    parser.add_argument("--env-file", type=Path)
    return parser


async def run(args: argparse.Namespace) -> None:
    """装配完整 human 路径；无记忆地址时查询返回未接入，不阻止启动。"""
    load_env_file(args.env_file)
    app_config = load_config(args.config).config
    review = app_config.review
    if review.mode == "off" or review.link_url is None:
        raise ValueError("review.mode 为 off：没有要服务的席位，请在配置里改成 human / ai / both")
    parsed = urlsplit(review.link_url)
    if parsed.scheme != "ws" or not parsed.hostname:
        raise ValueError("本地 reviewer 监听地址必须是 ws://host:port")
    has_human = review.mode in {"human", "both"}
    has_ai = review.mode in {"ai", "both"}
    ai_settings = _ai_settings(app_config) if has_ai else None
    trace, client = _trace(app_config)
    memory_client, memory = _memory(app_config.services.memory_server_url)
    lines = StdinLines(sys.stdin.readline) if has_human else None
    human = HumanSeat(lines, _write, image_root=args.image_root) if lines is not None else None
    readers = ViewReaders(trace, memory, trace_delayed=app_config.trace.backend == "langfuse")
    hub = Hub(readers, on_activity=human.activity if human is not None else None)
    ai = _ai_seat(hub, ai_settings) if ai_settings is not None else None
    app = ReviewerApp(
        ReviewSeats(human=has_human, ai=has_ai),
        hub=hub,
        commands=Commands(hub),
        human=human,
        ai=ai,
        countdown_s=review.ai_countdown_s,
    )
    link = ReviewLinkServer(app, mode=review.mode)
    try:
        port = parsed.port if parsed.port is not None else 80
        async with await link.serve(parsed.hostname, port) as listener:
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            address = f"ws://{host}:{listener.sockets[0].getsockname()[1]}{parsed.path}"
            _write(
                f"[reviewer] 已启动：{address}；席位={review.mode}，"
                f"共享 trace={app_config.trace.backend}"
            )
            if has_human:
                await app.serve()
            else:
                await asyncio.Future()
    finally:
        app.close()
        if lines is not None:
            lines.close()
        await link.shutdown()
        if memory_client is not None:
            memory_client.stop()
        if client is not None:
            client.shutdown()


def _trace(
    app_config: AppConfig,
) -> tuple[ConfiguredTraceReader | None, LangfuseClientPort | None]:
    """Langfuse 缺配置时保留查询未接入，不静默改读本地账，也不阻止终端启动。"""
    if app_config.trace.backend == "local":
        trace_root = resolve_path(app_config.paths, "trace")
        return ConfiguredTraceReader(local=LocalTrace(root=trace_root)), None
    try:
        client = build_client_from_environment()
    except (RuntimeError, ValueError) as exc:
        logger.warning("Langfuse 读端口未接入：%s", exc)
        return None, None
    return ConfiguredTraceReader(client=client), client


def _memory(url: str | None) -> tuple[McpClient | None, MemoryTool | None]:
    """只用普通 MCP 查询能力；保留客户端句柄以便服务退出时停止线程。"""
    if not url:
        return None, None
    client = McpClient(mcp_endpoint(url))
    client.start()
    memory = MemoryTool(
        MemoryMcpTool(client, snapshot_root=Path(tempfile.gettempdir()) / "pokemon-review-memory")
    )
    return client, memory


def _ai_settings(
    app_config: AppConfig,
) -> tuple[Callable[..., AiReviewer], AppConfig, str]:
    """在启动读服务前核对 key 和 optional extra，避免失败时留下客户端线程。

    模型名与 base_url 取自 `review.agent_*`；只有密钥走环境变量。
    """
    api_key = env_str("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("AI 席需要配置 DEEPSEEK_API_KEY")
    try:
        from pokemon_agent.reviewer.seats.ai import AiSeat
    except ImportError as exc:
        raise RuntimeError("AI 席需安装项目 reviewer 可选依赖") from exc
    return AiSeat, app_config, api_key


def _ai_seat(hub: Hub, settings: tuple[Callable[..., AiReviewer], AppConfig, str]) -> AiReviewer:
    """使用已验证配置与当前 reviewer 的查询仲裁构造 AI 席。"""
    factory, app_config, api_key = settings
    review = app_config.review
    return factory(
        model_name=review.agent_model,
        api_key=api_key,
        base_url=review.agent_base_url,
        query=hub.query,
        max_tool_calls=review.agent_max_tool_calls,
        turn_budget_s=review.agent_turn_budget_s,
    )


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
