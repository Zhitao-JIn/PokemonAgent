# pokemon_agent/experiment/run_episode.py

"""跑一个真实 episode —— LLM 控制宝可梦红。

    $env:DASHSCOPE_API_KEY = "sk-..."
    python -m pokemon_agent.experiment.run_episode 12 "向北走出真新镇" --state assets/rom.state
    python -m pokemon_agent.experiment.run_episode 30 "走出真新镇，向北进入一号道路" --state assets/rom.state
    python -m pokemon_agent.experiment.run_episode 30 "…" --watch --state assets/rom.state
    python -m pokemon_agent.experiment.run_episode 30 "…" --state none

⚠️ 单发入口：build 一次、跑一个 episode、关闭。多个目标/完整会话请走
   run 级入口 `python -m pokemon_agent.main <目标1> <目标2> …`。
⚠️ trace 落盘在 trace_data/ 下，同时也推流到控制台（见 pokemon_agent/trace/）。

单发调用：装配一次 harness/world/tools（`build_session()`），跑一个目标，`world.stop()`。
多目标的完整会话由 run 级 `RunHarness` 承担（目标栈驱动，main.py 入口）。
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
from datetime import datetime

from pokemon_agent.build import build_real
from pokemon_agent.schemas.domain import TaskForHarness

ROM = "assets/rom"
STATE = "assets/rom.state"


# 验证执行环境
def check_environment():
    """为直接短程入口准备 run_id；长程入口会提前设置它。"""
    if "CLAUDE_RUN_ID" not in os.environ:
        os.environ["CLAUDE_RUN_ID"] = f"short-{datetime.now().strftime('%m%d-%H%M%S')}"


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
# 早先 main() 把两件事焊在一起：每次调用都重新 build_real() 一遍
# （重开 ROM、重开窗口），跑完这一个 episode 就 world.stop() 关掉。
# 这对单发调用没问题，但连续跑多个目标时，结果就是**每完成一个任务，
# PyBoy 窗口就被关掉一次**——多目标的完整会话本该是"同一局游戏、连续
# 接受新目标"，不是"每个目标单开一局"。
#
# 拆成两半之后，装配只做一次，`world.stop()` 只在会话真正结束时调一次；
# `run_one()` 只管"在这个已经开着的世界上跑一个 episode"，不碰 world 的生死。
# （多目标会话的完整路径是 run 级 `RunHarness`，见 main.py。）


def build_session(run_id: str, state: str | None, watch: bool):
    """装配一次 harness/trace/world，供同一个会话内的多个 episode 复用。

    调用方负责在真正要结束这个会话时调 `world.stop()`——这个函数本身
    不会关闭任何东西。

    接好 world/trace/harness，返回可复用的一套。
    """
    if state is not None and not pathlib.Path(state).is_file():
        print(f"错误: 存档不存在：{state}")
        print("要从 ROM 开头跑请指定 --state none")
        sys.exit(1)
    os.environ["EPISODE_START_STATE"] = state or ""

    return build_real(
        ROM,
        state,
        # **感知走 max 不走 flash。** 实测证据在 `vision_dump/`：同一张 696×632 的图里
        # 指令框的光标三角清晰可见（人一眼可读、没被网格压住），flash 连着两次把它报成
        # 第一项 FIGHT——不是信息不足，是这个档位分辨不了 8×8 的小图元。
        # 换句话说这是**感知精度不够**，加 prompt、加分辨率都补不上
        # （选型决策记录见 `CHANGELOG.md` 2026-09-05 条目）。
        vision_model="qwen3.8-max",
        text_model="qwen-plus",
        max_tokens=25600,
        watch=watch,
    )


def run_one(harness, run_id: str, max_steps: int, goal: str) -> dict:
    """在一个已经建好的 run 级 harness 上跑一个 episode（单层目标栈）。

    不建、不关 world。`episode_id` 由 run 级 `dispatch` 生成（`{run_id}-ep1`）。
    """
    print(f"\n🔍 run_id={run_id}  目标: {goal}")

    task = TaskForHarness(
        task_id=f"t{hashlib.sha256(goal.encode()).hexdigest()[:8]}",
        goal=goal,
        success_criteria="画面上出现能直接证明目标已达成的证据",
        max_steps=max_steps,
    )

    print("\n" + "-" * 62)
    result = harness.run(run_id, [task])  # 单层栈：这一个目标 = 一个 episode
    outcome = result.outcomes[0]
    print(f"\n结果      success={outcome.success}  steps={outcome.steps}  reason={outcome.reason}")

    # 保存状态 (供下阶段使用)
    save_episode_state(run_id, f"assets/run_{run_id}.state")

    return {
        "success": outcome.success,
        "steps": outcome.steps,
        "reason": outcome.reason,
        "episode_id": outcome.episode_id,
    }


# 单发调用入口：build + 跑一个 + stop，全焊在一起。保留给"只想跑一次、
# 跑完就关"的直接调用场景；多目标会话请走 run 级入口 main.py。
def main():
    """解析命令行、装配一整套实现，跑一局并打印结果。"""
    # 1. 环境验证
    check_environment()
    run_id = os.environ["CLAUDE_RUN_ID"]

    # 2. 位置参数验证
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(positional) < 2:
        print("错误: 缺少必要参数")
        print(
            "用法: python -m pokemon_agent.experiment.run_episode <步数> <目标> [--state 存档] [--watch]"
        )
        sys.exit(1)

    max_steps = int(positional[0])
    goal = positional[1]

    # 3. 解析关键字参数
    watch = "--watch" in sys.argv
    state_flag = sys.argv[sys.argv.index("--state") + 1] if "--state" in sys.argv else STATE
    state = None if state_flag == "none" else state_flag

    # 4. 装配 + 跑一个 + 关闭
    harness, trace, world, tools = build_session(run_id, state, watch)
    try:
        return run_one(harness, run_id, max_steps, goal)
    finally:
        world.stop()


if __name__ == "__main__":
    main()
