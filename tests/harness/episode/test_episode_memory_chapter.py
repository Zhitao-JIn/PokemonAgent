"""S3 的用法示范：**跑挂的局也要在记忆里留一条来源章**（"一局一条"）。

**为什么这个文件值钱**：`episode_memory` 原先只有"收尾链成功蒸馏"这一条写入路径。
于是两类局在记忆里**零痕迹**——整局异常、以及收尾时一条 task 记忆都没有（跳过蒸馏）。
后果不是报错，而是 **`plan` 读记忆时永远看不见"这个目标我试过、跑挂了"**。

修法是写一条**只有来源章、正文为空**的记录。204 起写入点**留在 episode 这一层的边上**
（每层的记忆只由本层写）：没有 task 记忆时由 `episode_done` 的 `leave_chapter` 补；整局异常时
由接住异常的 run `act` 代写（episode 图已经死了）。两处共用 `store_empty_chapter`；
run 的 `review_and_judge` 不再写任何记忆。

**没有标记位**（0914 99 连字段一起删了 `chapter_only`）：空不空看 `markdown` /
`summary` 自己——多一枚标记就是同一件事的第二个真相来源。

**通过共用内存传输夹具访问真 memory server**，存储契约与 MCP 错误信封均走真实实现。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from _doubles.memory_server import memory_server_context
from _harness_fixtures.app_config import DEFAULT_APP_CONFIG
from _harness_fixtures.prompt_text import record_text

from pokemon_agent.brain import Goal, Task
from pokemon_agent.harness.episode.episode_done.leave_chapter import store_empty_chapter
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run.review_and_judge import review_and_judge
from pokemon_agent.harness.run.run_state import RunState
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
    ModelCall,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeOutput, GoalEntry, Termination
from pokemon_agent.schemas.memory import EpisodeMemory

# ---- 假件 ----


class _Trace:
    """只记 append、读回空——`review` 要的两件事够用了。"""

    def __init__(self) -> None:
        self.appended: list = []

    def append(self, req):
        self.appended.append(req)
        return len(self.appended)

    def read_events(self, meta: dict | None = None) -> list:
        return []


class _Runtime:
    def __init__(self, deps: SimpleNamespace) -> None:
        self.context = deps


class _Judger:
    """run 级判定恒回"未达成"——本文件只关心补章，不关心停机。"""

    def judge(self, req):
        return FromHarnessToBrainToolJudgeResp(
            decision=("achieved" if False else "continue"), why="桩", calls=[ModelCall(payload={})]
        )


@pytest.fixture
def memory(tmp_path: Path) -> Iterator[MemoryTool]:
    """通过 MCP 测试真实存储契约，退出时关闭内存传输。"""
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (_, tool):
        yield tool


def _deps(memory: MemoryTool) -> SimpleNamespace:
    """`review_and_judge` 读的四样：记忆、记账、人审、判定。"""
    return SimpleNamespace(
        config=DEFAULT_APP_CONFIG,
        memory=memory,
        trace=_Trace(),
        reviewer=NullReviewer(),
        judger=_Judger(),
    )


def _running_entry(task_id: str = "g1") -> GoalEntry:
    return GoalEntry(
        task=Task(task_id=task_id, goal=f"目标 {task_id}", success_criteria="判据", max_steps=10),
        status=EntryStatus.RUNNING,
    )


def _failed_state(episode_id: str = "r1-ep1") -> RunState:
    return RunState(
        run_id="r1",
        run_goal=Goal(goal="总目标", criteria="判据"),
        goals=[_running_entry()],
        step=1,
        episode_outputs=[
            EpisodeOutput(
                episode_id=episode_id,
                goal_id="g1",
                termination=Termination.ERROR,
                reason="error: IllegalAction",
                tasks_used=0,
                acts_used=0,
            )
        ],
    )


def _stored(deps: SimpleNamespace, episode_id: str) -> list[EpisodeMemory]:
    resp = deps.memory.recall(
        FromHarnessToMemoryToolRecallReq(
            query="", conditions={"episode_id": episode_id}, limit=10**6
        )
    )
    return [
        EpisodeMemory(**item.payload, markdown=item.content)
        for item in resp.items
        if item.kind == "episode"
    ]


# ---- 补章 ----


def _leave(deps: SimpleNamespace) -> EpisodeMemory:
    return store_empty_chapter(
        deps,  # type: ignore[arg-type]
        run_id="r1",
        run_goal="测试总目标",
        goal_id="g1",
        episode_id="r1-ep1",
        goal="目标 g1",
        tasks_used=0,
        acts_used=0,
        termination=Termination.ERROR,
        reason="error: IllegalAction",
        source="run.act",
        step=0,
    )


def test_an_episode_that_left_nothing_gets_a_chapter(memory: MemoryTool) -> None:
    """零痕迹的局补一条**只有来源章**的记录，并记一笔 `write_episode_memory`。"""
    deps = _deps(memory)

    _leave(deps)

    stored = _stored(deps, "r1-ep1")
    assert len(stored) == 1, "一局一条"
    chapter = stored[0]
    assert chapter.markdown == "" and chapter.summary == "", "只有章，没有正文"
    assert chapter.episode_id == "r1-ep1" and chapter.run_id == "r1"
    assert chapter.goal == "目标 g1"
    assert chapter.success is False and chapter.steps == 0
    assert chapter.termination == "error" and chapter.reason == "error: IllegalAction"
    writes = [req for req in deps.trace.appended if req.kind is TraceKind.WRITE_EPISODE_MEMORY]
    assert len(writes) == 1 and writes[0].meta["episode_id"] == "r1-ep1", "章记在这一局名下"


def test_an_episode_that_already_has_a_memory_is_left_alone(memory: MemoryTool) -> None:
    """已经蒸馏过正文的局一个字都不动——补章只填空缺。"""
    deps = _deps(memory)
    deps.memory.memorize(
        FromHarnessToMemoryToolMemorizeReq(
            records=[
                FromHarnessToMemoryToolMemorizeRecord(
                    kind="episode",
                    payload=EpisodeMemory(
                        episode_id="r1-ep1",
                        run_id="r1",
                        goal="目标 g1",
                        steps=7,
                        summary="撞了三次墙",
                        quality_score=0.3,
                        quality_rationale="没走通",
                        markdown="# 本局复盘\n\n撞了三次墙",
                    ).model_dump(),
                )
            ]
        )
    )

    _leave(deps)

    stored = _stored(deps, "r1-ep1")
    assert len(stored) == 1, "不该多出一条章"
    assert stored[0].markdown.strip() and stored[0].steps == 7, "已有正文原样保留"
    assert not [r for r in deps.trace.appended if r.kind is TraceKind.WRITE_EPISODE_MEMORY], (
        "什么都没写，就不该记一笔 write_episode_memory"
    )


def test_run_review_writes_no_memory(memory: MemoryTool) -> None:
    """run 的 `review_and_judge` 只定案（`settle_goal`），不写记忆——每层的记忆只由本层写。"""
    deps = _deps(memory)

    review_and_judge(_failed_state(), _Runtime(deps))

    assert _stored(deps, "r1-ep1") == []
    stamps = [req for req in deps.trace.appended if req.kind is TraceKind.SETTLE_GOAL]
    assert len(stamps) == 1 and stamps[0].goal.status is EntryStatus.FAILED
    assert not [r for r in deps.trace.appended if r.kind is TraceKind.WRITE_EPISODE_MEMORY]


def test_a_chapter_renders_without_a_fake_body() -> None:
    """空正文的记录渲染出来**没有正文那几行**——空字段不该冒充内容进 prompt。"""
    chapter = EpisodeMemory(
        episode_id="r1-ep1",
        run_id="r1",
        goal="进商店买伤药",
        steps=0,
        summary="",
        quality_score=0.0,
        quality_rationale="本局没有产出可蒸馏的正文",
    )

    text = record_text(chapter)

    assert text.splitlines()[0] == "(r1-ep1) 目标：进商店买伤药（未成功，0 个 task / 0 键）", (
        "章在第一行"
    )
    assert "总结" not in text and "质量分" not in text, "没有正文就不要伪造正文"
    assert "本局没有产出可蒸馏的正文" in text, "至少说明为什么没有"


def test_store_refuses_a_body_that_is_only_half_there(memory: MemoryTool) -> None:
    """正文要么整条完整、要么整条为空——**半截的当场炸**。

    `markdown` 空着却写出了 `summary`，是"写入方在伪造内容"：读的人按
    `markdown` 判定这条没有正文，而 `summary` 又在那儿，两边打架。
    """
    bad = EpisodeMemory(
        episode_id="r1-ep1",
        run_id="r1",
        goal="某目标",
        steps=0,
        summary="其实有正文",
        quality_score=0.0,
        quality_rationale="桩",
    )

    with pytest.raises(AssertionError, match="同真同假"):
        memory.memorize(
            FromHarnessToMemoryToolMemorizeReq(
                records=[
                    FromHarnessToMemoryToolMemorizeRecord(kind="episode", payload=bad.model_dump())
                ]
            )
        )
