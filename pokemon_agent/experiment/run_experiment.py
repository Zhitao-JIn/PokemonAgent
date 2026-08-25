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

    tasks = {task.task_id: task for task in knowledge_recall_tasks(args.max_steps)}
    if not args.task_id:
        for task in tasks.values():
            print(f"{task.task_id}\t{task.initial_state_hint}")
        return
    assert args.task_id in tasks, f"unknown task_id: {args.task_id}"

    run_id = args.run_id or f"{datetime.now().strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    state = state_for_task(args.task_id)
    manifest = RunManifest(
        run_id=run_id, started_at=datetime.now().isoformat(),
        experiment_kind="single_episode", task_ids=[args.task_id],
        initial_state=str(state), notes=f"knowledge short task: {args.task_id}",
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
        outcome = run_one(harness, run_id, args.max_steps, tasks[args.task_id].goal)
        update_task_stats(args.task_id, outcome)
        print(outcome)
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
