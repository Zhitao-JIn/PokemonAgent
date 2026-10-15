"""`GameToolPort` 的实现：Harness 和世界之间那层薄壳。**不碰任何记忆。**

薄到几乎只是转发，但有两件事只在这里做：

- **动作掩码。** `get_action_space()` 按当前 overlay（有没有对话框、菜单、选择框）
  给出此刻能按的键；仅开放脚本的场合改给本场合的脚本签名、不给键。掩码**只看 overlay**，
  不看目标、不看历史——它回答的是"这一帧按下去有意义吗"，不是"这一步该按什么"。
- **前置检查。** `execute()` 断言动作确实来自最近一次给出的动作空间。
  大脑幻觉出不存在的键要在这里就地爆炸，而不是变成一个语义不明的模拟器错误。

掩码是**按这一帧算的，换帧就作废**，所以和帧哈希一起存。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只为标注返回值：MCP 模式返回的是远程门面，与 GameTools 同协议
    from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.direct.prompts import BUTTON_HELP, MAP_HINT, REPEAT_HINT
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolExecuteResp,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSaveStateResp,
)
from pokemon_agent.world import (
    ActionSpace,
    Facts,
    TaskObservation,
    WorldPort,
)
from pokemon_agent.world.action_space import compute_action_space

# `BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT` 的组装逻辑全在
# `pokemon_agent/direct/prompts/decide_action.py`（decide_action.md 一个模板的
# 全部装配逻辑收在一处）——这里只是消费方。


def _action_space(obs: TaskObservation, all_actions: list[str]) -> ActionSpace:
    """动作空间由 world 的 `compute_action_space` 算出（`names` / `mask` / `entries` 的唯一出处），
    本函数不改它们，只给开放按键的场合补上 prompt 要渲染的按键说明、连按用法与地图规则。

    这三段文案属 prompt 层（`direct/prompts`），world 不依赖它，所以在这一层补。
    脚本接管场合也有方向键；没有后端按键能力时不补文案。

    `get_action_space()` 和 `execute()` 共用它，而**不是让后者去调前者**——
    两个方法各自对外的语义不同（一个交出动作空间、一个校验并执行），
    让后者内部调前者只会多绕一层，读代码的人还要多想一步谁依赖谁。
    """
    space = compute_action_space(obs, all_actions)
    if not space.names:
        return space
    overlay = obs.facts.overlay or Facts.Overlay.NONE
    # `note`/`map_note` 分开是有意的：地图/证据规则（`map_note`）要紧跟在已知事实
    # 后面渲染，连按用法（`note`）留在可用按键说明这一节——见
    # `ActionSpace.map_note` 的字段说明。
    return space.model_copy(
        update={
            "descriptions": {
                name: BUTTON_HELP[overlay].get(name, BUTTON_HELP[Facts.Overlay.NONE].get(name, ""))
                for name in space.names
            },
            "note": REPEAT_HINT,
            "map_note": "" if obs.covered_by_script else MAP_HINT,
        }
    )


def _run_script_report(
    world: WorldPort, name: str, args: dict[str, str | int]
) -> dict[str, object]:
    """进程内脚本通道：world 包成 `WorldConsole` → 按名执行 → `ScriptResult` 折成
    JSON 形状的终态报告（与 MCP 面上脚本 tool 的返回形状逐字段一致，P5 定案）。"""
    from pokemon_agent.world.scripts.catalog import run_script_by_name
    from pokemon_agent.world.scripts.console_adapter import WorldConsoleAdapter

    result = run_script_by_name(WorldConsoleAdapter(world), name, args)
    return {
        "ok": result.ok,
        "code": result.code,
        "data": result.data,
        "events": list(result.events),
        "calls": list(result.calls),
    }


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
        world_server_url: str | None = None,
    ) -> GameTools | WorldMcpTool:
        """造一个接了真实世界的 `GameTools`——**装配点唯一的入口**。

        `world_server_url`（MCP 化新增）：world server 的 **base 地址**
        （`http://127.0.0.1:8767`，路径由 `mcpclient` 的协议常量拼）；
        给了 = 世界住在另一个进程，返回 `WorldMcpTool`（同一个 `GameToolPort`，
        信封翻译随迁）；缺省 = 进程内 `PyBoyWorld`（与改造前行为一致）。
        **不在这里探活**——探活是 run 开始前的一道闸，放装配点显式打。

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

        **        `watch` 与 `speed` 是两个独立的旋钮**（0914 解耦，详见
        `PyBoyWorld.__init__` 的 docstring）：前者只管开不开窗口，后者只管跑多快
        （`0` = 不限速、`1` = 真实速度）。缺省 `speed=0` 与解耦前的无头行为相同。
        """
        if world_server_url:
            from pokemon_agent.mcpclient.client import McpClient, mcp_endpoint
            from pokemon_agent.mcpclient.world_tool import WorldMcpTool

            client = McpClient(mcp_endpoint(world_server_url))
            client.start()
            return WorldMcpTool(client)

        # 导入放函数内：`pyboy_world` 一整条链拖着 `pyboy` + `PIL`，
        # 不该在 import 本模块时连带拉起（`tools/__init__.py` 的懒加载链同理）。
        from pokemon_agent.brain.vision_factory import build_vision_provider
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
        """开新一局。**不感知**——调用方另调 `perceive_task()` 拿第一帧。

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

    def save_state(
        self, req: FromHarnessToGameToolSaveStateReq
    ) -> FromHarnessToGameToolSaveStateResp:
        """模拟器完整状态 → `req.path`（先写临时文件再改名，崩溃不留半个存档）。"""
        data = self._world.save_state()
        path = Path(req.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        assert path.stat().st_size == len(data) > 0
        return FromHarnessToGameToolSaveStateResp(path=str(path), size=len(data))

    def load_state(self, req: FromHarnessToGameToolLoadStateReq) -> None:
        """`req.path` → 模拟器完整状态。"""
        self._world.load_state(Path(req.path).read_bytes())

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        """task 层的一帧：world 的 `TaskPerceived` 原样摊平进信封（不调模型、不会失败）。"""
        perceived = self._world.perceive_task()
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=perceived.observation, frame_png=perceived.frame_png, ram=perceived.ram
        )

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """掩码发生在这里，**只看 obs 里的 overlay**。

        前置条件：`req.observation` 是调用方当下正在依据的那份观测。
        后置条件：至少一个动作可用。走投无路也必须给至少一个动作——
            空动作空间是这一层的 bug，不能推给大脑处理。

        **这是一个纯函数，不碰 world。** 掩码的依据由调用方交出来：它按哪份
        观测做的决策，就该拿哪份观测算动作空间。这样"用过期的掩码"在结构上
        不可能发生，不需要运行时比对帧哈希去发现。

        按这份观测的 overlay 给出能按的键。
        """
        return FromHarnessToGameToolGetActionSpaceResp(
            action_space=_action_space(req.observation, self._world.all_actions())
        )

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> FromHarnessToGameToolExecuteResp:
        """执行**一个键或一条脚本**，推进世界。
        **不感知**——调用方另调 `perceive_task()` 拿新观测。

        前置条件：`req.observation` 是这个动作**据以选出**的那份观测；
            `req.action` 是单键（连按已在 Harness 的循环里展开成多步）或一条脚本调用。
        后置条件：脚本动作时 `resp.report` 是终态报告（`{ok, code, data, events, calls}`
            的 JSON 形状）；按键时 `resp.event` 是本键的裸事件（可为 None）。

        **依据由调用方交出来，不由本对象攒着**——调用方本来就知道自己按的是
        哪份观测，让它说出来即可。

        步骤 1：脚本 → 校验脚本名在本帧空间里，包上 adapter 交脚本层执行到底。
        步骤 2：键 → 校验单键且在掩码里，按下去。
        """
        action = req.action
        space = _action_space(req.observation, self._world.all_actions())

        # 步骤 1：脚本。一次调用占 harness 账一步——内部 N 键不展开（P5 定案）。
        if action.script is not None:
            script_names = [e.name for e in space.entries if e.kind == "script"]
            entry = space.entry(action.script.name)
            assert entry is not None and entry.kind == "script" and space.enabled(entry.name), (
                f"execute() got script {action.script.name!r} outside {script_names}"
            )
            report = _run_script_report(self._world, action.script.name, dict(action.script.args))
            return FromHarnessToGameToolExecuteResp(report=report)

        # 步骤 2：键。**执行粒度是一个键。** 收到多段说明调用方没展开——那等于把"一次决策
        # 按多少键"从循环里偷了回来，就地拦下好过替它展开。
        assert len(action.sequence) == 1, (
            "execute() 只接受单键动作；连按应由 Harness 的循环展开成多步"
        )
        segment = action.sequence[0]
        assert space.contains(segment.name), f"execute() got {segment.name!r} outside {space.names}"
        # world 不认识 `Action`，这里拆成 `(按键名, 连按次数)` 的裸列表交给它；
        # 事件判定在 world 侧（P6：`observe_step`，前后各一帧 RAM 感知）。
        from pokemon_agent.world.object_events import observe_step

        _moved, event = observe_step(
            self._world, [(segment.name, segment.times)], settle=req.settle
        )
        return FromHarnessToGameToolExecuteResp(event=event)

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """无输入推进 N 帧（世界自己演化）——harness 等决策 LLM 时的空闲填充。"""
        self._world.evolve(req.frames)
