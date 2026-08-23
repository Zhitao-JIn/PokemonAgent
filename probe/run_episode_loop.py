# probe/run_episode_loop.py

"""循环执行器：人类引导式长程任务

用法:
  python -m probe.run_episode_loop <步数> [--state <存档>] [--watch]

交互命令:
- 输入目标描述: 每次运行指定独立任务目标
- exit: 退出循环
- Ctrl+C: 优雅终止
"""
import sys
import os
import time
import hashlib
import traceback
from pathlib import Path
from datetime import datetime

# 本地导入 (避免循环依赖)
sys.path.insert(0, str(Path(__file__).parent.parent))
from probe.run_episode import build_session, run_one

try:
    from pokemon_agent.trace.index import EpisodeIndex
except ImportError:
    # Fallback for standalone execution
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

STORAGE_ROOT = Path("trace_data")

# 测试模式标识
IS_TEST_MODE = "--test" in sys.argv
TEST_GOALS = [
    "向北走出真新镇",
    "击败尼比道馆馆主",
    "收集5个精灵球"
]


def generate_run_id() -> str:
    """生成 run_id - 会话级别唯一标识"""
    if "--run-id" in sys.argv:
        idx = sys.argv.index("--run-id") + 1
        if idx < len(sys.argv) and not sys.argv[idx].startswith("--"):
            return sys.argv[idx]


    # 自动创建唯一 run_id
    timestamp = time.strftime("%m%d-%H%M%S")
    entropy = hashlib.sha256(f"{time.time()}{os.urandom(8)}".encode()).hexdigest()[:6]
    return f"{timestamp}-{entropy}"


def get_next_goal(run_id: str, previous_goal: str | None = None) -> str | None:
    """获取用户输入的下一个目标"""
    # 测试模式 (自动提供目标)
    if IS_TEST_MODE:
        if previous_goal is None:
            print(f"[AUTO] 使用测试目标: {TEST_GOALS[0]}")
            return TEST_GOALS[0]
        elif previous_goal == TEST_GOALS[-1]:
            print(f"[AUTO] 已完成所有测试目标，终止会话")
            return None
        else:
            try:
                current_idx = TEST_GOALS.index(previous_goal)
                next_idx = current_idx + 1
                if next_idx < len(TEST_GOALS):
                    print(f"[AUTO] 下一测试目标: {TEST_GOALS[next_idx]}")
                    return TEST_GOALS[next_idx]
            except ValueError:
                pass
        return None

    # 交互模式 (需要人工输入)
    if not sys.stdin.isatty():
        print("\n[ERROR] 脚本需要在交互式终端中运行")
        print("原因：需要等待用户输入新目标")
        print("请在命令行中直接运行，而不是通过管道/重定向")
        print("例如：python -m probe.run_episode_loop 5 --state assets/pallet.state")
        sys.exit(1)

    print("\n" + "="*50)
    print("[GOAL] 任务输入")
    print("="*50)

    if previous_goal:
        print(f" - 已完成: {previous_goal}")
        print(" - 请指定接下来的行动")
    print("- 示例:")
    print("  * '向北走出真新镇'")
    print("  * '击败尼比道馆馆主'")
    print("  * '收集10个精灵球'")
    print("="*50)

    try:
        goal = input(" > ").strip()
    except EOFError:
        print("\n[ERROR] 输入流已终止。")
        print("此脚本需要在交互式终端中运行，而非通过管道或重定向。")
        sys.exit(1)

    if not goal or goal.lower() in ["exit", "quit", "stop"]:
        return None

    # 目标描述长度检查
    if len(goal) > 50:
        print("⚠️ 目标描述限50字内，自动截断")
        goal = goal[:50]

    return goal


def get_state_path() -> str | None:
    """获取正确的状态文件路径"""
    # 检查 --state 参数
    for i, arg in enumerate(sys.argv):
        if arg == "--state" and i + 1 < len(sys.argv):
            state_path = sys.argv[i + 1]
            # 明确指定"none"表示从ROM开头
            if state_path == "none":
                return None
            return state_path

    # 没有--state参数时使用默认存档
    return "assets/pallet.state"


def get_watch() -> bool:
    """是否开窗口——整场会话只读这一次，装配时定，中途不会变。"""
    return "--watch" in sys.argv


def get_max_steps() -> int:
    """每个 episode 的步数上限，来自命令行第一个位置参数（整场会话共用一个）。"""
    return int(sys.argv[1])


def save_progress(run_id: str, goal: str, outcome: dict) -> None:
    """记录进度到日志"""
    log_path = STORAGE_ROOT / run_id / "progress.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(f"{time.time():.0f}|{goal}|{outcome['steps']}|{outcome['success']}|{outcome['reason']}\n")


def report_final_summary(run_id: str, completed: list) -> None:
    """生成最终报告"""
    print("\n" + "=" * 50)
    print("[REPORT] 任务总结")
    print(f"Run ID: {run_id}")
    print("-"*50)

    # 计算总成功率
    total = len(completed)
    success = sum(1 for _, succ in completed)

    print(f"共完成 {total} 个阶段")
    print(f"整体成功率: {success}/{total} ({success/total:.0%})")
    print("-"*50)

    for i, (goal, outcome) in enumerate(completed):
        status = "[OK]" if outcome['success'] else "[FAILED]"
        steps = outcome['steps']
        reason = outcome['reason']
        print(f"{i+1}. {status} {goal} (步数: {steps}, 原因: {reason[:20]}{'...' if len(reason)>20 else ''})")

    print("-"*50)
    print(f"实验数据位置: trace_data/{run_id}")


def should_exit() -> bool:
    """检查是否应该退出"""
    return 'EXIT_REQUESTED' in os.environ and os.environ['EXIT_REQUESTED'] == '1'


def run_session():
    """运行主会话"""
    # 1. 生成会话run_id (单次)
    RUN_ID = generate_run_id()

    print(f"\n[INFO] 任务引导会话 | run_id={RUN_ID}")
    print(f"   * 实验数据保存至: trace_data/{RUN_ID}")
    print("   * 每次运行需要指定独立任务目标")

    # 2. 初始化状态（state/watch/max_steps 整场会话只读一次——装配只做一次，
    #    不再是"每问一个新目标就重新拼一遍命令行参数、重新 build 一局"）
    os.environ["CLAUDE_RUN_ID"] = RUN_ID
    state_path = get_state_path()
    watch = get_watch()
    max_steps = get_max_steps()
    completed = []
    attempts = 0

    # 3. 获取第一个目标
    current_goal = get_next_goal(RUN_ID)
    if not current_goal:
        return

    # 4. 装配一次 harness/world——同一个 PyBoy 窗口跑完整场会话的所有目标，
    #    不会因为某一个目标完成了就把窗口关掉。真正关闭放在 finally 里，
    #    覆盖正常退出、异常、以及 Ctrl+C 三条路径。
    harness, trace, world = build_session(RUN_ID, state_path, watch)

    try:
        # 5. 开始主循环
        while current_goal and not should_exit():
            attempts += 1
            print(f"\n[ATTEMPT] 尝试 #{attempts} | 目标: '{current_goal}'")

            try:
                outcome = run_one(harness, RUN_ID, max_steps, current_goal)

                if outcome.get("success", False):
                    print(f"\n[SUCCESS] 成功完成 | 步数: {outcome['steps']}")
                    print(f"   * 原因: {outcome.get('reason', '无')}")
                else:
                    print(f"\n[WARNING] 未能完成 | 步数: {outcome['steps']}")
                    print(f"   * 原因: {outcome.get('reason', '无')}")

                # 跟踪完成目标
                completed.append((current_goal, outcome))
                save_progress(RUN_ID, current_goal, outcome)

            except Exception as e:
                print(f"\n[ERROR] 执行失败: {type(e).__name__}: {e}")
                traceback.print_exc()

            # 6. 获取下一个目标——这一步不成功（非交互终端 / EOF）不该
            #    把整个会话带崩：已经开着的这一局仍然是有效状态，只是拿不到
            #    新目标了，按"结束这场会话"处理，走到 finally 正常收尾。
            current_goal = get_next_goal(RUN_ID, previous_goal=current_goal)

        # 7. 输出汇总
        report_final_summary(RUN_ID, completed)
    finally:
        world.stop()


def setup_signal_handlers():
    """设置信号处理器"""
    import signal
    def signal_handler(signum, frame):
        print(f"\n\n[INFO] 正在保存当前实验数据... (信号: {signum})")
        os.environ['EXIT_REQUESTED'] = '1'
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# 入口
if __name__ == "__main__":
    # 检查trace_data目录是否存在
    if not os.path.exists("trace_data"):
        os.makedirs("trace_data", exist_ok=True)

    # 设置信号处理
    setup_signal_handlers()
    os.environ.pop('EXIT_REQUESTED', None)

    # 处理测试模式
    if "--test" in sys.argv:
        IS_TEST_MODE = True
        sys.argv = [a for a in sys.argv if a != "--test"]
        print("[AUTO] 已启用测试模式 - 自动提供任务目标")
    else:
        IS_TEST_MODE = False

    # 验证参数
    if len(sys.argv) < 3:
        print("用法: python -m probe.run_episode_loop <步数> [--state <存档>] [--watch]")
        print("示例: python -m probe.run_episode_loop 20 \"向北走出真新镇\" --state assets/pallet.state")
        sys.exit(1)


    # 调试输出
    print(f"[DEBUG] 参数列表: {sys.argv}")

    try:
        run_session()
    except Exception as e:
        print(f"\n[ERROR] 系统错误: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)