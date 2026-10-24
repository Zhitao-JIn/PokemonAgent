"""`RunStream`：一条样本 run 的全部账，类型化后按层取用。

只读盘上 trace（经 `pokemon_agent.direct.trace.parse`），不重新加载模拟器。样本从存档恢复，
账本里有打包时的 `main` 线（只有一条 `checkpoint_save`）与恢复出的新执行线；只取后者。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pokemon_agent.direct.trace import ParsedEvent, TraceTool, parse
from pokemon_agent.direct.trace.content import (
    EpisodeEndContent,
    EpisodeStartContent,
    RunEndContent,
    SenseFrameContent,
)
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.world.interface import DecodedText


@dataclass(frozen=True)
class Frame:
    """一帧观测（episode 层或 task 层的 `sense_frame`）。"""

    uuid: str
    episode_id: str
    task_id: str
    step: int
    content: SenseFrameContent

    @property
    def from_decode(self) -> bool:
        """这一帧带屏幕解码的文字（`ram.decoded`，可当真值）。"""
        return self.content.ram is not None

    @property
    def text(self) -> DecodedText:
        """这一帧屏幕解码出的对话 / 选项 / 光标。

        判据只读它，不读 `facts` 里的（episode 层那份来自视觉）。

        前置条件：`from_decode`。
        """
        ram = self.content.ram
        assert ram is not None, "没有内存读数的帧没有解码文字"
        return ram.decoded


class RunStream:
    """一条执行线上的全部账，按 `(ts, uuid)` 升序。"""

    def __init__(self, events: list[ParsedEvent]) -> None:
        """前置条件：`events` 属于同一 run 的同一条执行线、已按时间排好。"""
        self.events = events

    @classmethod
    def load(
        cls,
        trace_root: str | Path,
        run_id: str,
        branch: str | None = None,
        backend: str = "local",
    ) -> RunStream:
        """读一个 run 的账；`branch` 缺省自动检测（local）或由调用方必给（langfuse）。

        `backend`：与 TraceTool.build 同语义——`local` 读 `trace_root` 下的本地账，
        `langfuse` 直接问本机 Langfuse 服务（`trace_root` 忽略，不传）。**与写账侧同源**：
        run-one 用哪种后端写，scorer 就用哪种读。

        读取用**空 meta 全量**（不走 TraceTool 的血缘可见性拼接——那条路在 branch 缺省
        main 时只见父线，恢复线整个不可见，335 首跑实锤），分支过滤在本层自己做：
        打分只需要本执行线的账，祖先线（打包种子等）明确排除。

        **langfuse 寻址按 (run_id, branch)**（336 spec）：trace_id 由两者共同决定，
        所以 `branch` 必须来自 `run.json`（run-one 收尾时写入 `RunResult.branch`）；
        没给则退 `main`——大概率读不到账 → unjudgeable。
        """
        if backend == "local":
            tool = TraceTool.build(run_id=run_id, trace_root=trace_root, backend=backend)
            parsed = [parse(e) for e in tool.read_events()]
            if branch is None:
                restored = [p for p in parsed if p.kind == TraceKind.CHECKPOINT_RESTORE]
                branch = restored[-1].meta.branch if restored else "main"
            return cls([p for p in parsed if p.meta.branch == branch])
        # langfuse：trace_id 按 (run_id, branch) 寻址——branch 必给。
        tool = TraceTool.build(run_id=run_id, branch=branch or "main", backend=backend)
        parsed = [parse(e) for e in tool.read_events()]
        want = branch or "main"
        return cls([p for p in parsed if p.meta.branch == want])

    @property
    def branch(self) -> str:
        """执行线名。"""
        return self.events[0].meta.branch if self.events else ""

    def of_kind(self, *kinds: str) -> list[ParsedEvent]:
        """某几种账，保持时间序。"""
        wanted = set(kinds)
        return [e for e in self.events if e.kind in wanted]

    def run_end(self) -> RunEndContent | None:
        """run 的收尾；没有（出错或没跑完）为 None。"""
        ends = self.of_kind(TraceKind.RUN_END)
        return ends[-1].content if ends else None  # type: ignore[return-value]

    def run_episodes(self) -> list[str]:
        """本执行线上开局过的全部 `episode_id`，按开局先后、去重。

        run 粒度的取局口径：run 内只有一个 run goal，归属键是 `run_id`（`load` 已按 run
        与分支过滤），不在 `episode_start.goal_id` 上——planner 合法拆解时会新建目标 id。
        """
        starts = (
            e
            for e in self.of_kind(TraceKind.EPISODE_START)
            if isinstance(e.content, EpisodeStartContent)
        )
        return list(dict.fromkeys(e.meta.episode_id for e in starts))

    def episodes_for(self, goal_id: str) -> list[str]:
        """派给这个目标的各局 `episode_id`，按开局先后。"""
        return [
            e.meta.episode_id
            for e in self.of_kind(TraceKind.EPISODE_START)
            if isinstance(e.content, EpisodeStartContent) and e.content.goal_id == goal_id
        ]

    def episode_end(self, episode_id: str) -> EpisodeEndContent | None:
        """某一局的收尾。"""
        for e in self.of_kind(TraceKind.EPISODE_END):
            if e.meta.episode_id == episode_id and isinstance(e.content, EpisodeEndContent):
                return e.content
        return None

    def frames(self, episode_ids: list[str] | None = None) -> list[Frame]:
        """这些局里的全部帧（两层 `sense` 都算）；`None` = 整个 run。"""
        keep = set(episode_ids) if episode_ids is not None else None
        out: list[Frame] = []
        for e in self.of_kind(TraceKind.SENSE_FRAME):
            if keep is not None and e.meta.episode_id not in keep:
                continue
            assert isinstance(e.content, SenseFrameContent)
            out.append(Frame(e.uuid, e.meta.episode_id, e.meta.task_id, e.meta.step, e.content))
        return out

    def in_episodes(self, episode_ids: list[str], *kinds: str) -> list[ParsedEvent]:
        """这些局里的某几种账。"""
        keep = set(episode_ids)
        return [e for e in self.of_kind(*kinds) if e.meta.episode_id in keep]


__all__ = ["Frame", "RunStream"]
