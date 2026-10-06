"""e2e 跑批的启动配置（用户 0929 两次定向：入口统一 `inspect eval`；配置**全填、零缺省**）。

`evals/config.json` 是唯一口径：task 装配时经 `load_config()` 读取，**缺任何一键直接
ValueError 列出缺的键**——杜绝"缺省值兜底读错目录"一类事故（335 实锤）。`models`
五条链路也必须显式全填，`resolve_models` 不再做 null/主型号回退。

被测系统的 harness 旋钮（如红线阈值）不在这里——仍从 `pokemon_agent.config` 装配期
读一次进 metadata 快照。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
"""eval 线的启动配置文件（进 git——它是口径的一部分）。"""

REQUIRED_KEYS: tuple[str, ...] = (
    "version",
    "split",
    "samples",
    "knowledge",
    "speed",
    "timeout",
    "epochs",
    "log_dir",
    "trace_backend",
    "watch",
    "models",
)
"""config.json 必须全填的键；缺一即错。"""

MODEL_LINKS: tuple[str, ...] = (
    "vision_model",
    "text_model",
    "judge_model",
    "verify_model",
    "plan_model",
)
"""`build_real` 收的五条链路参数名（与 `pokemon_agent/build.py` 签名一一对应）。"""


def load_config() -> dict[str, Any]:
    """读 `config.json`；**零缺省**——缺一键就 ValueError 列出缺的键。"""
    if not CONFIG_PATH.is_file():
        raise ValueError(f"启动配置缺失：{CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_KEYS if key not in cfg]
    if missing:
        raise ValueError(f"config.json 缺键：{missing}（配置必须全填，无缺省）")
    return cfg


def resolve_models(models_cfg: dict[str, Any]) -> dict[str, str]:
    """链路型号表：五条链路必须**全部显式**给出型号，缺/空即 ValueError（不再回退）。"""
    missing = [link for link in MODEL_LINKS if not models_cfg.get(link)]
    if missing:
        raise ValueError(f"config.json models 缺链路型号：{missing}（不再做回退）")
    return {link: str(models_cfg[link]) for link in MODEL_LINKS}


__all__ = ["CONFIG_PATH", "MODEL_LINKS", "REQUIRED_KEYS", "load_config", "resolve_models"]
