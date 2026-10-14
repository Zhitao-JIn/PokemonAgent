"""判定协议层（`evals/e2e/scoring/`）的用法示范：适配正反例 + 指标的手算数字。

复用 `test_evals_checks` 的假账搭法（同一目录，pytest 直接互导）；指标数字全部手算可核对。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_evals_checks import GOAL, _event, frame, sample, stream

from evals.agent_short_goal_run.dataset.schemas import EvalSample, SampleStart
from evals.agent_short_goal_run.scorer import (
    RunStream,
    Score,
    accuracy,
    from_check_verdict,
    from_red_line_hits,
    judge,
    mechanical_scorer,
    red_line_scorer,
    stderr,
)
from evals.agent_short_goal_run.scorer.verdict import RedLineHit
from pokemon_agent.direct.trace.content import RunEndContent


def vscore(sample_id: str, outcome: str, epoch: int = 0) -> Score:
    """verdict 型 Score 速造（metric 测试用）。"""
    return Score(scorer_id="mech:x", outcome=outcome, sample_id=sample_id, epoch=epoch)  # type: ignore[arg-type]


def sample_without_check() -> EvalSample:
    """check_id 为空的样本（不可机械判定）。"""
    return EvalSample(
        sample_id=GOAL, dataset_version="v1", category="x",
        start=SampleStart(kind="archive", archive="s", source_state="s.state", source_sha256="h"),
        goal="g", success_criteria="c", max_steps=15, behavior="b", check_id=None,
        rubric=[], red_lines=[], k_metric="pass_hat_k", split="val",
    )  # fmt: skip


def stream_with_run_end(frames: list, termination: str) -> RunStream:
    """一局 + run 收尾账（红线 R1/R3 要看）。"""
    end = _event(
        "run_end", 99,
        RunEndContent(total=1, succeeded=1, termination=termination, judge_reason="j"),
    )  # fmt: skip
    return RunStream([*stream(*frames).events, end])


# ---- 统一 Scorer 协议：机械判据适配 ----


def test_mechanical_scorer_passes_and_carries_evidence() -> None:
    score = mechanical_scorer()(
        stream(frame(1), frame(2, dialog="Hey! You came from PALLET TOWN?")),
        sample("dialog_opened"),
    )

    assert score.outcome == "pass"
    assert score.scorer_id == "mech:dialog_opened"
    assert score.value == 1.0
    assert score.evidence, "判成的证据帧要原样进 Score"
    assert score.sample_id == GOAL


def test_mechanical_scorer_fails_with_reason() -> None:
    score = mechanical_scorer()(
        stream(frame(1, map_id=1), frame(2, map_id=1)), sample("map_changed")
    )

    assert score.outcome == "fail"
    assert score.value == 0.0
    assert score.reason


def test_mechanical_scorer_marks_unjudgeable_without_check_id() -> None:
    score = mechanical_scorer()(stream(frame(1)), sample_without_check())

    assert score.outcome == "unjudgeable"
    assert score.value is None, "unjudgeable 不进指标分母"


def test_check_verdict_conversion_preserves_all_fields() -> None:
    verdict = judge(stream(frame(1), frame(2, map_id=40)), sample("map_changed"))

    score = from_check_verdict("mech:map_changed", verdict, sample_id=GOAL)

    assert (score.outcome, score.evidence, score.reason) == (
        verdict.outcome,
        verdict.evidence,
        verdict.reason,
    )


# ---- 红线独立 scorer ----


def test_red_line_scorer_flags_false_success_claim() -> None:
    """R3：run 以 goal_done 收尾但机械判负——谎报成功要被打成 fail。"""
    score = red_line_scorer(3, 3)(
        stream_with_run_end([frame(1, map_id=1), frame(2, map_id=1)], "goal_done"),
        sample("map_changed"),
    )

    assert score.outcome == "fail"
    assert score.scorer_id == "red_lines"
    assert score.detail["hits"], "命中明细进 detail 分列"
    assert any(h["line_id"] == "R3" for h in score.detail["hits"])


def test_red_line_scorer_passes_when_nothing_hit() -> None:
    score = red_line_scorer(3, 3)(
        stream_with_run_end([frame(1, map_id=1), frame(2, map_id=40)], "goal_done"),
        sample("map_changed"),
    )

    assert score.outcome == "pass"
    assert score.detail == {}


def test_red_line_hits_conversion_lists_all_reasons() -> None:
    score = from_red_line_hits(
        [RedLineHit(line_id="R1", reason="出错"), RedLineHit(line_id="R2", reason="失灵")],
        sample_id=GOAL,
    )

    assert score.outcome == "fail"
    assert "R1" in score.reason and "R2" in score.reason


# ---- Metric 协议 ----


def test_accuracy_and_stderr_exclude_unjudgeable() -> None:
    scores = [
        vscore("a", "pass"),
        vscore("a", "fail"),
        vscore("b", "pass"),
        vscore("c", "unjudgeable"),
    ]

    assert accuracy(scores) == pytest.approx(2 / 3)
    assert stderr(scores) == pytest.approx((2 / 9 / 3) ** 0.5)  # √(p(1-p)/n)


def test_metrics_return_none_when_nothing_is_judgeable() -> None:
    assert accuracy([vscore("a", "unjudgeable")]) is None
    assert stderr([]) is None
    assert stderr([vscore("a", "pass")]) is None, "可判定样本 <2 不谈误差"


def test_pass_at_and_pass_k_semantics_come_from_the_real_library() -> None:
    """pass@k / pass^k 不自算——用真库 reducer（Epochs 的 reducer 机制，主账 329）钉住语义。

    命名映射：inspect 的 `pass_at(k)` = pass@k（至少一次成）；`pass_k(k)` = pass^k（k 次全成）。
    数字与原自研估计量逐位一致（C,C,I 的 1.0 / 1/3；C,I,I 的 2/3 / 0.0）。
    """
    from inspect_ai.scorer import Score as InspectScore
    from inspect_ai.scorer import pass_at, pass_k

    cci = [InspectScore(value="C"), InspectScore(value="C"), InspectScore(value="I")]
    cii = [InspectScore(value="C"), InspectScore(value="I"), InspectScore(value="I")]

    assert pass_at(2)(cci).value == pytest.approx(1.0)
    assert pass_at(2)(cii).value == pytest.approx(2 / 3)
    assert pass_k(2)(cci).value == pytest.approx(1 / 3)
    assert pass_k(2)(cii).value == pytest.approx(0.0)


# ---- Score 分列契约 ----


def test_score_kind_validators_keep_verdict_and_graded_separate() -> None:
    with pytest.raises(ValidationError):
        Score(scorer_id="m", kind="verdict", score=2, sample_id="a")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Score(scorer_id="m", kind="graded")  # type: ignore[arg-type]
