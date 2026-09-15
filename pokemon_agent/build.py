"""全项目唯一装配点：把所有具体实现 new 起来，拼成 RunHarness 与 GameTools。

**四个独立模块（brain / world / memory / trace）的实现类，本文件一律零 import**
——各自由 tool 层上的接线工厂造好：`BrainTool.build()` / `GameTools.build()` /
`MemoryTool.build()` / `TraceTool.build()`。装配点只递裸字段（型号名、路径、开关）。
本文件对 `pokemon_agent.{brain,world,memory,trace}` 的 AST import 点都是 **0**。

想知道"怎么拼起来"读这个文件；想知道"怎么互相调用"读 harness/run/harness.py。

**入口是 run 级**：返回的 `RunHarness` 是主 agent（完整一局游戏），它内部编译并
`invoke` episode 子图（21 个节点，按七个功能域分文件夹，见 `harness/episode/`）。
旧调用方拿到的 `harness.run(run_id, goals)` 是 run 级签名。

**步 4 起装配只剩"造一个 `HarnessDeps`"这一件事**：全图唯一的 context 里装着
6 根 Port + 策略对象 + 两个行为开关 + 整 run 的记号——`RunHarness(deps)` 只收它，
不再逐个把同样的东西再递一遍（那会有两份真源，而"两边不是同一个对象"不报错）。
"""

from __future__ import annotations

from pokemon_agent.harness import (
    BrainPlanner,
    HarnessDeps,
    Planner,
    Reviewer,
    RunHarness,
)
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.tools import (
    BrainTool,
    GameTools,
    MemoryTool,
    TraceTool,
)


def build_real(
    rom: str,
    state_file: str | None = None,
    vision_model: str = "qwen3.8-max",
    text_model: str = "qwen-plus",
    judge_model: str = "qwen3.8-max",
    verify_model: str = "doubao-seed-2-1-pro-260628",
    plan_model: str = "doubao-seed-2-1-pro-260628",
    max_tokens: int = 25600,
    watch: bool = False,
    speed: int = 0,
    run_id: str = "local",
    # 供应商由**型号名前缀**决定（0914 起，表在 `brain/providers.py::_PROVIDER_PREFIXES`）：
    # `qwen*` → DashScope、`doubao*` → 火山方舟、`deepseek*` → DeepSeek 官方 API。
    # 下面这几个缺省值因此不只是"型号名"，它们同时**选定了厂商**。
    #
    # 缺省组合的历史依据（0908 实测，见 CHANGELOG）：perception/judge 走 qwen3.8-max
    # （DashScope 图像按分辨率计费，原生 160×144 每张仅 74 tok，而 judge 每步带
    # 2-3 张历史帧）；verify/plan 留在火山方舟（豆包图像按张计费，实测恒定
    # 1294 tok/张、与分辨率无关，verify 的多帧拼接成一张后图费与帧数解耦）。
    # **这不是硬约束**：换哪家只改这几个字符串，`provider_for()` 会造出配套的类
    # ——"传 Qwen 型号名给 verify 会 404"那种事现在在装配期就变成 `ValueError`，
    # 因为型号名前缀与厂商类必须配套这件事已经由表保证。
    # state_file: None = 从开机起跑；API 装配默认传 `rom + ".state"`（存在时）。
    reviewer: Reviewer | None = None,
    planner: Planner | None = None,
    auto_push_goals: bool = True,
    auto_decide_done: bool = True,
) -> tuple[RunHarness, GameTools]:
    """装配真实链路；返回 `(harness, game)`。

    **`world` 不在返回值里**（0913 夜）：生命周期归 `GameTools` 持有——
    `build_real` 再交一个 `PyBoyWorld` 出去，
    只会逼调用方去认一个 world 类型，而它此前唯一的用途
    （`_RunHandle.world` + `getattr(world, "close")`）是**死码**
    （真实实现上的方法叫 `stop()`，那个 `getattr` 恒为 `None`）。
    与 trace 那次"`build_real` 返回值去掉零消费者的 `trace` 项"同款。

    **事件流不在返回值里**（0913 下午）：harness 侧全部读点走
    `HarnessDeps.trace`（`TraceToolPort`），装配点把 `LocalTrace` 交出去只会
    逼调用方去认一个 trace 类型。`trace_data/` 落盘的路径由 tool 层持有，
    外部要读账一律经 `deps.trace`。

    `reviewer` / `planner`：人与图之间的那扇门、与 plan 位置的 input 来源
    （**两个同步接口**，控制台实现会阻塞读 stdin）。**两者的缺省不一样**：

    - `reviewer` 不传 → `NullReviewer`（没人插话、没人推翻）；
    - `planner` 不传 → **`BrainPlanner`（模型自主规划）**——这是 0914 S2 起的
      缺省（`docs/PLAN_planner_v2.md`），plan 位置的来源从"人"换成了"模型"。

    所以**"无头"不等于"两个都是 Null"**：要一个"不加目标、不表态"的规划器，
    必须**显式传 `NullPlanner()`**；或者让 `auto_push_goals=False` 使 `plan`
    根本不去调它（那条路上"装配的是谁"不影响结果，但**也不验证任何读口**）。
    不传 `reviewer` 而无头，是一个正常场景（测试、CI、无头批量跑），不是缺配置。

    **两者必须共享同一份策略对象**：`reviewer` 被 `plan`（插话）和 `review`
    （审）两处读，传进来的必须是同一个实例——否则"人对 plan 的那一版说的话"
    传到审那一格就断了，而表现只是"人说了话、图却像没听见"。

    **`watch` 与 `speed` 是两个独立旋钮**（0914 解耦）：`watch` 开 SDL 窗口
    （看得见画面），`speed` 是模拟器速度（`0` = 不限速，缺省；`1` = 真实速度，
    过场看得清但 CPU 占用大幅下降）。两者可以单独动——"开窗口 + 不限速"
    （`watch=True, speed=0`）是合法组合，而解耦前它**根本写不出来**
    （那时 `speed` 只在 `watch=True` 时才生效）。无头批量跑用缺省即可
    （关窗 + 不限速），与解耦前的行为逐字相同。

    **没有存档 / 恢复参数**（0913 存档链整体删除）：`resume_cursor` 这类
    "从第 N 个事件接着跑"的入口与存档端是**成对的**，恢复链删掉之后它就没有
    消费方了——单独留一个裸游标参数，只会让下一个人以为还能接上。`save_checkpoint`
    节点自己仍在图上占位空转（见 `config.NODES_PER_DECISION`），那是图拓扑的事，
    与这里有没有参数无关。
    """
    # **world 本体也不在这里造**（0913 夜）：`GameTools.build()` 是它唯一的
    # 接线工厂——"造一个 `PyBoyWorld`、给它挂哪个感知实现、temperature 钉多少"
    # 都是这条链路的接线知识，与 `BrainTool.build()` / `MemoryTool.build()` /
    # `TraceTool.build()` 同一条判据，收在 tool 层离消费者近。装配点只递
    # 裸字段（ROM 路径、存档、开关、型号名）。
    #
    # 此前这里有两行：`build_vision_provider(...)`（零件工厂，0913 深夜九建的）
    # 与 `PyBoyWorld(...)`（本体，直接 new）——"造零件在 tool 层、装配在装配点"
    # 的半截工厂，也是四个独立模块里**唯一没做工厂的一个**。现在收平：
    # **本文件对 `pokemon_agent.world` 零 import**。
    game = GameTools.build(
        rom, state_path=state_file, watch=watch, vision_model=vision_model, speed=speed
    )

    # 一条事件一个 json 文件落盘（0910 重构）；
    # 文件名是时间递增 uuid，**排序看内容里的 `(ts, uuid)`**（0914 封套改造：
    # 原先那个全局单调 `event_id` 已删，见 `trace/store.py` 的模块 docstring）。
    # **不再有内存事件槽**：`event_sink` 双写随 `RunDataCenter` 一起删除，
    # 磁盘账本（`deps.trace.read_events()`）是唯一真相——图内节点直接读它
    # （原来的另一个读者 SSE 端点随 `api.py` 0913 晚一起删了）。
    #
    # **`LocalTrace` 不在这里造**（0913 下午）：`TraceTool.build()` 是唯一的
    # 接线工厂——落盘记录的完整形状在它内部接好，本装配点只递裸字段。与
    # `BrainTool.build()` / `MemoryTool.build()` / `GameTools.build()` 同形。
    # **本文件对 `pokemon_agent.trace` 零 import**。
    trace_tool = TraceTool.build(run_id=run_id)

    # EpisodeHarness 伸向记忆的唯一通道
    # **memory 的两个检索 provider 不在这里造**（2026-09-13，深夜十二）：
    # "这条链路要接哪个实现"是接线知识，收在 `MemoryTool.build()`——与
    # `BrainTool.build()` / `GameTools.build()` 同形。本装配点对
    # `pokemon_agent.memory` **零 import**（此前第 25 行有一行
    # `from pokemon_agent.memory import FastEmbedReranker, FastEmbedText`，
    # 并在此处直接 new 两个实现）。
    memory = MemoryTool.build()

    # **brain 的四个 provider 不在这里造**（2026-09-13，S6）：哪个技能接哪家
    # 厂商、temperature 分几层，都是 brain 那条链路的接线知识，收在
    # `brain/build_llm_providers.py` + `BrainTool.build()`。
    # 本装配点只递**型号名**这几个裸字段（0913 深夜九：此前递的是
    # `BrainLlmConfig`，需要 `from pokemon_agent.brain import BrainLlmConfig`
    # ——一行非 tool 层的 brain import；改成裸字段后本文件对 brain 零 import）。
    #
    # **厂商由型号名前缀决定**（0914 起）：四个位置可以任意混搭，
    # 表在 `brain/providers.py::_PROVIDER_PREFIXES`。前缀不认识时 `provider_for()`
    # 在装配期抛 `ValueError`（不拖到第一次调用才 404）。
    #
    # temperature 分层（0907 实测依据，见 CHANGELOG）：judge/verify/plan 是
    # 判定与结构化输出任务，确定性优先 → 0；decision 保留 0.3 的少量随机
    # （完全归零会让同一局面反复交出同一动作，探索多样性靠它兜底，
    # 死循环另有 stall 检测与 judge 兜底）。这三个值住在
    # `brain/build_llm_providers.py` 的常量里（常量不是旋钮）。
    # 选型的入口收敛到本方法的关键字参数。
    brain_tool = BrainTool.build(
        text=text_model,
        judge=judge_model,
        verify=verify_model or "doubao-seed-2-1-pro-260628",
        plan=plan_model or "doubao-seed-2-1-pro-260628",
        max_tokens=max_tokens,
    )

    # `interaction` 那个"在这里先落实成一个真实例"的步骤已删（0914 控制台改造）：
    # 跨线程信箱整套下线，取而代之的是 `reviewer`/`planner` 两个同步接口——
    # 无头场景由上面 `HarnessDeps` 构造处的 `Null*` 兜底，不存在"两份实例"的风险。

    # **全图唯一的 context**（D3/F10）：episode 子图的 21 个节点、run 图的 5 个节点、
    # 图外两个入口（`episode_entry.run_new` 与 `run_entry.new_run`）共用它一份。同一个
    # trace 实例注入两端——episode 写事件、run 级读盘；同一个 reviewer 实例注入
    # `plan`（插话）与 `review`（审）两处——人对 plan 那一版说的话和审时的表态
    # 走的是同一扇门。
    #
    # **两个行为开关也住这里**（步 4 归位）：它们是"这次 run 怎么跑"的构造期决定，
    # 读它的是 `run/nodes/plan.py`。此前它们是 `RunHarness.__init__` 的参数、与 deps 各存
    # 一份——现在只有一个来源。
    #
    # **`reviewer` / `planner` 不传就装配成 Null 实现**（0914 控制台改造）：
    # 无头 run 的语义是"LLM 出什么就是什么、没人插话也没人加目标"。
    # **`planner` 默认是模型**（0914 S2）：plan 位置的来源从"人"换成"模型"
    # （`docs/PLAN_planner_v2.md`），所以 `BrainPlanner` 是默认实现——
    # 它读本 run 的局索引 + 少量详情 + 地图事实，自主维护目标表。
    # **不花多余的钱**：`auto_push_goals=False` 时 `plan` 节点根本不调 planner
    # （那一版注定不加目标），无头核对脚本因此仍是"零规划调用"。
    # 人手动驾驶传 `ConsolePlanner()` 即可覆盖。
    deps = HarnessDeps(
        game=game,
        memory=memory,
        brain_tool=brain_tool,
        trace=trace_tool,
        reviewer=reviewer or NullReviewer(),
        planner=planner or BrainPlanner(brain_tool),
        run_id=run_id,
        # `False`：plan 不自动压栈，新目标改走人工通道 `POST /runs/{id}/goals`。
        auto_push_goals=auto_push_goals,
        # `False`：plan 也不自己判 done，栈空时改路由去 review 问人，
        # 只有人类的 STOP 才能真的结束 run。
        auto_decide_done=auto_decide_done,
    )
    run_harness = RunHarness(deps)

    return run_harness, game
