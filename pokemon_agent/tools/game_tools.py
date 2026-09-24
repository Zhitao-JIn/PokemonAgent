"""`GameToolPort` 的实现：Harness 和世界之间那层薄壳。**不碰任何记忆。**

薄到几乎只是转发，但有三件事只在这里做：

- **动作掩码。** `get_action_space()` 按当前 overlay（有没有对话框、菜单、选择框）
  给出此刻能按的键。掩码**只看 overlay**，不看目标、不看历史——它回答的是
  "这一帧按下去有意义吗"，不是"这一步该按什么"。
- **前置检查。** `execute()` 断言动作确实来自最近一次给出的动作空间。
  大脑幻觉出不存在的键要在这里就地爆炸，而不是变成一个语义不明的模拟器错误。
- **感知的重试循环与翻译**（0913 夜从 harness 节点搬来）：`perceive_with_retry()`
  反复问 world，把它的 `PerceptionAttemptFailed` 收成整条账、耗尽后翻译成
  tool 层的 `MaxRetriesExceeded`——与 `BrainTool._attempt_loop()` 同一位置、
  同一分工（P4「桥只建在 tool 层」在 world 这条链上的落地）。
  这是 world 的异常**唯一**需要被听懂的地方，也是它不必继承 `AgentError` 的原因。

掩码是**按这一帧算的，换帧就作废**，所以和帧哈希一起存。
"""

from __future__ import annotations

import time

from pokemon_agent.brain.errors import ProviderRejected, ToolTimeout
from pokemon_agent.config import PERCEPTION_MAX_RETRIES
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolPerceiveOnceResp,
    FromHarnessToGameToolResetReq,
    ModelCall,
    ModelCallLog,
)
from pokemon_agent.tools.backoff import backoff_seconds
from pokemon_agent.tools.prompts import BUTTON_HELP, MAP_HINT, REPEAT_HINT
from pokemon_agent.world import (
    OVERLAY_ACTIONS,
    ActionSpace,
    Facts,
    Observation,
    WorldPort,
)
from pokemon_agent.world.errors import PerceptionAttemptFailed

# `BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT` 的组装逻辑全在
# `pokemon_agent/tools/prompts/decide_action.py`（decide_action.md 一个模板的
# 全部装配逻辑收在一处）——这里只是消费方。


def _mask(obs: Observation, all_actions: list[str]) -> ActionSpace:
    """按这份观测的 overlay 算动作空间。**纯函数，不碰 world。**

    后置条件：`names` 非空。走投无路也必须给至少一个动作——
        空动作空间是这一层的 bug，不能推给大脑处理。

    `get_action_space()` 和 `execute()` 共用它，而**不是让后者去调前者**——
    两个方法各自对外的语义不同（一个交出动作空间、一个校验并执行），
    让后者内部调前者只会多绕一层，读代码的人还要多想一步谁依赖谁。
    """
    # 直接拿结构化的 `facts.overlay`——不再是"文本塞回枚举"的反解，
    # `obs.facts` 本来就是 `Facts` 模型，`overlay` 该是 `Facts.Overlay` 就是
    # `Facts.Overlay`，缺失时才退回 `NONE`。
    overlay = obs.facts.overlay or Facts.Overlay.NONE
    names = [a for a in OVERLAY_ACTIONS[overlay] if a in all_actions]

    assert names, f"action space must never be empty (overlay={overlay})"
    return ActionSpace(
        names=names,
        descriptions=dict(BUTTON_HELP[overlay]),
        # `note`/`map_note` 分开是有意的：地图/证据规则（`map_note`）要紧跟在已知事实
        # 后面渲染，连按用法（`note`）留在可用按键说明这一节——见
        # `ActionSpace.map_note` 的字段说明。
        note=REPEAT_HINT,
        map_note=MAP_HINT,
    )


def _last_error(calls: list[ModelCall]) -> str:
    """把最后一次尝试的失败信息折成一句话。

    与 `brain_tool._last_error` 同形——两个循环各有一个私有副本，
    不互相 import：它是 4 行的记账措辞，不是契约（`MaxRetriesExceeded.last_reason`
    只要求"一句话"）。
    """
    if not calls:
        return "no attempts recorded"
    last = calls[-1]
    return f"{last.error_kind}: {last.error}"


class GameTools:
    """`GameToolPort` 的唯一实现。持有 world，**不持有记忆**。"""

    def __init__(self, world: WorldPort) -> None:
        """接好世界。**本对象没有状态。**

        掩码校验的依据由参数回答：`execute(action, obs)` 收下"这个动作是按
        哪份观测选的"，就地用同一个纯函数重算一遍掩码去校验——依据不在
        本对象攒着（那次取舍见 `CHANGELOG.md` 2026-09-03 条目）。
        """
        self._world = world

    # ---- 接线工厂（装配点唯一的入口）----

    @classmethod
    def build(
        cls,
        rom: str,
        *,
        state_path: str | None = None,
        watch: bool = False,
        vision_model: str = "qwen3.8-max",
        speed: int = 0,
    ) -> GameTools:
        """造一个接了真实世界的 `GameTools`——**装配点唯一的入口**。

        **为什么"造 `PyBoyWorld` + 挂哪个感知实现"收在这一处**：与
        `BrainTool.build()` / `MemoryTool.build()` / `TraceTool.build()` 同一条
        判据——"这个技能接哪个实现"是这条链路的接线知识，装配点不该 import
        具体类。此前 `build.py` 直接 `PyBoyWorld(...)`，是四个独立模块里
        **唯一还没做工厂的一个**；零件工厂（`build_vision_provider()`）早就有，
        本体却还在装配点，是"造零件在 tool 层、装配在装配点"的半截工厂。

        前置条件：`rom` 是存在的 ROM 路径；`state_path` 给了就必须存在
            （缺了在构造时当场炸，不留到 `reset()`——见 `PyBoyWorld.__init__`）。
        后置条件：返回的对象已跑完 `PyBoyWorld.__init__` 的全部前置检查，
            但**世界还没 reset**——开局由 harness 的第一格调 `reset()`。

        **`watch` 与 `speed` 是两个独立的旋钮**（0914 解耦，详见
        `PyBoyWorld.__init__` 的 docstring）：前者只管开不开窗口，后者只管跑多快
        （`0` = 不限速、`1` = 真实速度）。缺省 `speed=0` 与解耦前的无头行为相同。
        """
        # 导入放函数内：`pyboy_world` 一整条链拖着 `pyboy` + `PIL`，
        # 不该在 import 本模块时连带拉起（`tools/__init__.py` 的懒加载链同理）。
        from pokemon_agent.tools.vision_factory import build_vision_provider
        from pokemon_agent.world import PyBoyWorld

        return cls(
            PyBoyWorld(
                rom,
                # temperature 钉死在 0：感知是抽取不是创作，同一张图两次读出
                # 不同结果是纯噪声（`build_vision_provider` 的默认值已保证，
                # 显式写出来是给读代码的人看）。
                build_vision_provider(model=vision_model, temperature=0.0),
                state_path=state_path,
                watch=watch,
                speed=speed,
            )
        )

    # ---- GameToolPort ----

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """开新一局。**不感知**——调用方另调 `perceive_with_retry()` 拿第一帧。

        把 `req.task`（`Task`）拆成裸字段交给 world——world 不认识
        `Task` 这个 brain 的类型，只用得到这几个原始值。
        """
        task = req.task
        self._world.reset(
            task_id=task.task_id,
            goal=task.goal,
            success_criteria=task.success_criteria,
            max_steps=task.max_steps,
            initial_state_hint=task.initial_state_hint,
        )

    def perceive_with_retry(
        self, *, ram_only: bool = False
    ) -> tuple[FromHarnessToGameToolPerceiveOnceResp, ModelCallLog]:
        """感知当前这一帧——**重试循环与异常翻译都在这里**（对齐 `BrainTool._attempt_loop`）。

        **为什么循环在这一层**（0913 夜，从 harness 节点搬来）："失败之后该怎么办"
        依赖调用方的处境——只有循环控制者知道试了几次、还剩几次预算、耗尽之后
        这个节点怎么收场。这与 `BrainTool` 把五条链路的循环收在自己手里是同一条
        判据，也是 P4「桥只建在 tool 层」在 world 这条链上的落地：

            world 抛 PerceptionAttemptFailed ──► 本方法捕获、重试
                                            ──► 耗尽抛 MaxRetriesExceeded ──► harness

        搬回 tool 层之后 world 的词汇**跨不过这座桥**，所以 `world/errors.py`
        自成一根 `WorldError`（不继承 `AgentError`）——world 就此出边归零。

        `ram_only=True` 时不问模型：world 那一档只读内存、**不会失败**，
        循环第一次就返回（`log` 为空，没有 `MODEL_CALL` 要记）。

        **账随结果走，落账仍在宿主**：成功返回 `(resp, log)`——`resp.calls` 是
        world 原样的账（`list[dict]`），`log` 是**整条重试链**的账（失败尝试 +
        最后一次成功；"第几次"由账在链上的位置回答，没有 `attempt` 戳）。
        耗尽时整条账随 `MaxRetriesExceeded.calls` 带出。**"账写在它的宿主里"
        这条规则不变**：本层只把账打包好，`deps.trace.append` 收下整条链
        （`calls=…`）由 harness 节点调（与 `think_action` 的分工逐字相同）。

        前置条件：世界已 `reset()`（`world.perceive_once()` 会 assert）。
        后置条件：成功时 `resp.observation` 非空；失败时抛 `MaxRetriesExceeded`
            （`source="sense"`）。**不返回任何兜底观测**——那会让大脑基于
            假观测决策，而且这类失败在 replay 里必须能被统计到。
        """
        log: ModelCallLog = []
        for nth in range(1, PERCEPTION_MAX_RETRIES + 1):
            try:
                perceived = self._world.perceive_once(ram_only=ram_only)
            except PerceptionAttemptFailed as exc:
                # 单次失败：把这次的账收进来，继续下一次。
                # **error_kind 尽量还原真相**：world 的包装把底层异常名留在
                # `error` 字段前缀（`"{TypeName}: …"`）——4xx（`ProviderRejected`）
                # 重试注定无用，第一轮就耗尽（0915，与 `_attempt_loop` 同判据）；
                # 其余保持 `PerceptionParseFailure`（world 只会包成"这次没读出"，
                # 不区分底层，`ProviderRejected` 是唯一能从账上认出的）。
                underlying = str(exc.call.get("error", ""))
                kind = underlying.split(":", 1)[0].strip() if underlying else ""
                raw = exc.call.get("raw", "")
                log.append(
                    ModelCall(
                        payload=exc.call,
                        error_kind=kind or "PerceptionParseFailure",
                        error=raw or underlying,
                    )
                )
                if kind == ProviderRejected.__name__:
                    raise MaxRetriesExceeded(
                        len(log), _last_error(log), log, source="sense"
                    ) from exc
                if nth < PERCEPTION_MAX_RETRIES:
                    timeouts = sum(c.error_kind == ToolTimeout.__name__ for c in log)
                    time.sleep(backoff_seconds(kind == ToolTimeout.__name__, timeouts))
                continue

            # 成功：逐条收账——一次感知可能有多条 call。
            log.extend(ModelCall(payload=call) for call in perceived.calls)
            return (
                FromHarnessToGameToolPerceiveOnceResp(
                    observation=perceived.observation,
                    calls=perceived.calls,
                    frame_png=perceived.frame_png,
                ),
                log,
            )

        # 预算耗尽：升级成 tool 层的词汇，整条账随异常带出。
        raise MaxRetriesExceeded(
            PERCEPTION_MAX_RETRIES,
            _last_error(log),
            log,
            source="sense",
        )

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """掩码发生在这里，**只看 obs 里的 overlay**。

        前置条件：`req.observation` 是调用方当下正在依据的那份观测。
        后置条件：names 非空。走投无路也必须给至少一个动作——
            空动作空间是这一层的 bug，不能推给大脑处理。

        **这是一个纯函数，不碰 world。** 掩码的依据由调用方交出来：它按哪份
        观测做的决策，就该拿哪份观测算动作空间。这样"用过期的掩码"在结构上
        不可能发生，不需要运行时比对帧哈希去发现。

        按这份观测的 overlay 给出能按的键。
        """
        return FromHarnessToGameToolGetActionSpaceResp(
            action_space=_mask(req.observation, self._world.all_actions())
        )

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> None:
        """执行**一个键**，推进世界。**不感知**——调用方另调 `perceive_with_retry()` 拿新观测。

        前置条件：`req.observation` 是这个动作**据以选出**的那份观测；
            `req.action` 是单键（连按已在 Harness 的循环里展开成多步）。

        **依据由调用方交出来，不由本对象攒着**——调用方本来就知道自己按的是
        哪份观测，让它说出来即可。

        校验动作合法后按下去，推进世界。
        """
        action = req.action
        # **执行粒度是一个键。** 收到多段说明调用方没展开——那等于把"一次决策
        # 按多少键"从循环里偷了回来，就地拦下好过替它展开：展开出来的每一步
        # 都要各写一条记忆、各判一次中止，那只能是循环的事。
        assert len(action.sequence) == 1, (
            "execute() 只接受单键动作；连按应由 Harness 的循环展开成多步"
        )
        segment = action.sequence[0]
        space = _mask(req.observation, self._world.all_actions())
        assert space.contains(segment.name), f"execute() got {segment.name!r} outside {space.names}"
        # world 不认识 `Action`，这里拆成 `(按键名, 连按次数)` 的裸列表交给它。
        # `settle` 原样转达：链中间的键不等过场走完（理由见 `ExecuteReq.settle`）。
        self._world.step([(segment.name, segment.times)], settle=req.settle)

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """无输入推进 N 帧（世界自己演化）——harness 等决策 LLM 时的空闲填充。"""
        self._world.evolve(req.frames)
