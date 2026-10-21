"""从重打的冻结 run 起点恢复，逐层原样录制全部生产脑调用。"""

import argparse
import sys
from pathlib import Path

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.runner.archive import prepare_archive
from evals.agent_short_goal_run.solver.runner.one import run_id_for
from evals.common.brain_capture import record_brain_calls
from evals.common.capture_configuration import capture_budget
from evals.common.invocation import write_record
from evals.runconfig import load_config, resolve_models
from pokemon_agent.build import build_real
from pokemon_agent.env import load_env_file
from pokemon_agent.harness import RunRuntime
from pokemon_agent.harness.checkpoint import restore_run
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.run_config import RunConfig


def capture_case(sample: EvalSample, directory: Path, archive_root: Path | None = None) -> None:
    """从指定新起点恢复；原样录制，异常保留原产物和调用账。"""
    load_env_file()
    configuration = load_config()
    budget = capture_budget()
    config = RunConfig(budget=budget)
    directory.mkdir(parents=True, exist_ok=False)
    configuration_path = directory / "run_config.json"
    write_record(configuration_path, config)
    write_record(directory / "sample.json", sample)
    games: list[WorldMcpTool] = []

    def build_branch(branch: str) -> RunRuntime:
        harness, game = build_real(
            run_id=run_id_for(sample.sample_id),
            branch=branch,
            trace_backend="local",
            trace_root=directory / "trace",
            memory_root=directory / "memory",
            checkpoint_root=directory / "checkpoints",
            config=configuration_path,
            **resolve_models(configuration["models"]),
        )
        games.append(game)
        record_brain_calls(harness.deps, directory / "brain_calls")
        return harness.deps

    try:
        manifest = (
            archive_root / sample.sample_id / "manifest.json"
            if archive_root
            else prepare_archive(sample, directory / "start")
        )
        result = restore_run(manifest, build_branch, sample_id=sample.sample_id)
        write_record(directory / "run_result.json", result)
    finally:
        original_error = sys.exception()
        for game in games:
            try:
                game.release_lease()
            except Exception as release_error:
                if original_error is None:
                    raise
                original_error.add_note(f"world release failed: {release_error}")


def main() -> None:
    """内部串行 worker；一进程只跑一个独立样本。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args()
    samples = {sample.sample_id: sample for sample in load_samples()}
    if arguments.sample not in samples:
        raise ValueError("unknown sample")
    capture_case(samples[arguments.sample], arguments.out.resolve(), arguments.archive_root)


if __name__ == "__main__":
    main()
