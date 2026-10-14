"""审格的用法示范：**judge 说「已达成」时亮给人审；人推翻，本层接着跑**，
下一次拆解 / 规划看得见为什么。

样本是 `_fake_run` 把真的三张图跑一遍的落盘账本。人由一个按脚本答的 reviewer 扮演：
插话一律没意见；审到哪一层的模型裁决就按脚本认或推翻，其余审（task / 一局的结果）一律认账。
"""

from __future__ import annotations

import json
from pathlib import Path

from _fake_run import every, never, run_fake

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)

RUN_ID = "r1"
EP1 = "r1-ep1"


class _ScriptedHuman:
    """按脚本答：对 `overturn_at` 里点名的那一层，第一次审模型裁决时推翻，其余都认账。"""

    def __init__(self, overturn_at: str, note: str) -> None:
        self._overturn_at, self._note = overturn_at, note
        self.judgements: list[str] = []

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        return FromHarnessToReviewerInjectResp(text="", answered=True)

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        if isinstance(req.outcome, FromHarnessToBrainToolJudgeResp):
            self.judgements.append(req.episode_id)
            if req.episode_id == self._overturn_at and self.judgements.count(req.episode_id) == 1:
                return FromHarnessToReviewerAuditResp(
                    verdict=AuditVerdict.OVERTURN, note=self._note, answered=True
                )
        return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT, answered=True)


def _content(event: dict) -> dict:
    return json.loads(event["content"])


def _meta(event: dict) -> dict:
    return json.loads(event["meta"])


def _of(events: list[dict], kind: str, episode_id: str) -> list[dict]:
    """某本账在某一层（`meta.episode_id`）的全部条目，按发生顺序。"""
    return [e for e in events if e["kind"] == kind and _meta(e)["episode_id"] == episode_id]


def test_overturning_the_episode_judge_keeps_it_running_and_tells_the_next_decompose(
    tmp_path: Path,
) -> None:
    """第 2 个 task 后 judge 判「已达成」，人推翻 → 本局不收工，重拆的 prompt 里有人的理由。"""
    human = _ScriptedHuman(overturn_at=EP1, note="还没按「是」，球没拿到")
    events = run_fake(tmp_path, episode=every(2), run=every(1), reviewer=human)

    verdicts = [_content(e) for e in _of(events, "judge_verdict", EP1)]
    overturned = [v for v in verdicts if v["audit"] == "overturn"]
    assert len(overturned) == 1
    assert overturned[0]["termination"] == ""
    assert "被人推翻：还没按「是」" in overturned[0]["judge_reason"]
    assert overturned[0]["human_note"] == "还没按「是」，球没拿到"

    decompose_prompts = [_content(e)["prompt"] for e in _of(events, "decompose_call", EP1)]
    assert len(decompose_prompts) == 2
    assert "## 上一次本局判定" not in decompose_prompts[0]
    assert "人推翻了这个判定：还没按「是」，球没拿到" in decompose_prompts[1]


def test_a_not_done_judgement_is_not_audited_but_reaches_the_next_decompose(
    tmp_path: Path,
) -> None:
    """judge 判「没达成」不问人；它的理由照样带给下一次拆解。"""
    human = _ScriptedHuman(overturn_at="nobody", note="")
    events = run_fake(tmp_path, episode=never, run=every(1), reviewer=human)

    assert EP1 not in human.judgements
    assert all(_content(e)["audit"] == "" for e in _of(events, "judge_verdict", EP1))
    decompose_prompts = [_content(e)["prompt"] for e in _of(events, "decompose_call", EP1)]
    assert "判定员说：还没达成——w" in decompose_prompts[1]


def test_overturning_the_run_judge_keeps_the_run_going_and_tells_the_next_plan(
    tmp_path: Path,
) -> None:
    """第一局后 run 的 judge 判「已达成」，人推翻 → run 再派一局，下一次规划看得见人的理由。"""
    human = _ScriptedHuman(overturn_at=RUN_ID, note="第一个道馆还没打")
    events = run_fake(tmp_path, run=every(1), reviewer=human)

    run_verdicts = [_content(e) for e in _of(events, "judge_verdict", RUN_ID)]
    assert "overturn" in [v["audit"] for v in run_verdicts]
    assert run_verdicts[-1]["audit"] == "accept"
    assert run_verdicts[-1]["termination"] == "goal_done"

    plan_prompts = [_content(e)["prompt"] for e in _of(events, "plan_call", RUN_ID)]
    assert "（还没有判定过）" in plan_prompts[0]
    assert any("人推翻了这个判定：第一个道馆还没打" in p for p in plan_prompts[1:])


def test_every_audit_is_on_the_books_with_what_was_audited(tmp_path: Path) -> None:
    """四个审点在账上分得开：`review_audit.form_kind` 说审的是什么，`answered` 说人真答了没有。"""
    human = _ScriptedHuman(overturn_at=EP1, note="n")
    events = run_fake(tmp_path, episode=every(2), run=every(1), reviewer=human)

    kinds = {_content(e)["form_kind"] for e in events if e["kind"] == "review_audit"}
    assert kinds == {"TaskOutput", "EpisodeOutput", "JudgeVerdict"}
    assert all(_content(e)["answered"] == "true" for e in events if e["kind"] == "review_audit")
