"""按生产 Port 原样记录完整脑调用；不拼输入、不读取额外记忆。"""

from pathlib import Path

from pokemon_agent.direct.interface import (
    ChoosePort,
    DecomposePort,
    JudgePort,
    PlanPort,
    ReflectPort,
    RunSummarizePort,
    SummarizePort,
    TaskSummarizePort,
    VerifyPort,
)
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeResp,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeRunResp,
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToBrainToolSummarizeTaskResp,
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToBrainToolVerifyResp,
)

from .invocation import RecordingInvocation


class RecordedPlanner:
    """PlanPort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: PlanPort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.plan, directory)

    def plan(
        self, request: FromHarnessToBrainToolPlanOnceReq
    ) -> FromHarnessToBrainToolPlanOnceResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedDecomposer:
    """DecomposePort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: DecomposePort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.decompose, directory)

    def decompose(
        self, request: FromHarnessToBrainToolDecomposeReq
    ) -> FromHarnessToBrainToolDecomposeResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedChooser:
    """ChoosePort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: ChoosePort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.choose, directory)

    def choose(
        self, request: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedJudger:
    """JudgePort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: JudgePort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.judge, directory)

    def judge(self, request: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedVerifier:
    """VerifyPort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: VerifyPort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.verify, directory)

    def verify(self, request: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedReflector:
    """ReflectPort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: ReflectPort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.reflect, directory)

    def reflect(
        self, request: FromHarnessToBrainToolReflectReq
    ) -> FromHarnessToBrainToolReflectResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedSummarizer:
    """SummarizePort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: SummarizePort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.summarize, directory)

    def summarize(
        self, request: FromHarnessToBrainToolSummarizeReq
    ) -> FromHarnessToBrainToolSummarizeResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedTaskSummarizer:
    """TaskSummarizePort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: TaskSummarizePort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.summarize_task, directory)

    def summarize_task(
        self, request: FromHarnessToBrainToolSummarizeTaskReq
    ) -> FromHarnessToBrainToolSummarizeTaskResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)


class RecordedRunSummarizer:
    """RunSummarizePort 的旁路录制器；完整保留请求、响应、异常和等待时间。"""

    def __init__(self, inner: RunSummarizePort, directory: Path) -> None:
        """注入原端口；目录只能有一个串行写入者。"""
        self._record = RecordingInvocation(inner.summarize_run, directory)

    def summarize_run(
        self, request: FromHarnessToBrainToolSummarizeRunReq
    ) -> FromHarnessToBrainToolSummarizeRunResp:
        """请求先落盘；原对象传入、原响应返回、原异常抛出。"""
        return self._record(request)
