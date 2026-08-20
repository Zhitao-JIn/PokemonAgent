"""跑一个真实 episode —— LLM 控制宝可梦红。

    $env:DASHSCOPE_API_KEY = "sk-..."
    python -m probe.run_episode                                  # 12 步，无头
    python -m probe.run_episode 30 "走出真新镇，向北进入一号道路"
    python -m probe.run_episode 30 "…" watch                      # 开窗口看着它玩
    python -m probe.run_episode 30 "…" --state assets/route1.state --task-id t_route1
    python -m probe.run_episode 30 "…" --state none               # 从 ROM 开头跑

**默认无头**（`window="null"`）：跑实验时墙钟是瓶颈，开窗口和限速只会拖慢。
`watch` 只影响你看不看得见，不影响 agent 行为——它读的是 `screen.ndarray`。

⚠ 别同时开着 `probe.play`：两个 PyBoy 实例共用同一个 ROM 时，
退出时都会写 `assets/rom.ram`，后退出的覆盖先退出的。

每步会打印：观测摘要、可用动作、大脑选了什么、为什么。
结束后汇总感知与决策**各自**的 token —— 这两笔账拆得开，
是「感知走便宜模型、决策走强模型」这条成本叙事的依据。

⚠ trace 是内存里的，进程一退就没了。落盘是阶段 2 的事。
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
from datetime import datetime

from pokemon_agent.build import build_real
from pokemon_agent.errors import AgentError
from pokemon_agent.mocks.mock_trace import MockTrace
from pokemon_agent.schemas.core import EventType, Source, Task
from probe.echo_trace import EchoTrace

ROM = "assets/rom"
STATE = "assets/rom.state"
"""默认存档。**用 `--state` 换掉它。**

存档就是**任务的起点**：想让 agent 从"已经站在一号道路上"开跑，
就存一个那儿的档、`--state` 指过去，用不着改任何代码。

这也是唯一能让两批数据可比的办法——同一个 `task_id` 下的多次尝试，
起点不同的话成功率就没有意义。**存档要和 `--task-id` 一起看**：
换了存档就该换 task_id，否则两个不同的任务被聚合成了一个数。

`--state none` = 不加载存档，从 ROM 开头跑（开场动画、命名流程都得自己过）。
"""


def _flag(name: str, default: str) -> str:
    """从 `--name value` 里取值。写个小函数而不是上 argparse：

    这是 probe 脚本，参数就三四个，argparse 的帮助信息和错误处理反而喧宾夺主。
    """
    argv = sys.argv[1:]
    if name not in argv:
        return default
    i = argv.index(name) + 1
    return argv[i] if i < len(argv) else default


def main() -> None:
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    # 跳过被 --flag 消费掉的那些值
    consumed = {sys.argv[1:][i + 1] for i, a in enumerate(sys.argv[1:])
                if a.startswith("--") and i + 1 < len(sys.argv) - 1}
    positional = [a for a in positional if a not in consumed]

    max_steps = int(positional[0]) if positional else 12
    goal = positional[1] if len(positional) > 1 else "探索周围环境，向北走出真新镇"
    watch = "watch" in positional[2:]

    vision_model = _flag("--vision", "qwen3-vl-plus")
    text_model = _flag("--text", "qwen-plus")
    grid = _flag("--grid", "on") == "on"
    judge_model = _flag("--judge", "")   # 空 = 和决策同型号
    # **上限不是预算**：只在模型自己想说这么多时才花得掉。
    # 被 API 拒了（各家对 max_tokens 有硬上限）就调低这个数。
    max_tokens = int(_flag("--max-tokens", "25600"))
    # `none` 明确表示"不要存档"。用空串表示的话，它和"这个 flag 没写"
    # 分不开，而那两件事的结果差着一整段开场动画。
    state_flag = _flag("--state", STATE)
    state = None if state_flag == "none" else state_flag
    # **早失败。** 路径打错时 PyBoy 要么静默从头跑、要么在几十行
    # 初始化日志之后才炸，两种都会浪费一整局才发现起点根本不对。
    if state is not None and not pathlib.Path(state).is_file():
        raise SystemExit(f"存档不存在：{state}（要从 ROM 开头跑就写 --state none）")

    task = Task(
        # **task_id 不能写死。** 它是成功率的分组键：写死的话，命令行换了目标
        # 跑出来的两批数据会被当成同一个任务聚合，算出来的成功率没有意义。
        # 默认从目标文本派生（同一个目标 = 同一个 task_id，跨进程稳定），
        # 想手动指定就用 --task-id。
        task_id=_flag("--task-id", f"t{hashlib.sha256(goal.encode()).hexdigest()[:8]}"),
        goal=goal,
        # **默认判据是同义反复**（"出现证据"没说是什么证据），只够跑通链路。
        # 真做实验必须用 --criteria 给一句**只看一帧就能判真假**的话，
        # 否则判定器只能凭"看起来差不多了"回答，成功率就不可信。
        success_criteria=_flag("--criteria", "画面上出现能直接证明这个目标已达成的证据"),
        max_steps=max_steps,
    )

    # 实时打印挂在 trace 上，不往图节点里塞 print：
    # 实时观测和事后 replay 看的是同一份数据，不会出现「只有控制台有」的信息。
    # id 规则：
    #   run_id      一次进程调用，时间戳
    #   episode_id  run_id + 序号，**全局唯一**
    #   event_id    trace 分配的全局自增整数
    run_id = datetime.now().strftime("%m%d-%H%M%S")
    episode_id = f"{run_id}-ep0"

    harness, trace, world = build_real(
        ROM, state,
        vision_model=vision_model, text_model=text_model,
        judge_model=judge_model, grid=grid, max_tokens=max_tokens,
        watch=watch, trace=EchoTrace(MockTrace(run_id=run_id)),
    )
    print(f"task      {goal}")
    print(f"criteria  {task.success_criteria}")
    print(f"episode   {episode_id}")
    # **模型必须打出来。** 换模型对比时，日志上不写型号，两份输出摆在一起
    # 就分不清哪份是哪个跑的——而那正是做对比的全部目的。
    print(f"models    vision={vision_model}  text={text_model}  "
          f"judge={judge_model or text_model}  grid={'on' if grid else 'off'}  "
          f"max_tokens={max_tokens}")
    print(f"limit     {max_steps} steps | state {state or 'none（从 ROM 开头）'} | "
          f"{'windowed, realtime' if watch else 'headless, unlimited'}")
    print("-" * 62)

    try:
        outcome = harness.run(episode_id, task)
        print(f"\n结果      success={outcome.success}  steps={outcome.steps}  "
              f"reason={outcome.reason}")
    except AgentError as e:
        print(f"\n提前终止：{type(e).__name__}: {e}")
    finally:
        world.stop()

    _summary(trace.all_events())


def _summary(events: list) -> None:
    """从 trace 里读汇总，而不是让脚本自己记账。

    这一段以前是照着旧 schema 写的（`payload["source"]`、`EventType.COST`、
    `prompt_tokens`），schema 改了它没跟着改，于是**跑完一整局才在最后一行崩掉**——
    十几次模型调用的钱已经花完了。
    汇总要按信封字段（`e.source` / `e.type`）读，那是契约的一部分；
    payload 的键是各事件类型自己的事，最容易漂。
    """
    calls = [e for e in events if e.type is EventType.MODEL_CALL]

    print("\n" + "=" * 62)
    for src, label in ((Source.PERCEPTION, "perception"),
                       (Source.DECISION, "decision"),
                       (Source.JUDGE, "judge")):
        rows = [e for e in calls if e.source is src]
        if not rows:
            continue
        n_in = sum(int(e.payload.get("input_tokens", 0)) for e in rows)
        n_out = sum(int(e.payload.get("output_tokens", 0)) for e in rows)
        lat = [int(e.payload["latency_ms"]) for e in rows if "latency_ms" in e.payload]
        # 失败的调用同样烧了钱，所以单独报一列——只看总数会以为每次都有产出
        failed = sum(1 for e in rows if e.payload.get("ok") != "True")
        print(f"{label:<12} {len(rows):>3} 次（失败 {failed}）  "
              f"in={n_in:<7} out={n_out:<6} 平均 {sum(lat) // max(len(lat), 1)} ms")
    print("             ↑ perception 含细看（inspect 走的是同一个视觉模型，另一份 prompt）")

    # **三类动作各用了多少**，以及拆出来的子目标有多少是白拆的。
    # 这是目标栈和细看这两个机制唯一的直接证据：拆十条弹十条看着很好看，
    # 但如果八条是 superseded（父目标先成了，它跟着作废），那说明它在乱拆不是在规划。
    pressed = sum(1 for e in events if e.type is EventType.ACT)
    looked = sum(1 for e in events if e.type is EventType.INSPECT)
    pushed = sum(1 for e in events if e.type is EventType.GOAL_PUSH)
    pops = [e.payload.get("reason", "?") for e in events if e.type is EventType.GOAL_POP]
    print(f"动作         按键 {pressed} · 细看 {looked} · 拆子目标 {pushed}"
          f"（完成 {pops.count('done')} / 作废 {pops.count('superseded')}）")

    errors: dict[str, int] = {}
    for e in events:
        if e.type is EventType.ERROR:
            errors[e.payload.get("kind", "?")] = errors.get(e.payload.get("kind", "?"), 0) + 1
    if errors:
        print("失败模式     " + "  ".join(f"{k}×{v}" for k, v in sorted(errors.items())))
    print(f"事件         {len(events)} 条")


if __name__ == "__main__":
    main()
