"""装配点读取 JSON 运行配置；只包含预算段，不接管部署与模型选型。"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pokemon_agent.config import DEFAULT_RUN_BUDGET
from pokemon_agent.run_budget import RunBudget


class RunConfig(BaseModel):
    """运行配置；预算缺省字段使用共用的不可变默认档。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    budget: RunBudget = Field(default_factory=lambda: DEFAULT_RUN_BUDGET)


def load_run_config(path: str | Path | None) -> RunConfig:
    """读取配置文件；None 取默认档，缺文件或不合法 JSON/字段直接报错。"""
    import json

    if path is None:
        return RunConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("budget"), dict):
        data = {**data, "budget": {**DEFAULT_RUN_BUDGET.model_dump(), **data["budget"]}}
    return RunConfig.model_validate(data)
