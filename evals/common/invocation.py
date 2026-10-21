"""请求先落盘的串行调用录制器；单调时钟计时，强杀保留未完成调用。"""

from collections.abc import Callable
from pathlib import Path
from time import monotonic, time
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness import ModelCall

Request = TypeVar("Request", bound=BaseModel)
Response = TypeVar("Response", bound=BaseModel)


class InvocationStart(BaseModel):
    """请求写完后、调用之前的起点；无结束记录即尚未完成或被强杀。"""

    started_at: float
    request_file: str


class InvocationEnd(BaseModel):
    """完整工具调用的时间，包含 provider 等待、重试、退避和解析。"""

    ended_at: float
    elapsed_s: float
    status: str
    error_type: str = ""


class InvocationFailure(BaseModel):
    """失败保留异常和已返回的模型尝试；不冒充成功响应。"""

    error_type: str
    error: str
    calls: list[ModelCall] = Field(default_factory=list)


def write_record(path: Path, record: BaseModel) -> None:
    """独占创建；冲突或写失败向上传递，不覆盖已有产物。"""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(record.model_dump_json(indent=2) + "\n")


class RecordingInvocation(Generic[Request, Response]):
    """记录一条生产 Port；调用方保证单目录单写入者。"""

    def __init__(self, invoke: Callable[[Request], Response], directory: Path) -> None:
        """依赖由调用方传入；已有请求保留，从最大编号后追加。"""
        self._invoke = invoke
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self._sequence = max(
            (int(path.name.split(".")[0]) for path in directory.glob("*.request.json")),
            default=0,
        )

    def __call__(self, request: Request) -> Response:
        """先记请求与开始，再原样调用；任何失败都保留原异常。"""
        self._sequence += 1
        prefix = self._directory / f"{self._sequence:06d}"
        write_record(prefix.with_suffix(".request.json"), request)
        write_record(
            prefix.with_suffix(".start.json"),
            InvocationStart(started_at=time(), request_file=prefix.name + ".request.json"),
        )
        started = monotonic()
        try:
            response = self._invoke(request)
        except BaseException as error:
            self._failure(prefix, started, error)
            raise
        write_record(prefix.with_suffix(".response.json"), response)
        write_record(
            prefix.with_suffix(".end.json"),
            InvocationEnd(ended_at=time(), elapsed_s=monotonic() - started, status="success"),
        )
        return response

    def _failure(self, prefix: Path, started: float, error: BaseException) -> None:
        """落盘失败只附加到原异常；失败账不抹去原始调用错误。"""
        try:
            write_record(
                prefix.with_suffix(".failure.json"),
                InvocationFailure(
                    error_type=type(error).__name__,
                    error=str(error),
                    calls=list(getattr(error, "calls", ())),
                ),
            )
            write_record(
                prefix.with_suffix(".end.json"),
                InvocationEnd(
                    ended_at=time(),
                    elapsed_s=monotonic() - started,
                    status="failure",
                    error_type=type(error).__name__,
                ),
            )
        except OSError as recording_error:
            error.add_note(f"failure recording failed: {recording_error}")
