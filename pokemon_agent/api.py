"""`pokemon_agent.api.py` —— 后端暴露层：FastAPI 服务，含 SSE 事件流。

给前端（人机界面）用的 HTTP 面：启动 run、订阅事件流、提交人工审查决策、
查 run 状态。**协议在 `interfaces/` 与 `schemas/communication/`，实现在这里**——
删掉的 `trace/browser.py`（SSE 观测台）与 `main.py`（CLI）被这一层取代。

# 端点一览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET  | `/health`                 | 存活检查 |
| POST | `/runs`                   | 启动一个 run（后台线程执行） |
| GET  | `/runs/{id}/events`       | SSE 事件流（实时 + 断线补发） |
| GET  | `/runs/{id}`              | run 状态与结算 |
| GET  | `/runs`                   | 活跃 run 列表 |

# SSE 协议

`/runs/{id}/events` 返回 `text/event-stream`，三类消息：

- `event: trace`   —— 一条 `TraceEvent`（`data` 即其 JSON，`id` 是 `event_id`）
- `event: done`    —— run 结束（`data` 是本层拼的结算 JSON），随后流关闭
- `event: error`   —— run 异常终止（`data` 是 `{"message": ...}`），随后流关闭

数据源没有广播总线：端点按 `EVENT_POLL_INTERVAL`（0.1s）轮询两个只读源——
LocalTrace 内存事件表（trace，账本即真相）与 handle 终态（done/error）。
每 15 秒一条 `: ping` 注释行保活。**断线重连**：客户端把最后收到的
`event_id` 放进 `Last-Event-ID` 头（或 `?from_id=`），服务端从那之后继续发
（补发与实时是同一个循环）；若 run 已结束则补发终态后关闭。

**实时画面走独立端点 `/runs/{id}/frames`**（`event: frame`，`data` 是
`{"frame_png": <base64 PNG>}`）——和事件流是两条独立的线：帧由世界侧
`_tick` 每帧塞进单槽管道，这个端点按自己的节奏（~30fps）轮询取最新帧推给
前端；帧是瞬态显示数据，**不带 id、不补发、不落盘**。

# 为什么单进程只能跑一个 run

`_runs` 是这层自己的进程内字典，`start_run()` 一旦发现有 run 处于 `running`
就拒绝新请求（409）——这是 API 自己的设计选择：世界（PyBoy 模拟器）和帧管道
都是进程内单例，两个 run 共用同一份世界会互相踩状态。要并发跑多个 run，
出路是多进程/多实例，不是在这一层加锁排队。

# 装配

`create_app(build_run=None)`：`build_run` 是 `(run_id) -> (harness, trace, world)`
工厂，**默认用 `build_real` 装配真实 harness**（ROM 从 `POKEMON_ROM` 环境变量读）；
测试注入 fake 工厂即可，不碰模拟器。帧管道消费者（`tools.latest_frame`）由默认
装配从结果里接给 `_RunHandle.frames`。

启动：`POKEMON_ROM=/path/to/rom POKEMON_API_PORT=8000 python -m pokemon_agent.api`
（host/port 走 `POKEMON_API_HOST` / `POKEMON_API_PORT`，默认 127.0.0.1:8000）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pokemon_agent.build import build_real
from pokemon_agent.harness import DataCenterReviewer, RunDataCenter, RunHarness
from pokemon_agent.interfaces import TracePort
from pokemon_agent.schemas.brain import TaskForBrain
from pokemon_agent.schemas.frontend import (
    FromFrontendToGameToolLatestFrameReq,
    FromFrontendToGameToolLatestFrameResp,
    FromFrontendToRunHarnessSubmitEditReq,
)
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerReviewResp,
    HumanDecision,
)

SSE_HEARTBEAT = 15.0
"""SSE 心跳间隔（秒）：代理/浏览器空闲超时不会掐断连接。"""

EVENT_POLL_INTERVAL = 0.1
"""事件流端点的轮询间隔（秒）：每 0.1s 扫一遍内存 trace 表 + 终态。
账本是唯一数据源，轮询只读不锁——延迟上限 0.1s，对观测台无感；
换来的是没有任何广播队列/跨线程通道要维护。"""

FRAME_POLL_INTERVAL = 1 / 30
"""帧端点推送节拍（秒）：每 ~30fps 取一次最新帧推给前端。

帧是瞬态显示数据，这个节拍只决定"前端画面更新频率"，与模拟器帧率
（`_tick` 每帧都生产、单槽覆盖）无关——消费者永远取到最新一帧。
30fps 是观感与开销的平衡：160x144 的 PNG 编码 + base64 在 localhost
上每秒 30 次开销可忽略，再往上（60fps）收益递减而带宽翻倍。
"""

REVIEW_TIMEOUT = float(os.environ.get("POKEMON_REVIEW_TIMEOUT", "60"))
"""`RunHarness.review()` 阻塞等前端答复的超时（秒）。**默认 60**——`review`
是人工加目标的主要入口，要给人留够看完 episode 结果、想清楚要不要压新目标
的时间；真的阻塞等一
个人来答，**没人答则 `STOP`**——沉默不等于同意，没人在，run 停下来等下一
次明确指令，不假设"继续"是安全的默认值。
截止时间戳（`RunDataCenter.review_deadline()`）随 `/runs/{id}/review` 响应
一起给前端，前端拿它渲染倒计时，不用自己猜这个数。可用 `POKEMON_REVIEW_TIMEOUT`
环境变量覆盖（设 0 关掉阻塞审查）。"""

AUTO_PUSH_GOALS = os.environ.get("POKEMON_AUTO_PUSH_GOALS", "false").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
"""`plan()` 要不要自动压栈（**默认关**）。关掉后，
`plan()` 仍然照常问模型，只是不再采纳模型给的 `push_goals`——新目标改走
人工两条通道：`review()` 的 `PUSH` 决策（配合上面调大的 `REVIEW_TIMEOUT`），
或 `POST /runs/{id}/goals`。想改回自动压栈，设 `POKEMON_AUTO_PUSH_GOALS=true`
即可，不用改代码。见 `RunHarness.__init__`/`build_real()` 的 `auto_push_goals`
参数说明。"""

AUTO_DECIDE_DONE = os.environ.get("POKEMON_AUTO_DECIDE_DONE", "false").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
"""`plan()` 要不要自己判 run 该不该结束（**默认关**）。关掉后 `resp.done`
被忽略，`plan()` 不直接判 `done` 收尾，而是路由去 `review()` 问人——
没人应答时超时直接 `STOP`，run 会结束，不无限绕回去重问（沉默不等于
"继续"）。想改回自动结束，
设 `POKEMON_AUTO_DECIDE_DONE=true`。见 `RunHarness.__init__`/`build_real()`
的 `auto_decide_done` 参数说明。"""


# =====================================================================
# 事件流的数据源只有一个：LocalTrace（内存事件表）+ handle 终态。
# 没有广播总线——端点按 EVENT_POLL_INTERVAL 轮询这两个只读源，账本即真相。
# =====================================================================


# =====================================================================
# RunHandle —— 一个 run 的全部运行期状态
# =====================================================================


class _RunHandle:
    """API 层对一次 run 的句柄：trace/审查者 + 线程 + 终态。"""

    def __init__(
        self,
        run_id: str,
        trace: TracePort,
        harness: RunHarness,
        world: Any = None,
        frames: Callable[
            [FromFrontendToGameToolLatestFrameReq], FromFrontendToGameToolLatestFrameResp
        ]
        | None = None,
    ) -> None:
        self.run_id = run_id
        self.trace = trace
        self.harness = harness
        """run 的装配物：观测台读目标栈（latest_goals）与编辑（submit_edit）走它。"""
        self.world = world  # 进程级资源（模拟器），run 结束后关闭
        self.frames = frames
        """实时画面管道的消费者接口（`tools.latest_frame`）：取最新一帧 PNG。

        独立于事件流（`/runs/{id}/frames` 端点用它轮询推帧）；`None` = 装配
        不产帧（测试的 fake 工厂没接帧管道）。
        """
        self.thread: threading.Thread | None = None
        self.outcome: dict[str, Any] | None = None
        """run 级结算，**由本层自己拼**：harness 交出的是四个裸值，
        推给前端的 JSON 形状归 API 决定。"""
        self.error: str | None = None
        self.data_center = harness.data_center
        """跟 `harness` 内部读写的是同一个实例（构造时已经是同一份引用）——
        API 端点直接读写它，不经 `harness` 转发（见 `RunDataCenter` 文档）。"""

    @property
    def status(self) -> str:
        """`running` / `done` / `failed`。线程死了但没终态 = 异常外逃的兜底。"""
        if self.outcome is not None:
            return "done"
        if self.error is not None:
            return "failed"
        return "running" if (self.thread is not None and self.thread.is_alive()) else "stopped"


def _execute(handle: _RunHandle, harness: RunHarness, goals: list[TaskForBrain]) -> None:
    """run 线程体：跑完存终态（SSE 端点轮询可见），最后关掉进程级资源。"""
    try:
        outcomes, total, succeeded, success_rate = harness.run(run_id=handle.run_id, goals=goals)
        handle.outcome = {
            "run_id": handle.run_id,
            "outcomes": [o.model_dump() for o in outcomes],
            "total": total,
            "succeeded": succeeded,
            "success_rate": success_rate,
        }
    except Exception as exc:  # noqa: BLE001  守护线程内无处上抛，必须转成终态
        handle.error = str(exc)
    finally:
        close = getattr(handle.world, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001  world 清理失败不应掩盖 run 结算
                # 模拟器关闭失败只影响下次装配，不影响本次结果；没有第二处可上报，
                # 守护线程内也只能在这里就地消化——结果已在 outcome/error 里。
                pass


# =====================================================================
# 请求 schema
# =====================================================================
# 局部 Pydantic 模型会被 FastAPI 的请求体解析当成"不可见"（422）——所以
# 请求 schema 必须模块级；仅纯函数 helper 才是 create_app 的局部函数。


class Goal(BaseModel):
    """POST /runs 与目标栈 push 的目标输入。

    `task_id` 缺省由 API 生成（`api-{run_id}-{n}`）——**同一任务的多次尝试应
    显式传同一个 task_id**，它是实验分组的键（同目标重试/重跑靠它对齐）。
    """

    task_id: str | None = None
    goal: str = Field(min_length=1, description="给 LLM 读的目标描述")
    success_criteria: str = Field(min_length=1, description="成败判据的人类可读描述")
    max_steps: int = Field(gt=0, description="步数上限，超出即判失败")
    initial_state_hint: str = Field(default="", description="采集起点要求，不参与 prompt")


class StartRunReq(BaseModel):
    """POST /runs 的请求体：初始目标栈（栈顶 = 最后一个，先解决）。"""

    run_id: str | None = Field(default=None, description="缺省由 API 生成")
    goals: list[Goal] = Field(min_length=1, description="初始目标栈，非空")


class GoalsEditReq(BaseModel):
    """POST /runs/{id}/goals 的请求体：运行时目标栈编辑，整栈原子替换，不锁
    栈顶——前端把 `goals` 整栈（含栈顶）一次性同步过去，已有 task_id 的项
    保留 task_id（从而保留 `attempts` 计数），新项留空由后端生成。

    """

    goals: list[Goal] = Field(default_factory=list, description="完整新目标栈（栈顶=最后一项）")


class HumanNoteReq(BaseModel):
    """POST /runs/{id}/note 的请求体：人类实时插话，episode
    内下一次决策（`think_action`）会当成最高优先级指令读到，取到即清空，
    只对那一次生效——要一直提醒就得再发一次。"""

    text: str = Field(min_length=1, description="插的这句话，原文透传进 prompt")


class ReviewDecisionReq(BaseModel):
    """POST /runs/{id}/review 的请求体：人类（或未来的 LLM reviewer）对本轮
    审查的决策——形状对应 `FromHarnessToReviewerReviewResp`。

    加/改/删目标统一走
    `POST /runs/{id}/goals`（`FromFrontendToRunHarnessSubmitEditReq`），不在这个决策里。
    """

    decision: Literal["continue", "stop", "retry"] = Field(description="continue / stop / retry")


# =====================================================================
# App 工厂
# =====================================================================


def create_app(
    build_run: Callable[
        [str],
        tuple[RunHarness, TracePort, Any, Callable[[], bytes | None]],
    ]
    | None = None,
) -> FastAPI:
    """建 FastAPI app。

    `build_run`：run 装配工厂，签名为 `(run_id) -> (harness, trace, world,
    frames)`，缺省用 `build_real`（ROM 读
    `POKEMON_ROM` 环境变量）。测试注入 fake 工厂，不碰模拟器。
    """

    def default_build_run(
        rom: str,
    ) -> Callable[
        [str],
        tuple[RunHarness, TracePort, Any, Callable[[], bytes | None]],
    ]:
        """用 `build_real` 装配真实 harness（审查者走默认自动继续；
        SSE 端点直接轮询 LocalTrace）。

        默认开始存档 = `rom + ".state"`（与实验入口一致）：存在才用，
        缺失回退从开机跑——换 ROM 没配存档不该让 run 直接炸。"""

        def build(run_id: str) -> tuple[RunHarness, TracePort, Any, Callable[[], bytes | None]]:
            start_state = rom + ".state" if os.path.isfile(rom + ".state") else None
            # 同一个 RunDataCenter 实例传两处（reviewer 与 harness 自己）——
            # 两边要读写同一份状态，`DataCenterReviewer` 才等得到 `review()`
            # 刚发布的那个请求的答复，见 harness/run_data_center.py。
            data_center = RunDataCenter(review_timeout=REVIEW_TIMEOUT)
            harness, trace, world, tools = build_real(
                rom=rom,
                run_id=run_id,
                state_file=start_state,
                reviewer=DataCenterReviewer(data_center, timeout=REVIEW_TIMEOUT),
                data_center=data_center,
                auto_push_goals=AUTO_PUSH_GOALS,
                auto_decide_done=AUTO_DECIDE_DONE,
            )
            return harness, trace, world, tools.latest_frame

        return build

    if build_run is None:
        rom = os.environ.get("POKEMON_ROM")
        if not rom:
            raise RuntimeError(
                "未设置 POKEMON_ROM 环境变量（指向游戏 ROM 文件）；"
                "或注入 build_run 工厂（测试/自定义装配）"
            )
        build_run = default_build_run(rom)

    _runs: dict[str, _RunHandle] = {}
    app = FastAPI(title="pokemon-agent API", version="0.1.0")

    # 开发期全放行；上线前按前端来源收紧。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def goal_to_task(g: Goal, run_id: str, index: int, prefix: str = "api") -> TaskForBrain:
        """GoalIn → TaskForBrain；task_id 缺省生成（`{prefix}-{run_id}-{n}`，从 1 起）。

        `prefix` 区分来源：初始栈 `api-`、观测台 push 编辑 `edit-`——不同来源
        都从 1 编号，不区分会撞 task_id（remove/replace 靠它定位）。"""
        return TaskForBrain(
            task_id=g.task_id or f"{prefix}-{run_id}-{index + 1}",
            goal=g.goal,
            success_criteria=g.success_criteria,
            max_steps=g.max_steps,
            initial_state_hint=g.initial_state_hint,
        )

    @app.post("/runs", status_code=202)
    def start_run(body: StartRunReq) -> dict[str, str]:
        if any(h.status == "running" for h in _runs.values()):
            raise HTTPException(
                status_code=409,
                detail="同一进程一次只能跑一个 run（世界/帧管道是进程内单例）",
            )
        run_id = body.run_id or f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        goals = [goal_to_task(g, run_id, i) for i, g in enumerate(body.goals)]
        harness, trace, world, frames = build_run(run_id)
        handle = _RunHandle(
            run_id=run_id,
            trace=trace,
            harness=harness,
            world=world,
            frames=frames,
        )
        handle.thread = threading.Thread(
            target=_execute, args=(handle, harness, goals), name=f"run-{run_id}", daemon=True
        )
        _runs[run_id] = handle
        handle.thread.start()
        return {"run_id": run_id, "status": "running"}

    @app.get("/runs")
    def list_runs() -> list[dict[str, str]]:
        return [{"run_id": rid, "status": h.status} for rid, h in _runs.items()]

    def goals_view(handle: _RunHandle) -> list[dict[str, Any]]:
        """目标栈的观测视图（栈顶标记）——`GET /runs/{id}` 和独立的
        `GET /runs/{id}/goals` 共用同一份，避免两处分叉。"""
        goals = handle.harness.latest_goals()
        return [
            {
                "task_id": g.task_id,
                "goal": g.goal,
                "success_criteria": g.success_criteria,
                "max_steps": g.max_steps,
                "top": i == len(goals) - 1,
            }
            for i, g in enumerate(goals)
        ]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        outcome = handle.outcome
        return {
            "run_id": handle.run_id,
            "status": handle.status,
            "event_count": len(handle.data_center.events()),
            "outcome": outcome,
            "error": handle.error,
            "goals": goals_view(handle),
            "review_pending": handle.data_center.pending_review() is not None,
        }

    @app.get("/runs/{run_id}/goals")
    def get_goals(run_id: str) -> list[dict[str, Any]]:
        """目标栈单独的读接口：跟 `POST /runs/{id}/goals`（push）配对，读写各自独立于
        `GET /runs/{id}` 那个大而全的 run 状态接口。前端在每次看到一条
        `Source.PLAN`/`kind=verdict` 的 trace 事件（`plan()` 刚跑完一轮、
        栈刚被消费/可能刚被模型自己压过）时调这个刷新本地草稿——这是目标栈
        在后端真正变化的精确时刻，比"review 变 pending"这个粗糙信号更及时
        （plan → dispatch/reflect 一整个 episode 之后才轮到 review）。
        """
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        return goals_view(handle)

    @app.post("/runs/{run_id}/goals")
    def edit_goals(run_id: str, body: GoalsEditReq) -> dict[str, bool]:
        """运行时目标栈编辑：整栈原子替换，不锁栈顶（由 harness 消费时应用）。

        run 已结束则 409（终态后编辑无意义）；运行中一律接受——指令由
        run 线程在下一轮 plan 消费，不要求此刻恰好处于 plan 节点。
        """
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        if handle.outcome is not None or handle.error is not None:
            raise HTTPException(status_code=409, detail="run 已结束，不能再编辑目标栈")
        push_goals = [goal_to_task(g, run_id, i, prefix="push") for i, g in enumerate(body.goals)]
        handle.harness.submit_edit(FromFrontendToRunHarnessSubmitEditReq(goals=push_goals))
        return {"accepted": True}

    @app.post("/runs/{run_id}/note")
    def submit_human_note(run_id: str, body: HumanNoteReq) -> dict[str, bool]:
        """人类实时插话：非阻塞写入单槽（最新一条覆盖旧的、还没被
        episode 内 `think_action` 取走的），下一次决策会读到。

        run 已结束则 409（终态后插话无意义，没有下一次决策会去读它）；
        运行中一律接受，不要求此刻恰好处于某个特定节点——跟 `edit_goals`
        同一个约定。
        """
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        if handle.outcome is not None or handle.error is not None:
            raise HTTPException(status_code=409, detail="run 已结束，不能再插话")
        handle.harness.submit_human_note(body.text)
        return {"accepted": True}

    @app.get("/runs/{run_id}/review")
    def get_pending_review(run_id: str) -> dict[str, Any] | None:
        """当前待处理的审查请求（`FromHarnessToReviewerReviewReq`），没有则 `null`。

        前端按 `GET /runs/{id}` 的 `review_pending` 标志判断要不要拉这个
        端点——避免每次轮询都传一份可能带完整 `episode_trace` 的大 payload。
        """
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        req = handle.data_center.pending_review()
        if req is None:
            return None
        body = req.model_dump()
        body["deadline_ts"] = handle.data_center.review_deadline()
        return body

    @app.post("/runs/{run_id}/review")
    def submit_review(run_id: str, body: ReviewDecisionReq) -> dict[str, bool]:
        """提交这一轮审查的决策——写进 `RunDataCenter` 的决策槽，
        `RunHarness.review()` 阻塞轮询会读到它（见 `docs/ROADMAP.md`
        "前后端交互统一"）。没有待处理请求时 409（来晚了或本来就没什么好答的）。
        """
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        accepted = handle.data_center.submit_review_response(
            FromHarnessToReviewerReviewResp(
                decision=HumanDecision(body.decision),
            )
        )
        if not accepted:
            raise HTTPException(status_code=409, detail="当前没有待处理的审查请求")
        return {"accepted": True}

    def sse_message(kind: str, data: str, msg_id: str = "") -> str:
        """把一条 SSE 消息拼成线格式（`event:`/`id:`/`data:` 三行 + 空行）。

        注意与"游戏画面帧"（FrameSlot 的 PNG）无关——这里 frame 指**协议层
        的一条消息封装**，两条流（events / frames）都靠它复用格式化逻辑。
        `msg_id` 为空则不带 id 行——控制消息不该污染客户端的 Last-Event-ID
        （补发只认 trace 的 `event_id`）。"""
        if msg_id:
            return f"event: {kind}\nid: {msg_id}\ndata: {data}\n\n"
        return f"event: {kind}\ndata: {data}\n\n"

    def parse_from_id(value: str | None) -> int | None:
        """客户端最后看到的 `event_id`（Last-Event-ID 头或 `?from_id=`）；解析不出 → None。"""
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        """SSE 事件流：轮询两个只读源——LocalTrace（trace，账本即真相）与
        handle 终态（done/error）。

        补发与实时是同一个循环：`last_id` 从 `Last-Event-ID`（或 `?from_id=`）
        起步，每轮把 event_id 更新的 trace 全部发出；终态补发后关流。"""
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")
        from_id = parse_from_id(
            request.headers.get("last-event-id") or request.query_params.get("from_id")
        )

        async def stream():
            last_id = from_id if from_id is not None else -1
            last_output = time.monotonic()
            while True:
                emitted = False
                # 1) 新 trace 事件（内存表追加序，event_id 严格单调）
                for ev in handle.data_center.events():
                    if ev.event_id > last_id:
                        yield sse_message("trace", ev.model_dump_json(), str(ev.event_id))
                        last_id = ev.event_id
                        emitted = True
                # 2) 终态 → 补发后关流
                if handle.outcome is not None:
                    yield sse_message("done", json.dumps(handle.outcome, ensure_ascii=False))
                    return
                if handle.error is not None:
                    yield sse_message(
                        "error", json.dumps({"message": handle.error}, ensure_ascii=False)
                    )
                    return
                if emitted:
                    last_output = time.monotonic()
                elif time.monotonic() - last_output >= SSE_HEARTBEAT:
                    yield ": ping\n\n"
                    last_output = time.monotonic()
                await asyncio.sleep(EVENT_POLL_INTERVAL)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/runs/{run_id}/frames")
    async def run_frames(run_id: str) -> StreamingResponse:
        """实时画面流（**独立于事件流**）：轮询帧管道消费者，推最新一帧。

        帧由世界侧 `_tick` 每帧塞进单槽管道（覆盖式，永远是最新）；这里按
        `FRAME_POLL_INTERVAL` 的节奏取并推——帧是瞬态显示数据，**不补发、
        不带 id**，run 结束（或异常）后关流。`frames` 消费者为 None（装配
        不产帧）时直接关流。
        """
        handle = _runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} 不存在")

        async def stream():
            while True:
                if handle.outcome is not None or handle.error is not None:
                    return  # run 已终态，关流
                frame = (
                    handle.frames(FromFrontendToGameToolLatestFrameReq()).frame_png
                    if handle.frames is not None
                    else None
                )
                if frame is not None:
                    payload = json.dumps(
                        {"frame_png": base64.b64encode(frame).decode("ascii")},
                        ensure_ascii=False,
                    )
                    yield sse_message("frame", payload)
                await asyncio.sleep(FRAME_POLL_INTERVAL)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def main() -> None:
    """`python -m pokemon_agent.api` 入口。"""
    rom = os.environ.get("POKEMON_ROM")
    if not rom:
        raise RuntimeError(
            "POKEMON_ROM 环境变量未设置（指向游戏 ROM 文件）。"
            "示例：POKEMON_ROM=/path/to/rom.gb python -m pokemon_agent.api"
        )
    host = os.environ.get("POKEMON_API_HOST", "127.0.0.1")
    port = int(os.environ.get("POKEMON_API_PORT", "8000"))
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
