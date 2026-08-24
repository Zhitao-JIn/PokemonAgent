from __future__ import annotations

from typing import Dict, Any

from pokemon_agent.interfaces.embedding import EmbeddingProvider
from pokemon_agent.interfaces.rerank import RerankerProvider
from pokemon_agent.memory.episode.episode_summarizer import EpisodeMemoryGenerator
from pokemon_agent.memory.semantic.retrieval import hybrid_retrieve
from pokemon_agent.memory.episode.utils import _get_episode_memories, _memory_entry_to_episode_steps
from pokemon_agent.schemas.action import Action
from pokemon_agent.schemas.memory_episode import EpisodeMemory
from pokemon_agent.schemas.memory_episode_summary import EpisodeContext
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.memory.semantic.knowledge.store import load_chunks as _load_knowledge_chunks
from pokemon_agent.memory.semantic.knowledge.store import load_named_chunks as _load_named_knowledge_chunks
from pokemon_agent.memory.semantic.knowledge.store import mtime as _knowledge_dir_mtime
from pokemon_agent.interfaces.semantic_memory import SemanticObjectStore
from pokemon_agent.memory.semantic.object_store import ObjectMemory
from pokemon_agent.memory.semantic.util import kind_in_frame, parse_landmarks, surrounding_cells
from pokemon_agent.schemas.memory_semantic import (
    RESULT_DIALOG,
    RESULT_NONE,
    RESULT_WARP_PREFIX,
    ObjectFact,
)
from pokemon_agent.schemas.observation import (
    BUTTON_FACING,
    INTERACT_KEY,
    Observation,
    Place,
)

INTERACTIVE = ("人", "招牌", "门")

# 跨局摘要记忆 / 知识库排序：混合检索（关键词 BM25 + 向量 + reranker 精排，见
# `memory/retrieval.py`）给出的 reranker 分数是"文本相关性"这一项，值域没有
# 自然的上下界（cross-encoder 输出的是未经归一化的 logits），所以每次查询后
# 现算 min-max 归一化到 [0, 1] 再叠加权重——不能直接拿 reranker 的原始分数
# 和质量分/成败这些本来就在 [0, 1] 或布尔量级的信号相加，量纲对不上。
# 权重比例延续之前的结论：相关性最重要（"这条经验到底切不切题"），
# 质量/成功用来在相关性接近时挑更可信的那条，不该反过来压过相关性。
EPISODE_RELEVANCE_WEIGHT = 10.0
EPISODE_QUALITY_WEIGHT = 3.0
EPISODE_SUCCESS_WEIGHT = 1.5

# 混合检索粗筛阶段留几个候选给 reranker 精排——比 `limit` 大一截，给 reranker
# 留出"重新排出比粗筛更准的顺序"的空间；候选集本来就小于这个数时，
# `hybrid_retrieve` 会自动只处理实际有的那些，不会因为要凑数而出错。
EPISODE_FUSE_TOP_K = 10
KNOWLEDGE_FUSE_TOP_K = 10


def _normalize(scores: list[float]) -> list[float]:
    """min-max 归一化到 [0, 1]。全部并列（`max == min`）时统一给 1.0——
    这种情况下没有相关性上的高低之分，不该被除零判成全部是 0（那样会让
    质量/成功权重在"文本同样相关"的场景里反而失去区分度）。
    """
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


class MemoryTool:
    """`MemoryToolPort` 的唯一实现。持有单步情景记忆、跨局摘要记忆、
    语义记忆（object + knowledge）存储。
    """

    def __init__(
        self,
        trace_port: TracePort,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider,
        objects: SemanticObjectStore | None = None,
    ) -> None:
        self._episodes: list[MemoryEntry] = []
        self._episode_memories: list[EpisodeMemory] = []
        self._episode_memory_vectors: dict[str, list[float]] = {}
        """`episode_id → embedding`，**写入时算好、缓存住**——查询时只用现算
        `query` 自己的向量，不用每次检索都把全部候选重新 embed 一遍。
        """
        self._objects: SemanticObjectStore = objects or ObjectMemory()
        self._embedding = embedding_provider
        self._reranker = reranker_provider
        self._knowledge_chunks: list[str] = []
        self._knowledge_names: list[str] = []
        self._knowledge_vectors: list[list[float]] = []
        self._knowledge_mtime: float = -1.0
        """哨兵值：任何真实 mtime 都 ≥ 0，第一次 `knowledge_base()` 调用
        一定会命中"和缓存不一致"从而触发首次加载。
        """
        self.episode_generator = EpisodeMemoryGenerator(trace_port, llm_provider)

    # ---- 情景记忆：episodic（单步，全量，不检索） ----

    def query_episodic(self, episode_id: str) -> list[MemoryEntry]:
        assert episode_id, "query_episodic() needs a non-empty episode_id"
        hits = sorted(
            (m for m in self._episodes if m.episode_id == episode_id),
            key=lambda m: m.step,
        )
        return hits

    def recent(self, episode_id: str, limit: int) -> list[MemoryEntry]:
        assert limit > 0, "recent() needs a positive limit"
        return [m for m in self._episodes if m.episode_id == episode_id][-limit:]

    def write_episodic(self, entry: MemoryEntry) -> None:
        assert entry.rationale, "write_episodic() got an entry without a rationale"
        self._episodes.append(entry)

    @property
    def episodic_size(self) -> int:
        return len(self._episodes)

    # ---- 跨局摘要记忆：episode memory（混合检索） ----

    def query_episode_memories(self, scene: str, query: str, limit: int = 3) -> list[EpisodeMemory]:
        """场景硬过滤（含通配，见 `EpisodeMemory.matches_scene`）之后，
        用混合检索（BM25 + 向量 + reranker）排出"文本相关性"，
        再叠加质量分和是否成功两个信号，取前 `limit` 条。
        """
        assert scene, "query_episode_memories() needs a non-empty scene"
        assert limit > 0, f"limit must be > 0, got {limit}"
        candidates = [m for m in self._episode_memories if m.matches_scene(scene)]
        if not candidates:
            return []

        documents = [m.render() for m in candidates]
        vectors = [self._episode_memory_vectors[m.episode_id] for m in candidates]
        fuse_top_k = max(limit * 3, EPISODE_FUSE_TOP_K)
        results = hybrid_retrieve(
            query, documents, self._embedding, self._reranker,
            fuse_top_k=fuse_top_k, document_vectors=vectors,
        )
        relevance = _normalize([score for _, score in results])

        scored = []
        for (idx, _), rel in zip(results, relevance):
            memory = candidates[idx]
            quality = memory.content.quality.score * EPISODE_QUALITY_WEIGHT
            success = EPISODE_SUCCESS_WEIGHT if memory.success else 0.0
            scored.append((rel * EPISODE_RELEVANCE_WEIGHT + quality + success, memory))
        scored.sort(key=lambda p: p[0], reverse=True)

        hits = [memory for _, memory in scored[:limit]]
        assert len(hits) <= limit, "query_episode_memories must respect the limit"
        return hits

    def write_episode_memory(self, entry: EpisodeMemory) -> None:
        assert entry.rationale, "write_episode_memory() got an entry without a rationale"
        assert entry.content.summary, "write_episode_memory() got an entry without a summary"
        self._episode_memories.append(entry)
        self._episode_memory_vectors[entry.episode_id] = self._embedding.embed([entry.render()])[0]

    @property
    def episode_memory_size(self) -> int:
        return len(self._episode_memories)

    def summarize_episode(
        self, episode_id: str, run_id: str, goal: str, outcome: Dict[str, Any]
    ) -> EpisodeMemory:
        """一局结束时调用：把这一局的单步记忆蒸馏成一条跨局摘要记忆，写入并返回。

        前置条件：`episode_id` 对应的单步记忆已经全部写完（调用方保证——
            harness 在真正结束这一局之后才该调它，不是提前调）。
        """
        entries = _get_episode_memories(self._episodes, episode_id)
        context = EpisodeContext(
            episode_id=episode_id,
            run_id=run_id,
            goal=goal,
            success=bool(outcome.get("success", False)),
            steps=int(outcome.get("steps", len(entries))),
            max_steps=int(outcome.get("max_steps", len(entries) or 1)),
            initial_state=entries[0].before.render() if entries else "",
            final_state=entries[-1].after.render() if entries else "",
            key_steps=_memory_entry_to_episode_steps(entries),
        )
        episode_memory = self.episode_generator.generate_summary(
            episode_id, run_id, goal, outcome, context
        )
        self.write_episode_memory(episode_memory)
        return episode_memory

    # ---- 语义记忆：object ----

    def known_here(self, obs: Observation) -> str:
        if obs.place is None:
            return ""
        lines = [fact.render() for fact in self._objects.query_map(obs.place.map_id)]
        return "\n".join(sorted(lines))

    def see_objects(self, obs: Observation, stamp: str) -> None:
        self._objects.see(parse_landmarks(obs), stamp)

    def note_step(
        self,
        before: Observation,
        action: Action,
        after: Observation
    ) -> list[ObjectFact]:
        if not self._should_note_step(before, action, after):
            return []

        facing = BUTTON_FACING.get(action.name, before.facts.get("facing", ""))
        if not facing or before.place is None or after.place is None:
            return []

        ahead = before.place.step_toward(facing)
        key_desc = f"x={before.place.x} y={before.place.y}→{action.name}"
        if action.name == INTERACT_KEY:
            kind = self._kind_at(before, ahead)
            if kind is None:
                return []
            text = after.facts.get("dialog_text", "")
            fact = self._objects.touch(ahead, kind, text)
            self._objects.record_attempt(
                ahead, kind, key_desc, RESULT_DIALOG if text.strip() else RESULT_NONE
            )
            return [fact]

        if action.args.get("times", "1") != "1":
            return []

        moved = self._outcome(before, after, facing)
        if not moved:
            return []


        candidates = [
            (place, self._kind_at(before, place))
            for place in surrounding_cells(before.place)
        ]
        known = [kind for _, kind in candidates if kind is not None]
        changed = before.place.map_id != after.place.map_id
        if changed and len(known) > 1:
            return []


        result = f"{RESULT_WARP_PREFIX}{after.place.map_id}" if changed else RESULT_NONE
        touched: list[ObjectFact] = []
        for place, kind in candidates:
            if kind is None:
                continue
            touched.append(self._objects.record_attempt(place, kind, key_desc, result))
        return touched

    def _kind_at(self, obs: Observation, place: Place) -> str | None:
        kind = kind_in_frame(obs, place, INTERACTIVE)
        if kind is not None:
            return kind
        fact = self._objects.query(place)
        if fact is not None and fact.landmark.kind in INTERACTIVE:
            return fact.landmark.kind
        return None

    @staticmethod
    def _outcome(before: Observation, after: Observation, facing: str) -> str:
        assert before.place is not None and after.place is not None
        if after.place.map_id != before.place.map_id:
            return "warp"
        if (after.place.x, after.place.y) != (before.place.x, before.place.y):
            return "moved"
        if before.facts.get("facing", "") == facing:
            return "stay"
        return ""

    @staticmethod
    def _should_note_step(before: Observation, action: Action, after: Observation) -> bool:
        return before.place is not None and after.place is not None and action.name != ""

    # ---- 语义记忆：知识库（和坐标无关的通用先验，混合检索） ----

    def knowledge_base(self, query: str, limit: int = 5) -> str:
        assert query, "knowledge_base() needs a non-empty query"
        assert limit > 0, f"limit must be > 0, got {limit}"
        self._refresh_knowledge_index()
        if not self._knowledge_chunks:
            return ""

        fuse_top_k = max(limit * 3, KNOWLEDGE_FUSE_TOP_K)
        results = hybrid_retrieve(
            query, self._knowledge_chunks, self._embedding, self._reranker,
            fuse_top_k=fuse_top_k, document_vectors=self._knowledge_vectors,
        )
        hits = results[:limit]
        return "\n\n".join(self._knowledge_chunks[idx] for idx, _ in hits)

    def knowledge_sources(self, query: str, limit: int = 5) -> list[str]:
        assert query, "knowledge_sources() needs a non-empty query"
        assert limit > 0, "knowledge_sources() limit must be positive"
        self._refresh_knowledge_index()
        if not self._knowledge_chunks:
            return []
        results = hybrid_retrieve(
            query, self._knowledge_chunks, self._embedding, self._reranker,
            fuse_top_k=max(limit * 3, KNOWLEDGE_FUSE_TOP_K),
            document_vectors=self._knowledge_vectors,
        )
        return [self._knowledge_names[idx] for idx, _ in results[:limit]]

    def _refresh_knowledge_index(self) -> None:
        """知识库文件的 mtime 变了才重新分片、重新 embed——**不是每次查询都重算**。

        `load_chunks()` 本身很便宜（读取每个文件），贵的是 `embed()`；
        用 mtime 判断"文件是不是被运营编辑过"，既保留了原来"编辑 `.md` 文件
        不用重启进程就生效"的性质（见 `memory/semantic/knowledge/store.py`），
        又不用像 `load_all()` 那版一样每次查询都重新付一次 embedding 的成本。
        """
        current = _knowledge_dir_mtime()
        if current != self._knowledge_mtime:
            self._knowledge_chunks = _load_knowledge_chunks()
            self._knowledge_names = [name for name, _ in _load_named_knowledge_chunks()]
            self._knowledge_vectors = (
                self._embedding.embed(self._knowledge_chunks) if self._knowledge_chunks else []
            )
            self._knowledge_mtime = current
