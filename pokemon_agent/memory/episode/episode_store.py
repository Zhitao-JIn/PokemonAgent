"""episode 记忆的存储：md 是主内容，元数据是它的 frontmatter。**纯存储，不调模型。**

单条跨局摘要 = 一个 `.md` 文件：

    ---
    {"episode_id": "...", "run_id": "...", "goal": "...", "success": true,
     "steps": 12, "summary": "...", "reusable_patterns": [...], ...}
    ---
    （蒸馏出的完整记忆正文）

**md 是唯一真相**：正文给人看、给知识库用；frontmatter 里的字段（summary/
patterns/decisions/quality/scenes/tags）是检索要的结构化元数据。重启后扫描目录、
解析 frontmatter 就能完整重建检索索引——"文档存了、数据丢了"的分裂不存在。

**单步记忆（`StepMemory`）落盘写穿**（checkpoint 恢复的前置依赖）：按局分文件
`steps-{episode_id}.jsonl`，与 `semantic/semantic_store.py` 的 `EventObjectStore`
同构——append 写穿（盘上永不落后于内存）、`truncate(episode_id, step)` 供
checkpoint 恢复截断、构造时全量读回。它的生命周期仍是一局：局结束
（`discard_episode_steps`）连文件一起删，不跨局累积。

蒸馏（LLM 调用）与组装都在 `Brain.verify_and_summarize()`（见 ROADMAP 16）——
本文件只剩 `FileEpisodeMemoryStore` 一个类，只管存。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import ValidationError

from pokemon_agent.schemas.datastore import EpisodeMemory, StepMemory

from .util import parse_md, safe_filename


def _safe_episode_id(episode_id: str) -> str:
    """把 episode_id 压成文件名安全的一段（与 `semantic_store` 同一规则）。"""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


def _memory_dir() -> Path:
    """跨局摘要的落盘目录：**与 `episode_store.py` 同目录的 `memory/`**。

    数据留在包内这个位置，但**不进 git**（见 `.gitignore` 的
    `pokemon_agent/memory/episode/memory/`）——它和 `semantic/knowledge/*.md`
    （运营手写内容，进版本库）不是一回事：这里是 agent 运行期攒出来的产物。
    """
    return Path(__file__).resolve().parent / "memory"


class FileEpisodeMemoryStore:
    """`EpisodeMemoryStore` 的文件实现：单步记忆落盘写穿（JSONL），
    跨局摘要落盘为 md + frontmatter。"""

    def __init__(
        self,
        directory: str | Path | None = None,
        max_summaries: int = 50,
    ) -> None:
        self._dir = Path(directory) if directory is not None else _memory_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        # step 记忆按局隔离：`episode_id → 局内列表`。它的生命周期就是**一局**——
        # 只服务本局决策（查询都按当前局取），蒸馏完（`discard_episode_steps`）
        # 连落盘文件一起删，不跨局累积。
        # 落盘写穿（checkpoint 恢复的前置依赖，与 EventObjectStore 同构）：
        # 盘上是真相，内存是进程内副本；`_step_max` 是 append 单调前置的
        # 依据（恢复后同局重跑，step 号从截断点重新出发）。
        self._steps: dict[str, list[StepMemory]] = {}
        self._step_max: dict[str, int] = {}
        self._load_steps()
        self._max_summaries = max_summaries
        """跨局摘要的上限：超过就按质量淘汰最差的（平手淘汰最旧）。
        防止经验库无限膨胀——检索候选越多越慢、越杂。"""
        self._summary_files: dict[str, Path] = {}
        """`episode_id → 落盘 md 路径`：淘汰时要删对应文件，不能只删内存。"""
        self._summaries: list[EpisodeMemory] = self._load_all()
        self._trim_over_limit()  # 启动时磁盘上可能已超限（历史 run 攒的）

    # ---- 读端 ----

    def query_episode_steps(self, episode_id: str) -> list[StepMemory]:
        """取这一局全部的单步情景记忆，按 step 升序。"""
        assert episode_id, "query_episode_steps() needs a non-empty episode_id"
        return sorted(self._steps.get(episode_id, ()), key=lambda m: m.step)

    def query_recent_steps(self, episode_id: str, limit: int) -> list[StepMemory]:
        """取这一局最近几条情景记忆。"""
        assert limit > 0, "query_recent_steps() needs a positive limit"
        return self._steps.get(episode_id, ())[-limit:]

    def all_episode_summaries(self) -> list[EpisodeMemory]:
        """取全部跨局摘要记忆，未排序。"""
        return list(self._summaries)

    def episode_summary_count(self) -> int:
        """库里有多少条跨局摘要记忆。"""
        return len(self._summaries)

    # ---- 写端 ----

    def store_episode_step(self, entry: StepMemory) -> None:
        """写入一条单步情景记忆：写穿落盘（append 一行 JSON）+ 进内存索引。

        前置条件：`entry.step` ≥ 该局文件里已有的最大 step（恢复后同局重跑，
        截断把 `_step_max` 退回截断点，重跑的 step 号自然过闸）。
        后置条件：落盘与内存同时生效——崩溃最多丢"没写完的那一行"。
        """
        assert entry.rationale, "store_episode_step() got an entry without a rationale"
        assert entry.step >= self._step_max.get(entry.episode_id, 0), (
            f"store_episode_step got a stale entry: episode {entry.episode_id} "
            f"step {entry.step} < max {self._step_max.get(entry.episode_id, 0)}"
        )
        with self._step_file(entry.episode_id).open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
        self._steps.setdefault(entry.episode_id, []).append(entry)
        self._step_max[entry.episode_id] = max(
            self._step_max.get(entry.episode_id, 0), entry.step
        )

    def truncate(self, episode_id: str, step: int) -> None:
        """把这一局 step 大于 `step` 的单步记忆全部删掉（checkpoint 恢复的截断）。

        与 `EventObjectStore.truncate` 同构：键控幂等（没有超界记录就什么都不
        做）；删完把该局文件原子重写（临时文件 + rename）。后置条件由断言执行：
        重算后该局不存在 step > step 的记忆。
        """
        survivors = [e for e in self._steps.get(episode_id, ()) if e.step <= step]
        removed = len(self._steps.get(episode_id, ())) - len(survivors)
        if removed == 0:
            return
        target = self._step_file(episode_id)
        tmp = target.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for entry in survivors:
                fh.write(entry.model_dump_json() + "\n")
        os.replace(tmp, target)
        self._steps[episode_id] = survivors
        self._step_max[episode_id] = max((e.step for e in survivors), default=0)

    def query_episode_range(
        self, episode_id: str, step_min: int, step_max: int
    ) -> list[StepMemory]:
        """取这一局 `[step_min, step_max]` 区间的单步记忆（checkpoint 归档取废弃段用）。"""
        assert episode_id, "query_episode_range() needs a non-empty episode_id"
        return sorted(
            (e for e in self._steps.get(episode_id, ()) if step_min <= e.step <= step_max),
            key=lambda m: m.step,
        )

    def discard_episode_steps(self, episode_id: str) -> None:
        """局结束后丢弃该局的单步记忆：内存清空 + **落盘文件删除**。

        step 记忆**不跨 episode**：只服务本局决策，蒸馏完成后没有消费方。
        落盘文件的使命是"局进行中的 checkpoint 恢复"，局正常结束即失效——
        不删的话，下次进程启动 `_load_steps` 会把已完结的局读回来，
        破坏"单步不跨局"。不清理的话，长 run 也会让磁盘无限累积。"""
        self._steps.pop(episode_id, None)
        self._step_max.pop(episode_id, None)
        self._step_file(episode_id).unlink(missing_ok=True)

    def store_episode_summary(self, memory: EpisodeMemory) -> None:
        """写入一条跨局摘要记忆：落盘为 md（frontmatter = 元数据 + 正文 = markdown）。

        写入后按 `max_summaries` 裁剪：超限就淘汰质量最差的（见 `_trim_over_limit`）。"""
        assert memory.markdown.strip(), "store_episode_summary() got an empty markdown"
        self._summaries.append(memory)

        name = safe_filename(memory.filename)
        target = self._dir / f"{name}.md"
        if target.exists():
            # 文件名撞了（不同局给了同名文件）——加 episode_id 后缀区分
            suffix = re.sub(r"[^a-zA-Z0-9_-]+", "_", memory.episode_id).strip("_-")
            target = self._dir / f"{name}_{suffix}.md"

        meta = memory.model_dump(exclude={"markdown"})
        frontmatter = json.dumps(meta, ensure_ascii=False, indent=2)
        target.write_text(f"---\n{frontmatter}\n---\n{memory.markdown}\n", encoding="utf-8")
        self._summary_files[memory.episode_id] = target

        self._trim_over_limit()

    # ---- 内部 ----

    def _step_file(self, episode_id: str) -> Path:
        """单步记忆按局分文件（与跨局摘要的 md 同目录，前缀 `steps-` 区分）。"""
        return self._dir / f"steps-{_safe_episode_id(episode_id)}.jsonl"

    def _load_steps(self) -> None:
        """启动时读回全部单步记忆文件（盘上是真相，内存是进程内副本）。

        崩溃截断的残行是预期内的运行期情况，读不出来就跳过；已完结局残留的
        文件（crash 在 discard 之前）也会被读回——它们的生命周期由
        `discard_episode_steps` 或 checkpoint 截断负责终结。
        """
        for path in sorted(self._dir.glob("steps-*.jsonl")):
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = StepMemory.model_validate_json(line)
                    except ValidationError:
                        continue
                    self._steps.setdefault(entry.episode_id, []).append(entry)
                    self._step_max[entry.episode_id] = max(
                        self._step_max.get(entry.episode_id, 0), entry.step
                    )

    def _load_all(self) -> list[EpisodeMemory]:
        """启动时扫描目录，解析每个 md 的 frontmatter，重建检索索引。"""
        loaded: list[EpisodeMemory] = []
        for path in sorted(self._dir.glob("*.md")):
            try:
                memory = parse_md(path)
            except ValueError:
                # 旧的纯正文 md（无 frontmatter）不是本期格式，跳过不崩——
                # 它可能是更早版本留下的存档，留着不动。
                continue
            if memory is not None:
                loaded.append(memory)
                self._summary_files[memory.episode_id] = path
        return loaded

    # ---- 上限维护 ----

    def _trim_over_limit(self) -> None:
        """超过 `max_summaries` 时淘汰质量最差的（平手淘汰最旧的），并删对应文件。

        跨局摘要的价值是"高质量可复用经验"，所以**按质量淘汰**而不是 FIFO——
        FIFO 会保留一堆早期低质量经验；质量最低的先走，平手时先写入的先走。
        """
        while len(self._summaries) > self._max_summaries:
            victim = min(
                enumerate(self._summaries),
                key=lambda iv: (iv[1].quality_score, iv[0]),
            )[1]
            self._summaries.remove(victim)
            path = self._summary_files.pop(victim.episode_id, None)
            if path is not None:
                path.unlink(missing_ok=True)
