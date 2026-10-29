"""e2e 跑批的启动配置（用户 0929 两次定向：入口统一 `inspect eval`；配置**全填、零缺省**）。

`evals/config.json` 是唯一口径：task 装配时经 `load_config()` 读取，**缺任何一键直接
ValueError 列出缺的键**——杜绝"缺省值兜底读错目录"一类事故（335 实锤）。`models`
四条链路也必须显式全填，`resolve_models` 不再做 null/主型号回退。

被测系统的 harness 旋钮（如红线阈值）不在这里——由 `pokemon_agent.settings` 的
`default.json` 加覆盖文件解析，评测线只经 `evals/common/overlay.py` 写覆盖层。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
"""eval 线的启动配置文件（进 git——它是口径的一部分）。"""

REQUIRED_KEYS: tuple[str, ...] = (
    "version",
    "split",
    "samples",
    "timeout",
    "budget",
    "epochs",
    "log_dir",
    "trace_backend",
    "ignore_initial_memory",
    "export_memory_dir",
    "models",
    "evaluation_models",
)
"""config.json 必须全填的键；缺一即错。"""

MODEL_LINKS: tuple[str, ...] = (
    "text_model",
    "judge_model",
    "summary_model",
    "plan_model",
)

BUDGET_DERIVATION_DEFAULTS: dict[str, int] = {
    "seconds_per_action": 40,
    "reserve_s": 120,
    "timeout_margin_s": 300,
    "long_max_episodes": 6,
}
"""评测配置里的链路型号键（由 `overlay.py` 映射到 settings 的 models 各节）。"""


class ResultGraderConfig(BaseModel):
    """独立结果评分员的完整配置；字段无缺省，不包含密钥值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    temperature: float = Field(ge=0)
    max_tokens: int = Field(gt=0)
    timeout_s: float = Field(gt=0)
    thinking: bool


def load_config() -> dict[str, Any]:
    """读 `config.json`；**零缺省**——缺一键就 ValueError 列出缺的键。"""
    if not CONFIG_PATH.is_file():
        raise ValueError(f"启动配置缺失：{CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_KEYS if key not in cfg]
    if missing:
        raise ValueError(f"config.json 缺键：{missing}（配置必须全填，无缺省）")
    cfg.setdefault("budget_derivation", dict(BUDGET_DERIVATION_DEFAULTS))
    cfg.setdefault("budget_derivation", dict(BUDGET_DERIVATION_DEFAULTS))
    return cfg


def resolve_models(models_cfg: dict[str, Any]) -> dict[str, str]:
    """链路型号表：四条链路必须**全部显式**给出型号，缺/空即 ValueError（不再回退）。"""
    missing = [link for link in MODEL_LINKS if not models_cfg.get(link)]
    if missing:
        raise ValueError(f"config.json models 缺链路型号：{missing}（不再做回退）")
    return {link: str(models_cfg[link]) for link in MODEL_LINKS}


def resolve_result_grader(evaluation_models: Mapping[str, Any]) -> ResultGraderConfig:
    """读取 result_grader；缺对象或任意字段时 ValueError 列出缺键，无缺省。"""
    values = evaluation_models.get("result_grader")
    if not isinstance(values, dict):
        raise ValueError("config.json evaluation_models 缺 result_grader 对象")
    missing = [key for key in ResultGraderConfig.model_fields if key not in values]
    if missing:
        raise ValueError(f"config.json result_grader 缺键：{missing}（无缺省）")
    return ResultGraderConfig.model_validate(values)


def resolve_grader(
    evaluation_models: Mapping[str, Any],
    grader_model: str | None = None,
) -> ResultGraderConfig | None:
    """解析本次生效的评分员配置；`none` 关闭，其他字符串只覆盖型号。"""
    grader = resolve_result_grader(evaluation_models)
    if grader_model is not None and grader_model.lower() == "none":
        return None
    if grader_model is not None:
        grader = ResultGraderConfig.model_validate({**grader.model_dump(), "model": grader_model})
    return grader


__all__ = [
    "CONFIG_PATH",
    "BUDGET_DERIVATION_DEFAULTS",
    "MODEL_LINKS",
    "REQUIRED_KEYS",
    "ResultGraderConfig",
    "load_config",
    "resolve_grader",
    "resolve_models",
    "resolve_result_grader",
]
