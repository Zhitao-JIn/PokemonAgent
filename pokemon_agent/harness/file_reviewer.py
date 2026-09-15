"""`FileReviewer`：把"人"换成一**对文件**的 `Reviewer` 实现——插话走信箱，审一期直接认账。

**它为什么存在**：`ConsoleReviewer` 要求人坐在**同一个终端**上敲回车，而驱动方
（另一个 agent、一个脚本、一次无人值守的真机跑）手里没有那个终端。把"我需要裁决"
写成盘上的一个文件、把回话读成盘上的另一个文件，人在环里的那两下就变成了
**文件握手**——谁在等、等什么、等到了没有，全在盘上看得到，进程也不必有人守着 stdin。

| 文件 | 谁写 | 含义 |
|---|---|---|
| `.workbuddy/review_request.json` | 本类 | "节点正阻塞等你裁决"的信号 + 这张表单是什么 |
| `.workbuddy/review_answer.txt` | 驱动方 | 回应：**非空 = 插话**，**空 = 看过了，没意见** |

`review_request.json` 只装三件：`{"form_kind", "prompt", "ts"}`。**结构体本体不进文件**
——它可能是任意 Pydantic 模型（`Action` / `JudgeVerdict` / `PlannerOutcome`…），序列化
它等于把"怎么渲染"这件事从调用方搬到实现里；要看本体读 trace。

## 怎么判"这个回应属于这一问"：**新鲜度**，不是删除

这一版和最初的写法有一处不同：**握手的两端都不删任何文件**。判据是 **mtime**——
`response` 只在 `answer.mtime > request.mtime` 时才算数，否则按"还没人回答"处理。

*为什么不能用删除*：沙箱有一道**单回合删除次数硬闸**（实测阈值 50）。插话点
（`plan` / `judge` / `think_action` 三处）每问删两个文件，一局几十次删除——
**实测把进程就地掐掉过一次**（`realcheck-0915-052314`，死在 step 22 的 judge 握手上，
无 traceback、无 run_error，日志里只有那行 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`）。
删除这条路在真机跑不通。

新鲜度给出的是**同一份保证**（"永远不会把上一次的回应当成这一次的"）：请求永远在
上一次消费**之后**才写，所以它的 mtime 恒大于任何残留回应；驱动方看到请求比回应新，
才落新的回应。两个文件都只剩覆盖写，盘上**永远只有这一对**。

**控制台输出**（0915 加）：每次"请求已写入 / 回答已读 / 超时没答"都往 stdout 打一行
`[review] …`（带 flush）。信箱是**覆盖式**的——盘上永远只有一对文件，问题序列在盘上
不留历史，可见性全靠这几行（`_seq` 计数也只在控制台可见）。

**两个文件都是原子的**（先写同目录 `.tmp` 再 `rename`）：轮询的读方随时可能撞上写方的
半截文件，而同分区 `rename` 是原子的，于是"看到一个文件"就等于"看到一份完整的它"
（`rename` 不计入那道删除闸——已实测）。

**它不做三件事**（与 `ConsoleReviewer` 同款）：不重问 LLM、不写状态、不改变图的形状。

**`audit()` 一期恒认账**（与 `NullReviewer` 同款）：run 级那次审（这一局算成算败）还没有
要给人推翻的场景——推翻要接的是目标表的状态机，先不做。注意它**不能**回裸字符串：
`review` 节点读的是 `resp.verdict`。

## 超时是上限，不是计划中的等待

`timeout`（缺省 **300s**，0915 二次上调）兜的是"驱动方挂了"：没人接电话就当作
没意见继续跑（与 `ConsoleReviewer` 的语义一致）。超时**什么都不用清**——残留的请求由
新鲜度自然作废（下一次 `inject` 覆盖它）。

**为什么是 300s**（0915 定稿）：驱动方是 AI agent 时，它的响应节奏是**每轮工具调用
15~60s**——首次 45s 的窗口比这还短，实测驱动方每次都白等满、一问都没接住（这就是
FileReviewer 当日被撤的直接原因）。**问题不在文件协议，在窗口 < 响应节奏**。
300s 给了 5~10 倍余量；漏答的代价只是"这一问按没意见降级"，run 不会卡死。

**问的次数没那么多**（修正 0915 的旧口径"30+ 次"）：插话点只有 `plan` / `judge` /
`think_action` 三处、并非每步都有——实测 30 步一局只有 **6~7 问**。就算每问都等满
300s 也不会撞看门狗（`check_harness` 在 `--review` 模式下把上限提到 30 分钟）。
"""

from __future__ import annotations

import json
import os
import pathlib
import time

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
)

REQUEST_NAME = "review_request.json"
"""请求信号的文件名（相对 `FileReviewer` 的 directory）。"""

ANSWER_NAME = "review_answer.txt"
"""回应文件的文件名（相对 `FileReviewer` 的 directory）。"""

DEFAULT_TIMEOUT = 300.0
"""等一次回应的上限（秒）。0915 从 45s 上调：驱动方是 AI agent 时，其响应节奏
（每轮工具调用 15~60s）必须被窗口罩住。见模块 docstring 的「超时是上限」一节。"""

DEFAULT_POLL_INTERVAL = 0.5
"""轮询回应的间隔（秒）。"""


def _write_atomic(path: pathlib.Path, text: str) -> None:
    """先写同目录 `.tmp` 再 `rename`——读方只会看到"完整"或"不存在"两种状态。

    前置条件：`path.parent` 存在。
    后置条件：`path` 的内容是 `text`（读写两端不会观察到半截文件）。
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _mtime(path: pathlib.Path) -> float | None:
    """文件的 mtime；不存在返回 `None`。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _short(text: object, limit: int = 80) -> str:
    """压成单行、截到 `limit` 字——给控制台的摘要，不是数据（别拿它做判据）。"""
    flat = " ".join(str(text).split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _say(line: str) -> None:
    """往 stdout 打一行信箱动态（带 flush——被重定向进 tee 时也要实时可见）。"""
    print(f"[review] {line}", flush=True)


class FileReviewer:
    """文件信箱实现：写请求等人回话，读到什么算什么；没有回话就继续。"""

    def __init__(
        self,
        directory: str | os.PathLike[str] = ".workbuddy",
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        """构造。

        directory：信箱目录（相对当前工作目录解析）。**一次跑只有一个信箱**——
            两个模拟器实例并存时会让两个进程抢同一对文件，那正是要避免的。
        timeout：等一次回应的上限秒数；`<= 0` 表示只查一次（等价于"没有驱动方"）。
        poll_interval：轮询间隔秒数。

        后置条件：`directory` 已存在（不存在就地建出来，含父目录）。
        """
        self._directory = pathlib.Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._seq = 0
        """已发出的提问计数（信箱是覆盖式，盘上只有一对文件——计数只在控制台可见）。"""

    @property
    def directory(self) -> pathlib.Path:
        """信箱目录（驱动方按它定位那对文件）。"""
        return self._directory

    def inject(self, req: FromHarnessToReviewerInjectReq) -> str:
        """**插话**：把请求写进信箱，阻塞等一个**比它新**的回应；空串 = 没人有意见。

        前置条件：`self._directory` 存在（构造时已保证）。
        后置条件：返回回应全文（`strip()` 过）；返回空串**当且仅当**回应为空或超时。
            返回时盘上只有这一对文件（覆盖写，不产生也不删除任何文件）。
        """
        request_path = self._directory / REQUEST_NAME
        answer_path = self._directory / ANSWER_NAME

        # 请求写在**上一次消费之后**，所以它的 mtime 恒大于任何残留回应——
        # 于是"比请求新"就是"属于这一问"，不需要删任何东西。
        _write_atomic(
            request_path,
            json.dumps(
                {
                    "form_kind": req.form_kind,
                    "prompt": req.prompt,
                    "ts": time.time(),
                },
                ensure_ascii=False,
            ),
        )
        asked_at = request_path.stat().st_mtime

        self._seq += 1
        _say(
            f"→ request 已写入（第 {self._seq} 问，form_kind={req.form_kind or '-'}，"
            f"信箱 {self._directory}）：{_short(req.prompt)}……等回应，上限 {self._timeout:g}s"
        )

        deadline = time.monotonic() + self._timeout
        while True:
            answered_at = _mtime(answer_path)
            if answered_at is not None and answered_at > asked_at:
                answer = answer_path.read_text(encoding="utf-8").strip()
                _say(
                    f"← answer 已读（第 {self._seq} 问，{len(answer)} 字，"
                    f"{'非空=插话已采纳' if answer else '空=没意见'}）：{_short(answer)}"
                )
                return answer
            if time.monotonic() >= deadline:
                _say(f"← {self._timeout:g}s 无回答（第 {self._seq} 问），按「没意见」继续")
                return ""
            time.sleep(self._poll_interval)

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """**审**：一期恒认账（不能回裸字符串——`review` 读的是 `resp.verdict`）。"""
        return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT)


__all__ = [
    "ANSWER_NAME",
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_TIMEOUT",
    "FileReviewer",
    "REQUEST_NAME",
]
