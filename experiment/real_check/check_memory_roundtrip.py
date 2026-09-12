"""维度 6（memory roundtrip）：MemoryTool 四类记忆的真实写→读→检索→归档。

维度 4 只查"记忆文件落盘了没有"，本脚本把 MemoryTool 的**每条读写路径**
在真实实现下过一遍：真实 `MemoryStore`（注入临时 `memory_root`，不污染
真实记忆库；一条记录一个 uuid 文件 + 每文件夹倒排索引）、真实 fastembed ONNX
（embedding + reranker）。

覆盖五条路径，各自独立判定：
  1. episodic 写读回环：存 3 条单步记忆 → 升序读回、最近 N 条读回；
  2. object 写读回环：追加 3 条交互事件 → 按地图读回、按格读回；
  3. 知识库检索：真实知识库（`memory/knowledge_memory/*.md`）混合检索命中；
  4. 跨局摘要写入 + 混合检索：自造一条摘要落盘 → BM25+向量+reranker 检索命中
     它；run_id 隔离生效（别的 run 查不到）；
  5. 归档（checkpoint 恢复的记忆侧）：`void_memory_after` 后 step>N 的单步记忆与
     交互事件从检索里消失、计数正确；**该局的跨局摘要整条一起归档**（摘要是局
     收尾的产物，收尾在最后一个 checkpoint 之后——不归档就会留下同 episode 的
     第二份账）。文件**留在** `memory/voided-<ts>/`（归档不删除）；再删掉
     `index.json` 强制重建，被归档的记录不得复活（"归档后索引依旧有效"）。

前置条件：无外部 key（fastembed 本地推理）。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path


def main() -> None:
    from pokemon_agent.memory import MemoryStore
    from pokemon_agent.providers import FastEmbedReranker, FastEmbedText
    from pokemon_agent.schemas.harness import (
        FromHarnessToMemoryToolAppendObjectEventsReq,
        FromHarnessToMemoryToolQueryEpisodeStepsReq,
        FromHarnessToMemoryToolQueryEpisodeSummariesReq,
        FromHarnessToMemoryToolQueryKnowledgeReq,
        FromHarnessToMemoryToolQueryObjectEventsAtReq,
        FromHarnessToMemoryToolQueryObjectEventsReq,
        FromHarnessToMemoryToolQueryRecentStepsReq,
        FromHarnessToMemoryToolStoreEpisodeStepReq,
        FromHarnessToMemoryToolStoreEpisodeSummaryReq,
        FromHarnessToMemoryToolVoidMemoryAfterReq,
    )
    from pokemon_agent.schemas.memory import EpisodeMemory, StepMemory
    from pokemon_agent.world import PlaceInWorld
    from pokemon_agent.tools import MemoryTool

    eid = f"memcheck-{time.strftime('%m%d-%H%M%S')}"
    run_id = "memcheck-run"
    tmp = Path("trace_data") / eid
    embedder = FastEmbedText()
    reranker = FastEmbedReranker()
    memory = MemoryTool(
        embedding_provider=embedder,
        reranker_provider=reranker,
        memory_root=tmp / "memory",
    )
    print(f"[1/7] MemoryTool 就绪（eid={eid}，临时目录 {tmp}）", flush=True)

    def place(x: int, y: int) -> PlaceInWorld:
        """世界侧的格子真身——按格查事件、void 这些消费方要的就是 `world.PlaceInWorld`。"""
        return PlaceInWorld(map_id=40, x=x, y=y)

    def snapshot(x: int, y: int) -> dict[str, int]:
        """`PlaceInWorld` 拍平成裸字段，喂给记忆侧各自声明的快照 `Place` 类。

        记忆模型**不引用** `world.PlaceInWorld`（模块间零依赖），只声明形状一致的
        内部类型；桥梁就是这一下 `model_dump()`——生产路径同款（`Brain._snapshot()`）。
        直接把 `PlaceInWorld` 实例丢进去会被 pydantic 拒收。
        """
        return place(x, y).model_dump()

    def obs(step: int, x: int, y: int) -> StepMemory.Observation:
        return StepMemory.Observation(
            step=step,
            place=snapshot(x, y),
            status="测试桩：站在道路上",
            facts={},
            done=False,
        )

    # ---- 路径 1：episodic 写读回环 ----
    for step in (1, 2, 3):
        memory.store_episode_step(
            FromHarnessToMemoryToolStoreEpisodeStepReq(
                entry=StepMemory(
                    episode_id=eid,
                    run_id=run_id,
                    step=step,
                    before=obs(step, 10, 10 + step),
                    rationale=["测试桩：向北走"],
                    action="press up",
                    after=obs(step, 10, 9 + step),
                )
            )
        )
    steps = memory.query_episode_steps(
        FromHarnessToMemoryToolQueryEpisodeStepsReq(episode_id=eid)
    ).steps
    assert [s.step for s in steps] == [1, 2, 3], f"episodic 读回不是升序：{[s.step for s in steps]}"
    recent = memory.query_recent_steps(
        FromHarnessToMemoryToolQueryRecentStepsReq(episode_id=eid, limit=2)
    ).steps
    assert [s.step for s in recent] == [2, 3], (
        f"query_recent_steps 不是最近两条：{[s.step for s in recent]}"
    )
    print("[2/7] 路径 1 episodic：3 条写入 → 升序/最近 N 条读回 PASS", flush=True)

    # ---- 路径 2：object 写读回环 ----
    from pokemon_agent.schemas.memory import ObjectStillEvent

    events = [
        ObjectStillEvent(
            episode_id=eid,
            run_id=run_id,
            step=step,
            actor_place=snapshot(10, 10),
            place=snapshot(11, 10),
            kind="sign",
            button="a",
        )
        for step in (1, 2, 3)
    ]
    memory.append_object_events(FromHarnessToMemoryToolAppendObjectEventsReq(events=events))
    by_map = memory.query_object_events(
        FromHarnessToMemoryToolQueryObjectEventsReq(map_id=40)
    ).events
    got = [e.step for e in by_map]
    assert got == [1, 2, 3], f"按地图读回不是升序全量：{got}"
    by_place = memory.query_object_events_at(
        FromHarnessToMemoryToolQueryObjectEventsAtReq(place=place(11, 10))
    ).events
    assert len(by_place) == 3, f"按格读回应得 3 条，实为 {len(by_place)}"
    assert not memory.query_object_events_at(
        FromHarnessToMemoryToolQueryObjectEventsAtReq(place=place(99, 99))
    ).events, "空格不应返回事件"
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
    )
    memory.store_episode_summary(FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=summary))
    hits = memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(
            scene="40", query="怎么穿过 1 号道路", limit=3, run_id=run_id
        )
    ).summaries
    assert hits, "跨局摘要检索没有命中刚写入的摘要"
    assert hits[0].episode_id == eid, f"检索命中的不是刚写入的那条：{hits[0].episode_id}"
    others = memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(
            scene="40", query="穿过道路", limit=3, run_id="别的run"
        )
    ).summaries
    assert others == [], "run_id 隔离失效：别的 run 查到了本 run 的摘要"
    print("[5/7] 路径 4 episode summary：写入 → 混合检索命中 → run_id 隔离 PASS", flush=True)

    # ---- 路径 5：归档（checkpoint 恢复的记忆侧）----
    # 计数里含 episode_memories=1：路径 4 刚给 `eid` 落了一条摘要，而作废范围
    # 覆盖"该局的全部摘要"（不按 step 筛），它必须一起走。
    removed = memory.void_memory_after(
        FromHarnessToMemoryToolVoidMemoryAfterReq(episode_id=eid, step=2)
    ).removed
    assert removed == {
        "step_memories": 1,
        "object_events": 1,
        "episode_memories": 1,
    }, f"归档计数不对：{removed}"
    kept_steps = memory.query_episode_steps(
        FromHarnessToMemoryToolQueryEpisodeStepsReq(episode_id=eid)
    ).steps
    kept_events = memory.query_object_events(
        FromHarnessToMemoryToolQueryObjectEventsReq(map_id=40)
    ).events
    assert [s.step for s in kept_steps] == [1, 2], "归档后单步记忆残留"
    assert [e.step for e in kept_events] == [1, 2], "归档后交互事件残留"
    still_there = memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(
            scene="40", query="怎么穿过 1 号道路", limit=3, run_id=run_id
        )
    ).summaries
    assert not [s for s in still_there if s.episode_id == eid], (
        "归档后该局的跨局摘要仍可检索——void_memory_after 漏了 episode_memory 这一类"
    )
    voided_dirs = sorted((tmp / "memory").glob("voided-*"))
    assert voided_dirs, "memory/voided-<ts>/ 归档目录没有生成"
    archived_json = list(voided_dirs[0].rglob("*.json"))
    archived_md = list((voided_dirs[0] / "episode_memory").glob("*.md"))
    assert len(archived_json) == 2, (
        f"归档目录里应有 step+object 共 2 个 json，实为 {len(archived_json)}"
    )
    assert len(archived_md) == 1, f"归档目录里应有 1 条局摘要 md，实为 {len(archived_md)}"
    print(
        "[6/7] 路径 5 void：void_memory_after(eid, 2) 归档 step>2 全部 + 该局摘要，"
        "文件留档可查 PASS",
        flush=True,
    )

    # ---- 路径 5b：归档后索引依旧有效（删 index.json 强制重建，废弃记录不复活）----
    for kind in ("step_memory", "object_memory", "episode_memory"):
        (tmp / "memory" / kind / "index.json").unlink()
    rebuilt = MemoryStore(embedder, reranker, "step_memory", tmp / "memory")
    back = sorted(
        int(meta["step"])
        for _u, meta, _p, _t in rebuilt.get_many(rebuilt.filter({"episode_id": eid}))
    )
    assert back == [1, 2], f"索引重建后被归档的记录复活了：step={back}"
    rebuilt_sums = MemoryStore(embedder, reranker, "episode_memory", tmp / "memory")
    back_sums = rebuilt_sums.filter({"episode_id": eid})
    assert back_sums == [], f"索引重建后被归档的局摘要复活了：{back_sums}"
    print("[7/7] 路径 5b 重建：删 index.json 重建后只剩保留区间（无复活）PASS", flush=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"PASS  memory_roundtrip: 五条读写路径全过（临时目录已清理 {tmp}）", flush=True)


if __name__ == "__main__":
    main()
