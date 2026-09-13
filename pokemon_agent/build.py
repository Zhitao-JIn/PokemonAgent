"""全项目唯一装配点：把所有具体实现 new 起来，拼成 RunHarness 与 world。

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
    AutoContinueReviewer,
    HarnessDeps,
    HumanReviewer,
    RunDataCenter,
    RunHarness,
)
from pokemon_agent.memory import FastEmbedReranker, FastEmbedText
from pokemon_agent.tools import (
    BrainTool,
    GameTools,
    MemoryTool,
    TraceTool,
    build_vision_provider,
)
from pokemon_agent.trace import LocalTrace
from pokemon_agent.world import PyBoyWorld


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
    run_id: str = "local",
    resume_cursor: int | None = None,
    # 供应商与模型按"图费结构"分岗（0908 实测，见 CHANGELOG）：
    # - perception/judge 走 qwen3.8-max（DashScope）：图像按分辨率计费，
    #   原生 160×144 每张仅 74 tok（judge 每步带 2-3 张历史帧）；
    # - verify/plan 留在火山方舟（`ArkProvider`，豆包）：豆包图像按张计费
    #   （实测恒定 1294 tok/张，与分辨率无关），verify 的多帧拼接成一张后
    #   图费与帧数解耦（0909 去掉 2x 上采样：不省图费、省模型显存压力）；
    #   plan 将来
    #   带跨局历史图片时同理受益。传给 `ArkProvider` 的必须是豆包模型名
    #   （带日期后缀，见 `ArkProvider.__init__` 的 assert），传 Qwen 型号名
    #   会直接 404，不是"退化成纯文本"这种优雅失败。
    # `vision_model`/`text_model`/`judge_model` 走 DashScope（`QwenProvider`）。
    # state_file: None = 从开机起跑；API 装配默认传 `rom + ".state"`（存在时）。
    reviewer: HumanReviewer | None = None,
    data_center: RunDataCenter | None = None,
    auto_push_goals: bool = True,
    auto_decide_done: bool = True,
) -> tuple[RunHarness, LocalTrace, PyBoyWorld, GameTools]:
    """装配真实链路；返回 `(harness, trace, world, tools)`。

    `world` 给调用方管生命周期（`close`）；`tools` 的 `latest_frame()` 是
    实时画面管道的消费者接口（API 的独立 SSE 端点用它推帧）。

    `data_center`：前后端交互中间层（goals 槽 + review 槽）。API 层要接
    `DataCenterReviewer` 时，必须把**同一个** `RunDataCenter` 实例传两处——
    这里和 `reviewer`——两边才是在读写同一份状态，不传就各自新建一个，
    互不相干。
    """
    # **world 的视觉 provider 也不在这里造**（0913 深夜九）：它由 tool 层的
    # `build_vision_provider()` 造——"世界的感知要一个 Qwen 实现、temperature
    # 钉死在 0"是接线知识，跟 brain 那四个 provider 的接线同属一类，
    # 收在 tool 层离消费者近。装配点只递型号名，**不再 import
    # `pokemon_agent.brain.providers`**（那是"只有 tool 层依赖 brain"这条命题
    # 此前唯一漏掉的一处）。
    #
    # temperature 钉死在 0：感知是抽取不是创作，同一张图两次读出不同结果是
    # 纯噪声（默认值已保证，这里显式写出来是给读代码的人看）。
    vision = build_vision_provider(model=vision_model, temperature=0.0)

    # PyBoy 模拟器 + 视觉感知的粘合层
    world = PyBoyWorld(rom, vision, state_path=state_file, watch=watch)

    # 一条事件一个 json 文件落盘（0910 重构，见 PLAN_memory_trace_layout §6）
    # + 内存表（SSE 端点直接轮询内存表，无推送钩子）
    data_center = data_center or RunDataCenter()
    trace = LocalTrace(
        run_id=run_id,
        event_sink=data_center.publish_event,
    )
    # harness 的记账通道：组装 req → tool 按 kind 渲染 payload → 落盘
    trace_tool = TraceTool(trace)

    # EpisodeHarness 伸向世界的唯一通道
    game = GameTools(world)

    # EpisodeHarness 伸向记忆的唯一通道
    memory = MemoryTool(
        embedding_provider=FastEmbedText(),
        reranker_provider=FastEmbedReranker(),
    )

    # **brain 的四个 provider 不在这里造**（2026-09-13，S6）：哪个技能接哪家
    # 厂商、哪个位置必须是豆包型号名、temperature 分几层，都是 brain 那条链路的
    # 接线知识，收在 `brain/build_llm_providers.py` + `BrainTool.build()`。
    # 本装配点只递**型号名**这几个裸字段（0913 深夜九：此前递的是
    # `BrainLlmConfig`，需要 `from pokemon_agent.brain import BrainLlmConfig`
    # ——一行非 tool 层的 brain import；改成裸字段后本文件对 brain 零 import）。
    #
    # 供应商与模型按"图费结构"分岗（0908 实测，见 CHANGELOG）：
    # - decide/judge 走 qwen3.8-max（DashScope）：图像按分辨率计费，
    #   原生 160×144 每张仅 74 tok（judge 每步带 2-3 张历史帧）；
    # - verify/plan 留在火山方舟（豆包）：豆包图像按张计费
    #   （实测恒定 1294 tok/张，与分辨率无关），verify 的多帧拼接成一张后
    #   图费与帧数解耦（0909 去掉 2x 上采样：不省图费、省模型显存压力）；
    #   plan 将来带跨局历史图片时同理受益。verify/plan 的型号名**必须是豆包名**
    #   （带日期后缀），传 Qwen 型号名会直接 404，不是"退化成纯文本"这种优雅失败。
    #
    # temperature 分层（0907 实测依据，见 CHANGELOG）：judge/verify/plan 是
    # 判定与结构化输出任务，确定性优先 → 0；decision 保留 0.3 的少量随机
    # （完全归零会让同一局面反复交出同一动作，探索多样性靠它兜底，
    # 死循环另有 stall 检测与 judge 兜底）。这三个值住在
    # `brain/build_llm_providers.py` 的构造语句里（常量不是旋钮），
    # 选型的入口收敛到本方法的关键字参数。
    brain_tool = BrainTool.build(
        text=text_model,
        judge=judge_model,
        verify=verify_model or "doubao-seed-2-1-pro-260628",
        plan=plan_model or "doubao-seed-2-1-pro-260628",
        max_tokens=max_tokens,
    )

    # `data_center` 在这里先落实成一个真实例（不传就自己建一个）——
    # episode 的 `decide/think_action`（human_note 槽）和 run 图的 `plan`/`review`
    # （goals/review 两槽）必须共享同一个实例，缺一处这里落实就会各自新建一份、
    # 互不相干（`RunHarness.__init__` 自己也有"缺省就新建"的兜底，但那个兜底建
    # 出来的实例不会是节点手里这份，两边就断开了）。

    # **全图唯一的 context**（D3/F10）：episode 子图的 21 个节点、run 图的 6 个节点、
    # 图外两个入口（`episode_entry.run_new` 与 `run_entry.new_run`）共用它一份。同一个
    # trace 实例注入两端——episode 写事件、run 级按类型 mask 读；同一个 data_center
    # 实例注入两端——episode 消费 human_note 槽、run 级消费 goals/review 两槽。
    #
    # **两个行为开关也住这里**（步 4 归位）：它们是"这次 run 怎么跑"的构造期决定，
    # 读它的是 `run/nodes/plan.py`。此前它们是 `RunHarness.__init__` 的参数、与 deps 各存
    # 一份——现在只有一个来源。
    deps = HarnessDeps(
        game=game,
        memory=memory,
        brain_tool=brain_tool,
        trace=trace_tool,
        reviewer=reviewer or AutoContinueReviewer(),
        data_center=data_center,
        run_id=run_id,
        # `False`：plan 不自动压栈，新目标改走人工通道 `POST /runs/{id}/goals`。
        auto_push_goals=auto_push_goals,
        # `False`：plan 也不自己判 done，栈空时改路由去 review 问人，
        # 只有人类的 STOP 才能真的结束 run。
        auto_decide_done=auto_decide_done,
    )
    run_harness = RunHarness(deps)

    return run_harness, trace, world, game
