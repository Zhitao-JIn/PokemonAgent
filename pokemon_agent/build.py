"""全项目唯一装配点：把所有具体实现 new 起来，拼成 RunHarness 与 world。

想知道"怎么拼起来"读这个文件；想知道"怎么互相调用"读 harness/run_harness.py。

**入口是 run 级**：返回的 `RunHarness` 是主 agent（完整一局游戏），内部
包着 `EpisodeHarness`（子 agent，解决栈顶一个目标）。旧调用方拿到的
`harness.run(run_id, goals)` 是 run 级签名。
"""

from __future__ import annotations

from pathlib import Path

from pokemon_agent.brain import Brain
from pokemon_agent.harness import EpisodeHarness, RunDataCenter, RunHarness
from pokemon_agent.interfaces import HumanReviewer
from pokemon_agent.providers import FastEmbedReranker, FastEmbedText
from pokemon_agent.tools import BrainTool, GameTools, MemoryTool, TraceTool
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
    from pokemon_agent.providers import ArkProvider, QwenProvider

    # temperature 钉死在 0：感知是抽取不是创作，同一张图两次读出不同结果是
    # 纯噪声（`QwenProvider` 不自带默认值，每次构造都要显式给，见该类
    # `__init__` 的 docstring）。
    vision = QwenProvider(model=vision_model, temperature=0.0)

    # PyBoy 模拟器 + 视觉感知的粘合层
    world = PyBoyWorld(rom, vision, state_path=state_file, watch=watch)

    # 一条事件一个 json 文件落盘（0910 重构，见 PLAN_memory_trace_layout §6）
    # + 内存表（SSE 端点直接轮询内存表，无推送钩子）
    data_center = data_center or RunDataCenter()
    trace = LocalTrace(
        run_id=run_id,
        resume_after_event_id=resume_cursor,
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

    # checkpoint 手（PLAN_checkpoint）：checkpoint 根目录独立于 trace 的落盘
    # 目录（0909 起不再是 trace_data 下的子目录，见 CheckpointTool 类
    # docstring）；trace_dir 仍然要给它——void_after() 截断 trace/截图要用。
    from pokemon_agent.tools import CheckpointTool

    checkpoint_tool = CheckpointTool(
        checkpoint_dir=Path("checkpoints") / run_id,
        trace_dir=Path("trace_data") / run_id,
        memory=memory,
    )

    # 决策走 DashScope（Qwen），判定/校验走火山方舟（豆包）——两条链路
    # 不同供应商。
    #
    # temperature 分层（0907 实测依据，见 CHANGELOG）：judge/verify/plan 是
    # 判定与结构化输出任务，确定性优先 → 0；decision 保留 0.3 的少量随机
    # （完全归零会让同一局面反复交出同一动作，探索多样性靠它兜底，
    # 死循环另有 stall 检测与 judge 兜底）。doubao 实测理睬 temperature
    # （temp=0 三次输出全同、temp=1 出现变化），不是被服务端强制覆盖的摆设。
    brain = Brain(
        decide_llm=QwenProvider(model=text_model, temperature=0.3, max_tokens=max_tokens),
        judge_llm=QwenProvider(model=judge_model, temperature=0.0, max_tokens=max_tokens),
        # verify（step 校验）单独一个 provider 实例（豆包 + 多帧拼接，见
        # `prompts/verify_and_summarize.py` 的 `stitch_frames`）——回退链只落
        # 豆包默认型号：judge_model 已换成 Qwen 型号名，传给 `ArkProvider`
        # 会 404，不能再作 verify/plan 的回退。
        verify_llm=ArkProvider(
            model=verify_model or "doubao-seed-2-1-pro-260628",
            temperature=0.0,
            max_tokens=max_tokens,
        ),
        # run 级规划器（plan_once）同样单独一个 provider 实例——回退链落
        # judge_model（跟 verify 同理）。这是同一个 `Brain` 实例的第四个技能，
        # 不是另开一条依赖：episode 内的决策和 run 级规划共享这一个大脑。
        plan_llm=ArkProvider(
            model=plan_model or "doubao-seed-2-1-pro-260628",
            temperature=0.0,
            max_tokens=max_tokens,
        ),
    )

    # harness 与大脑之间那层翻译壳：两跳契约独立维护，Brain 只在这里出现
    brain_tool = BrainTool(brain)

    # `data_center` 在这里先落实成一个真实例（不传就自己建一个）——
    # `EpisodeHarness`（human_note 槽）和 `RunHarness`（goals/review 两槽）
    # 必须共享同一个实例，缺一处这里落实就会各自新建一份、互不相干
    # （`RunHarness.__init__` 自己也有"不传就新建"的兜底，但那个兜底建出来的
    # 实例不会是 `EpisodeHarness` 手里这份，两边就断开了）。

    # 子 agent（一局）→ 主 agent（一个 run）：
    # 同一个 trace 实例注入两端——episode 写事件、run 级按类型 mask 读；
    # 同一个 data_center 实例注入两端——episode 消费 human_note 槽、run 级
    # 消费 goals/review 两槽。
    episode = EpisodeHarness(
        game,
        memory,
        brain_tool,
        trace_tool,
        run_id=run_id,
        data_center=data_center,
        checkpoint=checkpoint_tool,
    )
    run_harness = RunHarness(
        episode=episode,
        trace=trace_tool,
        # run 级规划：同一个 `BrainTool` 实例（`plan_once` 是 Brain 的第四个
        # 技能）——`RunHarness` 只认 `BrainToolPort`，跟 trace 的接线同一个模式。
        brain_tool=brain_tool,
        # human-in-the-loop：不传默认 AutoContinueReviewer；API 层注入阻塞式审查者。
        reviewer=reviewer,
        data_center=data_center,
        checkpoint=checkpoint_tool,
        # `False`：plan 不自动压栈，新目标改走人工通道 `POST /runs/{id}/goals`。
        auto_push_goals=auto_push_goals,
        # `False`：plan 也不自己判 done，栈空时改路由去 review 问人，
        # 只有人类的 STOP 才能真的结束 run。
        auto_decide_done=auto_decide_done,
    )

    return run_harness, trace, world, game
