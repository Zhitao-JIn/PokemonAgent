"""共享模型价格表与 token 费用估算。"""

from __future__ import annotations

PRICES = {
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "qwen3.8-flash": (0.12, 0.03, 0.40),
    "deepseek-flash": (0.30, 0.06, 1.20),
}


def estimate(model: str, inputs: int, cached: int, outputs: int) -> float:
    """输出已含 reasoning，不重复加算。"""
    incoming, hit, outgoing = PRICES[model]
    return (max(0, inputs - cached) * incoming + cached * hit + outputs * outgoing) / 1e6
