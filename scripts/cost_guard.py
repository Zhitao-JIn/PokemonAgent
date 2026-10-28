"""监视子进程的 DeepSeek 人民币余额，达到费用上限时终止运行。"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pokemon_agent.env import env_str, load_env_file
from scripts.model_prices import estimate
from scripts.token_usage_by_provider import read_calls


class BalanceUnavailable(RuntimeError):
    """余额不可读取；消息不得包含认证信息。"""


class CostGuard:
    """按余额最小读数累计本次运行的费用。"""

    def __init__(self, start_balance: float, limit_cny: float = 20.0) -> None:
        if limit_cny <= 0:
            raise ValueError("limit_cny must be positive")
        self.start_balance = float(start_balance)
        self.limit_cny = float(limit_cny)
        self.min_balance = float(start_balance)

    def observe(self, balance: float) -> None:
        """记录余额；余额回升不改变已观察到的最低值。"""
        self.min_balance = min(self.min_balance, float(balance))

    def spent(self) -> float:
        """返回非负的余额差。"""
        return max(0.0, self.start_balance - self.min_balance)

    def exceeded(self) -> bool:
        """达到阈值即封顶。"""
        return self.spent() >= self.limit_cny


def fetch_cny_balance(
    api_key: str,
    *,
    base_url: str = "https://api.deepseek.com",
    timeout: float = 10,
    opener: Callable[..., object] | None = None,
) -> float:
    """读取账户 CNY 总余额；网络、HTTP、JSON 与币种错误均明确失败。"""
    request = Request(
        f"{base_url.rstrip('/')}/user/balance",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    open_url = opener or urlopen
    try:
        response = open_url(request, timeout=timeout)
        with response as result:
            payload = json.loads(result.read().decode("utf-8"))
    except HTTPError as error:
        raise BalanceUnavailable(f"balance HTTP error ({error.code})") from None
    except (URLError, TimeoutError, OSError) as error:
        reason = "timeout" if isinstance(error, TimeoutError) else "network error"
        raise BalanceUnavailable(reason) from None
    except (ValueError, UnicodeDecodeError, TypeError):
        raise BalanceUnavailable("invalid balance JSON") from None
    infos = payload.get("balance_infos") if isinstance(payload, dict) else None
    if not isinstance(infos, list):
        raise BalanceUnavailable("missing balance_infos")
    for item in infos:
        if isinstance(item, dict) and item.get("currency") == "CNY":
            try:
                value = float(item["total_balance"])
            except (KeyError, TypeError, ValueError):
                raise BalanceUnavailable("invalid CNY total_balance") from None
            if value < 0:
                raise BalanceUnavailable("invalid CNY total_balance")
            return value
    raise BalanceUnavailable("CNY balance is unavailable")


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """终止整棵进程树：Windows taskkill；POSIX 对新进程组发信号。"""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            check=False,
            capture_output=True,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)


def redact_command(command: list[str]) -> list[str]:
    """遮蔽认证参数值与形似 API key 的独立参数。"""
    redacted: list[str] = []
    mask_next = False
    for item in command:
        if mask_next:
            redacted.append("***")
            mask_next = False
            continue
        if re.search(r"(?i)(api[-_]?key|token|secret|password|authorization)", item):
            if "=" in item:
                redacted.append(item.split("=", 1)[0] + "=***")
            else:
                redacted.append(item)
                mask_next = True
        elif re.search(r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)", item):
            redacted.append("***")
        else:
            redacted.append(item)
    return redacted


def estimate_trace_cost(root: Path, model: str, usd_cny: float) -> float:
    """复用 provider token reader 并按共享价格估算人民币成本。"""
    search_root = root.parent.parent.parent if root.name == "trace" else root
    calls, _ = read_calls([search_root], {})
    grouped: dict[str, list[int]] = {}
    for call in calls:
        if call["failed_calls"]:
            continue
        name = str(call["model"])
        if name.startswith("unknown"):
            name = model
        if name not in grouped:
            grouped[name] = [0, 0, 0]
        grouped[name][0] += int(call["input_tokens"] or 0)
        grouped[name][1] += int(call["cached_tokens"] or 0)
        grouped[name][2] += int(call["output_tokens"] or 0)
    return sum(estimate(name, *tokens) for name, tokens in grouped.items()) * usd_cny


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析费用护栏选项与被监视命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-cny", type=float, default=20.0)
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fallback-trace-root", type=Path)
    parser.add_argument("--usd-cny", type=float, default=7.2)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.report.is_absolute() or args.interval <= 0 or args.limit_cny <= 0:
        parser.error("absolute --report and positive limit/interval required")
    args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.command:
        parser.error("a command after -- is required")
    return args


def run(
    args: argparse.Namespace,
    *,
    balance_reader: Callable[[str], float] | None = None,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    terminator: Callable[[subprocess.Popen[bytes]], None] = terminate_process_tree,
) -> int:
    """启动受保护的命令，轮询余额並写脱敏报告。"""
    key = env_str("DEEPSEEK_API_KEY")
    if not key:
        load_env_file()
        key = env_str("DEEPSEEK_API_KEY")
    reader = balance_reader or (lambda secret: fetch_cny_balance(secret))
    start_time = datetime.now(UTC).isoformat()
    start_tick = clock()
    try:
        if not key:
            raise BalanceUnavailable("missing API key")
        start_balance = reader(key)
        source = "balance"
        guard = CostGuard(start_balance, args.limit_cny)
    except BalanceUnavailable as error:
        if args.fallback_trace_root is None:
            print(f"Balance unavailable: {error}", file=sys.stderr)
            args.report.write_text(
                json.dumps(
                    {
                        "start_balance": None,
                        "end_balance": None,
                        "min_balance": None,
                        "spent_cny": None,
                        "limit_cny": args.limit_cny,
                        "capped": False,
                        "exit_code": 1,
                        "command": redact_command(args.command),
                        "started_at": start_time,
                        "ended_at": datetime.now(UTC).isoformat(),
                        "poll_count": 0,
                        "cost_source": "balance",
                        "error": f"Balance unavailable: {error}",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return 1
        source = "estimate"
        start_balance = None
        guard = None
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = popen(
        args.command,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    polls = 0
    capped = False
    error_text = ""
    end_balance = start_balance
    balance_failed = False
    last_estimate = 0.0
    while process.poll() is None:
        sleeper(args.interval)
        polls += 1
        if source == "balance":
            try:
                balance = reader(key)
                guard.observe(balance)
                if guard.exceeded():
                    capped = True
                    terminator(process)
                    break
            except BalanceUnavailable:
                if args.fallback_trace_root is None:
                    error_text = "余额不可用，已停止以保留费用保护"
                    balance_failed = True
                    terminator(process)
                    break
                source = "estimate"
                error_text = "费用来自估算，不是余额"
        if source == "estimate":
            try:
                last_estimate = estimate_trace_cost(
                    args.fallback_trace_root, args.model, args.usd_cny
                )
            except (ValueError, OSError, KeyError):
                last_estimate = 0.0
            if last_estimate >= args.limit_cny:
                capped = True
                terminator(process)
                break
    exit_code = process.wait()
    if source == "balance":
        try:
            end_balance = reader(key)
            guard.observe(end_balance)
        except BalanceUnavailable:
            if args.fallback_trace_root is not None:
                source = "estimate"
                error_text = "费用来自估算，不是余额"
            else:
                balance_failed = True
                error_text = "余额不可用，无法确认最终费用"
    if source == "estimate":
        with suppress(ValueError, OSError, KeyError):
            last_estimate = estimate_trace_cost(args.fallback_trace_root, args.model, args.usd_cny)
        spent = last_estimate
        min_balance = None
        end_balance = None
    else:
        spent = guard.spent()
        min_balance = guard.min_balance
    report = {
        "start_balance": start_balance,
        "end_balance": end_balance,
        "min_balance": min_balance,
        "spent_cny": spent,
        "limit_cny": args.limit_cny,
        "capped": capped,
        "exit_code": 75 if capped else (1 if balance_failed else exit_code),
        "command": redact_command(args.command),
        "started_at": start_time,
        "ended_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": max(0.0, clock() - start_tick),
        "poll_count": polls,
        "cost_source": source,
        "note": error_text or ("费用来自估算，不是余额" if source == "estimate" else ""),
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 75 if capped else (1 if balance_failed else exit_code)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
