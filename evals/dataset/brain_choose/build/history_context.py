"""还原决策时刻的完整历史，并与此前同格 judge 的真实输入核对；不读取模型答案。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from evals.common.legacy_requests.judge import FromHarnessToBrainToolJudgeReq
from evals.common.legacy_requests.judge_prompt import build_prompt
from evals.dataset.brain_choose.build.from_capture import CaptureRow, read_request
from evals.dataset.io import contained_file
from pokemon_agent.direct.brain_tool import dedup_snapshots
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
)
from pokemon_agent.world.interface.domain.ram_readout import RamReadout


def digest(text: str) -> str:
    """对原始字符串取摘要，不重编码截图或缩减历史。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class JudgeInput(BaseModel):
    """只保留已发生的 judge 输入，明确排除其响应、why 与之后动作。"""

    event_id: str
    sequence: int
    prompt: str
    images: list[str]


class HistoryPacket(BaseModel):
    """完整生产请求是素材真源；judge 文本与图片摘要只用于核对同口径。"""

    case_id: str
    request: FromHarnessToBrainToolChooseOnceReq
    request_sha256: str
    context_path: str
    current_ram: RamReadout
    current_frame: str
    history_steps: list[int]
    judge_prompt: str
    judge_image_sha256: list[str]
    matched_judge_event_ids: list[str]
    judge_input_verified: bool
    task_id: str
    run_id: str
    episode_id: str


def judge_inputs(trace: Path) -> dict[tuple[str, str, int], list[JudgeInput]]:
    """索引实际 task judge 输入；其他账以及所有模型输出不进入返回值。"""
    result: dict[tuple[str, str, int], list[JudgeInput]] = {}
    for path in trace.glob("*.json"):
        event = json.loads(path.read_text(encoding="utf-8"))
        if event["kind"] != "judge_call":
            continue
        meta = json.loads(event["meta"])
        if meta["source"] != "task.review_and_judge":
            continue
        content = json.loads(event["content"])
        marker = (meta["episode_id"], meta["task_id"], meta["step"])
        result.setdefault(marker, []).append(
            JudgeInput(
                event_id=event["uuid"],
                sequence=event["seq"],
                prompt=content["prompt"],
                images=content["images"],
            )
        )
    return result


def validate_history(req: FromHarnessToBrainToolChooseOnceReq, meta: dict[str, object]) -> None:
    """验证历史没有跨 task、越过当前观察或断开末态；不要求全局步号从零开始。"""
    steps = [memory.step for memory in req.memories]
    if steps != sorted(set(steps)):
        raise ValueError("历史顺序错误或步号重复")
    for memory in req.memories:
        if any(getattr(memory, key) != meta[key] for key in ("run_id", "episode_id", "task_id")):
            raise ValueError("历史混入其他 run/episode/task")
        if memory.step >= req.obs.step or memory.after.step > req.obs.step:
            raise ValueError("历史包含决策时刻之后的步骤")
        if not memory.before_frame or not memory.after_frame:
            raise ValueError("历史缺少前后截图，不得静默裁掉")
    if req.memories:
        last = req.memories[-1].after
        last_place = last.place.model_dump() if last.place is not None else None
        current_place = req.obs.place.model_dump() if req.obs.place is not None else None
        if last_place != current_place:
            raise ValueError("历史末态位置与当前观察不符")
        for field in ("overlay", "dialog_text", "options", "cursor", "screen", "walk_map"):
            if getattr(last.facts, field) != getattr(req.obs.facts, field):
                raise ValueError(f"历史末态 {field} 与当前观察不符")


def build_packet(
    batch: Path, row: CaptureRow, inputs: dict[tuple[str, str, int], list[JudgeInput]]
) -> HistoryPacket:
    """完整还原并核对同一决策之前的 judge；空历史明确表示本 task 尚无动作。"""
    req = read_request(batch, row)
    context_path = contained_file(batch, row.context)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    meta = context["meta"]
    validate_history(req, meta)
    judge_req = FromHarnessToBrainToolJudgeReq(
        goal=req.goals[-1],
        history=req.memories,
        task_index=req.task_index,
        knowledge=req.knowledge,
        allow_interrupt=True,
    )
    prompt = build_prompt(judge_req)
    images, _snapshots = dedup_snapshots(req.memories)
    marker = (meta["episode_id"], meta["task_id"], meta["step"])
    matches = inputs.get(marker, [])
    choose_sequence = min(event["seq"] for event in context["choose_call_events"])
    if any(item.sequence >= choose_sequence for item in matches):
        raise ValueError(f"{row.id}: judge 输入来自 choose 之后")
    if any(item.prompt != prompt or item.images != images for item in matches):
        raise ValueError(f"{row.id}: judge 实际输入与完整历史重建不一致")
    if bool(req.memories) != bool(matches):
        raise ValueError(f"{row.id}: 历史与实际 task judge 调用存在性不一致")
    sense = context["sense_event"]["content"]
    return HistoryPacket(
        case_id=row.id,
        request=req,
        request_sha256=digest(contained_file(batch, row.request).read_text(encoding="utf-8")),
        context_path=str(context_path),
        current_ram=RamReadout.model_validate(sense["ram"]),
        current_frame=sense["frame"],
        history_steps=[entry.step for entry in req.memories],
        judge_prompt=prompt,
        judge_image_sha256=[digest(frame) for frame in images],
        matched_judge_event_ids=[item.event_id for item in matches],
        judge_input_verified=bool(matches),
        task_id=meta["task_id"],
        run_id=meta["run_id"],
        episode_id=meta["episode_id"],
    )


def load_packets(source: Path) -> list[HistoryPacket]:
    """按审核索引顺序还原全部现场；不读响应文件或之后执行的动作。"""
    cache: dict[Path, dict[tuple[str, str, int], list[JudgeInput]]] = {}
    packets: list[HistoryPacket] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        batch = Path(raw["batch"])
        row = CaptureRow(
            id=raw["case_id"],
            sample_id=raw["case_id"].split("/")[-2],
            scene=raw["scene"],
            task_goal=raw["goal"],
            task_criteria=raw["criteria"],
            request=raw["request"],
            context=raw["context"],
        )
        trace = contained_file(batch, row.request).parent / "trace"
        if trace not in cache:
            cache[trace] = judge_inputs(trace)
        packets.append(build_packet(batch, row, cache[trace]))
    if len({packet.case_id for packet in packets}) != len(packets):
        raise ValueError("历史审核索引 id 重复")
    return packets
