"""settings：全项目配置的唯一入口——一份保底 JSON，启动时按需叠加覆盖文件。

对外：`load_config()` 加载；`AppConfig` 是生效配置的类型；`ResolvedConfig` 带出处与摘要；
各配置段的类型（`ModelsConfig` / `RetryConfig` / …）供 tool 层工厂做类型标注。
"""

from .errors import ConfigFileError, ConfigValidationError, SettingsError
from .loader import load_config
from .paths import resolve_path, write_snapshot
from .schema import (
    ActionLimitsConfig,
    AppConfig,
    BudgetConfig,
    CheckpointSection,
    DebugSection,
    LoopConfig,
    MemoryConfig,
    ModelLink,
    ModelsConfig,
    PathsSection,
    PlanModelLink,
    RequestTimeoutsConfig,
    ResolvedConfig,
    RetryConfig,
    ReviewConfig,
    RunSection,
    ServicesSection,
    TraceSection,
)

__all__ = [
    "ActionLimitsConfig",
    "AppConfig",
    "BudgetConfig",
    "CheckpointSection",
    "ConfigFileError",
    "ConfigValidationError",
    "DebugSection",
    "LoopConfig",
    "MemoryConfig",
    "ModelLink",
    "ModelsConfig",
    "PathsSection",
    "PlanModelLink",
    "RequestTimeoutsConfig",
    "ResolvedConfig",
    "RetryConfig",
    "ReviewConfig",
    "RunSection",
    "ServicesSection",
    "SettingsError",
    "TraceSection",
    "load_config",
    "resolve_path",
    "write_snapshot",
]
