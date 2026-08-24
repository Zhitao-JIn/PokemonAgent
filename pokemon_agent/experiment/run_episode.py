# pokemon_agent/experiment/run_episode.py

"""跑一个真实 episode —— LLM 控制宝可梦红。

    $env:DASHSCOPE_API_KEY = "sk-..."
    python -m pokemon_agent.experiment.run_episode 12 "向北走出真新镇" --state assets/rom.state
    python -m pokemon_agent.experiment.run_episode 30 "走出真新镇，向北进入一号道路" --state assets/rom.state
    python -m pokemon_agent.experiment.run_episode 30 "…" --watch --state assets/rom.state
    python -m pokemon_agent.experiment.run_episode 30 "…" --state none

⚠️ 本文件必须被 run_episode_loop.py 调用，不能直接执行
⚠️ trace 落盘在 trace_data/ 下，同时也推流到控制台（见 pokemon_agent/trace/）。

`run_episode_loop.py` 现在只在会话开始时装配一次 harness/world
（`build_session()`），同一个 PyBoy 窗口在整个交互会话里跑完一个又一个目标，
`world.stop()` 只在整个会话真正结束时调一次——不再是"每问完一个目标就关窗口、
下一个目标再重开一局"。`main()` 保留作为单发调用入口（build + 跑一个 + 关），
不是循环器现在走的路径。
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
from datetime import datetime

from pokemon_agent.build import build_real
from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.task import Task
from pokemon_agent.schemas.trace import EventType, Source
from pokemon_agent.trace.store import LocalTrace
from pokemon_agent.trace.browser import BrowserTraceServer

try:
    from pokemon_agent.trace.index import EpisodeIndex
except ImportError:
    # `pokemon_agent/trace/index.py` 还不存在（只有 run_episode_loop.py 里的
    # 占位实现），先兜底成"永远唯一"，不阻塞跑局。真正的去重索引是"阶段 2"落盘
    # 之后的事——见 run_episode_loop.py 顶部同名的 fallback。
    class EpisodeIndex:
        @classmethod
        def is_unique(cls, episode_id: str, run_id: str) -> bool:
            return True

        @classmethod
        def register(cls, episode_id: str, run_id: str) -> None:
            pass

        @classmethod
        def clean_incomplete_episodes(cls, run_id: str) -> None:
            pass

ROM = "assets/rom"
STATE = "assets/rom.state"


# 验证执行环境
def check_environment():
    """确保本文件由 run_episode_loop 调用"""
    if "CLAUDE_RUN_ID" not in os.environ:
        print("\n" + "="*50)
        print("⚠️ 严重错误: 缺少 CLAUDE_RUN_ID 环境變量")
        print("="*50)
        print("原因: 任务阶段必须通过 run_episode_loop.py 启动")
        print("      直接运行会导致实验数据断裂")
        print("\n正确的启动方式:")
        print("  python -m pokemon_agent.experiment.run_episode_loop <steps> <goal> [--state PATH] [--watch]")
        print("  (例如: python -m pokemon_agent.experiment.run_episode_loop 5 '向北走出真新镇' --state assets/pallet.state)")
        print("="*50)
        sys.exit(1)


# 生成唯一 episode_id
def generate_episode_id(run_id: str) -> str:
    """生成全局唯一且可读的 episode_id"""
    timestamp = datetime.now().strftime("%H%M%S%f")[:-3]  # 精确到毫秒
    base_id = f"{run_id}-ep{timestamp}"
    counter = 1
    while not EpisodeIndex.is_unique(base_id, run_id):
        base_id = f"{run_id}-ep{timestamp}-{counter}"
        counter += 1
    return base_id


# 更新状态文件以便下阶段使用
def save_episode_state(run_id: str, source_path: str) -> None:
    """保存当前状态供后续阶段使用"""
    if not source_path or not pathlib.Path(source_path).exists():
        return

    target = pathlib.Path(f"assets/run_{run_id}.state")
    try:
        # 确保目录存在
        target.parent.mkdir(exist_ok=True)
        # 备份现有文件 (如有)
        if target.exists():
            target.rename(f"{target}.backup")
        # 创建新文件
        with open(source_path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
    except Exception as e:
        print(f"❌ 无法保存状态文件: {e}")


# 建一次、跑多个 episode 共用：把"装配 harness/world"和"跑一个 episode"拆开
#
# 早先 main() 把两件事焊在一起：每次被 run_episode_loop.py 调用都重新
# build_real() 一遍（重开 ROM、重开窗口），跑完这一个 episode 就 world.stop()
# 关掉。这对单发调用没问题，但被循环器每问一个新目标就调一次 main()，
# 结果就是**每完成一个任务，PyBoy 窗口就被关掉一次**——循环器的本意是
# "同一局游戏、连续接受新目标"，不是"每个目标单开一局"。
#
# 拆成两半之后，装配只在会话开始时做一次，`world.stop()` 只在整个会话
# （所有目标问完、用户输入 exit、或 Ctrl+C）结束时调一次；`run_one()` 只管
# "在这个已经开着的世界上跑一个 episode"，不碰 world 的生死。


def build_session(run_id: str, state: str | None, watch: bool):
    """装配一次 harness/trace/world，供同一个会话内的多个 episode 复用。

    调用方负责在真正要结束这个会话时调 `world.stop()`——这个函数本身
    不会关闭任何东西。
    """
    if state is not None and not pathlib.Path(state).is_file():
        print(f"错误: 存档不存在：{state}")
        print("要从 ROM 开头跑请指定 --state none")
        sys.exit(1)
    os.environ["EPISODE_START_STATE"] = state or ""

    browser = BrowserTraceServer()
    browser.start()
    print(f"[INFO] 浏览器观测台: {browser.url}")
    return build_real(
        ROM,
        state,
        vision_model="qwen3-vl-flash",
        text_model="qwen-plus",
        judge_model="qwen-plus",
        grid="on",
        max_tokens=25600,
        watch=watch,
        trace=LocalTrace(run_id=run_id, sse_sink=browser.publish),
    )


def run_one(harness, run_id: str, max_steps: int, goal: str) -> dict:
    """在一个已经建好的 harness 上跑一个 episode。不建、不关 world。"""
    episode_id = generate_episode_id(run_id)
    _snapshot_episode_start(run_id, episode_id)
    print(f"\n🔍 实验标识: run_id={run_id}, episode_id={episode_id}")
    print(f"   • 目标: {goal}")

    task = Task(
        task_id=f"t{hashlib.sha256(goal.encode()).hexdigest()[:8]}",
        goal=goal,
        success_criteria="画面上出现能直接证明目标已达成的证据",
        max_steps=max_steps,
    )

    print("\n" + "-" * 62)
    try:
        result = harness.run(episode_id, task)
        outcome = {"success": result.success, "steps": result.steps, "reason": result.reason}
        print(f"\n结果      success={outcome['success']}  steps={outcome['steps']}  "
              f"reason={outcome['reason']}")
    except AgentError as e:
        print(f"\n提前终止：{type(e).__name__}: {e}")
        outcome = {"success": False, "steps": 0, "reason": str(e)}

    # 保存状态 (供下阶段使用)
    save_episode_state(run_id, f"assets/run_{run_id}.state")

    return {**outcome, "episode_id": episode_id}


def _snapshot_episode_start(run_id: str, episode_id: str) -> None:
    """保存本 episode 实际使用的起点存档；replay/resume 不能只依赖 run 级存档。"""
    configured = os.environ.get("EPISODE_START_STATE", "")
    source = pathlib.Path(configured) if configured else pathlib.Path(f"assets/run_{run_id}.state")
    if not source.is_file():
        source = pathlib.Path(STATE)
    if not source.is_file():
        return
    target = pathlib.Path("trace_data") / run_id / "episodes" / f"{episode_id}.start.state"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


# 单发调用入口：build + 跑一个 + stop，全焊在一起。保留给"只想跑一次、
# 跑完就关"的直接调用场景；run_episode_loop.py 现在改走上面 build_session()
# + run_one() 那条路径，不再经过这里。
def main():
    # 1. 环境验证
    check_environment()
    run_id = os.environ["CLAUDE_RUN_ID"]

    # 2. 位置参数验证
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(positional) < 2:
        print("错误: 缺少必要参数")
        print("用法: 由run_episode_loop.py内部调用")
        sys.exit(1)

    max_steps = int(positional[0])
    goal = positional[1]

    # 3. 解析关键字参数
    watch = "--watch" in sys.argv
    state_flag = sys.argv[sys.argv.index("--state") + 1] if "--state" in sys.argv else STATE
    state = None if state_flag == "none" else state_flag

    # 4. 装配 + 跑一个 + 关闭
    harness, trace, world = build_session(run_id, state, watch)
    try:
        return run_one(harness, run_id, max_steps, goal)
    finally:
        world.stop()
