"""人类本次原话，不包含预排版。"""

from pydantic import BaseModel


class HumanNoteParams(BaseModel):
    note: str
