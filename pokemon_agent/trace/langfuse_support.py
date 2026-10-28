"""Langfuse SDK boundary helpers for `LangfuseTrace`."""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any, Protocol
from urllib.parse import urlparse

from .datastore.event import _Event
from .interface.event import Event

PAGE_SIZE = 1000
logger = logging.getLogger(__name__)

LANGFUSE_ENVIRONMENT_NAME = "local"
"""Langfuse trace 的 environment 标注（2026-09-27 占位定案）。

SDK docstring 约束该值只许小写字母数字 + 连字符 + 下划线、不得以 `langfuse`
开头——带点号的版本号不合规，所以 version 走逐账 `version=` 字段、environment
用这个固定词。取真实取值体系（按执行通道区分等）前先占位。
"""

LANGFUSE_ADAPTER_VERSION = "0.1.0"
"""逐账盖进 Langfuse observation `version` 字段的适配器版本（2026-09-27 占位）。

语义是"这条账由哪个版本的落库适配器写入"（封套形状 + 字段适配轮次），
不是项目版本；升版时机 = 封套或投影规则变更（如本轮双时刻改造）。
"""

RETRIEVE_KINDS = frozenset(
    {
        "read_act_memory",
        "read_episode_memory",
        "read_knowledge",
        "read_task_memory",
    }
)
"""六条 RAG 读口账（`render.retrieve_node` 渲染的五本账名，run/perceive 的
`read_plan_context` 一处发两本）——Langfuse 落库时落成 `retriever` 类型、
input 投检索请求面。裸字符串：trace 是独立模块，不认识 `TraceKind`。"""


class _Observation(Protocol):
    id: str

    def end(self) -> None:
        """结束本次 observation——OTEL span 不 end 就不会被导出。"""
        ...


class LangfuseClientPort(Protocol):
    """Small SDK shape consumed by adapter helpers and injectable clients."""

    api: Any

    def create_trace_id(self, *, seed: str) -> str: ...

    def start_as_current_observation(
        self,
        *,
        trace_context: dict[str, str],
        name: str,
        as_type: str,
        input: Any = None,
        output: Any = None,
        metadata: Any = None,
        version: str | None = None,
        model: str | None = None,
        usage_details: dict[str, int] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> AbstractContextManager[_Observation]: ...

    def start_observation(
        self,
        *,
        trace_context: dict[str, str],
        name: str,
        as_type: str,
        metadata: Any = None,
        version: str | None = None,
    ) -> _Observation: ...

    def create_event(
        self,
        *,
        trace_context: dict[str, str],
        name: str,
        input: Any = None,
        output: Any = None,
        metadata: Any = None,
        version: str | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> _Observation: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


def langfuse_trace_seed(run_id: str, branch: str) -> str:
    """Langfuse trace 的 seed：**一次执行尝试 (run_id, branch) = 一个 trace**（0929 定案）。

    同 `(run_id, branch)` 重入 = 事件追加进同一 trace（预期内；branch 每次 restore 随机
    新发，实际不重入）；不同 branch / epoch / 样本各自独立 trace。寻址规则见
    `docs/PLAN_trace_branch_addressing.md`。
    """
    return f"{run_id}::{branch}"


def build_client_from_environment() -> Any:
    """Create the SDK client for a configured local Langfuse instance."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    base_url = os.getenv("LANGFUSE_BASE_URL", "").strip()
    if not public_key or not secret_key or not base_url:
        raise RuntimeError(
            "Langfuse backend needs LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and "
            "LANGFUSE_BASE_URL for the local self-hosted instance"
        )
    hostname = urlparse(base_url).hostname or ""
    if hostname == "langfuse.com" or hostname.endswith(".langfuse.com"):
        raise ValueError("Langfuse backend is local-only; LANGFUSE_BASE_URL must not target Cloud")
    if not _is_local_host(hostname):
        logger.warning("LANGFUSE_BASE_URL points to a non-local host: %s", hostname)
    # 自建 httpx client 显式跟随重定向：self-hosted v4（实测 4.46.0）对
    # observations v2 查询回 308 内部规范化跳转，SDK 自建 client 不传
    # follow_redirects（httpx 默认 False），读侧会直接抛 ApiError。
    # trust_env=False：本模块只连本机服务，绝不过系统代理——实测代理会把
    # 带 cursor 的翻页请求打回 308（重定向回同一 URL），httpx 跟随后死循环。
    # 生命周期归本进程：SDK 不关闭调用方传入的 client，随进程退出释放。
    import httpx
    from langfuse import Langfuse

    return Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        environment=LANGFUSE_ENVIRONMENT_NAME,
        httpx_client=httpx.Client(follow_redirects=True, timeout=60.0, trust_env=False),
    )


def assert_server_ready(base_url: str | None = None, timeout: float = 5.0) -> str:
    """启动前探针：Langfuse 服务必须可达且健康，失败就明确报错。

    Langfuse 从 0927 起是真实 run 的默认 trace backend——SDK 是异步批量发送，
    服务不在场时**写入侧静默丢账**（队列在内存里），等跑到一半才发现就晚了。
    所以装配点（`build.py::build_real`）在选 `langfuse` 后端时先打一发健康检查，
    把"服务没起 / 配置缺失"挡在 run 开始之前。

    `base_url`：缺省读 `LANGFUSE_BASE_URL` 环境变量（与 `build_client_from_environment`
    同一来源）。返回服务版本字符串（如 `"4.46.0"`），供调用方打进日志。

    前置条件：环境变量三件已配（本函数只探服务在场，不管密钥——密钥缺失由
    `build_client_from_environment` 就地报）。
    后置条件：`/api/public/health` 返回 200 且 `status == "OK"`，否则抛 `RuntimeError`。
    """
    url = (base_url or os.getenv("LANGFUSE_BASE_URL", "")).strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "Langfuse backend needs LANGFUSE_BASE_URL (and the two keys) before launch"
        )
    import httpx

    try:
        response = httpx.get(
            f"{url}/api/public/health", timeout=timeout, follow_redirects=True, trust_env=False
        )
    except httpx.HTTPError as error:
        raise RuntimeError(
            f"Langfuse 服务不可达（{url}）——run 开始前先把它起起来：{error}"
        ) from error
    if response.status_code != 200:
        raise RuntimeError(
            f"Langfuse 健康检查非 200（{url}/api/public/health → {response.status_code}）"
        )
    payload = response.json()
    if payload.get("status") != "OK":
        raise RuntimeError(f"Langfuse 健康检查未通过：{payload}")
    return str(payload.get("version", "unknown"))


def stamp_generation_fields(content: Any) -> dict[str, Any]:
    """Extract SDK generation fields without changing the persisted envelope."""
    if not isinstance(content, dict):
        return {}
    usage = {
        key: content[source]
        for key, source in (("input", "input_tokens"), ("output", "output_tokens"))
        if isinstance(content.get(source), int) and content[source] >= 0
    }
    fields: dict[str, Any] = {"usage_details": usage} if usage else {}
    model = content.get("model")
    if isinstance(model, str) and model:
        fields["model"] = model
    return fields


def generation_input_fields(content: Any) -> dict[str, Any]:
    """generation 的 `input` 投影：发出去的请求（prompt / images）供 Dashboard 直读。

    Langfuse 的惯例是 generation 的 input=请求、output=回复；本项目的无损封套
    （prompt 与 raw 同在一条账里）整份放 output，这里只把请求部分**引**一份进
    input 作展示面——封套本体仍是唯一真源，缺键就不投影（调用方退回占位）。
    """
    if not isinstance(content, dict):
        return {}
    fields: dict[str, Any] = {}
    prompt = content.get("prompt")
    if isinstance(prompt, str) and prompt:
        fields["prompt"] = prompt
    images = content.get("images")
    if isinstance(images, list) and images:
        fields["images"] = images
    return fields


def retrieve_input_fields(content: Any) -> dict[str, Any]:
    """retriever 的 `input` 投影：这次检索的请求面（`query`）供 Dashboard 直读。

    与 `generation_input_fields` 同一条口径：input=请求。六条读口的正文形状是
    `{query, refs}`（`render.retrieve_node`），query 记的就是真正交给记忆读口的
    检索条件（BM25 检索词原文或 `k=v` 等值条件）；refs 是命中清单、封套里有，
    不重复投。缺键退空（调用方退回占位）。
    """
    if not isinstance(content, dict):
        return {}
    query = content.get("query")
    return {"query": query} if isinstance(query, str) and query else {}


def new_event_envelope(
    event_uuid: str,
    seq: int,
    kind: str,
    event_type: str,
    started_at: float,
    ended_at: float,
    meta: dict[str, Any],
    content: Any,
) -> dict[str, Any]:
    """Keep the project event in one lossless, version-neutral output value."""
    return {
        "uuid": event_uuid,
        "seq": seq,
        "kind": kind,
        "type": event_type,
        "started_at": started_at,
        "ended_at": ended_at,
        "meta": meta,
        "content": content,
    }


def matches_meta(event_meta: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Match every requested metadata key by equality."""
    return all(event_meta.get(key) == value for key, value in wanted.items())


def json_decode_meta(value: str) -> dict[str, Any] | None:
    """Decode JSON metadata while treating malformed stored rows as unreadable."""
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def decode_observation_event(observation: object) -> Event | None:
    """Decode only observations carrying this adapter's lossless trace envelope."""
    output = value_of(observation, "output")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return None
    if not isinstance(output, dict):
        return None
    envelope = output.get("pokemon_trace")
    if not isinstance(envelope, dict):
        return None
    try:
        return _Event(
            uuid=str(envelope["uuid"]),
            seq=int(envelope["seq"]),
            kind=str(envelope["kind"]),
            type=str(envelope["type"]),
            started_at=float(envelope["started_at"]),
            ended_at=float(envelope["ended_at"]),
            meta=json.dumps(envelope["meta"], ensure_ascii=False),
            content=json.dumps(envelope["content"], ensure_ascii=False),
        )
    except (KeyError, TypeError, ValueError):
        return None


def create_scope_observation(
    client: LangfuseClientPort,
    trace_id: str,
    name: str,
    metadata: dict[str, Any],
    parent_id: str | None,
) -> str:
    """Create a scope span (a parent anchor only) and end it immediately.

    scope 不带事件封套，`read_events` 永远读不到；OTEL span 不 end() 就不会被
    导出（真机 v4.46 实测缺席，事件全成了无父孤儿），所以创建即结束。
    """
    context: dict[str, str] = {"trace_id": trace_id}
    if parent_id:
        context["parent_span_id"] = parent_id
    observation = client.start_observation(
        trace_context=context,
        name=name,
        as_type="span",
        metadata=metadata,
        version=LANGFUSE_ADAPTER_VERSION,
    )
    observation_id = observation.id
    # 与 `_MIN_SPAN_SECONDS` 同一条口径（langfuse_trace）：scope 锚也是"创建即
    # 结束"，不垫一拍在 Dashboard 里同样被折叠时间段。这里直接 sleep，避免为
    # 一个常量造循环 import。
    time.sleep(0.003)
    observation.end()
    return observation_id


def response_cursor(response: object) -> str | None:
    meta = value_of(response, "meta")
    value = value_of(meta, "cursor") if meta is not None else None
    return str(value) if value else None


def sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def value_of(value: object | None, key: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def observation_time_bounds() -> tuple[datetime, datetime]:
    """Bound API queries: from the earliest allowed time to one second past now.

    下界不用"本实例构造时刻"：同一个 run 恢复后是新进程新实例，上一实例写的
    `checkpoint_save` / 历史 observation 时间在本实例之前——拿构造时刻当下界
    会把它们全部挡在门外（血缘 lookup 与 `read_events` 都会瞎）。兜底取 API
    允许的最早有效时间，数据集由 `trace_id` 限定（见 langfuse-spec §六）。
    """
    start = datetime.fromtimestamp(0.0, tz=UTC)
    return start, datetime.now(UTC) + timedelta(seconds=1)


def _is_local_host(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def read_observations(client: Any, trace_id: str) -> list[object]:
    """Read all currently visible observations with bounded v2 cursor pages."""
    observations: list[object] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        from_start_time, to_start_time = observation_time_bounds()
        kwargs: dict[str, Any] = {
            "trace_id": trace_id,
            "fields": "core,basic,io,metadata,usage",
            "limit": PAGE_SIZE,
            "from_start_time": from_start_time,
            "to_start_time": to_start_time,
        }
        if cursor:
            kwargs["cursor"] = cursor
        response = client.api.observations.get_many(**kwargs)
        observations.extend(sequence(value_of(response, "data", [])))
        next_cursor = response_cursor(response)
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return observations


def create_error_event(
    client: LangfuseClientPort,
    context: dict[str, str],
    name: str,
    input: Any,
    output: Any,
    metadata: dict[str, Any],
) -> str:
    """Create a Langfuse EVENT for an error ledger item under the current step."""
    return client.create_event(
        trace_context=context,
        name=name,
        input=input,
        output=output,
        metadata=metadata,
        version=LANGFUSE_ADAPTER_VERSION,
        level="ERROR",
        status_message=name,
    ).id
