"""eval_set 编排薄适配：epochs / retry / resume 的真库入口（V2）。

真签名（0.3.271 实测）：`eval_set(tasks, log_dir, epochs=Epochs(n, reducer=…),
retry_attempts=…) -> (bool, list[EvalLog])`。R3 把 batch.py 的循环交到这里；
本模块先只 re-export。
"""

from __future__ import annotations

from inspect_ai import Epochs, eval_set

__all__ = ["Epochs", "eval_set"]
