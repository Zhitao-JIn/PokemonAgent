"""普通视觉评测入口，模型选择沿用 config，默认四线程。"""

import argparse

from evals.common.run import run_evaluation
from evals.runconfig import load_config
from pokemon_agent.brain.vision_factory import build_vision_provider
from pokemon_agent.env import load_env_file

from .dataset import build_cases, select_frames
from .scorer import FieldMatch
from .solver import SCORE_KEYS


def main() -> int:
    """打印调用不通帧；其余用例由原生统计与退出码表示结果。"""
    parser = argparse.ArgumentParser(description="单帧视觉字段评测")
    parser.add_argument("--vision-model")
    parser.add_argument("--per-scene", type=int)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    arguments = parser.parse_args()
    if arguments.workers < 1 or (arguments.per_scene is not None and arguments.per_scene < 1):
        parser.error("workers 与 per-scene 必须为正")
    load_env_file()
    model = arguments.vision_model or str(load_config()["models"]["vision_model"])
    vision = build_vision_provider(model=model, temperature=0.0)
    cases, failures = build_cases(
        select_frames(arguments.per_scene, not arguments.all), vision, arguments.workers
    )
    if failures:
        print(
            "视觉调用不通，未计分："
            + "；".join(f"{item.sample_id}: {item.reason}" for item in failures)
        )
    if not cases:
        return 0
    return run_evaluation(
        test_cases=cases,
        metrics=[FieldMatch(key) for key in SCORE_KEYS],
        results_folder="eval_results/episode_vision_read",
        hyperparameters={"dataset": "frames/v2", "model": model, "workers": arguments.workers},
    )


if __name__ == "__main__":
    raise SystemExit(main())
