"""`RunDataCenter`：前后端交互的统一中间层，**一个 run 一个实例**。

`api.py`（前端那一侧）和 `RunHarness`（后端那一侧）各持一个引用，双方都只
对它读写，不互相直接调对方的方法（见 `docs/ROADMAP.md`"前后端交互统一"）：

- **goals 槽**：把原来在 `RunHarness` 内部的 `_edit`/`_edit_lock`/
  `_latest_goals` 原样搬过来，语义不变——非阻塞，`plan()` 读到就应用、没
  读到跳过，最新一条编辑覆盖旧的、还没消费的。
- **review 槽（新）**：两个子槽。请求槽由 `RunHarness.review()` 写入（带上
  刚跑完那一局的完整 trace）；决策槽由前端 `POST /runs/{id}/review`
  写入。`RunHarness` 侧读决策槽走 `await_review_response`——**阻塞轮询，
  配超时兜底**，不是读一次没有就当默认；那样等于没有真的问人，跟自动
  放行没区别。
- **trace/frame**：不在这里管——两条通道已经各自有独立端口
  （`TracePort`/帧管道消费者），这里不重复状态，纯粹是转发点收口，不是
  新状态的容器。

这次统一顺带打开一个口子：`review` 槽的决策生产者不必是真人——接一个
LLM 驱动的 reviewer（读 `FromHarnessToReviewerReviewReq`，尤其是 `episode_trace`，
自己判断 continue/stop/retry/push）可以复用同一套槽位协议，只是
`submit_review_response` 的调用方从"前端按钮"换成"另一个模型调用"。
"""

from __future__ import annotations

import threading
import time

from pokemon_agent.brain import Task
from pokemon_agent.schemas.frontend import FromFrontendToRunHarnessSubmitEditReq
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerReviewReq,
    FromHarnessToReviewerReviewResp,
)
from pokemon_agent.trace import TraceEvent

from .interface import HumanDecision

REVIEW_POLL_INTERVAL = 0.2
"""`await_review_response` 阻塞轮询的节拍（秒）——够快到人提交后近乎无感，
又不至于空转烧 CPU（这是内存读写，不是网络轮询，代价很低）。"""


class RunDataCenter:
    """一个 run 的前后端交互中间层：goals 槽 + review 槽（请求/决策）。

    所有方法内部自己加锁——调用方（`api.py` 的请求线程、`RunHarness` 的
    run 线程）不需要关心跨线程安全。
    """

    def __init__(self, review_timeout: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._events_lock = threading.Lock()
        self._events: list[TraceEvent] = []
        """事件流槽（PLAN_checkpoint §7.2）：前端可见状态的唯一聚合点——
        SSE 与实时数字都读这里；checkpoint 恢复时由
        `rebuild()` 单点重建（主前缀 + goals），观测台历史完整可恢复。"""
        self._goals_edit: FromFrontendToRunHarnessSubmitEditReq | None = None
        self._latest_goals: list[Task] = []
        self._review_request: FromHarnessToReviewerReviewReq | None = None
        self._review_response: FromHarnessToReviewerReviewResp | None = None
        self._review_timeout = review_timeout
        self._review_deadline: float | None = None
        """请求发布那一刻算出的绝对截止时间戳（`time.time()` 口径，不是
        `time.monotonic()`——这个值要传给前端渲染倒计时，前端只有墙钟）。
        `review_timeout <= 0` 时恒为 `None`（不阻塞，没有"截止"这个概念）。"""
        self._human_note: str = ""
        """人类实时插话槽：非阻塞、单槽、覆盖式——跟 goals 槽
        同一个约定，最新一条覆盖旧的、还没被 `take_human_note()` 消费的。
        `EpisodeHarness.think_action` 每一步取一次、取到即清空（一次性，只
        对**下一次**决策生效，不会一直粘着）；没人写过就恒为空串。"""

    # ---- 事件流槽：TraceTool 落盘后双写；前端只读这里 ----

    def publish_event(self, event: TraceEvent) -> None:
        """收一条已落盘的事件进事件流槽（`TraceTool` 落盘成功后同步调用）。"""
        with self._events_lock:
            self._events.append(event)

    def events(self, event_types: frozenset | None = None) -> list[TraceEvent]:
        """读事件流（追加序，event_id 严格单调），按类型 mask（读取即过滤）。"""
        with self._events_lock:
            snapshot = list(self._events)
        if event_types is None:
            return snapshot
        return [e for e in snapshot if e.type in event_types]

    def rebuild(self, prefix_events: list[TraceEvent], goals: list[Task]) -> None:
        """checkpoint 恢复的单点重建：事件主前缀整体换入 + goals 槽对齐。

        前置条件：`prefix_events` 是截断后的主前缀（event_id 升序）。
        后置条件：事件流槽与 goals 槽同时就位——前端恢复 = 重连 DataCenter。
        """
        with self._events_lock:
            self._events = sorted(prefix_events, key=lambda e: e.event_id)
        self.publish_goals(goals)

    # ---- goals 槽：harness 发布快照 / 消费编辑；api 读快照 / 写编辑 ----

    def publish_goals(self, goals: list[Task]) -> None:
        """harness 在 `plan` 入口发布最新目标栈快照（观测台读用）。"""
        with self._lock:
            self._latest_goals = list(goals)

    def latest_goals(self) -> list[Task]:
        """观测台读最近一次快照；run 未开始过为空。"""
        with self._lock:
            return list(self._latest_goals)

    def submit_goals_edit(self, edit: FromFrontendToRunHarnessSubmitEditReq) -> None:
        """api 层收一条编辑指令进单槽（最新一条覆盖，还没消费的旧指令丢弃）。"""
        with self._lock:
            self._goals_edit = edit

    def take_goals_edit(self) -> FromFrontendToRunHarnessSubmitEditReq | None:
        """harness 在 `plan` 入口消费一次：取走并清空。"""
        with self._lock:
            edit = self._goals_edit
            self._goals_edit = None
            return edit

    # ---- human_note 槽：api 写 / episode harness 每步取一次并清空 ----

    def submit_human_note(self, text: str) -> None:
        """api 层收一条人类实时插话，覆盖式写入单槽（最新一条覆盖旧的、
        还没被消费的）。"""
        with self._lock:
            self._human_note = text

    def take_human_note(self) -> str:
        """`EpisodeHarness.think_action` 每步取一次：取走并清空。没有待消费
        的插话时返回空串（不是 `None`——调用方不需要区分"没写过"和"取过了"，
        两者对这一步的影响是同一件事：这一步没有插话）。"""
        with self._lock:
            note, self._human_note = self._human_note, ""
            return note

    # ---- review 槽：请求（harness 写）/ 决策（api 或未来的 LLM reviewer 写）----

    def publish_review_request(self, req: FromHarnessToReviewerReviewReq) -> None:
        """harness 进 `review()` 节点时发布这一轮要问的上下文，顺带清掉
        上一轮可能残留的决策（新一轮请求必须配一个新答案，不能复用旧的）。

        顺带算好这一轮的 `_review_deadline`——跟 `await_review_response`
        用的是同一个 `_review_timeout`，两边必须口径一致，所以这里不重新
        接收参数，直接读构造时存的那份。
        """
        with self._lock:
            self._review_request = req
            self._review_response = None
            self._review_deadline = (
                time.time() + self._review_timeout if self._review_timeout > 0 else None
            )

    def review_deadline(self) -> float | None:
        """当前这轮审查的截止时间戳（`time.time()` 口径），没有待处理请求或
        `review_timeout <= 0` 时为 `None`。给 `/runs/{id}/review` 端点透传给
        前端渲染倒计时用——后端不做"提醒"这件事，只给数据。"""
        with self._lock:
            return self._review_deadline

    def pending_review(self) -> FromHarnessToReviewerReviewReq | None:
        """api 层查有没有待处理的审查请求（`GET /runs/{id}` 的
        `review_pending` 字段、`GET /runs/{id}/review` 的详情都读它）。"""
        with self._lock:
            return self._review_request

    def submit_review_response(self, resp: FromHarnessToReviewerReviewResp) -> bool:
        """写决策。没有待处理请求时返回 `False`（不是错误——这次提交要么
        来晚了，要么本来就没什么好答的），调用方（API 端点）据此决定要不要
        报 409。"""
        with self._lock:
            if self._review_request is None:
                return False
            self._review_response = resp
            return True

    def await_review_response(
        self, timeout: float, poll_interval: float = REVIEW_POLL_INTERVAL
    ) -> FromHarnessToReviewerReviewResp | None:
        """`RunHarness` 侧阻塞轮询决策槽，直到有答复或超时。

        **必须是真的等**：读一次没有就当默认，等于没有真的问人，"人机协作"
        又会退化成现在这个自动放行桩（见 `docs/ROADMAP.md`"前后端交互统一"）。
        `timeout <= 0` 时不轮询，立即返回 `None`——留给没有前端接入的场景
        （测试、CLI）秒退化成"无人应答"，调用方（`DataCenterReviewer`）按
        `None` 兜底成 `CONTINUE`，行为等价于 `AutoContinueReviewer`。

        超时返回 `None`；调用方决定怎么兜底，这一层不替它做假设。
        """
        if timeout > 0:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with self._lock:
                    if self._review_response is not None:
                        return self._review_response
                time.sleep(poll_interval)
        return None

    def clear_review(self) -> None:
        """一轮审查结束（无论决策来自哪条路径——真答复还是超时兜底），
        清空请求/决策/截止时间三个槽。`RunHarness.review()` 拿到决策后统一
        调用，不管走的是哪条路径——这样"待审查"标志不会在决策已经拿到之后
        还留着。
        """
        with self._lock:
            self._review_request = None
            self._review_response = None
            self._review_deadline = None


class DataCenterReviewer:
    """`HumanReviewer` 的阻塞式实现：真的等前端通过 `RunDataCenter` 的决策槽
    答一次，而不是读一次没有就当默认。

    `RunHarness.review()` 已经把请求发进 `data_center`（同一个实例）——这里
    只负责等答案，不重复发布，符合"谁控制循环，谁记账"：请求的生命周期归
    `RunHarness`，这里只是它的一个可插拔决策来源。

    超时没人答 → **`STOP`**：沉默不等于同意，"人没有回应"统一表现为"停下来
    等下一次明确的指令"，不在没人看着的时候继续往下跑。这跟
    `AutoContinueReviewer`（压根没有人工审查、没有超时概念，永远 `CONTINUE`）
    是两种不同的场景，行为不要求一致。
    """

    def __init__(self, data_center: RunDataCenter, timeout: float) -> None:
        self._data_center = data_center
        self._timeout = timeout

    def review(self, req: FromHarnessToReviewerReviewReq) -> FromHarnessToReviewerReviewResp:
        """等 `timeout` 秒；有答复用答复，超时就 `STOP`（不再是 `CONTINUE`）。"""
        resp = self._data_center.await_review_response(self._timeout)
        if resp is not None:
            return resp
        return FromHarnessToReviewerReviewResp(decision=HumanDecision.STOP)
