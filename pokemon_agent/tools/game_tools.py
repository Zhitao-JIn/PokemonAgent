"""`GameToolPort` 的实现：Harness 和世界之间那层薄壳。**不碰任何记忆。**

薄到几乎只是转发，但有两件事只在这里做：

- **动作掩码。** `get_action_space()` 按当前 overlay（有没有对话框、菜单、选择框）
  给出此刻能按的键。掩码**只看 overlay**，不看目标、不看历史——它回答的是
  "这一帧按下去有意义吗"，不是"这一步该按什么"。
- **前置检查。** `execute()` 断言动作确实来自最近一次给出的动作空间。
  大脑幻觉出不存在的键要在这里就地爆炸，而不是变成一个语义不明的模拟器错误。

掩码是**按这一帧算的，换帧就作废**，所以和帧哈希一起存。
"""

from __future__ import annotations

from pokemon_agent.prompts import BUTTON_HELP, MAP_HINT, REPEAT_HINT
from pokemon_agent.schemas.frontend import (
    FromFrontendToGameToolLatestFrameReq,
    FromFrontendToGameToolLatestFrameResp,
)
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateBytesReq,
    FromHarnessToGameToolPerceiveOnceResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateBytesResp,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSetTaskReq,
)
from pokemon_agent.world import (
    INTERACT_KEY,
    OVERLAY_ACTIONS,
    ActionSpace,
    Facts,
    Observation,
    WorldPort,
)

# `BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT` 的组装逻辑全在
# `pokemon_agent/prompts/decide_action.py`（decide_action.md 一个模板的
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


class GameTools:
    """`GameToolPort` 的唯一实现。持有 world，**不持有记忆**。"""

    def __init__(self, world: WorldPort) -> None:
        """接好世界。**本对象没有状态。**

        掩码校验的依据由参数回答：`execute(action, obs)` 收下"这个动作是按
        哪份观测选的"，就地用同一个纯函数重算一遍掩码去校验——依据不在
        本对象攒着（那次取舍见 `CHANGELOG.md` 2026-09-03 条目）。
        """
        self._world = world

    # ---- GameToolPort ----

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """开新一局。**不感知**——调用方另调 `perceive_once()` 拿第一帧。

        把 `req.task`（`TaskForBrain`）拆成裸字段交给 world——world 不认识
        `TaskForBrain` 这个 brain 的类型，只用得到这几个原始值。
        """
        task = req.task
        self._world.reset(
            task_id=task.task_id,
            goal=task.goal,
            success_criteria=task.success_criteria,
            max_steps=task.max_steps,
            initial_state_hint=task.initial_state_hint,
        )

    def perceive_once(self) -> FromHarnessToGameToolPerceiveOnceResp:
        """感知当前这一帧，只问一次视觉模型，不重试。

        转发给 world；重试循环在 Harness。world 吐出来的是它自己的
        `Perceived`（不是信封），这里原样摊开进 harness 认识的 Resp。
        """
        perceived = self._world.perceive_once()
        return FromHarnessToGameToolPerceiveOnceResp(
            observation=perceived.observation,
            calls=perceived.calls,
            frame_png=perceived.frame_png,
        )

    def save_state(self, req: FromHarnessToGameToolSaveStateReq) -> None:
        """把当前世界状态存成一个文件。"""
        self._world.save_state(req.path)

    def save_state_bytes(self) -> FromHarnessToGameToolSaveStateBytesResp:
        """把当前世界状态存成字节串（checkpoint 每步世界快照用）。"""
        return FromHarnessToGameToolSaveStateBytesResp(
            emulator_state=self._world.save_state_bytes()
        )

    def load_state_bytes(self, req: FromHarnessToGameToolLoadStateBytesReq) -> None:
        """从字节串恢复世界状态（checkpoint 恢复用）。"""
        self._world.load_state_bytes(req.emulator_state)

    def set_task(self, req: FromHarnessToGameToolSetTaskReq) -> None:
        """只挂任务标记，不动模拟器状态（checkpoint 恢复后配 load_state_bytes 用）。"""
        task = req.task
        self._world.set_task(
            task_id=task.task_id,
            goal=task.goal,
            success_criteria=task.success_criteria,
            max_steps=task.max_steps,
            initial_state_hint=task.initial_state_hint,
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
        """执行动作，推进世界。**不感知**——调用方另调 `perceive_once()` 拿新观测。

        前置条件：`req.observation` 是这个动作**据以选出**的那份观测。

        **依据由调用方交出来，不由本对象攒着**——调用方本来就知道自己按的是
        哪份观测，让它说出来即可。

        校验动作合法后按下去，推进世界。
        """
        action = req.action
        space = _mask(req.observation, self._world.all_actions())
        for segment in action.segments():
            assert space.contains(segment.name), (
                f"execute() got {segment.name!r} outside {space.names}"
            )
        if action.sequence and len(action.sequence) > 1:
            body, tail = action.sequence[:-1], action.sequence[-1]
            directions = {"up", "down", "left", "right"}
            assert all(segment.name in directions for segment in body) and (
                tail.name in directions or (tail.name == INTERACT_KEY and tail.times == 1)
            ), (
                "multi-step action sequence may contain only directional keys, "
                "plus at most one trailing 'a'"
            )
        # **整条链交给 world 一次执行完**，这里不自己展开——一次决策就是一次
        # 感知（中间帧没有会被用到的信息，展开成逐次调用会成倍烧感知 token，
        # 实测数据见 `CHANGELOG.md` 2026-09-03 条目）。world 不认识
        # `ActionFromBrain`，这里拆成 `(按键名, 连按次数)` 的裸列表交给它。
        self._world.step([(segment.name, segment.times) for segment in action.segments()])

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """无输入推进 N 帧（世界自己演化）——harness 等决策 LLM 时的空闲填充。"""
        self._world.evolve(req.frames)

    def latest_frame(
        self, req: FromFrontendToGameToolLatestFrameReq
    ) -> FromFrontendToGameToolLatestFrameResp:
        """取最新一帧的 PNG 字节（消费者接口）；还没 tick 过返回 `frame_png=None`。

        帧管道是生产者-消费者模型：`_tick`（生产者）每帧塞进槽，这里
        （消费者，经 world 转发）按自己的节奏取最新帧。编码是惰性的——
        只在取帧那一刻发生。供 API 的独立 SSE 端点推给前端。
        """
        return FromFrontendToGameToolLatestFrameResp(frame_png=self._world.latest_frame())
