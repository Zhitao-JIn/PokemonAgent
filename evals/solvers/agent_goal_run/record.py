"""solver 向回放与评分交接的单样本运行记录。"""

from inspect_ai.util import StoreModel
from pydantic import BaseModel


class RunOneRecord(BaseModel):
    """run.json 的文件契约，不绑定 Inspect 的当前 store。"""

    run_id: str
    branch: str = ""
    invalid: str = ""
    error: str = ""


class AgentRunRecord(StoreModel):
    """保存 run-one 的定位信息与原始结果；无效样本不读账。"""

    run_id: str = ""
    branch: str = ""
    invalid: str = ""
    error: str = ""
    work_dir: str = ""
    run_result: str = ""
