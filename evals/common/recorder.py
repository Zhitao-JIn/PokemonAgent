"""串行采集 choose 的生产信封；请求先落盘，响应与异常保持原样透传。"""

from pathlib import Path

from pydantic import BaseModel, Field

from pokemon_agent.direct.interface import ChoosePort
from pokemon_agent.errors import BudgetExhausted, MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    ModelCall,
)


class _FailureRecord(BaseModel):
    """失败摘要保留异常类型、消息与已有调用账，不冒充生产成功响应。"""

    error_type: str
    error: str
    calls: list[ModelCall] = Field(default_factory=list)


def _write(path: Path, record: BaseModel) -> None:
    """独占创建 JSON 文件；已有文件或写入失败直接报错，不覆盖、不删除。"""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(record.model_dump_json(indent=2) + "\n")


class RecordingChooser:
    """实现 ChoosePort 的串行包装器；同一目录同时只允许一个写入者。"""

    def __init__(self, inner: ChoosePort, out_dir: str | Path) -> None:
        """依赖由调用方注入；目录须可写，已有编号保留并从最大编号后追加。"""
        self._inner = inner
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        numbers = [
            int(path.name.split(".", 1)[0])
            for pattern in ("*.request.json", "*.response.json")
            for path in self._out_dir.glob(pattern)
            if path.name.split(".", 1)[0].isdigit()
        ]
        self._sequence = max(numbers, default=0)

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """先存请求再调用 inner；成功返回同一响应对象，失败抛出同一异常对象。

        前置条件：串行调用，目录可写。请求或成功响应写入失败时抛 OSError；
        inner 失败后的落盘错误附到原异常的 notes，不替换原异常。
        """
        self._sequence += 1
        prefix = self._out_dir / f"{self._sequence:06d}"
        _write(prefix.with_suffix(".request.json"), req)
        try:
            response = self._inner.choose(req)
        except BaseException as error:
            record = _FailureRecord(
                error_type=type(error).__name__,
                error=str(error),
                calls=error.calls
                if isinstance(error, (MaxRetriesExceeded, BudgetExhausted))
                else [],
            )
            try:
                _write(prefix.with_suffix(".response.json"), record)
            except OSError as recording_error:
                error.add_note(f"response recording failed: {recording_error}")
            raise
        _write(prefix.with_suffix(".response.json"), response)
        return response
