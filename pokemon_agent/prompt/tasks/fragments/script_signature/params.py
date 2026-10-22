"""脚本签名只接收原始能力条目。"""

from pydantic import BaseModel

from ....actions import ActionEntryRecord


class ScriptSignatureParams(BaseModel):
    entry: ActionEntryRecord
