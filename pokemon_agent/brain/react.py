"""ReAct 大脑 —— 感知、推理、执行三段里的"推理"那一段。

**这个类必须是无状态的**（CLAUDE.md 铁律 1）：没有任何跨步骤的实例变量。
构造函数存的三个依赖是不可变的协作者，不是状态。
判据：连续两次用相同的 (observation, action_space) 调 choose()，行为必须完全一致。

它也不认识 harness 和 world，只认识三个 Protocol（铁律 2）。
"""

from __future__ import annotations

import json
import time

from pokemon_agent.errors import (
    IllegalAction,
    MaxRetriesExceeded,
    OutputTruncated,
    ParseFailure,
)
from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.interfaces.tools import ToolPort
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.schemas.core import (
    MAX_RATIONALE,
    Action,
    ActionSpace,
    EventType,
    MemoryEntry,
    Observation,
    Snapshot,
    Source,
)


class ReActBrain:
    """把观测变成动作。一次 choose() = ReAct 的一轮 Thought -> Action。

    重试策略放在这里而不是 LLMProvider 里，是因为"什么算失败"是**大脑的判断**：
    解析不出来算失败、选了不存在的动作也算失败，而这两件事 provider 都不知道。
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolPort,
        trace: TracePort,
        *,
        max_retries: int = 3,
        memory_limit: int = 5,
    ) -> None:
        """依赖全部注入，类型标成接口而非实现（CLAUDE.md 第三节第 3 条）。

        前置条件：max_retries >= 1，memory_limit >= 1。
        """
        assert max_retries >= 1, f"max_retries must be >= 1, got {max_retries}"
        assert memory_limit >= 1, f"memory_limit must be >= 1, got {memory_limit}"

        self._llm = llm
        self._tools = tools
        self._trace = trace
        self._max_retries = max_retries
        self._memory_limit = memory_limit
        # 构造时加载一次。持有它是为了 `sha` —— 每条 THINK 事件都带上它，
        # 实验数据才说得清是哪一版 prompt 跑出来的。改了 prompt 不记版本，
        # 前后两批数字就没法比。
        self._prompt = load_prompt("decide_action")

    def choose(self, episode_id: str, obs: Observation, space: ActionSpace) -> Action:
        """选出下一步动作。

        前置条件：space.names 非空。空动作空间是 harness 的 bug（见 ToolPort 契约），
            大脑不为这种情况兜底。
        后置条件：返回的 action.name 属于 space。
        失败：连续 max_retries 次拿不到合法动作时抛 MaxRetriesExceeded，
            并已写入一条 ERROR 事件。这是一类要被 replay 统计的失败模式，不是"再试试就好"。
        """
        assert space.names, "choose() got an empty action space"
        assert not obs.done, "choose() called on a finished episode"
        assert obs.goal, "choose() got an observation without a goal"

        memories = self._recall(episode_id, obs)
        prompt = self._build_prompt(obs, space, memories)

        last_reason = ""
        for attempt in range(1, self._max_retries + 1):
            # 每次重试都重新调用，而不是复用上次输出——LLM 的随机性本身就是重试的意义所在。
            t0 = time.perf_counter()
            completion = self._llm.complete(prompt)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            parsed: Action | None = None
            reason = ""
            try:
                # 截断要**先于**解析检查。不然它会以 "少了个右括号" 的形式
                # 变成一条 ParseFailure，指向完全错误的修法。
                if completion.truncated:
                    raise OutputTruncated(completion.completion_tokens)
                parsed = self._parse(completion.text, space)
            except (ParseFailure, IllegalAction, OutputTruncated) as exc:
                # 外部输入不合法属于预期内情况（CLAUDE.md 第八节），走异常 + trace，不 assert。
                reason = f"{type(exc).__name__}: {exc}"

            # **一次模型调用 = 一条事件**，成功失败都记。
            # 之前失败的那几次只留下 COST，拿不到它到底吐了什么；
            # 而 `raw` 让你改进解析器之后能**离线重算，不必再花 token 重跑**。
            self._trace.append(
                episode_id, obs.step, EventType.MODEL_CALL, Source.DECISION,
                {
                    "prompt_sha": self._prompt.sha,
                    "input_tokens": str(completion.prompt_tokens),
                    "output_tokens": str(completion.completion_tokens),
                    "latency_ms": str(latency_ms),
                    "attempt": str(attempt),
                    "ok": str(parsed is not None),
                    "raw": completion.text,
                },
            )

            if parsed is None:
                last_reason = reason
                self._trace.append(
                    episode_id, obs.step, EventType.ERROR, Source.DECISION,
                    # kind 单独一列：聚合失败模式时不必去解析 reason 字符串
                    {"kind": reason.split(":")[0], "reason": reason, "attempt": str(attempt)},
                )
                continue

            self._trace.append(
                episode_id, obs.step, EventType.THINK, Source.DECISION,
                {
                    "thought": parsed.thought,
                    "action": parsed.name,
                    # args 必须记：不记的话分不清「模型没给参数」和「给了但没显示」。
                    "args": json.dumps(parsed.args, ensure_ascii=False),
                    # rationale 也记在这里，不只依赖 MEMORY_WRITE ——
                    # **无记忆基线组不写记忆**，那时 rationale 只剩这一处落点。
                    "rationale": json.dumps(parsed.rationale, ensure_ascii=False),
                    "attempt": str(attempt),
                },
            )
            assert space.contains(parsed.name), f"brain returned {parsed.name!r} outside space"
            return parsed

        self._trace.append(
            episode_id, obs.step, EventType.ERROR, Source.DECISION,
            {"kind": "MaxRetriesExceeded", "reason": "max_retries_exceeded", "last": last_reason},
        )
        raise MaxRetriesExceeded(self._max_retries, last_reason)

    def remember(
        self, episode_id: str, before: Observation, action: Action, after: Observation
    ) -> None:
        """把这一步发生的事写进记忆：**看到什么 → 为什么 → 做了什么 → 变成什么**。

        `after` 是一个**完整的观察**，不是一句话结果。上一版只存
        "结果：你在野外"，取回十条全长一个样——把结果压成标签，
        这条经验就回答不了"那一下到底改变了什么"，而那正是它唯一的价值。

        写进去的是 `rationale` 而不是 `thought`：完整推理留在 trace 里，
        进记忆的只有论据。这条经验因此是**自带标签**的——"我以为 P，结果 R"，
        取回时反例就贴在同一行，一条错误论据不会被当成知识使用。

        `key` 本阶段用位置占位（比 step 强：位置是可复用的作用域，step 不是）。
        机制一接进来时换成状态抽象的语义 key，**这个方法的签名不变**。
        """
        # 连按次数从动作本身取，不从观测里找——**动作是我们自己发出的，是确定的**。
        raw = action.args.get("times", "1")
        times = f" ×{raw}" if raw not in ("", "1") else ""
        entry = MemoryEntry(
            before=Snapshot.of(before),
            rationale=list(action.rationale),
            action=f"{action.name}{times}",
            after=Snapshot.of(after),
            key=Snapshot.of(before).position or str(before.step),
            step=before.step,
            episode_id=episode_id,
        )
        self._tools.memory_write(entry)
        self._trace.append(
            episode_id, before.step, EventType.MEMORY_WRITE, Source.HARNESS,
            {"key": entry.key, "content": entry.render()},
        )

    def _recall(self, episode_id: str, obs: Observation) -> list[MemoryEntry]:
        """检索相关记忆。检索策略属于 harness，这里只负责问和记账。"""
        # **用当前快照的渲染文本去查，不用 `obs.summary`。**
        # 记忆里存的是快照（位置 / 概况 / 地标 / 通行图），而 summary 是
        # "你在野外" 这种一句话——两边词汇几乎不重叠，字符打分会一条都选不中。
        # 查询和被查的东西必须是同一种表示，这也是 `Snapshot` 刻意照抄
        # `Observation.facts` 字段的原因。
        memories = self._tools.memory_query(
            Snapshot.of(obs).render(), limit=self._memory_limit
        )

        assert len(memories) <= self._memory_limit, "memory_query returned more than limit"
        # 记下**取回了哪几条**，不只是几条。
        # 只记数量的话，replay 时无法回答「这个决策是被哪条经验影响的」——
        # 而那正是「记忆到底有没有用」要查的东西。
        self._trace.append(
            episode_id, obs.step, EventType.MEMORY_READ, Source.HARNESS,
            {"count": str(len(memories)),
             "refs": " ".join(f"({m.episode_id}, {m.step})" for m in memories)},
        )
        return memories

    def _build_prompt(
        self, obs: Observation, space: ActionSpace, memories: list[MemoryEntry]
    ) -> str:
        """组装 prompt。

        每次都从参数完整组装，不留历史——这是"大脑无状态"在代码层面的体现。
        """
        facts = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items()) or "（无）"
        recalled = "\n\n".join(m.render() for m in memories) or "（无相关记忆）"
        actions = "\n".join(
            f"- {name}: {space.descriptions.get(name, '（无说明）')}" for name in space.names
        )
        if space.note:
            actions += f"\n\n{space.note}"
        return self._prompt.render(
            goal=obs.goal,
            summary=obs.summary,
            facts=facts,
            memories=recalled,
            actions=actions,
            max_rationale=MAX_RATIONALE,
        )

    def _parse(self, text: str, space: ActionSpace) -> Action:
        """把 LLM 输出解析成 Action。

        两类失败分开抛，因为它们在 replay 里是**不同的失败模式**：
        ParseFailure 说明格式没学会（该改 prompt 或上约束解码），
        IllegalAction 说明模型在幻觉动作（该改动作说明或收紧掩码）。
        """
        stripped = text.strip()
        # 容忍 ```json 包裹：这是模型最常见的格式偏差，为它单独重试一轮不划算。
        if stripped.startswith("```"):
            stripped = stripped.split("```")[1].removeprefix("json").strip()

        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ParseFailure(text, f"not valid json ({exc.msg})") from exc

        if not isinstance(raw, dict):
            raise ParseFailure(text, "top level is not an object")
        name = raw.get("action")
        if not isinstance(name, str) or not name:
            raise ParseFailure(text, "missing 'action' field")

        if not space.contains(name):
            raise IllegalAction(name, space.names)

        args = raw.get("args") or {}
        if not isinstance(args, dict):
            raise ParseFailure(text, "'args' is not an object")

        return Action(
            name=name,
            args={str(k): str(v) for k, v in args.items()},
            thought=self._parse_thought(text, raw),
            rationale=self._parse_rationale(text, raw),
        )

    @staticmethod
    def _parse_thought(text: str, raw: dict[str, object]) -> str:
        """取出推理。缺失是一类**单独的** ParseFailure。

        reason 用独立字符串而不是新增异常类型：replay 按 reason 聚合就能把
        "格式坏"和"不肯推理"拆开，够用了，不值得为它多一个异常类。
        """
        thought = raw.get("thought")
        if not isinstance(thought, str) or not thought.strip():
            raise ParseFailure(text, "missing 'thought' field")
        return thought.strip()

    @staticmethod
    def _parse_rationale(text: str, raw: dict[str, object]) -> list[str]:
        """取出论据。

        容忍单条写成裸字符串（`"rationale": "..."`），理由同 ```json 包裹：
        这是模型常见的格式偏差，语义无歧义，为它跑一轮重试不划算。

        **超过上限走 ParseFailure 而不是截断。** 模型认为有 4 条是承重的，
        悄悄丢掉第 4 条就是替它做了一个没有记录的决定；打回去重试至少留下痕迹。
        代价是这类重试要花 token——如果实测下来它占比很高，再改成截断也不迟。
        """
        rationale = raw.get("rationale")
        if isinstance(rationale, str):
            rationale = [rationale]
        if not isinstance(rationale, list):
            raise ParseFailure(text, "missing 'rationale' field")

        items = [str(r).strip() for r in rationale if str(r).strip()]
        if not items:
            raise ParseFailure(text, "missing 'rationale' field")
        if len(items) > MAX_RATIONALE:
            raise ParseFailure(
                text, f"too many rationale items ({len(items)} > {MAX_RATIONALE})"
            )
        return items
