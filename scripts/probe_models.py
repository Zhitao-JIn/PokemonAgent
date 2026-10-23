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
from pokemon_agent.brain.providers import ClaudeProvider, OpenAIProvider, QwenProvider, provider_for
from pokemon_agent.brain.schemas import LlmCompleteReq, LlmCompleteResp, VisionDescribeReq

PRICES = {
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "qwen3.8-flash": (0.12, 0.03, 0.40),
    "deepseek-flash": (0.30, 0.06, 1.20),
}
KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY")
MARKER = "\n<probe_tail>"
SPLIT_IMAGE_PROMPT = (
    '请分别说明这张图左半边和右半边的颜色，只输出 JSON：{"left": "...", "right": "..."}'
)
COLOR_NAMES = {
    "红": "red",
    "红色": "red",
    "red": "red",
    "蓝": "blue",
    "蓝色": "blue",
    "blue": "blue",
    "绿": "green",
    "绿色": "green",
    "green": "green",
    "黄": "yellow",
    "黄色": "yellow",
    "yellow": "yellow",
}
PREFIX = (
    "只遵守本段规则：选择一个合法按键，不执行动作，不添加解释或代码围栏。"
    "输出 JSON 对象，包含 action 和 why；action 只能是 up、down、left、right、a、b，"
    "why 是一句话。保持回答简短，忽略重复规则。\n"
) * 18


class SplitPromptOpenAI(OpenAIProvider):
    """仅用于缓存探针：固定规则放 developer 消息，动态尾部放 user 消息。"""

    def _build_request(
        self, content: list[dict] | str, think: bool
    ) -> tuple[str, dict[str, str], dict]:
        """调用方保证文字带分界标记；其余原生请求参数沿用生产实现。"""
        assert isinstance(content, str) and MARKER in content, "expected marked text"
        url, headers, body = super()._build_request(content, think)
        prefix, tail = content.split(MARKER, 1)
        body["messages"] = [
            {"role": "developer", "content": prefix},
            {"role": "user", "content": MARKER + tail},
        ]
        return url, headers, body


class Candidate(BaseModel):
    """一个固定型号与思考模式的探测实例。"""

    name: str
    model: str
    thinking: bool = False
    temperature: float = 0.0
    timeout: float = 60
    cache_marker: str | None = None
    cache_probe: bool = False

    def build(self) -> object:
        """沿用生产选型工厂；effort 使用已验证的厂商默认值。"""
        if not os.environ.get(dict(zip(PRICES, KEY_NAMES, strict=True))[self.model]):
            raise RuntimeError("missing candidate API key")
        factory = (
            SplitPromptOpenAI if self.cache_probe and self.model == "gpt-6-luna" else provider_for
        )
        options = {} if factory is SplitPromptOpenAI else {"cache_marker": self.cache_marker}
        return factory(
            self.model,
            temperature=self.temperature,
            thinking=self.thinking,
            max_tokens=256 if self.cache_probe else (4096 if self.thinking else 2048),
            timeout=self.timeout,
            **options,
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
    cache_strategy: str = ""


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
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--suite", choices=("base", "supplement", "supplement2"), default="base")
    parser.add_argument("--report-from", nargs="+", type=Path)
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--max-cost-usd", type=float)
    args = parser.parse_args(argv)
    limits = {"base": (60, 0.3, 60), "supplement": (30, 0.08, 30), "supplement2": (30, 0.03, 20)}
    request_limit, cost_limit, default_requests = limits[args.suite]
    args.max_requests = default_requests if args.max_requests is None else args.max_requests
    args.max_cost_usd = cost_limit if args.max_cost_usd is None else args.max_cost_usd
    if not args.out.is_absolute() or not 1 <= args.max_requests <= request_limit:
        parser.error(f"absolute --out and 1..{request_limit} --max-requests required")
    if not 0 < args.max_cost_usd <= cost_limit:
        parser.error(f"--max-cost-usd must be in (0, {cost_limit}]")
    if args.suite == "supplement" and (args.cache_only or args.candidates != "all"):
        parser.error("supplement has fixed candidates; do not combine --cache-only/--candidates")
    if args.suite == "supplement2" and (args.cache_only or args.candidates != "all"):
        parser.error("supplement2 has fixed candidates; do not combine --cache-only/--candidates")
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


def image_uri(
    left: tuple[int, int, int] = (255, 0, 0), right: tuple[int, int, int] = (0, 0, 255)
) -> str:
    """仅用标准库生成双色 RGB PNG；调用方保证颜色是三个有效字节。"""
    assert len(left) == len(right) == 3 and all(0 <= c <= 255 for c in (*left, *right))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = (b"\0" + bytes(left) * 80 + bytes(right) * 80) * 144
    header = struct.pack(">IIBBBBB", 160, 144, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    png += chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def candidates(selection: str, cache_only: bool = False) -> list[Candidate]:
    """四个候选先各安排一次，随后才安排思考对照实例。"""
    if cache_only:
        return [
            Candidate(
                name="c1_cache", model="claude-haiku-5-5", cache_marker=MARKER, cache_probe=True
            ),
            Candidate(name="c2_split", model="gpt-6-luna", cache_probe=True),
        ]
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
    result = Record(
        name=candidate.name, kind=kind, index=index, cache_strategy=cache_strategy(candidate)
    )
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
        "|实例|缓存策略|可用性|成功率|时延 min/median/max 秒|缓存率 2–6|"
        "JSON|图片送达/正确|推理中位数|错误|",
        "|---|---|---|---|---|---|---|---|---|---|",
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
            f"|{item.name}|{cache_strategy(item)}|{'可用' if success else '不可用/未证实'}|"
            f"{len(success)}/{len(rows)}|"
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
    if args.report_from:
        return report_saved(args.out, args.report_from)
    load_environment(args.env_file)
    if args.suite == "supplement2":
        items = supplement2_candidates()
    elif args.suite == "supplement":
        items = supplement_candidates()
    else:
        items = candidates(args.candidates, args.cache_only)
    providers, unavailable = {}, {}
    for item in items:
        try:
            providers[item.name] = item.build()
        except Exception as error:
            unavailable[item.name] = redact(f"{type(error).__name__}: {error}")
    if args.dry_run:
        configs = {n: p.config() for n, p in providers.items()}
        print(json.dumps(dict(configs=configs, unavailable=unavailable), ensure_ascii=False))
        required = args.suite in ("supplement", "supplement2")
        return 0 if providers and not (required and unavailable) else 1
    if args.suite in ("supplement", "supplement2") and unavailable:
        print(json.dumps(dict(unavailable=unavailable), ensure_ascii=False))
        return 1
    args.out.mkdir(parents=True, exist_ok=False)
    budget = Budget(max_requests=args.max_requests, max_cost=args.max_cost_usd)
    if args.suite == "supplement2":
        records, reason = execute_supplement2(items, providers, budget)
    else:
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
    renderers = {"supplement": supplement_summary, "supplement2": supplement2_summary}
    renderer = renderers.get(args.suite, summary)
    (args.out / "summary.md").write_text(
        renderer(items, records, unavailable, budget, reason), encoding="utf-8"
    )
    print(f"requests={budget.requests} estimated_cost_usd={budget.cost:.6f}")
    return 0


def trials(items: list[Candidate]) -> list[tuple[Candidate, str, int]]:
    """基础测试优先，末尾添加额外缓存实例；调用方保证候选非空。"""
    assert items, "expected selected candidates"
    if all(item.cache_probe for item in items):
        return [(item, "text", index) for index in range(1, 7) for item in items]
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
    if isinstance(items[0], SupplementCandidate):
        return execute_supplement(items, providers, budget)
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


class SupplementCandidate(Candidate):
    """补测实例独立构造，token_floor 只对带图的图片实例设为零。"""

    purpose: str
    prefix: str = ""
    image_detail: str | None = None

    def build(self) -> object:
        """按补测白名单构造，任一所需密钥缺失均拒绝真实运行。"""
        factories = {
            "claude-haiku-5-5": ClaudeProvider,
            "gpt-6-luna": OpenAIProvider,
            "qwen3.8-flash": QwenProvider,
        }
        key_name = dict(zip(PRICES, KEY_NAMES, strict=True))[self.model]
        if not os.environ.get(key_name):
            raise RuntimeError(f"missing {key_name}")
        options = {}
        if self.cache_marker is not None:
            options["cache_marker"] = self.cache_marker
        if self.image_detail is not None:
            options["image_detail"] = self.image_detail
        if self.purpose != "cache":
            options["token_floor"] = 0
        return factories[self.model](
            self.model,
            temperature=self.temperature,
            max_tokens=2048,
            timeout=self.timeout,
            thinking=False,
            **options,
        )


class SupplementRecord(Record):
    """额外保存旧下限比较和未缓存输入量，不伪称获得了原始缓存写入量。"""

    image_count: int = 0
    old_floor: int = 0
    uncached_input_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    waited_seconds: int = 0
    image_json_valid: bool | None = None
    image_colors_correct: bool | None = None
    image_fence_removed: bool = False


def supplement_candidates() -> list[SupplementCandidate]:
    """按前次实测分词量近似三千 token，固定规则的文字单元保持一致。"""
    unit = PREFIX[: len(PREFIX) // 18]
    return [
        SupplementCandidate(name="claude_images", model="claude-haiku-5-5", purpose="image"),
        SupplementCandidate(name="luna_images", model="gpt-6-luna", purpose="image"),
        SupplementCandidate(
            name="qwen_images", model="qwen3.8-flash", purpose="image", temperature=0.3, timeout=30
        ),
        SupplementCandidate(
            name="luna_cache_long", model="gpt-6-luna", purpose="cache", prefix=unit * 47
        ),
        SupplementCandidate(
            name="claude_cache_long",
            model="claude-haiku-5-5",
            purpose="cache",
            prefix=unit * 31,
            cache_marker="\n### 当前输入\n",
        ),
    ]


def supplement2_candidates() -> list[SupplementCandidate]:
    """两个图片 detail 实例与一个分消息带图实例；静态前缀沿用同一文字单元。"""
    unit = PREFIX[: len(PREFIX) // 18]
    return [
        SupplementCandidate(
            name="luna_detail_high", model="gpt-6-luna", purpose="detail", image_detail="high"
        ),
        SupplementCandidate(
            name="luna_detail_auto", model="gpt-6-luna", purpose="detail", image_detail="auto"
        ),
        SupplementCandidate(
            name="luna_split_image",
            model="gpt-6-luna",
            purpose="split_image",
            prefix=unit * 47,
            cache_marker=MARKER,
            image_detail="high",
        ),
    ]


def strip_fence(text: str) -> tuple[str, bool]:
    """剥掉包住整段回答的 Markdown 代码围栏，返回正文与是否曾带围栏。"""
    fence = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\s*```\s*", text, re.S | re.I)
    if fence is None:
        return text, False
    return fence[1], True


def single_image_answer_correct(text: str) -> bool:
    """判定单图 JSON `{"left": ..., "right": ...}` 是否为红左蓝右。"""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    actual = tuple(
        COLOR_NAMES.get(str(value.get(side, "")).strip().lower()) for side in ("left", "right")
    )
    return actual == ("red", "blue")


def image_answer_correct(text: str, count: int) -> bool:
    """要求 JSON、条数和每图左右颜色都一致，支持中英文颜色词。"""
    colors = COLOR_NAMES
    try:
        value = json.loads(text)
        rows = value.get("images") if isinstance(value, dict) else None
        if not isinstance(rows, list) or len(rows) != count:
            return False
        expected = [("red", "blue"), ("green", "yellow")][:count]
        for row, truth in zip(rows, expected, strict=True):
            if not isinstance(row, dict):
                return False
            actual = tuple(
                colors.get(str(row.get(side, "")).strip().lower()) for side in ("left", "right")
            )
            if actual != truth:
                return False
        return True
    except (ValueError, TypeError):
        return False


def cache_strategy(item: Candidate) -> str:
    """明确区分探针的分消息布局、单消息布局与 Claude 显式缓存断点。"""
    if item.model.startswith("claude"):
        return "explicit_marker" if item.cache_marker else "disabled"
    if item.model == "gpt-6-luna":
        return "split_messages" if item.cache_probe else "single_message"
    return "implicit"


def add_diagnostics(result: SupplementRecord, item: Candidate) -> SupplementRecord:
    """添加诊断字段；不修改原来的严格 image_correct 评分。"""
    result.cache_strategy = cache_strategy(item)
    if result.kind != "image" or result.error:
        return result
    try:
        json.loads(result.text)
        result.image_json_valid = True
    except (ValueError, TypeError):
        result.image_json_valid = False
    fence = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\s*```\s*", result.text, re.S | re.I)
    result.image_fence_removed = fence is not None
    diagnostic_text = fence[1] if fence else result.text
    result.image_colors_correct = image_answer_correct(diagnostic_text, result.image_count)
    return result


def supplement_response(item: SupplementCandidate, provider: object, index: int) -> LlmCompleteResp:
    """使用公开 complete/describe，保留生产响应映射，不读取或修改 provider 内部状态。"""
    if item.purpose == "cache":
        marker = item.cache_marker or MARKER
        return provider.complete(
            LlmCompleteReq(prompt=item.prefix + marker + str(index)), timeout_s=item.timeout
        )
    if item.purpose == "split_image":
        response = provider.describe(
            VisionDescribeReq(
                prompt=item.prefix + MARKER + SPLIT_IMAGE_PROMPT, images=[image_uri()]
            ),
            timeout_s=item.timeout,
        )
        return LlmCompleteResp(
            text=response.text,
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            reasoning_tokens=response.reasoning_tokens,
            truncated=response.truncated,
        )
    images = [image_uri()]
    if index > 2:
        images.append(image_uri((0, 255, 0), (255, 255, 0)))
    response = provider.describe(
        VisionDescribeReq(
            prompt="请依次说出每张图左半边和右半边的颜色，只输出 JSON："
            '{"images": [{"left": "...", "right": "..."}, ...]}',
            images=images,
        ),
        timeout_s=item.timeout,
    )
    return LlmCompleteResp(
        text=response.text,
        prompt_tokens=response.input_tokens,
        completion_tokens=response.output_tokens,
        cached_tokens=response.cached_tokens,
        reasoning_tokens=response.reasoning_tokens,
        truncated=response.truncated,
    )


def supplement_call(item: SupplementCandidate, provider: object, index: int) -> SupplementRecord:
    """调用一次并记录完整可见 usage；缓存写入量未暴露时保留为 null。"""
    result = SupplementRecord(name=item.name, kind=item.purpose, index=index)
    if item.purpose == "image":
        result.image_count = 1 if index <= 2 else 2
        result.old_floor = result.image_count * 100
    started = time.monotonic()
    try:
        response = supplement_response(item, provider, index)
        result = result.model_copy(update=response.model_dump())
        result.text = redact(result.text)
        result.uncached_input_tokens = max(result.prompt_tokens - result.cached_tokens, 0)
        if item.purpose == "image":
            result.image_delivered = True
            result.image_correct = image_answer_correct(result.text, result.image_count)
        else:
            result.json_valid = has_action(result.text)
    except Exception as error:
        result.error, result.message = type(error).__name__, redact(str(error))
        status = re.search(r"HTTP (\d{3})", str(error))
        result.status = int(status[1]) if status else 0
        if isinstance(error, EmptyCompletion):
            result.completion_tokens, result.reasoning_tokens = (
                error.completion_tokens,
                error.reasoning_tokens,
            )
    result.latency = time.monotonic() - started
    result.estimated_cost = estimate(
        item.model, result.prompt_tokens, result.cached_tokens, result.completion_tokens
    )
    if result.error and result.status not in (400, 401, 403, 404, 429):
        result.estimated_cost = estimate(item.model, len(item.prefix.encode()) + 5000, 0, 2048)
    return add_diagnostics(result, item)


def supplement2_call(item: SupplementCandidate, provider: object, index: int) -> SupplementRecord:
    """调用一次；判定前先剥围栏，围栏事实单独记录。"""
    result = SupplementRecord(
        name=item.name,
        kind=item.purpose,
        index=index,
        cache_strategy="split_messages" if item.purpose == "split_image" else "single_message",
    )
    result.image_count = 1 if item.purpose == "split_image" or index <= 2 else 2
    started = time.monotonic()
    try:
        response = supplement_response(item, provider, index)
        result = result.model_copy(update=response.model_dump())
        result.text = redact(result.text)
        result.uncached_input_tokens = max(result.prompt_tokens - result.cached_tokens, 0)
        result.image_delivered = True
        stripped, result.image_fence_removed = strip_fence(result.text)
        try:
            json.loads(stripped)
            result.image_json_valid = True
        except (ValueError, TypeError):
            result.image_json_valid = False
        result.image_correct = (
            single_image_answer_correct(stripped)
            if item.purpose == "split_image"
            else image_answer_correct(stripped, result.image_count)
        )
    except Exception as error:
        result.error, result.message = type(error).__name__, redact(str(error))
        status = re.search(r"HTTP (\d{3})", str(error))
        result.status = int(status[1]) if status else 0
        if isinstance(error, EmptyCompletion):
            result.completion_tokens, result.reasoning_tokens = (
                error.completion_tokens,
                error.reasoning_tokens,
            )
    result.latency = time.monotonic() - started
    result.estimated_cost = estimate(
        item.model, result.prompt_tokens, result.cached_tokens, result.completion_tokens
    )
    if result.error and result.status not in (400, 401, 403, 404, 429):
        result.estimated_cost = estimate(item.model, len(item.prefix.encode()) + 5000, 0, 2048)
    return result


def execute_supplement(
    items: list[SupplementCandidate], providers: dict[str, object], budget: Budget
) -> tuple[list[SupplementRecord], str]:
    """图片先各做首次调用；Luna 连续六次、等待后第七次，Claude 连续六次。"""
    image_items = [item for item in items if item.purpose == "image"]
    schedule = [(item, index) for index in range(1, 5) for item in image_items]
    schedule += [
        (item, index)
        for item in items
        if item.purpose == "cache"
        for index in range(1, 8 if item.model == "gpt-6-luna" else 7)
    ]
    records, blocked, first = [], set(), {}
    reason = ""
    for item, index in schedule:
        reason = budget.stopped()
        if reason:
            break
        if item.model in blocked:
            continue
        reserve = estimate(item.model, len(item.prefix.encode()) + 5000, 0, 2048)
        if budget.cost + reserve > budget.max_cost:
            reason = "剩余额度不足，因费用闸提前停止"
            break
        waited = item.name == "luna_cache_long" and index == 7
        if waited:
            time.sleep(15)
        result = supplement_call(item, providers[item.name], index)
        result.waited_seconds = 15 if waited else 0
        records.append(result)
        budget.requests += 1
        budget.cost += result.estimated_cost
        first.setdefault(item.model, not result.error)
        if result.status in (401, 403):
            blocked.add(item.model)
        if len(first) == len(image_items) and not any(first.values()):
            reason = "所有对象首次调用失败，停止"
            break
    return records, reason or budget.stopped()


def execute_supplement2(
    items: list[SupplementCandidate], providers: dict[str, object], budget: Budget
) -> tuple[list[SupplementRecord], str]:
    """两个 detail 实例各四次单/双图，分消息带图实例连续四次；无重试。"""
    detail_items = [item for item in items if item.purpose == "detail"]
    schedule = [(item, index) for index in range(1, 5) for item in detail_items]
    schedule += [
        (item, index) for item in items if item.purpose == "split_image" for index in range(1, 5)
    ]
    records, reason = [], ""
    for item, index in schedule:
        reason = budget.stopped()
        if reason:
            break
        reserve = estimate(item.model, len(item.prefix.encode()) + 5000, 0, 2048)
        if budget.cost + reserve > budget.max_cost:
            reason = "剩余额度不足，因费用闸提前停止"
            break
        result = supplement2_call(item, providers[item.name], index)
        records.append(result)
        budget.requests += 1
        budget.cost += result.estimated_cost
        if result.status in (401, 403):
            reason = "首次调用返回 401/403，停止"
            break
    return records, reason or budget.stopped()


def supplement2_summary(
    items: list[SupplementCandidate],
    records: list[SupplementRecord],
    unavailable: dict[str, str],
    budget: Budget,
    reason: str,
) -> str:
    """只列逐次数字与 min/median/max，不给出通过与否或型号能力结论。"""
    lines = [
        "图片 detail（token_floor=0，判定前剥离 Markdown 围栏）：",
        "|实例|图数|正确|输入 token min/median/max|时延 min/median/max 秒|围栏数|",
        "|---|---|---|---|---|---|",
    ]
    for item in (i for i in items if i.purpose == "detail"):
        for count in (1, 2):
            rows = [r for r in records if r.name == item.name and r.image_count == count]
            correct = sum(r.image_correct is True for r in rows)
            lines.append(
                f"|{item.name}（detail={item.image_detail}）|{count}|{correct}/{len(rows)}|"
                f"{spread([r.prompt_tokens for r in rows], 0)}|"
                f"{spread([r.latency for r in rows])}|"
                f"{sum(r.image_fence_removed for r in rows)}|"
            )
    lines += [
        "",
        "分消息 + 图片（developer/user 分界，image_detail=high）：",
        "|实例|序号|输入 token|命中 token|时延秒|正确|围栏|错误|",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in (r for r in records if r.kind == "split_image"):
        lines.append(
            f"|{row.name}|{row.index}|{row.prompt_tokens}|{row.cached_tokens}|"
            f"{row.latency:.3f}|{'是' if row.image_correct else '否'}|"
            f"{'是' if row.image_fence_removed else '否'}|{row.error}|"
        )
    lines += [
        "围栏数表示回答被 Markdown 代码围栏包住的次数；本套件判定前已剥离围栏。",
        "输入 token 的数字来自响应的 usage；命中 token 仅 OpenAI 返回值。",
        f"总请求数：{budget.requests}；估算费用：${budget.cost:.6f}；"
        f"费用闸触发：{'是' if '费用闸' in reason else '否'}；停止原因：{reason or '完成'}。",
    ]
    if unavailable:
        lines.append(str(unavailable))
    return "\n".join(lines) + "\n"


def spread(values: list[float], digits: int = 3) -> str:
    """min/median/max 三值；没有样本时记破折号。"""
    if not values:
        return "—"
    points = (min(values), statistics.median(values), max(values))
    return "/".join(f"{value:.{digits}f}" for value in points)


def supplement_image_lines(
    items: list[SupplementCandidate], records: list[SupplementRecord]
) -> list[str]:
    """列出颜色判定计数与旧 token 下限的数值对比。"""
    lines = [
        "图片（token_floor=0，仅本套件实例）：",
        "|对象|单图严格正确|双图严格正确|JSON 合法|颜色诊断正确|围栏数|"
        "单图/双图输入 token|旧下限对比|",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in (i for i in items if i.purpose == "image"):
        groups = [
            [r for r in records if r.name == item.name and r.image_count == count]
            for count in (1, 2)
        ]
        counts = [f"{sum(r.image_correct is True for r in group)}/{len(group)}" for group in groups]
        ranges = [
            f"{min(r.prompt_tokens for r in group)}–{max(r.prompt_tokens for r in group)}"
            if group
            else "—"
            for group in groups
        ]
        below = [
            sum(not r.error and r.prompt_tokens < r.old_floor for r in group) for group in groups
        ]
        rows = [add_diagnostics(r, item) for group in groups for r in group]
        valid = sum(r.image_json_valid is True for r in rows)
        colors = sum(r.image_colors_correct is True for r in rows)
        fences = sum(r.image_fence_removed for r in rows)
        lines.append(
            f"|{item.model}|{counts[0]}|{counts[1]}|{valid}/{len(rows)}|{colors}/{len(rows)}|"
            f"{fences}|{ranges[0]}/{ranges[1]}|"
            f"{below[0]} 次 <100；{below[1]} 次 <200|"
        )
    lines.append("颜色诊断允许移除外层 Markdown 围栏；严格正确评分仍要求原文是合法 JSON。")
    return lines


def supplement_summary(
    items: list[SupplementCandidate],
    records: list[SupplementRecord],
    unavailable: dict[str, str],
    budget: Budget,
    reason: str,
) -> str:
    """只列观察数字，不给出通过与否或厂商能力结论。"""
    lines = supplement_image_lines(items, records)
    lines += [
        "",
        "缓存：",
        "|对象|缓存策略|序号|输入 token|命中 token|未缓存输入量|时延秒|等待秒|错误|",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in (r for r in records if r.kind == "cache"):
        lines.append(
            f"|{row.name}|{row.cache_strategy}|{row.index}|{row.prompt_tokens}|{row.cached_tokens}|"
            f"{row.uncached_input_tokens}|{row.latency:.3f}|{row.waited_seconds}|{row.error}|"
        )
    luna = [r for r in records if r.name == "luna_cache_long"]
    if len(luna) == 7:
        lines += [
            f"Luna 第 6→7 次：命中 {luna[5].cached_tokens}→{luna[6].cached_tokens}；"
            f"命中量是否变化：{'是' if luna[5].cached_tokens != luna[6].cached_tokens else '否'}。"
        ]
    lines += [
        "Claude 原始 cache_creation_input_tokens 未由 provider 暴露，结果中为 null。",
        "未缓存输入量=prompt_tokens−cached_tokens，包含普通输入与缓存写入，不能等同缓存写入量。",
        "single_message 是原生产单消息布局；split_messages 是探针的 developer/user 分消息布局。",
        f"总请求数：{budget.requests}；估算费用：${budget.cost:.6f}；"
        f"费用闸触发：{'是' if '费用闸' in reason else '否'}；停止原因：{reason or '完成'}。",
    ]
    if unavailable:
        lines.append(str(unavailable))
    return "\n".join(lines) + "\n"


def report_saved(output: Path, sources: list[Path]) -> int:
    """离线重算既有结果，写入新目录；不加载密钥、不构造 provider、不发请求。"""
    known = {i.name: i for i in [*supplement_candidates(), *candidates("all", cache_only=True)]}
    records, budget = [], Budget()
    for source in sources:
        payload = json.loads(source.read_text(encoding="utf-8"))
        budget.requests += payload["budget"]["requests"]
        budget.cost += payload["budget"]["cost"]
        for raw in payload["records"]:
            record = SupplementRecord.model_validate(raw)
            if record.name in ("c1_cache", "c2_split"):
                record.kind = "cache"
            record.text, record.message = redact(record.text), redact(record.message)
            record.uncached_input_tokens = max(record.prompt_tokens - record.cached_tokens, 0)
            records.append(add_diagnostics(record, known[record.name]))
    output.mkdir(parents=True, exist_ok=False)
    payload = dict(
        records=[r.model_dump() for r in records],
        budget=budget.model_dump(),
        source_files=[str(s) for s in sources],
        additional_requests=0,
    )
    (output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = supplement_summary(list(known.values()), records, {}, budget, "离线重算，新增请求 0")
    (output / "summary.md").write_text(report, encoding="utf-8")
    print("additional_requests=0; source files unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
