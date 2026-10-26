"""安装八种能力、三层生产端口的完整录制，不改动 brain scope。"""

from pathlib import Path

from pokemon_agent.harness.run.runtime import RunRuntime

from .capture_review import RecordedReviewer
from .recorded_ports import (
    RecordedChooser,
    RecordedDecomposer,
    RecordedJudger,
    RecordedPlanner,
    RecordedReflector,
    RecordedRunSummarizer,
    RecordedSummarizer,
    RecordedTaskSummarizer,
)


def record_brain_calls(runtime: RunRuntime, directory: Path) -> None:
    """装配后、进图前调用一次；各层独立目录防止 judge 混层。"""
    episode = runtime.episode
    review_root = directory.parent / "review_calls"
    runtime.reviewer = RecordedReviewer(runtime.reviewer, review_root / "run")
    episode.reviewer = RecordedReviewer(episode.reviewer, review_root / "episode")
    episode.task.reviewer = RecordedReviewer(episode.task.reviewer, review_root / "task")
    task = episode.task
    runtime.planner = RecordedPlanner(runtime.planner, directory / "run/plan")
    runtime.judger = RecordedJudger(runtime.judger, directory / "run/judge")
    runtime.run_summarizer = RecordedRunSummarizer(
        runtime.run_summarizer, directory / "run/summarize_run"
    )
    episode.decomposer = RecordedDecomposer(episode.decomposer, directory / "episode/decompose")
    episode.judger = RecordedJudger(episode.judger, directory / "episode/judge")
    episode.summarizer = RecordedSummarizer(episode.summarizer, directory / "episode/summarize")
    task.chooser = RecordedChooser(task.chooser, directory / "task/choose")
    task.judger = RecordedJudger(task.judger, directory / "task/judge")
    task.reflector = RecordedReflector(task.reflector, directory / "task/reflect")
    task.task_summarizer = RecordedTaskSummarizer(
        task.task_summarizer, directory / "task/summarize_task"
    )
