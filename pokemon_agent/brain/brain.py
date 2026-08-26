"""Brain —— **一切需要 LLM 才能回答的问题，都在这个类里。**

它不是"一个模型"，是**一组互不通气的模型技能**的容器：

    choose   看着当前画面和可用动作，选下一步          decide_llm
    judge    看着当前画面和任务目标，判达成没达成       judge_llm
    reflect  把这一步整理成一条可检索的经验            （本版无模型调用）

**它不写 trace，也不知道自己在哪一局。** 三个方法都不收 `episode_id` / `step`，
构造函数里也没有 `TracePort`——账（`ModelCall`）跟着结果交给 Harness。
规则只有一句：**谁控制循环，谁记账。**

**`choose` 和 `judge` 必须分开。** 让做决策的模型顺便回答"我成功了吗"是误差同源：
它读错画面 → 以为达成了 → 判成功，错得越离谱数字越好看。隔离靠两条硬约束维持：
`judge()` 看得到最近几步**发生了什么**，但拿不到决策者对那几步的任何说辞；
`judge_llm` 是**另一个 provider 实例**，哪怕型号相同。

**无状态**（铁律 1）：没有任何跨步骤的实例变量，构造函数存的是不可变的协作者；
连续两次用相同参数调 `choose()`，行为必须完全一致。只认识 Protocol（铁律 2）。

完整论证——为什么这仍不是独立真值、上一版"谁写哪类事件"为什么难维护——
见 `docs/spec/brain/SPEC.md`。
"""

from __future__ import annotations

from agent_permission import require_permission

import json
import time
from collections.abc import Sequence

from pydantic import ValidationError

from pokemon_agent.errors import IllegalAction, OutputTruncated, ParseFailure
from pokemon_agent.interfaces.llm import LLMProvider
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.prompts.brain_hints import retry_note as _retry_note
from pokemon_agent.schemas.action import (
    MAX_RATIONALE,
    MAX_TIMES,
    Action,
    ActionSegment,
    ActionSpace,
    Goal,
)
from pokemon_agent.schemas.step_memory import StepMemory, Snapshot
from pokemon_agent.schemas.observation import INTERACT_KEY, Observation
from pokemon_agent.schemas.trace import Decision, ModelCall, Verdict


JUDGE_BLIND: frozenset[str] = frozenset({
    "known_objects", "walk_map", "landmarks",
})
"""判定器**看不到**的字段。判定器现在有历史了（`history` 参数），
但那份历史是**有界的**：只有本局、只有最近几步。这几个字段是无界的，所以挡掉。

- `known_objects`：**跨 episode 的流水**。「见过 7 次，互动 1 次」「他说过 XXX」
  ——上一局说过的那句话会留在里面，目标是"和母亲对话"时，
  它足以让判定器在**第 0 步**就判完成，而这一局什么都还没发生。
  `history` 之所以安全正是因为它两头有界；这一份没有那个界。
- `walk_map` / `landmarks`：**堵掉坐标推理的原料**。
  光在 prompt 里写"别做坐标换算"是不够的——实测它照做了：
  把 `walk_map` 的行号当成全局 y，得出"他还没进屋"，而 `map_id` 明写着他在屋里。
  拿不到就不会用。位置证据由 `where` 一行直接给出，那是答案，不是原料。
**这是一份黑名单而不是白名单**，方向是刻意选的：漏进一个新字段，代价是判定器
多看一眼；漏掉一个新字段，代价是判定器瞎掉——`dialog_text` 那次就是后者，
判定器一路在说"对话框内容未提供"，一局本该成功的 episode 被静默记成失败。
两种失败模式不对称，所以宁可多给。
"""

class Brain:
    """`BrainPort` 的唯一实现。"""

    def __init__(
        self,
        decide_llm: LLMProvider,
        judge_llm: LLMProvider,
        *,
        max_retries: int = 3,
    ) -> None:
        """依赖全部注入，类型标成接口而非实现（CLAUDE.md 第三节第 3 条）。

        `judge_llm` 单独一个参数、哪怕和 `decide_llm` 同型号：换判定模型时只改装配处，
        manifest 里两条链路也才看得出是可以分别选型的。

        存下两个 provider 与两份 prompt 模板，此后不再变。
        """
        assert max_retries >= 1, f"max_retries must be >= 1, got {max_retries}"

        self._decide = decide_llm
        self._judge_llm = judge_llm
        self._max_retries = max_retries
        # 持有它们是为了 `sha`：改了 prompt 不记版本，前后两批数字就没法比。
        self._decide_prompt = load_prompt("decide_action")
        self._judge_prompt = load_prompt("judge_success")

    @property
    def prompt_shas(self) -> dict[str, str]:
        """两条链路各自的 prompt 版本，进 manifest 用。"""
        return {"decide": self._decide_prompt.sha, "judge": self._judge_prompt.sha}

    # ---- 决策 ----

    @require_permission("execute:llm:decision")
    def choose(
        self, goals: list[Goal], obs: Observation, space: ActionSpace,
        memories: list[StepMemory],
    ) -> Decision:
        """选出下一步动作。一次 `choose()` = ReAct 的一轮 Thought → Action。

        前置条件：`space.names` 非空、`goals` 非空、`obs.done` 为 False。
        后置条件：`action` 非 None 时它属于 `space`；`calls` 至少一条。

        **重试用尽时返回 `action=None`，不抛异常**：那是一类要被统计的失败模式，
        而"这一局要不要因此终止"是 Harness 的判断。重试策略放在这里而不是
        provider 里，因为"什么算失败"（解析不出来、选了不存在的键）是大脑的判断。

        组装 prompt、调模型、解析成合法动作，失败就带着纠正说明重试。
        """
        assert space.names, "choose() got an empty action space"
        assert not obs.done, "choose() called on a finished episode"
        assert goals, "choose() got an empty goal stack"

        base = self._build_prompt(goals, obs, space, memories)
        refs = [f"({m.episode_id}, {m.step})" for m in memories]

        calls: list[ModelCall] = []
        prompt = base
        for attempt in range(1, self._max_retries + 1):
            # 带着上次的错误重问，不是原样再问——常见错误是系统性的，换个随机种子
            # 照样犯。纠正块追加在**末尾**，前缀缓存一个字不丢。
            t0 = time.perf_counter()
            completion = self._decide.complete(prompt)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            parsed: Action | None = None
            kind = reason = ""
            try:
                # 截断要**先于**解析检查，否则它会伪装成"少了个右括号"的 ParseFailure。
                if completion.truncated:
                    raise OutputTruncated(completion.completion_tokens)
                parsed = self._parse(completion.text, space)
            except (ParseFailure, IllegalAction, OutputTruncated) as exc:
                kind, reason = type(exc).__name__, str(exc)
            except ValidationError as exc:
                # `ValidationError` **不是** `AgentError` 的子类，不带上会穿过重试
                # 崩掉一整局。正常走不到（`_parse` 已经验过），但那套校验写了两遍
                # 且没有机制保证同步——兜住，让它退化成一次可统计的解析失败。
                kind, reason = "ParseFailure", f"Action 字段不合法：{exc.errors()[:1]}"

            # 一次模型调用 = 一条账，成功失败都留：失败的那几次同样烧了 token，
            # 而 `raw` 让改进解析器之后能离线重算，不必再花钱重跑。
            calls.append(ModelCall(
                payload={
                    "prompt_sha": self._decide_prompt.sha,
                    "input_tokens": str(completion.prompt_tokens),
                    "output_tokens": str(completion.completion_tokens),
                    "latency_ms": str(latency_ms),
                    "attempt": str(attempt),
                    "ok": str(parsed is not None),
                    "raw": completion.text,
                },
                error_kind=kind,
                error=reason,
            ))
            if parsed is None:
                prompt = base + _retry_note(
                    attempt + 1, reason, completion.text[:400],
                )
            if parsed is not None:
                assert space.contains(parsed.name), (
                    f"brain chose key {parsed.name!r} outside {space.names}"
                )
                return Decision(action=parsed, calls=calls, recalled=refs)

        return Decision(action=None, calls=calls, recalled=refs)

    # ---- 判定 ----

    @require_permission("execute:llm:judge")
    def judge(
        self, goal: Goal, obs: Observation, history: Sequence[StepMemory] = ()
    ) -> Verdict:
        """判断这个目标达成了没有。**永远返回 Verdict，不抛异常。**

        判不出来就是"没达成"加一条失败记录——判定器坏掉时表现是成功率悄悄变 0，
        必须能在失败模式分布里看见它。渲染也在 try 里：模板少个占位符就抛 KeyError，
        而 prompt 是最常改的那类文件。

        `history` 用 `render(reason=False)`：**发生过的事给判定器看，
        决策者对那件事的主张不给。** `JUDGE_BLIND` 挡掉的是同一条隔离的另一半。

        拿目标、判据和这一帧问一次判定模型，返回达成与否及依据。
        """
        t0 = time.perf_counter()
        try:
            # **渲染也在 try 里**：模板少一个占位符就抛 KeyError，而 prompt 是最常改的
            # 那类文件。放在外面的话"判定器永不抛异常"这条契约就有一个缺口。
            rendered = (
                "\n".join(
                    f"- {k}: {v}" for k, v in obs.facts.items() if k not in JUDGE_BLIND
                ) or obs.status
            )
            past = "\n\n".join(m.render(reason=False) for m in history)
            prompt = self._judge_prompt.render(
                goal=goal.goal, criteria=goal.criteria, observation=rendered,
                history=past or "（这是第一步，之前什么都没发生）",
            )
            completion = self._judge_llm.complete(prompt)
        except Exception as exc:  # noqa: BLE001  判定器不该让整局崩掉
            return Verdict(
                done=False,
                why=f"判定调用失败：{type(exc).__name__}",
                call=ModelCall(
                    payload={
                        "prompt_sha": self._judge_prompt.sha, "ok": "False",
                        "latency_ms": str(int((time.perf_counter() - t0) * 1000)),
                    },
                    error_kind=type(exc).__name__,
                    error=f"{exc}"[:200],
                ),
            )

        done, why, kind = self._parse_verdict(completion.text)
        return Verdict(done=done, why=why, call=ModelCall(
            payload={
                "prompt_sha": self._judge_prompt.sha,
                "input_tokens": str(completion.prompt_tokens),
                "output_tokens": str(completion.completion_tokens),
                "latency_ms": str(int((time.perf_counter() - t0) * 1000)),
                "raw": completion.text,
                "ok": str(not kind),
            },
            error_kind=kind,
            error=why if kind else "",
        ))

    @staticmethod
    def _parse_verdict(text: str) -> tuple[bool, str, str]:
        """解析成 `(done, why, 失败类型)`，第三项为空串表示解析成功。"""
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```")[1].removeprefix("json").strip()
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            return False, f"判定输出不是合法 JSON：{text[:80]!r}", "ParseFailure"

        if not isinstance(raw, dict) or not isinstance(raw.get("done"), bool):
            return False, f"判定输出缺少布尔 done：{text[:80]!r}", "ParseFailure"

        why = raw.get("why")
        return bool(raw["done"]), str(why) if why else "（未说明）", ""

    # ---- 记忆整理 ----

    @require_permission("execute:llm:memory_reflection")
    def reflect(
        self, before: Observation, action: Action, after: Observation
    ) -> StepMemory:
        """把这一步整理成一条经验：**看到什么 → 为什么 → 做了什么 → 变成什么**。

        **本版不调模型**：四样东西都已经在参数里，让模型再复述一遍只会引入
        它自己的措辞偏差，还多烧一次调用。要不要上模型是以后的事，
        接口按"可能会调"设计（返回 `StepMemory` 而不是就地写库）。

        **这个方法自己不写库**：写库是状态变更，而大脑无状态。
        `episode_id` 也留空由 Harness 盖章——大脑不知道自己在哪一局。

        把前后两帧和这次动作拼成一条可检索的记忆条目返回。
        """
        assert action.rationale, "reflect() got an action without a rationale"

        snapshot = Snapshot.of(before)
        return StepMemory(
            before=snapshot,
            rationale=list(action.rationale),
            action=action.describe(),
            after=Snapshot.of(after),
            key=snapshot.position or str(before.step),
            step=before.step,
            # `episode_id` 由 Harness 盖章——大脑不知道自己在哪一局。
            episode_id="",
        )

    # ---- 内部 ----

    def _build_prompt(
        self,
        goals: list[Goal],
        obs: Observation,
        space: ActionSpace,
        memories: list[StepMemory],
    ) -> str:
        """每次从参数完整组装，不留历史——"大脑无状态"在代码层面的体现。"""
        facts = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items()) or "（无）"
        recalled = "\n\n".join(m.render() for m in memories) or "（无相关记忆）"
        actions = "\n".join(
            f"- {name}: {space.descriptions.get(name, '（无说明）')}" for name in space.names
        )
        if space.note:
            actions += f"\n\n{space.note}"
        return self._decide_prompt.render(
            goals=self._render_goals(goals),
            status=obs.status,
            facts=facts,
            memories=recalled,
            actions=actions,
            max_rationale=MAX_RATIONALE,
        )

    @staticmethod
    def _render_goals(goals: list[Goal]) -> str:
        """把目标栈画出来，栈顶在最上面——模型是从上往下读 prompt 的。"""
        lines = []
        for depth, g in reversed(list(enumerate(goals))):
            mark = "← 你现在要完成的" if depth == len(goals) - 1 else ""
            role = "任务目标" if depth == 0 else f"子目标（第 {depth} 层）"
            lines.append(f"{depth}. [{role}] {g.goal}\n   判据：{g.criteria} {mark}".rstrip())
        return "\n".join(lines)

    def _parse(self, text: str, space: ActionSpace) -> Action:
        """把 LLM 输出解析成 `Action`，不合法就抛 `ParseFailure` / `IllegalAction`。"""
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

        # 只剩按键一类动作，所以没有"先取 intent 再分叉"那一段。
        raw_sequence = raw.get("sequence")
        if not isinstance(raw_sequence, list) or not raw_sequence:
            raise ParseFailure(text, "'sequence' must be a non-empty array")
        sequence = []
        for segment in raw_sequence:
            if not isinstance(segment, dict) or not isinstance(segment.get("action"), str):
                raise ParseFailure(text, "each sequence item needs an action")
            name = segment["action"]
            times = self._parse_times(text, segment)
            # **`a` 只按一次，在这里就定死。**
            #
            # 一条链只在结尾感知一次，所以连按会把中间那几帧整个吃掉；而 `a` 产出的
            # 恰恰是全项目最要紧的证据——对话框文字。连按三次推完整段对话，那几句
            # 一帧都没被看到，最后一次还会把对话框关掉，判定器看到一个没有对话框的
            # 画面，**一局本该成功的 episode 被静默记成失败**。`a` 的收益全在中间帧上，
            # **连按对它从来没有意义**。
            #
            # 夹在这里而不是 world 里：动作合法性是解析期的事，让非法的东西一路
            # 走到执行层再被悄悄改写，大脑就会以为自己按了三次。写死成 1 之后，
            # 交给 world 的链**就是真正会发生的那条链**。
            if name == INTERACT_KEY:
                times = 1
            sequence.append(ActionSegment(name=name, times=times))
        if len(sequence) > 1 and any(
            segment.name not in {"up", "down", "left", "right"} for segment in sequence
        ):
            raise ParseFailure(text, "multi-step sequence may contain only directional keys")

        for segment in sequence:
            if not space.contains(segment.name):
                raise IllegalAction(segment.name, space.names)

        return Action(
            name=sequence[0].name,
            thought=self._parse_thought(text, raw),
            rationale=self._parse_rationale(text, raw),
            sequence=sequence,
        )

    @staticmethod
    def _parse_times(text: str, values: dict[str, object]) -> int:
        """解析按键段次数，把外部格式错误转成可重试的 ParseFailure。"""
        raw_times = values.get("times", 1)
        try:
            times = int(raw_times)
        except (TypeError, ValueError) as exc:
            raise ParseFailure(text, "times must be an integer") from exc
        if not 1 <= times <= MAX_TIMES:
            raise ParseFailure(text, f"times must be between 1 and {MAX_TIMES}")
        return times

    @staticmethod
    def _parse_thought(text: str, raw: dict[str, object]) -> str:
        """缺失是一类**单独的** `ParseFailure`——"格式坏"和"不肯推理"要能分开聚合，
        但不值得为此多开一个异常类型，用 reason 字符串区分就够。

        取出推理文本，缺失或为空则抛。
        """
        thought = raw.get("thought")
        if not isinstance(thought, str) or not thought.strip():
            raise ParseFailure(text, "missing 'thought' field")
        return thought.strip()

    @staticmethod
    def _parse_rationale(text: str, raw: dict[str, object]) -> list[str]:
        """取出论据。

        超过 `MAX_RATIONALE` 条走 `ParseFailure` 而不是静默截断：模型认为需要
        4 条是有分量的，悄悄丢掉第 4 条等于替它做了一个没有留痕的决定。

        容忍裸字符串写法，校验条数，返回论据列表。
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
