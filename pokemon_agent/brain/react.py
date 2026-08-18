"""ReAct 大脑 —— 感知、推理、执行三段里的"推理"那一段。

**这个类必须是无状态的**（CLAUDE.md 铁律 1）：没有任何跨步骤的实例变量。
构造函数存的三个依赖是不可变的协作者，不是状态。
判据：连续两次用相同的 (observation, action_space) 调 choose()，行为必须完全一致。

它也不认识 harness 和 world，只认识三个 Protocol（铁律 2）。
"""

from __future__ import annotations

import json

from pokemon_agent.errors import IllegalAction, MaxRetriesExceeded, ParseFailure
from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.interfaces.tools import ToolPort
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.schemas.core import (
    MAX_RATIONALE,
    Action,
    ActionSpace,
    EventType,
    MemoryEntry,
    Observation,
)

_PROMPT_TEMPLATE = """你在玩神奇宝贝。按 ReAct 的方式思考并选出下一个动作。

## 当前任务目标
{goal}

## 当前状态
{summary}

## 已知事实
{facts}

## 相关记忆
{memories}

## 可用动作（只能从中选一个）
{actions}

## 输出格式
只输出一个 JSON 对象，不要有其他文字：
{{"thought": "你的完整推理", "rationale": ["论据一"], "action": "动作名", "args": {{}}}}

- **thought**：完整推理，想多长都可以。它只用于记录，不会进入以后的决策。
- **rationale**：1-{max_rationale} 条，写清楚「为什么这个动作在当前状态下成立」的依据。
  不要复述动作本身（"所以该往前走"不是论据）。
  **这些会被存进记忆，将来在相似状态下取回**——所以要写成以后还能判断真假的样子，
  例如"地上有药水而我手上没有"，而不是"我觉得这样比较好"。
"""


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
            completion = self._llm.complete(prompt)
            self._trace.append(
                episode_id,
                obs.step,
                EventType.COST,
                {
                    "prompt_tokens": str(completion.prompt_tokens),
                    "completion_tokens": str(completion.completion_tokens),
                    "attempt": str(attempt),
                },
            )

            try:
                action = self._parse(completion.text, space)
            except (ParseFailure, IllegalAction) as exc:
                # 外部输入不合法属于预期内情况（CLAUDE.md 第八节），走异常 + trace，不 assert。
                last_reason = f"{type(exc).__name__}: {exc}"
                self._trace.append(
                    episode_id,
                    obs.step,
                    EventType.ERROR,
                    {"reason": last_reason, "attempt": str(attempt)},
                )
                continue

            self._trace.append(
                episode_id,
                obs.step,
                EventType.THINK,
                {"thought": action.thought, "action": action.name, "attempt": str(attempt)},
            )
            assert space.contains(action.name), f"brain returned {action.name!r} outside space"
            return action

        self._trace.append(
            episode_id,
            obs.step,
            EventType.ERROR,
            {"reason": "max_retries_exceeded", "last": last_reason},
        )
        raise MaxRetriesExceeded(self._max_retries, last_reason)

    def remember(self, episode_id: str, obs: Observation, action: Action, result: str) -> None:
        """把这一步发生的事写进记忆。

        前置条件：result 非空。
        本阶段记忆内容是朴素的自然语言拼接，key 用 step 占位——
        机制一接进来时换成 state abstraction 的语义 key，**这个方法的签名不变**。

        写进去的是 `rationale` 而不是 `thought`：完整推理留在 trace 里，
        进记忆的只有论据。这条经验因此是**自带标签**的——"我以为 P，结果 R"，
        取回时反例就贴在同一行，一条错误论据不会被当成知识使用。
        """
        assert result, "remember() got an empty result"

        because = "；".join(action.rationale)
        entry = MemoryEntry(
            key=str(obs.step),
            content=f"在「{obs.summary}」时，因为{because}，选择了 {action.name}，结果：{result}",
            step=obs.step,
        )
        self._tools.memory_write(entry)
        self._trace.append(
            episode_id, obs.step, EventType.MEMORY_WRITE, {"key": entry.key}
        )

    def _recall(self, episode_id: str, obs: Observation) -> list[MemoryEntry]:
        """检索相关记忆。检索策略属于 harness，这里只负责问和记账。"""
        memories = self._tools.memory_query(obs.summary, limit=self._memory_limit)

        assert len(memories) <= self._memory_limit, "memory_query returned more than limit"
        self._trace.append(
            episode_id, obs.step, EventType.MEMORY_READ, {"count": str(len(memories))}
        )
        return memories

    def _build_prompt(
        self, obs: Observation, space: ActionSpace, memories: list[MemoryEntry]
    ) -> str:
        """组装 prompt。

        每次都从参数完整组装，不留历史——这是"大脑无状态"在代码层面的体现。
        """
        facts = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items()) or "（无）"
        recalled = "\n".join(f"- {m.content}" for m in memories) or "（无相关记忆）"
        actions = "\n".join(
            f"- {name}: {space.descriptions.get(name, '（无说明）')}" for name in space.names
        )
        return _PROMPT_TEMPLATE.format(
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
