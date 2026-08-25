"""Brain —— **一切需要 LLM 才能回答的问题，都在这个类里。**

它不是"一个模型"，是**一组互不通气的模型技能**的容器：

    choose   看着当前画面和可用动作，选下一步          decide_llm
    judge    看着当前画面和任务目标，判达成没达成       judge_llm
    reflect  把这一步整理成一条可检索的经验            （本版无模型调用，见下）

## 它不写 trace，也不知道自己在哪一局

三个方法都不收 `episode_id` / `step`，构造函数里也没有 `TracePort`。
账（`ModelCall`）跟着结果一起交给 Harness，由 Harness 翻译成事件。

上一版是 brain 写 MODEL_CALL / THINK / ERROR / MEMORY_READ、harness 写其余，
"某类事件归谁写"要一条条记，而且为了让判定器碰不到自己的账还开了个例外。
现在规则只有一句：**谁控制循环，谁记账。**

## 为什么 choose 和 judge 必须分开

成功率是这个项目唯一要报的硬数字。让做决策的那个模型顺便回答"我成功了吗"，
就是**误差同源**：它读错画面 → 以为达成了 → 判成功，而且错得越离谱数字越好看。

拆开之后至少做到三件事：**各自记账**（判定的 token 走 `Source.JUDGE`）、
**各自换型**（判定可以用更强或更便宜的模型）、**各自标定**（将来拿人工标注
的真值来对，能算出判定器本身的准确率——没有这一步，成功率就只是一个无法证伪的数字）。

合进一个类之后，这条隔离从**类型层面**降到了**约定层面**，所以它靠两条硬约束维持：

1. `judge()` 拿不到决策者的**任何说辞**。它看得到最近几步**发生了什么**
   （证据可能在三步前的对话框里），但看不到那几步的 `rationale`、
   看不到 thought、看不到当前这一步的候选动作。
   **发生过的事和它对那件事的主张，是两样东西**，只给前者。
2. `judge_llm` 是**另一个 provider 实例**，哪怕型号相同。共用一个的话，
   将来想给判定换模型就得改两处，而且 manifest 里两条链路会指向同一个对象，
   看不出它们是可以分别选型的。

**这仍然不是真正独立的真值**：判定看到的画面来自同一条感知链路，感知错了两边一起错。
真正的独立真值要么读游戏的事件旗标，要么人工标注。这一版先把结构立起来。

## 无状态

没有任何跨步骤的实例变量（CLAUDE.md 铁律 1）。构造函数存的是不可变的协作者。
判据：连续两次用相同参数调 `choose()`，行为必须完全一致。

它也不认识 Harness 和 world，只认识 Protocol（铁律 2）。
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
from pokemon_agent.schemas.action import MAX_RATIONALE, Action, ActionSpace, Goal
from pokemon_agent.schemas.memory_episodic import MemoryEntry, Snapshot
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.trace import Decision, ModelCall, Verdict

# `retry_note` 的组装逻辑在 `pokemon_agent/prompts/brain_hints.py`——
# 原因见那个文件的模块 docstring。这里只是消费方。

JUDGE_BLIND: frozenset[str] = frozenset({
    "known_objects", "walk_map", "landmarks", "inspected",
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
- `inspected`：那是**决策者自己挑的问题**得到的回答，跟着他的注意力走。
  让判定器读它，等于让被评价者给评价者递材料。

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

        前置条件：max_retries >= 1。

        **不再收 `tools`。** 大脑不持有任何工具/记忆实例——`choose()` 需要的
        情景记忆现在由 Harness 检索好，当参数传进来（见 `interfaces/brain.py`
        `BrainPort.choose` 的说明）。写库同理不走这里：`reflect()` 只返回 entry，
        落库由 Harness 做，"谁改了记忆"永远只有一个答案。
        """
        assert max_retries >= 1, f"max_retries must be >= 1, got {max_retries}"

        self._decide = decide_llm
        self._judge_llm = judge_llm
        self._max_retries = max_retries
        # 构造时加载一次。持有它们是为了 `sha` —— 每条事件都带上它，
        # 实验数据才说得清是哪一版 prompt 跑出来的。改了 prompt 不记版本，
        # 前后两批数字就没法比。
        self._decide_prompt = load_prompt("decide_action")
        self._judge_prompt = load_prompt("judge_success")

    @property
    def prompt_shas(self) -> dict[str, str]:
        """两条链路各自的 prompt 版本。进 manifest 用。"""
        return {"decide": self._decide_prompt.sha, "judge": self._judge_prompt.sha}

    # ---- 决策 ----

    @require_permission("execute:llm:decision")
    def choose(
        self, goals: list[Goal], obs: Observation, space: ActionSpace,
        memories: list[MemoryEntry],
    ) -> Decision:
        """选出下一步动作。一次 choose() = ReAct 的一轮 Thought -> Action。

        `memories` 是 Harness 检索好的情景记忆，直接进 prompt——**检索策略
        不是大脑的事**，大脑只回答"给了我这些，我选哪个动作"。

        前置条件：space.names 非空。空动作空间是工具层的 bug，大脑不为它兜底。
        后置条件：`action` 非 None 时它属于 `space`；`calls` 至少一条。

        **重试用尽时返回 `action=None`，不抛异常。** 那是一类要被统计的失败模式，
        而"这一局要不要因此终止"是 Harness 的判断，大脑只如实汇报。

        重试策略放在这里而不是 LLMProvider 里，是因为"什么算失败"是**大脑的判断**：
        解析不出来算失败、选了不存在的动作也算失败，而这两件事 provider 都不知道。
        """
        assert space.names, "choose() got an empty action space"
        assert not obs.done, "choose() called on a finished episode"
        assert goals, "choose() got an empty goal stack"

        base = self._build_prompt(goals, obs, space, memories)
        refs = [f"({m.episode_id}, {m.step})" for m in memories]

        calls: list[ModelCall] = []
        prompt = base
        for attempt in range(1, self._max_retries + 1):
            # 重试**带着上次的错误重问**，不是原样再问一遍。原样重问等于把三次调用
            # 当一次用：最常见的那类错误是系统性的（判据里写屏幕坐标），
            # 换个随机种子照样犯。纠正块追加在**末尾**，前缀缓存一个字不丢。
            t0 = time.perf_counter()
            completion = self._decide.complete(prompt)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            parsed: Action | None = None
            kind = reason = ""
            try:
                # 截断要**先于**解析检查。不然它会以 "少了个右括号" 的形式
                # 变成一条 ParseFailure，指向完全错误的修法。
                if completion.truncated:
                    raise OutputTruncated(completion.completion_tokens)
                parsed = self._parse(completion.text, space)
            except (ParseFailure, IllegalAction, OutputTruncated) as exc:
                # 外部输入不合法属于预期内情况（CLAUDE.md 第八节），走异常，不 assert。
                kind, reason = type(exc).__name__, str(exc)
            except ValidationError as exc:
                # `Action` 的 model_validator 抛的是 ValueError，pydantic 包成
                # ValidationError —— 它**不是** AgentError 的子类，不带上就会
                # 穿过重试直接崩掉一整局。
                #
                # 正常情况下走不到：`_parse` 在构造前把每个约束都自己验过一遍。
                # 但那意味着同一套校验写了两遍且没有任何机制保证同步——
                # 哪天 `Action` 上多一条约束而 `_parse` 没跟上，症状就是整局崩溃
                # 而不是一次重试。这里兜住，让它退化成一次可统计的解析失败。
                kind, reason = "ParseFailure", f"Action 字段不合法：{exc.errors()[:1]}"

            # **一次模型调用 = 一条账**，成功失败都留。
            # 失败的那几次同样烧了 token；而 `raw` 让你改进解析器之后能
            # **离线重算，不必再花 token 重跑**。
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
        self, goal: Goal, obs: Observation, history: Sequence[MemoryEntry] = ()
    ) -> Verdict:
        """判断这个目标达成了没有。**永远返回 Verdict，不抛异常。**

        **任务目标和子目标走同一个方法**，只是 `goal` 从目标栈的不同层取。
        判定这件事在两种粒度上是同一回事：拿着一句判据去看一帧画面。
        分成两个方法只会得到两份要各自标定的 prompt。

        区分哪一层是**调用方的事**：Harness 在 trace 里标 `depth`。
        更要紧的是**只有栈底那一层决定 episode 成败**——子目标完成只弹栈，
        不写 `success`。不然 agent 可以压一个"我已经到家了"的子目标，
        让判定器判它完成，成功率就变成它自己发的奖状了。

        ## `history` 给的是证据，不是说辞

        判定器**需要**看到最近几步：证据可能出现在三步以前那一帧的对话框里。
        子目标尤其如此——一条第 10 步才压进来的目标，前 9 步没人问过它，
        那几帧就永远丢了。原来那版靠"每步都问一次"兜底，兜不住这个洞。

        但历史里危险的不是画面，是 `rationale`——被评价者自己的说辞。
        所以这里渲染时一律 `reason=False`（见 `MemoryEntry.render`）：
        **发生过的事给它看，它对那件事的主张不给它看。**

        窗口两头都有界：只有本局、只有最近几条（`Harness.JUDGE_HISTORY`）。
        无界的历史会造出另一种错——上一局说过的那句话让它在第 0 步就判完成。

        `Verdict.call` 带着 token、延迟、原始输出交出去，由 Harness 记账。
        这已经不是判定器的特权设计，而是所有大脑调用的共同处境（见模块 docstring）。
        """
        t0 = time.perf_counter()
        try:
            # **渲染也在 try 里。** `render()` 用的是 `Template.substitute`，
            # 模板少一个占位符就抛 KeyError，而 prompt 是最常改的那类文件。
            # 放在外面的话，"判定器永不抛异常"这条契约就有一个缺口——
            # 一次本该记成"判定失败"的事件会变成一局丢失的数据。
            # （多层并发判定那一版里这条更要紧：worker 抛出来会穿过整个线程池。
            #  并发删了，契约不变——它保的是"判不出来"和"判了没完成"分得开。）
            rendered = (
                "\n".join(
                    f"- {k}: {v}" for k, v in obs.facts.items() if k not in JUDGE_BLIND
                ) or obs.summary
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
        """解析成 `(done, why, 失败类型)`。第三项为空串表示解析成功。

        解析不出来时 `done` 一律为 False —— **fail closed**。
        判成"完成"会立刻终止这一局并直接进实验数据；判成"没完成"只是多跑几步。
        代价不对称，所以所有不确定都往"没完成"倒。

        第三个返回值让调用方能把"判了没完成"和"根本没判出来"分开统计：
        前者是结论，后者是故障，混在一起会让**判定器的失效变得不可见**——
        表现就是成功率悄悄变成 0，而没人知道为什么。
        """
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
    ) -> MemoryEntry:
        """把这一步整理成一条经验：**看到什么 → 为什么 → 做了什么 → 变成什么**。

        `after` 是一个**完整的观察**，不是一句话结果。早先只存"结果：你在野外"，
        取回十条全长一个样——把结果压成标签，这条经验就回答不了"那一下到底改变了什么"，
        而那正是它唯一的价值。

        写进去的是 `rationale` 而不是 `thought`：完整推理留在 trace 里，
        进记忆的只有论据。这条经验因此是**自带标签**的——"我以为 P，结果 R"，
        取回时反例就贴在同一行，一条错误论据不会被当成知识使用。

        `key` 本阶段用位置占位（比 step 强：位置是可复用的作用域，step 不是）。
        机制一接进来时换成状态抽象的语义 key，**这个方法的签名不变**。

        ## 它现在没有模型调用

        「存入前的修饰」（改写措辞、抽出可复用的结论、判断这条值不值得存）
        是这个方法该长成的样子，挂载点就在这里。**但本版是纯格式化。**

        理由是成本：开一次修饰就是每步第三次模型调用，而现在还没有任何证据说明
        修饰过的条目检索得更准——检索本身都还是字符重叠（见 `MemoryTool.query_episodic`）。
        先把结构立在这里，等检索换成向量、能量出"修饰有没有提升命中"之后再开。
        开它的时候只改这一个方法体，签名和调用方都不动。

        它仍然放在 Brain 而不是 Tools：**记忆的措辞是大脑的产物**，
        今天恰好不需要模型，不代表它属于工具层。
        """
        assert action.rationale, "reflect() got an action without a rationale"

        # 连按次数从动作本身取，不从观测里找——**动作是我们自己发出的，是确定的**。
        raw = action.args.get("times", "1")
        times = f" ×{raw}" if raw not in ("", "1") else ""
        snapshot = Snapshot.of(before)
        return MemoryEntry(
            before=snapshot,
            rationale=list(action.rationale),
            action=f"{action.name}{times}",
            after=Snapshot.of(after),
            key=snapshot.position or str(before.step),
            step=before.step,
            # **episode_id 由 Harness 盖章** —— 大脑不知道自己在哪一局，
            # 和 `Observation.step` 一个道理。
            episode_id="",
        )

    # ---- 内部 ----

    def _build_prompt(
        self,
        goals: list[Goal],
        obs: Observation,
        space: ActionSpace,
        memories: list[MemoryEntry],
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
        return self._decide_prompt.render(
            goals=self._render_goals(goals),
            summary=obs.summary,
            facts=facts,
            memories=recalled,
            actions=actions,
            max_rationale=MAX_RATIONALE,
        )

    @staticmethod
    def _render_goals(goals: list[Goal]) -> str:
        """把目标栈画出来，**栈顶标出来**。

        倒序渲染（栈顶在最上面）：模型读 prompt 是从上往下的，
        把"你现在要做的那一条"放在最先读到的位置。
        下面几条仍然要给——不给的话它不知道自己为什么在做这件事，
        也就无法判断这个子目标是不是已经偏离了任务。
        """
        lines = []
        for depth, g in reversed(list(enumerate(goals))):
            mark = "← 你现在要完成的" if depth == len(goals) - 1 else ""
            role = "任务目标" if depth == 0 else f"子目标（第 {depth} 层）"
            lines.append(f"{depth}. [{role}] {g.goal}\n   判据：{g.criteria} {mark}".rstrip())
        return "\n".join(lines)

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

        # **只剩按键一类动作。** intent 分派（press / push_goal）连同枚举一起删了，
        # 所以这里不再有"先取 intent、再按 intent 分叉"那一段——
        # 拆子目标的机制会在别处重写，届时分叉回到这里还是换个形状，是那时的决定。
        name = raw.get("action")
        if not isinstance(name, str) or not name:
            raise ParseFailure(text, "no 'action' field")
        if not space.contains(name):
            # **走 `IllegalAction` 而不是 `ParseFailure`**：格式是对的，
            # 它是在幻觉一个此刻不可用的按键。两者在 replay 里是不同的失败模式，
            # 该改的东西也不同（前者改 masking 或 prompt，后者改输出格式）。
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
