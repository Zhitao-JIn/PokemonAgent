from __future__ import annotations

from typing import Dict, Any

from pokemon_agent.memory.episode_summarizer import EpisodeMemoryGenerator
from pokemon_agent.schemas.memory_episode_summary import (
    EpisodeSummaryRequest,
    EpisodeSummaryResponse
)
from pokemon_agent.schemas.action import Action
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.memory.semantic.knowledge.store import load_all as _load_knowledge_base
from pokemon_agent.memory.port import SemanticObjectStore
from pokemon_agent.memory.semantic.object_store import ObjectMemory
from pokemon_agent.memory.util import kind_in_frame, parse_landmarks, surrounding_cells
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


class MemoryTool:
    """`MemoryToolPort` 的唯一实现。持有情景记忆列表 + 语义记忆（object）存储。"""

    def __init__(
        self,
        trace_port: TracePort,
        llm_provider: LLMProvider,
        objects: SemanticObjectStore | None = None
    ) -> None:
        self._episodes: list[MemoryEntry] = []
        self._objects: SemanticObjectStore = objects or ObjectMemory()
        self._knowledge = _load_knowledge_base()
        self.episode_generator = EpisodeMemoryGenerator(trace_port, llm_provider)

    # ---- 情景记忆：episodic ----

    def query_episodic(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        assert limit > 0, f"limit must be > 0, got {limit}"
        scored = sorted(
            self._episodes,
            key=lambda m: (self._overlap(query, m.render()), m.step),
            reverse=True,
        )
        hits = [m for m in scored if self._overlap(query, m.render()) > 0][:limit]
        assert len(hits) <= limit, "query_episodic must respect the limit"
        return hits

    def recent(self, episode_id: str, limit: int) -> list[MemoryEntry]:
        assert limit > 0, "recent() needs a positive limit"
        return [m for m in self._episodes if m.episode_id == episode_id][-limit:]

    def write_episodic(self, entry: MemoryEntry) -> None:
        assert entry.rationale, "write_episodic() got an entry without a rationale"
        self._episodes.append(entry)



    @staticmethod
    def _overlap(query: str, content: str) -> int:
        return len(set(query) & set(content))

    # ---- 语义记忆：object ----

    def known_here(self, obs: Observation) -> str:
        if obs.place is None:
            return ""
        lines = [fact.render() for fact in self._objects.query_map(obs.place.map_id)]
        return "\n".join(sorted(lines))

    def knowledge_base(self) -> str:
        return self._knowledge

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