"""按仓库现有 state 启动一个可复现实验任务。"""

from __future__ import annotations

import argparse
import pathlib
import uuid
from datetime import datetime

from pokemon_agent.experiment.manifest import RunManifest
from pokemon_agent.experiment.tasks import TaskChain, knowledge_recall_tasks


STATE_ROOT = pathlib.Path("pokemon_agent/experiment/experiment_states/knowledge")


def state_for_task(task_id: str) -> pathlib.Path:
    """按任务类别选择当前仓库已有的基础 state。"""
    path = STATE_ROOT / f"{task_id}.state"
    assert path.is_file(), f"experiment state is missing: {path}"
    return path


def main() -> None:
    """解析命令行、写下 manifest，然后跑一个 knowledge 短程实验。"""
    parser = argparse.ArgumentParser(description="运行一个 knowledge 短程实验")
    parser.add_argument("--task-id", help="任务 id；不填时列出任务")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="同一个任务重复跑几遍（每遍都是独立的一次 run：独立的 run_id、"
             "独立的 manifest、从同一个 state 重新开局）",
    )
    args = parser.parse_args()

    # 命令行是**外部输入**，走 parser.error（退出码 2 + 用法提示），不用 assert：
    # assert 在 `python -O` 下会被删掉，而这个校验删不得。
    if args.repeat < 1:
        parser.error(f"--repeat 至少是 1，收到 {args.repeat}")

    chains = {chain.chain_id: chain for chain in knowledge_recall_tasks(args.max_steps)}
    if not args.task_id:
        for chain in chains.values():
            task_names = " -> ".join(task.task_id for task in chain.tasks)
            print(f"{chain.chain_id}\t{task_names}")
        return
    assert args.task_id in chains, f"unknown task_id: {args.task_id}"
    chain = chains[args.task_id]
    state = state_for_task(chain.initial_task.task_id)

    base_run_id = args.run_id or f"{datetime.now().strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    outcomes = []
    for repetition in range(1, args.repeat + 1):
        # 重复只有一遍时 run_id 原样不变——`--run-id` 是拿来指名道姓找这一跑的
        # 数据的（测试就这么用），给它加后缀等于让那条路径失效。
        run_id = base_run_id if args.repeat == 1 else f"{base_run_id}-r{repetition}"
        if args.repeat > 1:
            print(f"\n[EXPERIMENT] 第 {repetition}/{args.repeat} 遍  run_id={run_id}")
        outcomes.append(run_chain(chain, run_id, state, args.watch))

    if args.repeat > 1:
        succeeded = sum(1 for outcome in outcomes if outcome["success"])
        print(f"\n[EXPERIMENT] {chain.chain_id} 跑了 {args.repeat} 遍，"
              f"成功 {succeeded} 遍（{succeeded / args.repeat:.0%}）")


def run_chain(
    chain: TaskChain, run_id: str, state: pathlib.Path, watch: bool
) -> dict[str, object]:
    """跑完一条任务链，返回这一遍的结果。

    **每一遍都是一次完整独立的 run**：自己的 manifest、自己的 trace 目录、
    自己新建又关掉的 world。不复用上一遍的 harness/world——重复实验要的就是
    "从同一个 state 重新来一次"，复用会让第 2 遍从第 1 遍结束的画面开始，
    那测的就不是同一件事了。

    异常不吞：模拟器崩了、ROM 没了这类是预期外的失败，让它直接向上抛终止整轮，
    而不是带着一个坏掉的环境把剩下 N-1 遍也跑成假数据。已经跑完的那几遍
    统计早就落盘了（`update_task_stats` 每局都写），不会白跑。
    """
    manifest = RunManifest(
        run_id=run_id, started_at=datetime.now().isoformat(),
        experiment_kind="sequential_episodes", task_ids=[task.task_id for task in chain.tasks],
        initial_state=str(state), notes=f"knowledge task chain: {chain.chain_id}",
        providers={
            "vision": {"model": "qwen3-vl-flash", "temperature": "0.0", "preprocess": "grid"},
            "text": {"model": "qwen-plus", "temperature": "0.7", "max_tokens": "25600"},
            "judge": {"model": "qwen-plus", "temperature": "0.7", "max_tokens": "25600"},
            "embedding": {"model": "BAAI/bge-small-zh-v1.5", "runtime": "fastembed"},
            "reranker": {"model": "BAAI/bge-reranker-base", "runtime": "fastembed"},
        },
    ).with_prompts("decide_action", "judge_success", "episode_summary").with_permissions().validate_design()
    manifest.save(pathlib.Path("experiment_results") / run_id / "manifest.json")

    import os
    os.environ["CLAUDE_RUN_ID"] = run_id
    from pokemon_agent.experiment.run_episode import build_session, run_one
    harness, _, world = build_session(run_id, str(state), watch)
    try:
        print(f"[EXPERIMENT] run_id={run_id} task_id={chain.chain_id} state={state}")
        outcomes = []
        for index, task in enumerate(chain.tasks, start=1):
            print(f"[EXPERIMENT] chain step {index}/{len(chain.tasks)}: {task.task_id}")
            outcome = run_one(harness, run_id, task.max_steps, task.goal)
            outcome["task_id"] = task.task_id
            outcomes.append(outcome)
            if not outcome["success"]:
                break
        chain_outcome = {
            "chain_id": chain.chain_id,
            "run_id": run_id,
            "success": len(outcomes) == len(chain.tasks) and all(
                bool(outcome["success"]) for outcome in outcomes
            ),
            "tasks": outcomes,
        }
        update_task_stats(chain.chain_id, chain_outcome)
        print(chain_outcome)
        return chain_outcome
    finally:
        world.stop()


def update_task_stats(task_id: str, outcome: dict[str, object]) -> None:
    """按 task_id 累积多次 run 的尝试数、成功数和成功率。"""
    import json

    path = pathlib.Path("experiment_results") / "task_stats" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stats: dict[str, object] = {
        "task_id": task_id, "attempts": 0, "successes": 0, "success_rate": 0.0, "runs": [],
    }
    if path.is_file():
        stats = json.loads(path.read_text(encoding="utf-8"))
    stats["attempts"] = int(stats["attempts"]) + 1
    stats["successes"] = int(stats["successes"]) + int(bool(outcome.get("success")))
    stats["success_rate"] = int(stats["successes"]) / int(stats["attempts"])
    runs = stats["runs"]
    assert isinstance(runs, list)
    runs.append(outcome)
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
