"""维度 6（memory roundtrip）：MemoryTool 四类记忆的真实写→读→检索→截断。

维度 4 只查"记忆文件落盘了没有"，本脚本把 MemoryTool 的**每条读写路径**
在真实实现下过一遍：真实 `FileEpisodeMemoryStore` / `EventObjectStore` /
`KnowledgeStore`（注入临时目录，不污染真实记忆库）、真实 fastembed ONNX
（embedding + reranker）、真实权限运行时（`@initialize`，方法上的
`@require_permission` 全部生效）。

覆盖五条路径，各自独立判定：
  1. episodic 写读回环：存 3 条单步记忆 → 升序读回、最近 N 条读回；
  2. object 写读回环：追加 3 条交互事件 → 按地图读回、按格读回；
  3. 知识库检索：真实知识库（`memory/semantic/knowledge/*.md`）混合检索命中；
  4. 跨局摘要写入 + 混合检索：自造一条摘要落盘 → BM25+向量+reranker 检索命中
     它；run_id 隔离生效（别的 run 查不到）；
  5. 截断（checkpoint 恢复的记忆侧）：`void_memory_after` 后 step>N 的
     单步记忆与交互事件全部消失、返回计数正确。

前置条件：无外部 key（fastembed 本地推理）。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from agent_permission import initialize


@initialize
def main() -> None:
    from pokemon_agent.memory import EventObjectStore, FileEpisodeMemoryStore
    from pokemon_agent.providers import FastEmbedReranker, FastEmbedText
    from pokemon_agent.schemas.communication import FromHarnessToMemoryToolQueryKnowledgeReq
    from pokemon_agent.schemas.datastore import EpisodeMemory, StepMemory
    from pokemon_agent.schemas.domain import ObservationFromWorld, PlaceInWorld
    from pokemon_agent.tools import MemoryTool

    eid = f"memcheck-{time.strftime('%m%d-%H%M%S')}"
    run_id = "memcheck-run"
    tmp = Path("trace_data") / eid
    memory = MemoryTool(
        embedding_provider=FastEmbedText(),
        reranker_provider=FastEmbedReranker(),
        episodes=FileEpisodeMemoryStore(tmp / "episodic"),
        objects=EventObjectStore(tmp / "objects"),
    )
    print(f"[1/7] MemoryTool 就绪（eid={eid}，临时目录 {tmp}）", flush=True)

    def place(x: int, y: int) -> PlaceInWorld:
        return PlaceInWorld(map_id=40, x=x, y=y)

    def obs(step: int, x: int, y: int) -> ObservationFromWorld:
        return ObservationFromWorld(
            step=step, place=place(x, y), status="测试桩：站在道路上", facts={}, done=False
        )

    # ---- 路径 1：episodic 写读回环 ----
    for step in (1, 2, 3):
        memory.store_episode_step(
            StepMemory(
                episode_id=eid,
                run_id=run_id,
                step=step,
                before=obs(step, 10, 10 + step),
                rationale=["测试桩：向北走"],
                action="press up",
                after=obs(step, 10, 9 + step),
            )
        )
    steps = memory.query_episode_steps(eid)
    assert [s.step for s in steps] == [1, 2, 3], f"episodic 读回不是升序：{[s.step for s in steps]}"
    recent = memory.query_recent_steps(eid, 2)
    assert [s.step for s in recent] == [2, 3], (
        f"query_recent_steps 不是最近两条：{[s.step for s in recent]}"
    )
    print("[2/7] 路径 1 episodic：3 条写入 → 升序/最近 N 条读回 PASS", flush=True)

    # ---- 路径 2：object 写读回环 ----
    from pokemon_agent.schemas.datastore import ObjectStillEvent

    events = [
        ObjectStillEvent(
            episode_id=eid,
            run_id=run_id,
            step=step,
            actor_place=place(10, 10),
            place=place(11, 10),
            kind="sign",
            button="a",
        )
        for step in (1, 2, 3)
    ]
    memory.append_object_events(events)
    by_map = memory.query_object_events(40)
    got = [e.step for e in by_map]
    assert got == [1, 2, 3], f"按地图读回不是升序全量：{got}"
    by_place = memory.query_object_events_at(place(11, 10))
    assert len(by_place) == 3, f"按格读回应得 3 条，实为 {len(by_place)}"
    assert memory.query(place(99, 99)) == [], "空格不应返回事件"
    print("[3/7] 路径 2 object：3 条追加 → 按图/按格读回 PASS", flush=True)

    # ---- 路径 3：知识库混合检索（真实知识库 + 真实 reranker）----
    resp = memory.query_knowledge(
        FromHarnessToMemoryToolQueryKnowledgeReq(query="野外草丛遇到野生宝可梦怎么办", limit=3)
    )
    assert resp.contents, "知识库检索没有命中任何条目"
    assert len(resp.contents) == len(resp.sources), "contents 与 sources 数量不一致"
    n_hits = len(resp.contents)
    print(f"[4/7] 路径 3 knowledge：命中 {n_hits} 条，来源 {resp.sources} PASS", flush=True)

    # ---- 路径 4：跨局摘要写入 + 混合检索 + run_id 隔离 ----
    summary = EpisodeMemory(
        episode_id=eid,
        run_id=run_id,
        goal="从真新镇走到常磐市",
        success=True,
        steps=12,
        summary="出镇后沿 1 号道路向北，遇到挡路训练师先对话触发战斗再通过。",
        reusable_patterns=["遇到 NPC 挡路时先按 A 触发对话"],
        quality_score=0.8,
        quality_rationale="测试桩：路径明确、可复用。",
        applicable_scenes=["*"],
        markdown="## 经验\n\n出镇后沿 1 号道路向北直走，遇挡路训练师先按 A 触发对话再战斗。",
        filename=f"memcheck-{time.strftime('%m%d-%H%M%S')}",
    )
    memory.store_episode_summary(summary)
    hits = memory.query_episode_summaries(
        scene="40", query="怎么穿过 1 号道路", limit=3, run_id=run_id
    )
    assert hits, "跨局摘要检索没有命中刚写入的摘要"
    assert hits[0].episode_id == eid, f"检索命中的不是刚写入的那条：{hits[0].episode_id}"
    others = memory.query_episode_summaries(scene="40", query="穿过道路", limit=3, run_id="别的run")
    assert others == [], "run_id 隔离失效：别的 run 查到了本 run 的摘要"
    print("[5/7] 路径 4 episode summary：写入 → 混合检索命中 → run_id 隔离 PASS", flush=True)

    # ---- 路径 5：截断（checkpoint 恢复的记忆侧）----
    removed = memory.void_memory_after(eid, 2)
    assert removed == {"step_memories": 1, "object_events": 1}, f"截断计数不对：{removed}"
    assert [s.step for s in memory.query_episode_steps(eid)] == [1, 2], "截断后单步记忆残留"
    assert [e.step for e in memory.query_object_events(40)] == [1, 2], "截断后交互事件残留"
    print("[6/7] 路径 5 truncate：void_memory_after(eid, 2) 截掉 step>2 全部 PASS", flush=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"PASS  memory_roundtrip: 五条读写路径全过（临时目录已清理 {tmp}）", flush=True)


if __name__ == "__main__":
    main()
