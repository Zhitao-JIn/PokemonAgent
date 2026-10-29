"""solver 向回放与评分交接的单样本运行记录。"""

from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field


class RunOneRecord(BaseModel):
    """run.json 的文件契约，不绑定 Inspect 的当前 store。"""

    run_id: str
    branch: str = ""
    invalid: str = ""
    error: str = ""


class RunOneRequest(BaseModel):
    """solver 交给 worker 子进程的单样本请求（经 stdin 的 JSON）；两侧共用本模型，没有命令行。"""

    work_dir: str
    run_config_path: str
    sample_id: str
    epoch: int = 1
    models: dict[str, str]
    trace_backend: str
    version: str
    effective_budget: dict[str, int] = Field(default_factory=dict)


class AgentRunRecord(StoreModel):
    """保存 run-one 的定位信息与原始结果；无效样本不读账。"""

    run_id: str = ""
    branch: str = ""
    invalid: str = ""
    error: str = ""
    work_dir: str = ""
    run_result: str = ""
