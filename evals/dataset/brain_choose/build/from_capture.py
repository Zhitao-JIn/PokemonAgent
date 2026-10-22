"""从真实 task choose 录制生成未审草稿与完整审核索引；绝不生成 cases.jsonl。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from evals.dataset.brain_choose.build.prelabel import candidate_keys
from evals.dataset.brain_choose.schemas import ActionMatcher, ChooseCase
from evals.dataset.io import contained_file
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world.interface.domain.ram_readout import RamReadout

VERSION_LIMIT = "原批次以 73463bb 继续；无法证明采集全过程代码版本未变化，用户接受此限制。"
EVALUATION_SCENES = {"walk", "dialog", "battle_menu", "shop", "shop_items", "battle"}


class CaptureRow(BaseModel):
    """来源索引只消费请求与感知路径；不消费响应和执行动作。"""

    id: str
    sample_id: str
    scene: str
    task_goal: str
    task_criteria: str
    request: str
    context: str


class ReviewRow(BaseModel):
    """每个现场均留审核入口，未定记录没有伪造的 acceptable。"""

    case_id: str
    scene: str
    goal: str
    criteria: str
    request: str
    context: str
    status: str
    reason: str
    batch: str = ""
    version_limit: str = VERSION_LIMIT


def read_request(batch: Path, row: CaptureRow) -> FromHarnessToBrainToolChooseOnceReq:
    """还原生产信封并核对同帧感知和 RAM 解码；不一致立即失败。"""
    req = FromHarnessToBrainToolChooseOnceReq.model_validate_json(
        contained_file(batch, row.request).read_text(encoding="utf-8")
    )
    context = json.loads(contained_file(batch, row.context).read_text(encoding="utf-8"))
    sense = context["sense_event"]["content"]
    ram = RamReadout.model_validate(sense["ram"])
    expected = req.obs.facts.model_dump(mode="json")
    if (
        sense["facts"] != expected
        or sense["status"]
        != json.loads(contained_file(batch, row.request).read_text(encoding="utf-8"))["obs"][
            "status"
        ]
    ):
        raise ValueError(f"{row.id}: 感知与请求不一致")
    if row.scene != req.obs.scene or req.space.scene != req.obs.scene:
        raise ValueError(f"{row.id}: 场合不一致")
    if (row.task_goal, row.task_criteria) != (req.goals[-1].goal, req.goals[-1].criteria):
        raise ValueError(f"{row.id}: task 目标不一致")
    if not sense.get("frame") or not any(req.space.mask.values()):
        raise ValueError(f"{row.id}: 缺图或动作空间为空")
    decoded = ram.decoded
    if ram.text_source != "decode" or (
        decoded.dialog_text != req.obs.facts.dialog_text
        or decoded.options != req.obs.facts.options
        or decoded.cursor != (req.obs.facts.cursor or "")
    ):
        raise ValueError(f"{row.id}: RAM 文字证据不一致")
    return req


def capture_version_note(batch: Path) -> str:
    """补采有首尾代码摘要时必须一致；旧批次保留已接受的版本限制。"""
    before, after = batch / "code_before.json", batch / "code_after.json"
    if not before.exists() and not after.exists():
        return VERSION_LIMIT
    first = json.loads(before.read_text(encoding="utf-8"))
    last = json.loads(after.read_text(encoding="utf-8"))
    if first != last:
        raise ValueError("补采首尾代码版本不一致，停止草稿装配")
    return f"补采首尾 HEAD 与生产源码摘要一致：{first['head']} / {first['production_sha256']}。"


def build_drafts(batch: Path, *, case_prefix: str = "") -> tuple[list[ChooseCase], list[ReviewRow]]:
    """生成保守候选与全量审核索引；所有候选仍为未审，不可用于模型成绩发布。"""
    rows = json.loads((batch / "capture_index.json").read_text(encoding="utf-8"))
    cases: list[ChooseCase] = []
    reviews: list[ReviewRow] = []
    version_note = capture_version_note(batch)
    for raw in rows:
        row = CaptureRow.model_validate(raw)
        if case_prefix:
            row.id = f"{case_prefix}/{row.id}"
        req = read_request(batch, row)
        keys, reason = candidate_keys(req)
        if row.scene not in EVALUATION_SCENES:
            keys, reason = [], "补采新场合仅存档，不纳入当前六类评测"
        reviews.append(
            ReviewRow(
                case_id=row.id,
                scene=row.scene,
                goal=row.task_goal,
                criteria=row.task_criteria,
                request=row.request,
                context=row.context,
                status=(
                    "outside_scope"
                    if row.scene not in EVALUATION_SCENES
                    else "rule_draft"
                    if keys
                    else "pending"
                ),
                reason=reason,
                batch=str(batch),
                version_limit=version_note,
            )
        )
        if keys:
            cases.append(draft_case(batch, row, req, keys, reason, version_note))
    if len({row.case_id for row in reviews}) != len(reviews):
        raise ValueError("录制索引存在重复 id")
    return cases, reviews


def draft_case(
    batch: Path,
    row: CaptureRow,
    req: FromHarnessToBrainToolChooseOnceReq,
    keys: list[str],
    reason: str,
    version_note: str,
) -> ChooseCase:
    """给非空候选加未审标记；不得由此宣称 acceptable 完备。"""
    assert keys, "draft_case requires nonempty candidates"
    return ChooseCase(
        case_id=row.id,
        request=req,
        scene=req.obs.scene,
        acceptable=[ActionMatcher(key=key, max_times=1) for key in keys],
        source="collected",
        label_source="rule",
        origin=f"{batch.name}/{row.request}",
        tags=["read_screen"] if req.obs.menu_decode_complete is False else [],
        label_note=f"未审：{reason}。候选集合尚不完备，须人工审核。{version_note}",
    )


def write_rows(path: Path, rows: list[BaseModel]) -> None:
    """独占创建 JSONL；已有文件一律报错，不覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(row.model_dump_json() + "\n")


def main() -> None:
    """人工显式执行，输入录制目录，输出草稿与审核索引。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True, action="append")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    drafts = root / "v1" / "cases_draft.jsonl"
    index = root / "build" / "goals.jsonl"
    if drafts.exists() or index.exists():
        raise FileExistsError("草稿或审核索引已存在；拒绝覆盖")
    cases: list[ChooseCase] = []
    reviews: list[ReviewRow] = []
    for number, batch in enumerate(args.batch):
        extra_cases, extra_reviews = build_drafts(batch, case_prefix=batch.name if number else "")
        cases.extend(extra_cases)
        reviews.extend(extra_reviews)
    if len({row.case_id for row in reviews}) != len(reviews):
        raise ValueError("多批次审核索引存在重复 id")
    write_rows(drafts, cases)
    write_rows(index, reviews)
    print(
        json.dumps(
            {
                "total": len(reviews),
                "draft": len(cases),
                "scenes": dict(Counter(row.scene for row in reviews)),
                "draft_scenes": dict(Counter(case.scene for case in cases)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
