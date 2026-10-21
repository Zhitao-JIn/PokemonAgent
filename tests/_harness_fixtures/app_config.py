"""测试用生效配置：保底 `default.json` 加按段覆盖，返回冻结的 `AppConfig`。

用法示范：`app_config(budget={"max_episodes": 3})` 只改预算里的一个键，其余与生产保底一致。
"""

from __future__ import annotations

import json
from typing import Any

from pokemon_agent.direct.call_policy import CallPolicy
from pokemon_agent.settings import AppConfig, load_config
from pokemon_agent.settings.loader import deep_merge


def app_config(**sections: dict[str, Any] | None) -> AppConfig:
    """保底配置 + 逐段覆盖；覆盖值与生产覆盖文件同一语义（字典递归合并）。"""
    base = json.loads(load_config().merged_json)
    merged = deep_merge(base, {name: value for name, value in sections.items()})
    return AppConfig.model_validate_json(json.dumps(merged))


DEFAULT_APP_CONFIG = app_config()
"""不带任何覆盖的生产保底配置。"""


def call_policy(*, max_attempts: int | None = None, timeout_s: float = 60.0) -> CallPolicy:
    """一条链路的调用策略：重试与图片帽取保底配置，`max_attempts` / `timeout_s` 可按用例改。"""
    app = (
        app_config()
        if max_attempts is None
        else app_config(retry={"brain_max_attempts": max_attempts})
    )
    return CallPolicy(
        retry=app.retry, request_timeout_s=timeout_s, image_cap=app.memory.scope_image_cap
    )


ACTION_LIMITS = DEFAULT_APP_CONFIG.action_limits
"""保底的动作输出上限（`Chooser` 必传）。"""


def reconfigure(run_rt: Any, **sections: dict[str, Any]) -> AppConfig:
    """把三层 runtime 的生效配置同时换成"当前配置 + 段内字段覆盖"，返回新配置。

    走 `model_copy` 而不是重新校验：个别用例需要生产配置不允许的极端值（如 0 次动作预算）
    来触发机械收尾，这里只改值、不过 schema。
    """
    config = run_rt.config
    for name, values in sections.items():
        config = config.model_copy(update={name: getattr(config, name).model_copy(update=values)})
    for runtime in (run_rt, run_rt.episode, run_rt.episode.task):
        runtime.config = config
    return config
