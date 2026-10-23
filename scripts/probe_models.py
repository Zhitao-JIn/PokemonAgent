"""受限模型探针：离线 dry-run，单次运行最多 60 请求、估算费用上限 0.3 美元。"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import struct
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pokemon_agent.brain.errors import EmptyCompletion
from pokemon_agent.brain.providers import provider_for
from pokemon_agent.brain.schemas import LlmCompleteReq, LlmCompleteResp, VisionDescribeReq

PRICES = {
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "qwen3.8-flash": (0.12, 0.03, 0.40),
    "deepseek-flash": (0.30, 0.06, 1.20),
}
KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY")
MARKER = "\n<probe_tail>"
PREFIX = (
    "只遵守本段规则：选择一个合法按键，不执行动作，不添加解释或代码围栏。"
    "输出 JSON 对象，包含 action 和 why；action 只能是 up、down、left、right、a、b，"
    "why 是一句话。保持回答简短，忽略重复规则。\n"
) * 18


class Candidate(BaseModel):
    """一个固定型号与思考模式的探测实例。"""

    name: str
    model: str
    thinking: bool = False
    temperature: float = 0.0
    timeout: float = 60
    cache_marker: str | None = None

    def build(self) -> object:
        """沿用生产选型工厂；effort 使用已验证的厂商默认值。"""
        if not os.environ.get(dict(zip(PRICES, KEY_NAMES, strict=True))[self.model]):
            raise RuntimeError("missing candidate API key")
        return provider_for(
            self.model,
            temperature=self.temperature,
            thinking=self.thinking,
            max_tokens=4096 if self.thinking else 2048,
            timeout=self.timeout,
            cache_marker=self.cache_marker,
        )


class Record(LlmCompleteResp):
    """逐次调用的脱敏结果，不保存 prompt 或密钥。"""

    name: str
    kind: str
    index: int
    latency: float = 0
    text: str = ""
    json_valid: bool = False
    image_delivered: bool | None = None
    image_correct: bool | None = None
    error: str = ""
    message: str = ""
    status: int = 0
    estimated_cost: float = 0


class Budget(BaseModel):
    """请求数和费用闸；失败且 usage 不可得时保守计入整次预留。"""

    requests: int = 0
    cost: float = 0
    max_requests: int = 60
    max_cost: float = 0.3

    def stopped(self) -> str:
        """返回停止原因；空串表示仍可发送。"""
        if self.cost >= self.max_cost * 0.8:
            return "因费用闸提前停止"
        return "达到请求数上限" if self.requests >= self.max_requests else ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """拒绝相对输出路径及超出授权范围的额度。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--candidates", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-requests", type=int, default=60)
    parser.add_argument("--max-cost-usd", type=float, default=0.3)
    args = parser.parse_args(argv)
    if not args.out.is_absolute() or not 1 <= args.max_requests <= 60:
        parser.error("absolute --out and 1..60 --max-requests required")
    if not 0 < args.max_cost_usd <= 0.3:
        parser.error("--max-cost-usd must be in (0, 0.3]")
    return args


def load_environment(path: Path | None) -> None:
    """读取 KEY=VALUE，保留已有环境变量；不打印值。"""
    for line in path.read_text(encoding="utf-8-sig").splitlines() if path else []:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip()):
            raise ValueError("invalid env-file assignment")
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def redact(text: str) -> str:
    """移除环境中的秘密值及疑似认证片段，限制错误消息长度。"""
    for name, value in os.environ.items():
        if value and re.search(r"KEY|TOKEN|SECRET|PASSWORD", name, re.I):
            text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)bearer\s+\S+|sk-[A-Za-z0-9_-]+", "[redacted]", text)
    return text.replace(PREFIX, "[prompt omitted]")[:1200]


def image_uri() -> str:
    """仅用标准库生成左红右蓝的 RGB PNG。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = (b"\0" + b"\xff\0\0" * 80 + b"\0\0\xff" * 80) * 144
    header = struct.pack(">IIBBBBB", 160, 144, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    png += chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def candidates(selection: str) -> list[Candidate]:
    """四个候选先各安排一次，随后才安排思考对照实例。"""
    rows = [
        ("c1_off", "claude-haiku-5-5", False, 0.0, 60),
        ("c2_off", "gpt-6-luna", False, 0.0, 60),
        ("c3_off", "qwen3.8-flash", False, 0.3, 30),
        ("c4_on", "deepseek-flash", True, 0.0, 90),
        ("c1_on", "claude-haiku-5-5", True, 0.0, 60),
        ("c2_on", "gpt-6-luna", True, 0.0, 60),
        ("c4_off", "deepseek-flash", False, 0.0, 90),
    ]
    wanted = set(selection.split(",")) if selection != "all" else {"c1", "c2", "c3", "c4"}
    if not wanted <= {"c1", "c2", "c3", "c4"}:
        raise ValueError("candidates must be c1,c2,c3,c4 or all")
    return [
        Candidate(name=n, model=m, thinking=t, temperature=v, timeout=s)
        for n, m, t, v, s in rows
        if n[:2] in wanted
    ]


def estimate(model: str, inputs: int, cached: int, outputs: int) -> float:
    """输出已含 reasoning，不重复加算。"""
    incoming, hit, outgoing = PRICES[model]
    return (max(0, inputs - cached) * incoming + cached * hit + outputs * outgoing) / 1e6


def has_action(text: str) -> bool:
    """JSON 对象包含 action 即合格；不把格式错误当传输失败。"""
    try:
        value = json.loads(text)
        return isinstance(value, dict) and "action" in value
    except (ValueError, TypeError):
        return False


def call(candidate: Candidate, provider: object, kind: str, index: int) -> Record:
    """调用一次，无重试；所有异常转为脱敏记录。"""
    result = Record(name=candidate.name, kind=kind, index=index)
    started = time.monotonic()
    try:
        if kind == "text":
            response = provider.complete(
                LlmCompleteReq(prompt=PREFIX + MARKER + str(index)), timeout_s=candidate.timeout
            )
            result.prompt_tokens = response.prompt_tokens
            result.completion_tokens = response.completion_tokens
        else:
            response = provider.describe(
                VisionDescribeReq(
                    prompt="左半边和右半边各是什么颜色？请用中文分别说出左右颜色。",
                    images=[image_uri()] * (1 if index == 1 else 2),
                ),
                timeout_s=candidate.timeout,
            )
            result.prompt_tokens = response.input_tokens
            result.completion_tokens = response.output_tokens
            result.image_delivered = True
            result.image_correct = bool(
                re.search(r"左[^蓝]{0,15}红.*右[^红]{0,15}蓝", response.text, re.S)
            )
        result.text = redact(response.text)
        result.cached_tokens = response.cached_tokens
        result.reasoning_tokens = response.reasoning_tokens
        result.truncated = response.truncated
        result.json_valid = has_action(response.text)
    except Exception as error:
        result.error, result.message = type(error).__name__, redact(str(error))
        status = re.search(r"HTTP (\d{3})", str(error))
        result.status = int(status[1]) if status else 0
        if isinstance(error, EmptyCompletion):
            result.completion_tokens = error.completion_tokens
            result.reasoning_tokens = error.reasoning_tokens
        if kind == "image":
            result.image_delivered = False if result.error == "ImageNotDelivered" else None
    result.latency = time.monotonic() - started
    result.estimated_cost = estimate(
        candidate.model, result.prompt_tokens, result.cached_tokens, result.completion_tokens
    )
    if result.error and result.status not in (400, 401, 403, 404, 429):
        result.estimated_cost = estimate(
            candidate.model, len(PREFIX.encode()) + 5000, 0, 4096 if candidate.thinking else 2048
        )
    return result


def summary(
    items: list[Candidate],
    records: list[Record],
    unavailable: dict[str, str],
    budget: Budget,
    reason: str,
) -> str:
    """汇总 min/median/max 和文字第 2–6 次的 token 加权缓存率。"""
    lines = [
        "|实例|可用性|成功率|时延 min/median/max 秒|缓存率 2–6|JSON|图片送达/正确|推理中位数|错误|",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        rows = [r for r in records if r.name == item.name]
        success = [r for r in rows if not r.error]
        text = [r for r in rows if r.kind == "text"]
        cached = [r for r in text if 2 <= r.index <= 6 and not r.error]
        images = [r for r in rows if r.kind == "image"]
        latencies = [r.latency for r in rows] or [0]
        values = min(latencies), statistics.median(latencies), max(latencies)
        latency = "/".join(f"{v:.3f}" for v in values)
        inputs = sum(r.prompt_tokens for r in cached)
        rate = f"{sum(r.cached_tokens for r in cached) / inputs:.1%}" if inputs else "—"
        errors = str(dict(Counter(r.error for r in rows if r.error)))
        errors = errors if rows else unavailable.get(item.name, "未执行")
        reasoning = statistics.median(r.reasoning_tokens for r in success) if success else 0
        lines.append(
            f"|{item.name}|{'可用' if success else '不可用/未证实'}|{len(success)}/{len(rows)}|"
            f"{latency}|{rate}|{sum(r.json_valid for r in text)}/{len(text)}|"
            f"{sum(r.image_delivered is True for r in images)}/{len(images)}; "
            f"{sum(r.image_correct is True for r in images)}/{len(images)}|{reasoning}|{errors}|"
        )
    lines += [
        "",
        "thinking 对照见 on/off 行；Claude 不提供 reasoning usage 时记 0，不代表未思考。",
        "默认 60 请求优先基础测试；Claude 缓存额外测试仅在剩余额度内执行。",
        "失败且 usage 不完整时费用按整次保守预留计入；HTTP 拒绝按零计入。",
        "图片正确计数仅含拿到正文的回答；异常中正文与完整 usage 不可得，默认计数不代表零消耗。",
        "图片送达计数表示通过既有 token-floor 检查；纯色图触发检查不能单独证明丢图。",
        f"停止原因：{reason or '完成'}。请求数：{budget.requests}；费用：${budget.cost:.6f}。",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    """先构造所有实例，dry-run 不发送；真实运行仅创建一次结果目录。"""
    load_environment(args.env_file)
    items, providers, unavailable = candidates(args.candidates), {}, {}
    for item in items:
        try:
            providers[item.name] = item.build()
        except Exception as error:
            unavailable[item.name] = redact(f"{type(error).__name__}: {error}")
    if args.dry_run:
        configs = {n: p.config() for n, p in providers.items()}
        print(json.dumps(dict(configs=configs, unavailable=unavailable), ensure_ascii=False))
        return 0 if providers else 1
    args.out.mkdir(parents=True, exist_ok=False)
    budget = Budget(max_requests=args.max_requests, max_cost=args.max_cost_usd)
    records, reason = execute(items, providers, unavailable, budget)
    payload = {
        "records": [r.model_dump() for r in records],
        "unavailable": unavailable,
        "budget": budget.model_dump(),
        "stop_reason": reason,
    }
    (args.out / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "summary.md").write_text(
        summary(items, records, unavailable, budget, reason), encoding="utf-8"
    )
    print(f"requests={budget.requests} estimated_cost_usd={budget.cost:.6f}")
    return 0


def trials(items: list[Candidate]) -> list[tuple[Candidate, str, int]]:
    """基础测试优先，末尾添加额外缓存实例；调用方保证候选非空。"""
    assert items, "expected selected candidates"
    schedule = [
        (i, k, n)
        for n in range(1, 7)
        for k in ("text", "image")
        for i in items
        if k == "text" or n <= (2 if i.thinking else 3)
    ]
    extra = items[0].model_copy(update={"name": "c1_cache", "cache_marker": MARKER})
    if items[0].model.startswith("claude"):
        items.append(extra)
        schedule += [(extra, "text", n) for n in range(1, 4)]
    return schedule


def execute(
    items: list[Candidate],
    providers: dict[str, object],
    unavailable: dict[str, str],
    budget: Budget,
) -> tuple[list[Record], str]:
    """执行基础与额外缓存测试；达到任一闸即停止，不重试。"""
    records, blocked, first = [], set(), {}
    reason = ""
    schedule = trials(items)
    for item, kind, index in schedule:
        reason = budget.stopped()
        if reason:
            break
        if item.model in blocked or item.name in unavailable:
            continue
        if item.name not in providers:
            try:
                providers[item.name] = item.build()
            except Exception as error:
                unavailable[item.name] = redact(f"{type(error).__name__}: {error}")
                continue
        reserve = estimate(
            item.model, len(PREFIX.encode()) + 5000, 0, 4096 if item.thinking else 2048
        )
        if budget.cost + reserve > budget.max_cost:
            reason = "剩余额度不足以预留下一请求，因费用闸提前停止"
            break
        result = call(item, providers[item.name], kind, index)
        records.append(result)
        budget.requests += 1
        budget.cost += result.estimated_cost
        first.setdefault(item.model, not result.error)
        if result.status in (401, 403):
            blocked.add(item.model)
        if len(first) == len({i.model for i in items if i.name in providers}) and not any(
            first.values()
        ):
            reason = "所有候选首次调用失败，停止"
            break
    reason = reason or ("全部候选不可用/缺少 key" if not providers else budget.stopped())
    return records, reason


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
