"""装配 —— **全项目唯一一处 `new` 具体实现**（CLAUDE.md 第三节第 3 条）。

想知道"这套东西是怎么拼起来的"，只需要读这一个文件；
想知道"它们怎么互相调用"，读 `harness/harness.py`。这两件事分开放，
是因为上一版把它们塞在同一个 `graph/build.py` 里，看上去就像图认识 LLM。

    Harness  控制循环   ──→ GameToolPort ──→ WorldPort ──→ PyBoyWorld ──→ VisionProvider
                        └─→ MemoryToolPort ──→ memory/（语义记忆）
                        └─→ BrainPort ──→ LLMProvider
                        └─→ TracePort

图里没有一行碰得到 provider：它们是构造函数传进去的，只有这里 import 具体类。

曾经还有一个 `build_demo`（MockWorld + FakeLLM，离线跑最小闭环），
真实环境接进来之后已删除——留着两条装配路径，等于留着一条**没人真的跑**的代码路径。
"""

from __future__ import annotations

from pathlib import Path

from pokemon_agent.brain.brain import Brain
from pokemon_agent.harness.harness import Harness
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.tools.game_tools import GameTools
from pokemon_agent.tools.memory_tool import MemoryTool
from pokemon_agent.providers.local_embedding import FastEmbedText
from pokemon_agent.providers.local_reranker import FastEmbedReranker
from pokemon_agent.trace.store import LocalTrace
from pokemon_agent.world.pyboy_world import PyBoyWorld


def build_real(
    rom: str,
    state_path: str | None = None,
    *,
    vision_model: str = "qwen3-vl-plus",
    text_model: str = "qwen-plus",
    judge_model: str = "",
    memory_model: str = "",
    max_tokens: int = 25600,
    watch: bool = False,
    grid: bool = True,
    trace: TracePort | None = None,
    run_id: str = "local",
) -> tuple[Harness, TracePort, PyBoyWorld]:
    """装配真实的一套：PyBoy + 视觉感知 + 真实 LLM + 循环。

    三个模型是刻意分开的，不是设计洁癖——它由计费结构和实验方法共同决定：

    - **决策**走有资源包的文本模型；
    - **感知**每步都调、任务简单，走最便宜的视觉模型；
    - **判定**必须和决策分开，否则就是误差同源（见 `brain/brain.py`）。
      即使型号相同也**各建一个 provider 实例**：共用一个的话，将来想给判定
      换模型就得改两处，而且 manifest 里两条链路会指向同一个对象，
      看不出它们是可以分别选型的。

    trace 仍是 `LocalTrace`（本地事件列表 + JSONL）。
    是阶段 2 的事；在那之前跑出来的数据**进程一退就没了**，只适合调试。

    `run_id` 默认和 `LocalTrace(run_id="local")` 的默认值对齐——**这里没有单一
    真相来源**：`TracePort` 的实现自己持有一份 `run_id`（不对外暴露），
    `Harness` 另外持有一份用来标 `EpisodeMemory.run_id`。传自定义 `trace` 时
    记得把这里的 `run_id` 也传成同一个值，否则两处对不上。

    返回 world 是为了让调用方能 `stop()` 它——模拟器是进程级资源，
    谁开的谁关，Harness 不该管这件事。
    """
    from pokemon_agent.providers.dashscope import QwenText, QwenVision
    from pokemon_agent.vision.preprocess import GridOverlay

    # 网格是**给模型看的辅助线**，不是画面的一部分——所以它挂在 provider 上，
    # world 交出去的、存证用的、将来给 CV 通道用的，仍然是原图。
    vision = QwenVision(model=vision_model, preprocess=(GridOverlay(),) if grid else ())
    world = PyBoyWorld(rom, vision, state_path=state_path, watch=watch)
    trace = trace or LocalTrace()

    game = GameTools(world)
    # 跨局摘要记忆的蒸馏（`EpisodeMemoryGenerator`）也要一个文本模型——独立建一个
    # `QwenText` 实例，不借用 `decide_llm`：即使型号相同，理由和判定器分开建
    # 是一样的（见下面 `Brain` 那句注释）——manifest 里要能看出这条链路是可以
    # 单独换模型/调 max_tokens 的，共用一个实例就看不出来了。
    memory = MemoryTool(
        trace_port=trace,
        llm_provider=QwenText(model=memory_model or text_model, max_tokens=max_tokens),
        embedding_provider=FastEmbedText(),
        reranker_provider=FastEmbedReranker(),
    )
    # brain 拿不到 trace，也拿不到 tools/memory —— **写 trace 是 Harness 一个人的事，
    # 检索记忆也是**。大脑把账（ModelCall）连同结果交出来，由 Harness 翻译成事件。
    # 两条链路共用同一个 max_tokens 上限。判定每次只输出二三十个 token，
    # 抬高上限对它没有影响；分开配置只会多一个没人调的旋钮。
    brain = Brain(
        decide_llm=QwenText(model=text_model, max_tokens=max_tokens),
        judge_llm=QwenText(model=judge_model or text_model, max_tokens=max_tokens),
    )
    # `game` 只碰 world，`memory` 只碰记忆——两个互不相识的对象，
    # 组合是 `Harness` 的事，见 `interfaces/tools.py` 顶部说明。
    #
    # `Harness` 拿到的是裸的 `TracePort`——组装 payload 是 `trace/utils.py`
    # 里那堆纯函数的事（`Harness` 调用它们，自己不拼 `dict`），落地/推流是
    # `TracePort` 具体实现（这里是 `LocalTrace`）的事。返回值里的 `trace`
    # 和 `Harness` 手上那个是同一个对象，调用方可以直接用它做 `all_events()`
    # 这类调试查询。
    return Harness(
        game, memory, brain, trace, run_id=run_id,
        episode_state_dir=Path("trace_data") / run_id / "episodes",
    ), trace, world
