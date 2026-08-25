"""按仓库现有 state 启动一个可复现实验任务。"""

from __future__ import annotations

import argparse
import pathlib
import uuid
from datetime import datetime

from pokemon_agent.experiment.manifest import RunManifest
from pokemon_agent.experiment.tasks import knowledge_recall_tasks


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
    args = parser.parse_args()

    chains = {chain.chain_id: chain for chain in knowledge_recall_tasks(args.max_steps)}
    if not args.task_id:
        for chain in chains.values():
            task_names = " -> ".join(task.task_id for task in chain.tasks)
            print(f"{chain.chain_id}\t{task_names}")
        return
    assert args.task_id in chains, f"unknown task_id: {args.task_id}"
    chain = chains[args.task_id]

    run_id = args.run_id or f"{datetime.now().strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    state = state_for_task(chain.initial_task.task_id)
    manifest = RunManifest(
        run_id=run_id, started_at=datetime.now().isoformat(),
        experiment_kind="sequential_episodes", task_ids=[task.task_id for task in chain.tasks],
        initial_state=str(state), notes=f"knowledge task chain: {args.task_id}",
        providers={
            "vision": {"model": "qwen3-vl-flash", "temperature": "0.0", "preprocess": "grid"},
            "text": {"model": "qwen-plus", "temperature": "0.7", "max_tokens": "25600"},
            "judge": {"model": "qwen-plus", "temperature": "0.7", "max_tokens": "25600"},
            "embedding": {"model": "BAAI/bge-small-zh-v1.5", "runtime": "fastembed"},
            "reranker": {"model": "BAAI/bge-reranker-base", "runtime": "fastembed"},
        },
    ).with_prompts("decide_action", "judge_success").with_permissions().validate_design()
    manifest.save(pathlib.Path("experiment_results") / run_id / "manifest.json")

    import os
    os.environ["CLAUDE_RUN_ID"] = run_id
    from pokemon_agent.experiment.run_episode import build_session, run_one
    harness, _, world = build_session(run_id, str(state), args.watch)
    try:
        print(f"[EXPERIMENT] run_id={run_id} task_id={args.task_id} state={state}")
        outcomes = []
        for index, task in enumerate(chain.tasks, start=1):
            print(f"[EXPERIMENT] chain step {index}/{len(chain.tasks)}: {task.task_id}")
            outcome = run_one(harness, run_id, task.max_steps, task.goal)
            outcome["task_id"] = task.task_id
            outcomes.append(outcome)
            update_task_stats(task.task_id, outcome)
            if not outcome["success"]:
                break
        chain_outcome = {
            "chain_id": chain.chain_id,
            "success": len(outcomes) == len(chain.tasks) and all(
                bool(outcome["success"]) for outcome in outcomes
            ),
            "tasks": outcomes,
        }
        update_task_stats(chain.chain_id, chain_outcome)
        print(chain_outcome)
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
