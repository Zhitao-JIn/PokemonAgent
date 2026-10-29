"""recall / memorize 能力实现：六族 store 之上的统一回忆与统一记忆口。

**一份实现，两模式共用**（MCP 化定案 2026-09-29）：进程内模式下 `MemoryTool`
直调这里；MCP 模式下 `mcp_servers/memory_server.py` 的 tool 调这里——分族分流、
融合排序、kind 判别落族的逻辑只有这一份，不存在"进程内一套、server 一套"。

**两类动作**：

- `recall(query, conditions, limit)`：统一回忆口。**不指定记忆种类**——
  `conditions` 只放上下文 hint（`episode_id` / `map_id` / `place`），底层按
  hint 分族圈定 + 语义检索，融合排序后返回混合条目（每条自带 `kind` 身份）；
- `memorize(records)`：统一记忆口。records 按 `kind` 判别落族
  （act / task / episode / run / knowledge），metadata 拼装、knowledge 判重、
  step 单调前置校验——全部沿用原 `MemoryTool` 的既有规则。

**MemoryStorePort 的存储方法在本模块之后是内部接口**：能力面（recall/memorize）
是对外契约，存储原语不再是跨层 Port。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pokemon_agent.memory import EmbeddingProviderPort, LocalMemoryStore, RerankerProviderPort
from pokemon_agent.memory.retrieval import RRF_K
from pokemon_agent.schemas.memory import (
    ActMemory,
    EpisodeMemory,
    KnowledgeRecord,
    RunMemory,
    TaskMemory,
)

# kind（对外身份）→ store 子目录名
_KIND_DIRS: dict[str, str] = {
    "act": "step_memory",
    "task": "task_memory",
    "episode": "episode_memory",
    "run": "run_memory",
    "knowledge": "knowledge_memory",
}


def _natural_key(value: str | None) -> tuple:
    """自然序排序键：数字段按数值、其余按字面（`r1-ep2` < `r1-ep10`）；None 排最后。"""
    if value is None:
        return (1,)
    parts = re.split(r"(\d+)", value)
    return (0, *((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p))


def _default_root() -> Path:
    """缺省落盘根：进程启动目录下的 `memory/`（与 `memory/store.py` 同一条规矩）。"""
    return Path.cwd() / "memory"


class MemoryCapability:
    """recall / memorize 的唯一能力实现。持有六族统一索引层实例（各占
    `<kind>/` 子文件夹），不持有任何记录状态——记录在盘上，索引随各自文件夹。

    与原 `MemoryTool` 的关系：六族 store 的构造、metadata 拼装、knowledge 判重、
    step 单调前置——全部**随迁到这里**；`MemoryTool` 收敛为
    `MemoryToolPort`（recall / memorize 两方法）后委托本类，直至旧方法删除。
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProviderPort,
        reranker_provider: RerankerProviderPort,
        memory_root: str | Path | None = None,
        *,
        rrf_k: int = RRF_K,
        fuse_multiplier: int = 3,
        fuse_floor: int = 10,
    ) -> None:
        self._root = Path(memory_root) if memory_root is not None else _default_root()
        self._stores: dict[str, LocalMemoryStore] = {
            kind: LocalMemoryStore(
                embedding_provider,
                reranker_provider,
                dirname,
                self._root,
                rrf_k=rrf_k,
                fuse_multiplier=fuse_multiplier,
                fuse_floor=fuse_floor,
            )
            for kind, dirname in _KIND_DIRS.items()
        }
        self._step_max: dict[str, int] = {}

    # ---- 内部：store 便捷访问与单调校验 ----

    @property
    def root(self) -> Path:
        """记忆库落盘根——健康检查要报它：一眼确认"连的是不是我以为的那个库"。"""
        return self._root

    def _store(self, kind: str) -> LocalMemoryStore:
        return self._stores[kind]

    def _check_step_monotonic(
        self, episode_id: str, step: int, max_cache: dict[str, int], kind: str
    ) -> None:
        """append 单调前置：step ≥ 该局已有最大 step。缓存 miss 从索引现查填满。"""
        if episode_id not in max_cache:
            store = self._store(kind)
            existing = [
                int(payload.get("step", 0))
                for _u, _m, payload, _t in store.get_many(store.filter({"episode_id": episode_id}))
            ]
            max_cache[episode_id] = max(existing, default=0)
        assert step >= max_cache[episode_id], (
            f"memorize got a stale record: episode {episode_id} "
            f"step {step} < max {max_cache[episode_id]}"
        )

    def _advance_step_cache(self, episode_id: str, step: int, max_cache: dict[str, int]) -> None:
        """put 成功后推进该局的 max 缓存——同实例后续写入的单调检查以它为准。

        调用时机在 put 之后：put 抛异常时缓存不推进（盘上没多出记录，缓存也不该动）。
        此时 episode_id 必然已在缓存中（前面的 `_check_step_monotonic` 已填充）。
        """
        max_cache[episode_id] = max(max_cache[episode_id], step)

    # ---- recall：分族圈定 + 语义检索 + 融合 ----

    def recall(
        self,
        query: str,
        conditions: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """统一回忆口。返回 items：`[{kind, uuid, score, content, payload}]`。

        分族规则（机械，无启发式）：
        - `conditions["episode_id"]` → act（step 升序）+ task（total_acts 升序）；
        - `conditions["run_id"]` / `conditions["episode_id"]` → episode 摘要
          （无 query 时按 conditions 等值 filter 全量自然序；有 query 走语义 rank）；
        - `conditions["goal_id"]` 与 run_id → 本 run 同一 L1 goal 的 episode 摘要；
        - `conditions["runs"] == "all"` → 仅全部 run 记忆，按 run_id 自然序；
        - `query` 非空 → knowledge（语义 search）；
        融合：hint 命中族在前（族内按各自序），语义族随后按 score 降序。
        limit 为 None 时不截断；给定整数时在融合后截断。
        """
        conditions = conditions or {}
        if "run_goal" in conditions:
            raise ValueError("run_goal is not an episode scope; use run_id and goal_id")
        items: list[dict[str, Any]] = []
        retrieval_limit = 10**6 if limit is None else limit

        if conditions.get("runs") == "all":
            return self._recall_run_memories()[:limit]

        goal_id = conditions.get("goal_id")
        episode_id = conditions.get("episode_id")
        run_id = conditions.get("run_id")
        if goal_id and not run_id:
            raise ValueError("goal_id recall requires run_id")
        if episode_id:
            items.extend(self._recall_acts(episode_id))
            items.extend(self._recall_tasks(episode_id))

        if run_id or episode_id or goal_id or query:
            items.extend(self._recall_episode_summaries(query, conditions, retrieval_limit))

        if query:
            items.extend(self._recall_knowledge(query, retrieval_limit))

        return items if limit is None else items[:limit]

    def _recall_acts(self, episode_id: str) -> list[dict[str, Any]]:
        """本局 act 记忆，step 升序。score 恒 None（近因序，非语义分）。"""
        assert episode_id, "act recall needs a non-empty episode_id"
        store = self._store("act")
        items: list[dict[str, Any]] = []
        conditions = {"episode_id": episode_id}
        for uuid_, _meta, payload, _text in store.get_many(store.filter(conditions)):
            try:
                ActMemory.model_validate(payload)
            except ValidationError:
                continue
            items.append(
                {
                    "kind": "act",
                    "uuid": uuid_,
                    "score": None,
                    "content": str(payload.get("action", "")),
                    "payload": payload,
                }
            )
        items.sort(key=lambda item: item["payload"].get("step", 0))
        return items

    def _recall_tasks(self, episode_id: str) -> list[dict[str, Any]]:
        """本局 task 记忆，total_acts 升序。score 恒 None。"""
        assert episode_id, "task recall needs a non-empty episode_id"
        store = self._store("task")
        items: list[dict[str, Any]] = []
        for uuid_, _meta, payload, _text in store.get_many(
            store.filter({"episode_id": episode_id})
        ):
            try:
                memory = TaskMemory.model_validate(payload)
            except ValidationError:
                continue
            items.append(
                {
                    "kind": "task",
                    "uuid": uuid_,
                    "score": None,
                    "content": memory.summary,
                    "payload": payload,
                }
            )
        items.sort(key=lambda item: item["payload"].get("total_acts", 0))
        return items

    def _recall_episode_summaries(
        self, query: str, conditions: dict[str, str], limit: int
    ) -> list[dict[str, Any]]:
        """episode 摘要：query 非空走语义 rank（score = 相关性）；
        无 query 时按 conditions 等值 filter 全量自然序（score = None）。

        episode 族只认 run_id / episode_id / goal_id 三个等值键（success / scene 未来加）——
        其余 hint 键（place 等）不属于这一族，透传会查空。
        content 恒 = markdown（空章就是空串，消费方靠它区分空章与有正文）。
        """
        store = self._store("episode")
        store.refresh_changed()
        episode_conditions = {
            key: value
            for key, value in conditions.items()
            if key in ("run_id", "episode_id", "goal_id")
        }
        items: list[dict[str, Any]] = []
        if query:
            uuids = [u for u, _m, _p, _t in store.get_many(store.filter(episode_conditions))]
            hits, _timings = store.rank(uuids, query, limit)
            pairs: list[tuple[str, float | None]] = hits
        else:
            keyed = [
                ((_natural_key(meta.get("run_id")), _natural_key(meta.get("episode_id"))), uuid_)
                for uuid_, meta, _p, _t in store.get_many(store.filter(episode_conditions))
            ]
            keyed.sort(key=lambda row: row[0])
            pairs = [(uuid_, None) for _key, uuid_ in keyed]
        for uuid_, score in pairs:
            got = store.get(uuid_)
            if got is None:
                continue
            _meta, payload, text = got
            try:
                memory = EpisodeMemory(**payload, markdown=text)
            except ValidationError:
                continue
            items.append(
                {
                    "kind": "episode",
                    "uuid": uuid_,
                    "score": score,
                    "content": memory.markdown,
                    "payload": payload,
                }
            )
        return items

    def _recall_run_memories(self) -> list[dict[str, Any]]:
        """返回全部可解析 run 记录，按 run_id 自然序，正文为 markdown。"""
        store = self._store("run")
        store.refresh_changed()
        items: list[dict[str, Any]] = []
        for uuid_, _metadata, payload, text in store.get_many(store.filter({})):
            try:
                memory = RunMemory(**payload, markdown=text)
            except ValidationError:
                continue
            items.append(
                {
                    "kind": "run",
                    "uuid": uuid_,
                    "score": None,
                    "content": memory.markdown,
                    "payload": payload,
                }
            )
        items.sort(key=lambda item: _natural_key(item["payload"].get("run_id")))
        return items

    def _recall_knowledge(self, query: str, limit: int) -> list[dict[str, Any]]:
        """knowledge 语义检索（查前 mtime 增量刷新）。score 恒为 None：本路不回填相关
        性分，字段保留以与其他 kind 同形。"""
        store = self._store("knowledge")
        store.refresh_changed()
        hits, _timings = store.search(query, limit)
        items: list[dict[str, Any]] = []
        for uuid_ in hits:
            got = store.get(uuid_)
            if got is None:
                continue
            metadata, _payload, text = got
            items.append(
                {
                    "kind": "knowledge",
                    "uuid": uuid_,
                    "score": None,
                    "content": text,
                    "payload": {"source": metadata.get("source", ""), "text": text},
                }
            )
        return items

    # ---- memorize：按 kind 判别落族 ----

    def memorize(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """统一记忆口。每条 record：`{"kind": ..., "payload": {...}}`。

        按 kind 分发落族（metadata 拼装等规则随迁自原 MemoryTool）；
        返回 `stored`：真落库条目的摘要（kind + uuid），被判重跳过的不在其中。
        """
        stored: list[dict[str, Any]] = []
        for record in records:
            kind = record.get("kind")
            payload = record.get("payload")
            assert kind in _KIND_DIRS, f"memorize got unknown kind: {kind!r}"
            assert payload is not None, "memorize record needs a payload"
            if kind == "act":
                uuid_ = self._memorize_act(payload)
            elif kind == "task":
                uuid_ = self._memorize_task(payload)
            elif kind == "episode":
                uuid_ = self._memorize_episode(payload)
            elif kind == "run":
                uuid_ = self._memorize_run(payload)
            else:
                uuid_ = self._memorize_knowledge(payload)
            if uuid_:
                # 空 uuid = 被判重跳过（knowledge 同 topic+正文逐字相同）——不算落库
                stored.append({"kind": kind, "uuid": uuid_})
        return stored

    def _memorize_act(self, payload: dict[str, Any]) -> str:
        """落一条 act 记忆（原 store_act_memory：metadata 拼装 + step 单调）。"""
        entry = ActMemory.model_validate(payload)
        self._check_step_monotonic(entry.episode_id, entry.step, self._step_max, "act")
        map_id = entry.before.place.map_id if entry.before.place is not None else ""
        uuid_ = self._store("act").put(
            metadata={
                "run_id": entry.run_id,
                "episode_id": entry.episode_id,
                "step": str(entry.step),
                "map_id": str(map_id),
            },
            payload=entry.model_dump(),
            text="",
        )
        self._advance_step_cache(entry.episode_id, entry.step, self._step_max)
        return uuid_

    def _memorize_task(self, payload: dict[str, Any]) -> str:
        """落一条 task 记忆（metadata 只收等值坐标；text = summary）。"""
        memory = TaskMemory.model_validate(payload)
        return self._store("task").put(
            metadata={
                "run_id": memory.run_id,
                "episode_id": memory.episode_id,
                "task_id": memory.task_id,
            },
            payload=memory.model_dump(),
            text=memory.summary,
        )

    def _memorize_episode(self, payload: dict[str, Any]) -> str:
        """落一条跨局摘要（markdown/summary 自洽校验）。"""
        memory = EpisodeMemory(**payload)
        assert memory.episode_id, "episode memorize needs a non-empty episode_id"
        assert bool(memory.markdown.strip()) == bool(memory.summary.strip()), (
            "正文要么整条完整、要么整条为空——markdown 与 summary 必须同真同假"
        )
        store = self._store("episode")
        return store.put(
            metadata={
                "run_id": memory.run_id,
                "episode_id": memory.episode_id,
                "run_goal": memory.run_goal,
                "goal_id": memory.goal_id,
                "success": str(memory.success),
                "quality_score": f"{memory.quality_score:.2f}",
                "scene": "|".join(memory.applicable_scenes),
            },
            payload=memory.model_dump(exclude={"markdown"}),
            text=memory.markdown,
        )

    def _memorize_run(self, payload: dict[str, Any]) -> str:
        """落一条 run 记忆；调用方保证 run_id 非空、markdown 与 summary 同真同假。"""
        memory = RunMemory(**payload)
        assert memory.run_id, "run memorize needs a non-empty run_id"
        assert bool(memory.markdown.strip()) == bool(memory.summary.strip()), (
            "正文要么整条完整、要么整条为空——markdown 与 summary 必须同真同假"
        )
        return self._store("run").put(
            metadata={"run_id": memory.run_id, "run_goal": memory.run_goal},
            payload=memory.model_dump(exclude={"markdown"}),
            text=memory.markdown,
        )

    def _memorize_knowledge(self, payload: dict[str, Any]) -> str:
        """落一条 knowledge（判重 topic+正文逐字；落盘形态与手工先验一致）。

        已存在同条时返回空字符串——调用方据 `stored` 里没有它即知被跳过。
        """
        record = KnowledgeRecord(**payload)
        store = self._store("knowledge")
        store.refresh_changed()
        known = {text for _u, _m, _p, text in store.get_many(store.filter({"topic": record.topic}))}
        if record.text in known:
            return ""
        return store.put(
            metadata={"source": record.source, "topic": record.topic},
            payload={},
            text=record.text,
        )
