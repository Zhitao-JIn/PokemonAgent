"""`ConsoleReviewer`：控制台上的人机交互实现——**插话**与**审**。

**它是 `Reviewer` Protocol 的一个实现**（契约在
`harness/interface/reviewer.py`）。它住 `harness/` 而**不进 `interface/`**：
`interface/` 只放"契约"，这里放"一个具体实现"（读 stdin、写 stdout）。

**它不做三件事**（这是它保持薄的关键）：

1. **不重问 LLM**。"带着人的那句去重问"是调用方节点的事
   （`plan_episode` / `review_and_judge`）——它只负责把话拿到手。
2. **不写状态**。`audit` 只回"认 / 推翻"，harness 据此接受裁决或记录推翻理由。
3. **不阻塞图的结构**。它是节点内的一个同步函数调用——"问一句"不改变图的形状
   （加图节点要付 `recursion_limit` 的代价，见
   `docs/PLAN_console_reviewer.md` §3.2）。

**超时**（用户定调）：读 `pokemon_agent.config.CONSOLE_REVIEW_TIMEOUT`（默认 30s）。
超时按"人没意见"处理——插话回空串、审回认账，并标 `answered=False, by="none"`。
**这是控制台实现自己的策略**，不是 `Reviewer` 契约的一部分。

**渲染**走 `harness/review_render.py`，与 `WebReviewer` 同一份口径。

**为什么这里用线程读 stdin 做超时**：`input()` 没有超时参数，而"等 30 秒没人打字
就继续"要求可中断。用一条守护线程把 `input()` 阻塞包起来、主线程 `join(timeout)`
——这是标准库范围内唯一不依赖平台（Windows 的 `select` 不支持 stdin）的做法。
"""

from __future__ import annotations

import contextlib
import sys
import threading

from pokemon_agent.config import CONSOLE_REVIEW_TIMEOUT
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)

from .review_render import audit_prompt, format_form, render_outcome


class ConsoleReviewer:
    """控制台实现：把表单/结论打印到 stdout，从 stdin 读一行答复。"""

    def __init__(self, timeout: float = CONSOLE_REVIEW_TIMEOUT) -> None:
        """构造。

        timeout：等一次答复的秒数；`<= 0` 表示**不阻塞**（读到就返回、
            读不到当没意见）——无头/脚本化场景直接构造 `timeout=0` 即可
            （它等价于 `NullReviewer` 的行为，不必再单独造一个类）。
        """
        self._timeout = timeout

    # ---- 内部：带超时地读一行 ----

    def _read_line(self, prompt: str) -> str | None:
        """打印 prompt，等 `timeout` 秒读一行；超时或 EOF 返回 None。

        前置条件：prompt 已是要给人看的完整文本（本方法不加工它）。
        后置条件：返回读到的行（`strip()` 过，空行是 `""`）；超时或 EOF 返回 None。
        """
        sys.stdout.write(prompt)
        if not prompt.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

        if self._timeout <= 0:
            line = sys.stdin.readline()
            return line.strip() if line else None

        box: list[str] = []

        def _reader() -> None:
            with contextlib.suppress(EOFError, ValueError):
                box.append(sys.stdin.readline())

        worker = threading.Thread(target=_reader, daemon=True)
        worker.start()
        worker.join(self._timeout)
        if not box:
            # 超时：守护线程继续挂着等 stdin（不阻塞进程退出，daemon 线程随主线程结束）
            sys.stdout.write(f"（{self._timeout:g}s 无答复，按「没有意见」继续）\n")
            sys.stdout.flush()
            return None
        return box[0].strip() if box[0] else None

    # ---- Reviewer 契约的两个方法 ----

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        """**插话**：把表单亮给人，收一句反馈；空串表示没意见，超时标为无人作答。"""
        self._render_form(req)
        line = self._read_line(">>> 有意见就说（直接回车 = 没有）: ")
        if line is None:
            return FromHarnessToReviewerInjectResp(text="", answered=False, by="none")
        return FromHarnessToReviewerInjectResp(text=line, answered=True, by="human")

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """**审**：把 judge 的目标达成裁决亮给人，收一个表态。

        人答 `o`（overturn）就推翻——接着读一行当理由；空行或其它输入按**认账**；
        超时按认账并标 `answered=False, by="none"`。
        """
        header = f"\n=== {audit_prompt(req)} ===\n{render_outcome(req)}"
        answer = self._read_line(header + ">>> 回车 = 认账；输入 o = 推翻: ")
        if answer is None:
            return FromHarnessToReviewerAuditResp(
                verdict=AuditVerdict.ACCEPT, answered=False, by="none"
            )
        if answer.lower() in {"o", "overturn"}:
            note = self._read_line(">>> 推翻理由（下一次 plan 会看到）: ") or ""
            return FromHarnessToReviewerAuditResp(
                verdict=AuditVerdict.OVERTURN, note=note, answered=True, by="human"
            )
        return FromHarnessToReviewerAuditResp(
            verdict=AuditVerdict.ACCEPT, answered=True, by="human"
        )

    # ---- 渲染 ----

    @staticmethod
    def _render_form(req: FromHarnessToReviewerInjectReq) -> None:
        """把一张表单渲染到 stdout。

        `form` 是 `Any`（见 `FromHarnessToReviewerInjectReq` 的说明）——这里做
        **最保守**的渲染：Pydantic 模型走 `model_dump_json(indent=2)`，
        其余走 `str()`。节点若想给人看得更讲究，自己在 `req.prompt` 里写好文本。
        """
        print(f"\n=== 插话：{req.prompt} ===")
        if req.form_kind:
            print(f"  （表单类型：{req.form_kind}）")
        print(f"  {format_form(req.form)}")


__all__ = ["ConsoleReviewer"]
