"""用户本机串行采集 choose；仅显式运行 main 时装配真实链路。

从 worktree 根运行 python -m evals.dataset.brain_choose.build.collect
--state <原始.state> --goal <目标> --criteria <单帧判据> --steps N --out <新目录>。
先启动使用 ROM 的 world MCP server 和带 --enable-admin 的专用 memory MCP server，
设置 MCP_WORLD_SERVER_URL、MCP_MEMORY_SERVER_URL 与模型密钥。memory server 应为本次
采集新建的空库，本入口不会清空它。模型选择沿用 evals/config.json。
steps 是现有 harness 全局动作预算，含脚本内部按键；目标完成或其他生产终态可提前结束。
输出保留请求、响应、运行配置、trace、快照与结算，不删除采集产物。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from evals.common.brain_capture import record_brain_calls
from evals.common.overlay import eval_overlay, sample_overlay, write_overlay
from evals.common.recorder import RecordingChooser
from evals.paths import REPO_ROOT
from evals.runconfig import load_config
from pokemon_agent.brain.interface import Goal, Task
from pokemon_agent.build import build_real
from pokemon_agent.mcpclient.world_tool import WorldMcpTool

STATES_DIR = REPO_ROOT / "evals/agent_short_goal_run/dataset/v1/states"


def _release_world(game: WorldMcpTool) -> None:
    """正常或异常退出均归还租约；释放失败时保留原异常，不清理文件。"""
    active_error = sys.exception()
    try:
        game.release_lease()
    except Exception as release_error:
        if active_error is None:
            raise
        raise BaseExceptionGroup(
            "采集与 world 租约释放同时失败", [active_error, release_error]
        ) from None


def collect(
    state: Path, goal: str, criteria: str, steps: int, out: Path, *, all_calls: bool = False
) -> None:
    """从原始状态跑一次生产 harness，仅替换 task chooser 并设置动作预算。

    输入须为 states/ 内的 .state、非空目标与判据、正整数预算及不存在的输出目录；
    校验或服务失败显式抛出。装配成功后始终尝试归还 world 租约，产物原地保留。
    """
    state = state.resolve()
    if state.parent != STATES_DIR.resolve() or state.suffix != ".state" or not state.is_file():
        raise ValueError(f"--state 必须是 {STATES_DIR} 内的原始 .state 文件")
    if steps <= 0 or not goal.strip() or not criteria.strip():
        raise ValueError("--steps 必须为正整数，--goal 与 --criteria 必须非空")
    configuration = load_config()
    out.mkdir(parents=True, exist_ok=False)
    run_id = f"capture-choose-{uuid4().hex}"
    eval_config, _ = write_overlay(out / "config-eval.json", eval_overlay(configuration))
    sample_config, _ = write_overlay(
        out / "config-sample.json",
        {
            **sample_overlay(run_id=run_id, branch="main", work=out),
            "budget": {"max_total_actions": steps},
        },
    )
    harness, game = build_real(config=[eval_config, sample_config])
    try:
        if all_calls:
            record_brain_calls(harness.deps, out / "brain_calls")
        else:
            task_runtime = harness.deps.episode.task
            task_runtime.chooser = RecordingChooser(task_runtime.chooser, out)
        game.use_start_state(state)
        task = Task(task_id=run_id, goal=goal, success_criteria=criteria, max_steps=steps)
        result = harness.run(run_id, [task], run_goal=Goal(goal=goal, criteria=criteria))
        (out / "run_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    finally:
        _release_world(game)


def main(argv: list[str] | None = None) -> int:
    """解析五个必填参数后开始采集；--help 不装配服务、不调用模型。"""
    parser = argparse.ArgumentParser(
        prog="python -m evals.dataset.brain_choose.build.collect",
        description=__doc__,
    )
    parser.add_argument("--state", type=Path, required=True, help="states/ 内的原始 .state")
    parser.add_argument("--goal", required=True, help="目标文字")
    parser.add_argument("--criteria", required=True, help="单帧可判断的达成判据")
    parser.add_argument("--steps", type=int, required=True, help="全局动作预算，正整数")
    parser.add_argument("--out", type=Path, required=True, help="不存在的采集输出目录")
    parser.add_argument("--all-calls", action="store_true", help="按三层录制全部 brain Port")
    args = parser.parse_args(argv)
    if args.all_calls:
        collect(args.state, args.goal, args.criteria, args.steps, args.out, all_calls=True)
    else:
        collect(args.state, args.goal, args.criteria, args.steps, args.out)
    print(f"采集结束：{args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
