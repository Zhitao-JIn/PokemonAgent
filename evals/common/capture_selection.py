"""显式选择采集子集；按原数据集顺序执行，恢复不能改变选择。"""

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.dataset.schemas import EvalSample

CAPTURE_DATASET_VERSION = "v20261021_retest5"


def selected_samples(sample_ids: list[str] | None) -> list[EvalSample]:
    """None 选择全部；空、重复和未知 ID 明确拒绝，不静默扩大采集范围。"""
    samples = load_samples(CAPTURE_DATASET_VERSION)
    if sample_ids is None:
        return samples
    if not sample_ids or len(set(sample_ids)) != len(sample_ids):
        raise ValueError("capture selection must be nonempty and unique")
    known = {sample.sample_id for sample in samples}
    if set(sample_ids) - known:
        raise ValueError("capture selection contains unknown samples")
    return [sample for sample in samples if sample.sample_id in sample_ids]
