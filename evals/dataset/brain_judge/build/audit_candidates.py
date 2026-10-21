"""CP2：候选核对与真值审阅草稿生成器（只读审计工具）。

只读 `eval_results/brain_judge/cp0_audit.json` 与
`eval_results/brain_choose/{task_capture_20261018_102238,supplement_20261018_172952}/`
两批已恢复的采集产物，产出逐条草稿、CSV 审阅表与覆盖报告。不调用模型、不改生产代码。

真值口径（spec §2）：
- 只允许两种来源：已有独立机械规则（`evals.agent_short_goal_run.scorer.rules` 注册的
  `check_id`，在 judge 请求时刻的证据上跑）与人工据冻结历史/独立世界证据标注。
- 模型自己的 `done` / `why`、后续动作、run 最终结果、choose 的 `eligible` 一律不用。
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import evals.agent_short_goal_run.scorer.rules  # noqa: F401  # 导入即登记 RULES
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.registry import RULES
from evals.agent_short_goal_run.scorer.stream import RunStream
from evals.agent_short_goal_run.scorer.verdict import CheckVerdict
from pokemon_agent.brain import Goal
from pokemon_agent.direct.brain_tool import dedup_snapshots
from pokemon_agent.direct.prompts.judge_success import build_prompt
from pokemon_agent.direct.trace import parse
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq, TraceKind
from pokemon_agent.schemas.harness.domain.trace_event import TraceEvent
from pokemon_agent.schemas.memory import ActMemory

# --------------------------------------------------------------------------- #
# 路径常量
# --------------------------------------------------------------------------- #

_REPO_ROOT = Path(__file__).resolve().parents[4]
_EVAL_RESULTS = _REPO_ROOT / "eval_results"
_AUDIT_JSON = _EVAL_RESULTS / "brain_judge" / "cp0_audit.json"
_SOURCE_ROOT = _EVAL_RESULTS / "brain_choose"
_OUT_DIR = _EVAL_RESULTS / "brain_judge"

_DRAFT_JSONL = _OUT_DIR / "cp2_draft.jsonl"
_REVIEW_CSV = _OUT_DIR / "cp2_review.csv"
_COVERAGE_MD = _OUT_DIR / "cp2_coverage.md"

_TASK_CAPTURE = "task_capture_20261018_102238"
_SUPPLEMENT = "supplement_20261018_172952"

# --------------------------------------------------------------------------- #
# 真值判定：criteria 子串 → 已有机械规则 check_id（只收录无歧义映射）
# --------------------------------------------------------------------------- #

_MECHANICAL_CHECKS: list[tuple[str, str]] = [
    # 顺序敏感：更具体的在前。
    ("where 显示 map_id 仍是 12 且 y >= 14", "reach_map12_y14"),
    ("map_id 不再是", "map_changed"),
    ("对话框消失", "dialog_finished"),
    ("对话非空（overlay 为 dialog 且 dialog_text 非空）", "dialog_opened"),
    ("overlay 是 choice，且 options 含 BUY / SELL / QUIT", "shop_menu_opened"),
    ("含 BUY、SELL、QUIT 三个选项", "shop_menu_opened"),
    ("出现 BUY/SELL/QUIT 选单", "shop_menu_opened"),
    ("光标显示在 RUN 上", "cursor_on_run"),
    ("光标从 FIGHT 移到 RUN", "cursor_on_run"),
    ("选项从 FIGHT/PKMN/ITEM/RUN 变成招式列表", "move_list_opened"),
    ("options 变成招式名", "move_list_opened"),
    ("选项变为招式名", "move_list_opened"),
    ("出现招式选择界面", "move_list_opened"),
    ("options 不再是 FIGHT / PKMN / ITEM / RUN，而是宝可梦名字", "party_list_opened_in_battle"),
    ("options 不再是 FIGHT/PKMN/ITEM/RUN，而是宝可梦名字", "party_list_opened_in_battle"),
    ("overlay 仍是 choice，且 options 变成道具名", "bag_opened_in_battle"),
    ("出现道具列表", "bag_opened_in_battle"),
    ("背包/物品列表界面", "bag_opened_in_battle"),
    ("招式执行的结果文字", "move_used"),
    ("对手 HP 下降", "move_used"),
    ("scene 变回 field，或对话框里出现逃跑失败文字", "run_attempted"),
    ("出现 YES/NO 确认框", "shop_item_selected"),
    ("选项含 YES 与 NO", "shop_item_selected"),
    ("购买数量或 YES / NO", "shop_item_selected"),
    ("购买成功文字", "shop_bought"),
    ("MONEY 从", "shop_bought"),
    ("退回商品列表且没花钱", "shop_cancelled"),
    ("重新显示商品名选项", "shop_cancelled"),
    ("选项变为商品列表", "shop_list_opened"),
    ("选项变成商品列表", "shop_list_opened"),
    ("屏幕出现商品名选项", "shop_list_opened"),
]

# 上面列表中 check_id 为 None 的项实际不该出现；这里只保留有 check_id 的映射。
_MECHANICAL_CHECKS = [(k, v) for k, v in _MECHANICAL_CHECKS if v is not None]


def check_id_for(criteria: str) -> str | None:
    """按 criteria 子串匹配一条已有机械规则；无歧义命中才返回。"""
    for key, cid in _MECHANICAL_CHECKS:
        if key in criteria:
            return cid
    return None


# --------------------------------------------------------------------------- #
# 候选加载与去重
# --------------------------------------------------------------------------- #


@dataclass
class Candidate:
    """从 cp0_audit.json 读进来的一条候选。"""

    event_uuid: str
    source_batch: str
    source_choose_case: str
    run_id: str
    episode_id: str
    task_id: str
    step: int
    goal: str
    criteria: str
    goal_family: str
    exact_request_and_image_match_verified: bool
    capture_version_limit: str
    raw: dict = field(default_factory=dict)


def load_candidates() -> list[Candidate]:
    audit = json.loads(_AUDIT_JSON.read_text(encoding="utf-8"))
    out: list[Candidate] = []
    for c in audit["candidates"]:
        out.append(
            Candidate(
                event_uuid=c["event_uuid"],
                source_batch=c["source_batch"],
                source_choose_case=c["source_choose_case"],
                run_id=c["run_id"],
                episode_id=c["episode_id"],
                task_id=c["task_id"],
                step=c["step"],
                goal=c["goal"],
                criteria=c["criteria"],
                goal_family=c["goal_family_candidate"],
                exact_request_and_image_match_verified=c["exact_request_and_image_match_verified"],
                capture_version_limit=c["capture_version_limit"],
                raw=c,
            )
        )
    return out


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """按 `(run_id, episode_id, task_id, step)` 去重；重复即抛错（数据不该有重）。"""
    seen: dict[tuple, Candidate] = {}
    dups: list[tuple] = []
    for c in candidates:
        key = (c.run_id, c.episode_id, c.task_id, c.step)
        if key in seen:
            dups.append(key)
        seen[key] = c
    if dups:
        raise RuntimeError(f"judge 候选存在重复 (run,episode,task,step)：{dups}")
    return list(seen.values())


# --------------------------------------------------------------------------- #
# 源数据读取（带缓存）
# --------------------------------------------------------------------------- #

_trace_cache: dict[str, list[TraceEvent]] = {}
_sm_cache: dict[str, dict[tuple, tuple[dict, str]]] = {}


def _trace_events(batch: str, scene: str) -> list[TraceEvent]:
    key = f"{batch}/{scene}"
    if key not in _trace_cache:
        d = _SOURCE_ROOT / batch / scene / "trace"
        _trace_cache[key] = [
            TraceEvent.model_validate(json.loads(f.read_text(encoding="utf-8")))
            for f in sorted(d.glob("*.json"))
        ]
    return _trace_cache[key]


def _step_memories(batch: str, scene: str) -> dict[tuple, tuple[dict, str]]:
    """`(episode_id, task_id, step)` → `(完整 ActMemory payload（含 before/after 帧）, 文件名)`。"""
    key = f"{batch}/{scene}"
    if key not in _sm_cache:
        d = _SOURCE_ROOT / batch / "server_memory" / scene / "step_memory"
        idx: dict[tuple, tuple[dict, str]] = {}
        for f in d.glob("*.json"):
            if f.name == "index.json":
                continue
            p = json.loads(f.read_text(encoding="utf-8"))["payload"]
            idx[(p["episode_id"], p["task_id"], p["step"])] = (p, f.name)
        _sm_cache[key] = idx
    return _sm_cache[key]


def _judge_event(c: Candidate) -> TraceEvent:
    scene = c.source_choose_case.split("/")[0]
    return next(e for e in _trace_events(c.source_batch, scene) if e.uuid == c.event_uuid)


# --------------------------------------------------------------------------- #
# 请求重建 + 核对
# --------------------------------------------------------------------------- #


@dataclass
class Reconstruction:
    """一条候选的重建与核对结果。"""

    candidate: Candidate
    request: FromHarnessToBrainToolJudgeReq
    history: list[ActMemory]
    history_files: list[str]
    judge_images: list[str]
    prompt_exact: bool
    image_bound: bool
    request_sha256: str
    image_sha256s: list[str]


def reconstruct(c: Candidate) -> Reconstruction:
    """重建 `FromHarnessToBrainToolJudgeReq`，核 prompt 与图片绑定。"""
    scene = c.source_choose_case.split("/")[0]
    raw = _trace_events(c.source_batch, scene)
    judge = next(e for e in raw if e.uuid == c.event_uuid)
    judge_content = json.loads(judge.content)

    # 1) history：judge 之前本 task 已写的 ActMemory（seq 序）。
    writes = [
        e
        for e in raw
        if e.kind == TraceKind.WRITE_ACT_MEMORY
        and json.loads(e.meta).get("episode_id") == c.episode_id
        and json.loads(e.meta).get("task_id") == c.task_id
        and e.seq < judge.seq
    ]
    sm = _step_memories(c.source_batch, scene)
    history: list[ActMemory] = []
    history_files: list[str] = []
    for e in sorted(writes, key=lambda e: e.seq):
        step = json.loads(e.content)["before"]["step"]
        payload, filename = sm[(c.episode_id, c.task_id, step)]
        history.append(ActMemory.model_validate(payload))
        history_files.append(filename)

    # 2) request。
    goal = Goal(goal=c.goal, criteria=c.criteria)
    request = FromHarnessToBrainToolJudgeReq(goal=goal, history=history, allow_interrupt=True)

    # 3) prompt 核对（knowledge / task_index 实测为空，见 CP0；此处按生产口径留空）。
    prompt = build_prompt(request)
    prompt_exact = prompt == judge_content["prompt"]

    # 4) 图片绑定：dedup_snapshots(history) 与 judge 发送的图片逐张比对。
    judge_images = judge_content.get("images", [])
    frames, _ = dedup_snapshots(history)
    judge_hashes = [hashlib.sha256(x.encode()).hexdigest() for x in judge_images]
    frame_hashes = [hashlib.sha256(x.encode()).hexdigest() for x in frames]
    image_bound = judge_hashes == frame_hashes

    # 5) request 哈希（全量，含帧；sort_keys 规范化，跨环境可复现）。
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    request_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return Reconstruction(
        candidate=c,
        request=request,
        history=history,
        history_files=history_files,
        judge_images=judge_images,
        prompt_exact=prompt_exact,
        image_bound=image_bound,
        request_sha256=request_sha256,
        image_sha256s=judge_hashes,
    )


# --------------------------------------------------------------------------- #
# 真值判定
# --------------------------------------------------------------------------- #


@dataclass
class Truth:
    """一条候选的真值审阅结论。

    CP2 只自动产出机械真值；非机械样本一律留待人工审阅（`achieved` / `method` 均为 None），
    工具给出的推测只落在 `suggested_achieved`，不作为已审定标签。
    """

    method: str | None  # "mechanical" | None（None = 待人工审阅）
    achieved: bool | None  # 仅 mechanical 有值
    check_id: str | None  # 仅 mechanical 有值
    negative_mode: str | None  # 仅 mechanical 判负有值
    suggested_achieved: bool | None  # 非机械样本的自动推测（未审定）
    suggested_negative_mode: str | None
    evidence: list[dict]  # [{source, locator, summary}]，可追溯定位


def _truncated_stream(c: Candidate) -> RunStream:
    """judge 请求时刻为止、本 task 的 sense_frame 截断流。"""
    scene = c.source_choose_case.split("/")[0]
    raw = _trace_events(c.source_batch, scene)
    judge = next(e for e in raw if e.uuid == c.event_uuid)
    events = [
        parse(e)
        for e in raw
        if e.kind == TraceKind.SENSE_FRAME
        and e.seq < judge.seq
        and json.loads(e.meta).get("task_id") == c.task_id
    ]
    return RunStream(events)


def _sample_for(c: Candidate, check_id: str) -> EvalSample:
    return EvalSample(
        sample_id=c.source_choose_case.split("/")[0],
        dataset_version="v1",
        granularity="run",
        category="",
        start={"kind": "archive", "archive": "x"},
        goal=c.goal,
        success_criteria=c.criteria,
        max_steps=1,
        behavior="",
        check_id=check_id,
        rubric=[],
        red_lines=[],
        k_metric="pass_at_k",
        split="val",
    )


def _trace_locator(c: Candidate, uuid: str) -> str:
    scene = c.source_choose_case.split("/")[0]
    return f"{c.source_batch}/{scene}/trace/{uuid}.json"


def _step_memory_locator(rec: Reconstruction, index: int = -1, field: str = "after.facts") -> str:
    """指向某条历史记录对应的 step_memory 文件与 JSON 字段（相对 source 根）。"""
    c = rec.candidate
    scene = c.source_choose_case.split("/")[0]
    if rec.history_files and -len(rec.history_files) <= index < len(rec.history_files):
        fn = rec.history_files[index]
        return f"{c.source_batch}/server_memory/{scene}/step_memory/{fn} payload.{field}"
    return _trace_locator(c, c.event_uuid)


def _mechanical_evidence(c: Candidate, verdict: CheckVerdict) -> list[dict]:
    locs = [_trace_locator(c, u) for u in verdict.evidence] or [_trace_locator(c, c.event_uuid)]
    return [{"source": "trace", "locator": loc, "summary": verdict.reason} for loc in locs]


def _final_facts(rec: Reconstruction) -> tuple[dict, str, object]:
    """请求时刻最后一条 ActMemory 的 after facts、task 场景与 RAM（有则）。

    返回 (facts, task_scene, ram)：
    - `facts`：after.facts 的字段（where/dialog_text/options/cursor/map_id/…）。
    - `task_scene`：after 的 task 场景（`Observation.scene`，battle/walk/""）。
    - `ram`：截断流末帧的 RAM（机械规则用）。
    """
    facts: dict = {}
    task_scene = ""
    ram = None
    if rec.history:
        last = rec.history[-1].after
        facts = last.facts.model_dump(mode="json")
        task_scene = last.scene or ""
    stream = _truncated_stream(rec.candidate)
    frames = stream.frames()
    if frames:
        ram = frames[-1].content.ram
    return facts, task_scene, ram


def truth_for(rec: Reconstruction) -> Truth:
    """判定一条候选的真值草稿。

    - 有对应机械规则 → 跑规则自动赋真值（`method="mechanical"`）。
    - 否则 → 不赋真值；`_human_truth()` 的推测只落到 `suggested_achieved`，留待人工审阅。
    """
    c = rec.candidate
    check_id = check_id_for(c.criteria)
    if check_id is not None:
        stream = _truncated_stream(c)
        if not stream.frames():
            return Truth(
                None,
                None,
                check_id,
                None,
                None,
                None,
                [
                    {
                        "source": "trace",
                        "locator": _trace_locator(c, c.event_uuid),
                        "summary": "截断流里没有 sense 帧，机械规则不可跑",
                    }
                ],
            )
        verdict = RULES[check_id](stream, _sample_for(c, check_id))
        if verdict.outcome == "pass":
            return Truth(
                "mechanical", True, check_id, None, None, None, _mechanical_evidence(c, verdict)
            )
        if verdict.outcome == "fail":
            return Truth(
                "mechanical",
                False,
                check_id,
                _negative_mode_for(c, False, None),
                None,
                None,
                _mechanical_evidence(c, verdict),
            )
        return Truth(
            None,
            None,
            check_id,
            None,
            None,
            None,
            [
                {
                    "source": "trace",
                    "locator": _trace_locator(c, c.event_uuid),
                    "summary": f"机械规则不可判：{verdict.reason}",
                }
            ],
        )

    # 非机械样本：只给未审定建议，不赋真值。
    facts, task_scene, ram = _final_facts(rec)
    suggested = _human_truth(c, facts, task_scene, ram)
    if suggested is None:
        return Truth(None, None, None, None, None, None, [])
    suggested_achieved, summary, neg_hint = suggested
    evidence = [{"source": "step_memory", "locator": _step_memory_locator(rec), "summary": summary}]
    return Truth(
        None,
        None,
        None,
        None,
        suggested_achieved,
        _negative_mode_for(c, suggested_achieved, neg_hint),
        evidence,
    )


def _negative_mode_for(c: Candidate, achieved: bool, hint: str | None) -> str | None:
    if achieved:
        return None
    if hint is not None:
        return hint
    family = c.goal_family
    if family == "navigation":
        return "wrong_map_or_location"
    if family == "interaction":
        return "wrong_dialogue_or_event"
    return "required_state_missing"


def _where_match(facts: dict, x: int, y: int) -> bool:
    where = str(facts.get("where", ""))
    return f"x={x}" in where and f"y={y}" in where


def _human_truth(
    c: Candidate, facts: dict, task_scene: str, ram: object
) -> tuple[bool, str, str | None] | None:
    """据 criteria 文本 + 最终帧证据给一条人工草稿（无对应机械规则时）。

    返回 (achieved, evidence, negative_hint) 或 None（无法独立判定 → 待审）。
    **保守**：只处理能明确判定的单条件（或能拆清的简单「或」）；其余返回 None。
    """
    import re

    crit = c.criteria
    dialog = str(facts.get("dialog_text", ""))
    options = list(facts.get("options", []) or [])
    cursor = facts.get("cursor")
    scene = facts.get("scene")  # 判据侧「场景」= facts.scene（battle / None）

    # 1) 场景不再是 battle（可带「或出现战斗结束文字」）。
    if "场景不再是 battle" in crit or "scene 不再是 battle" in crit:
        ended = scene != "battle"
        end_text = any(
            t in dialog for t in ("fainted", "caught", "Can't escape", "Got away", "broke free")
        )
        ok = ended or end_text
        return (ok, f"末帧 scene={scene!r} dialog={dialog!r}，判据要求战斗已结束", None)

    # 2) 位置：where 显示 x=X y=Y（单条件，无 facing、无「或」）。
    if "where 显示 x=" in crit and "y=" in crit and "facing" not in crit and "或" not in crit:
        m = re.search(r"x=(\d+)\s+y=(\d+)", crit)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            ok = _where_match(facts, x, y)
            return (ok, f"末帧 where={facts.get('where')!r}，判据要求 x={x} y={y}", None)

    # 3) 位置 + facing（单条件「且」）。
    if "facing" in crit and "或" not in crit:
        m = re.search(r"x=(\d+)\s+y=(\d+)", crit)
        fm = re.search(r"facing 为 (\w+)|facing 朝(\w+)", crit)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            want = (fm.group(1) or fm.group(2)) if fm else None
            ok_pos = _where_match(facts, x, y)
            if want is None:
                return (ok_pos, f"末帧 where={facts.get('where')!r}，判据要求 x={x} y={y}", None)
            facing = str(facts.get("facing", ""))
            ok_facing = facing == want
            return (
                ok_pos and ok_facing,
                f"末帧 where={facts.get('where')!r} facing={facing!r}，判据要求 x={x} y={y} "
                f"facing={want}",
                None,
            )

    # 4) 光标在 ITEM 上（无对应机械规则）。
    if "光标在 ITEM" in crit and "或" not in crit:
        ok = cursor == "ITEM"
        return (ok, f"末帧 cursor={cursor!r}，判据要求 ITEM", None)

    # 5) 治疗完成文字（单条件）。
    if "治疗完成" in crit or "We hope to see you again" in crit:
        ok = any(t in dialog for t in ("see you again", "恢复", "欢迎再来"))
        return (ok, f"末帧 dialog_text={dialog!r}", None)

    # 6) 对话出现（单条件，无「或」）。
    if (
        "对话里出现过" in crit or "对话框里出现过" in crit or "对话框里出现" in crit
    ) and "或" not in crit:
        return (bool(dialog), f"末帧 dialog_text={dialog!r}", None)

    # 7) HEAL/CANCEL 选项（单条件）。
    if "HEAL 与 CANCEL" in crit:
        ok = "HEAL" in options and "CANCEL" in options
        return (ok, f"末帧 options={options!r}", None)

    # 8) 简单「或」：对话框里出现 X，或出现 BUY/SELL/QUIT 选项。
    if "或出现 BUY" in crit or "或出现 BUY / SELL / QUIT" in crit:
        ok = bool(dialog) or any(o in options for o in ("BUY", "SELL", "QUIT"))
        return (ok, f"末帧 dialog={dialog!r} options={options!r}", None)

    return None


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #


def _draft_record(rec: Reconstruction, truth: Truth) -> dict:
    c = rec.candidate
    # 完整 request 原样保留（含每条 ActMemory 的 before_frame / after_frame）。
    req_body = rec.request.model_dump(mode="json")
    return {
        "candidate_id": f"{c.source_choose_case}@{c.step}",
        "event_uuid": c.event_uuid,
        "run_id": c.run_id,
        "episode_id": c.episode_id,
        "task_id": c.task_id,
        "step": c.step,
        "source_batch": c.source_batch,
        "source_choose_case": c.source_choose_case,
        "goal": c.goal,
        "criteria": c.criteria,
        "goal_family": c.goal_family,
        "request": req_body,
        "request_sha256": rec.request_sha256,
        "prompt_exact": rec.prompt_exact,
        "image_bound": rec.image_bound,
        "image_sha256s": rec.image_sha256s,
        "n_history": len(rec.history),
        "n_images": len(rec.judge_images),
        "truth_method": truth.method,
        "achieved": truth.achieved,
        "check_id": truth.check_id,
        "negative_mode": truth.negative_mode,
        "suggested_achieved": truth.suggested_achieved,
        "suggested_negative_mode": truth.suggested_negative_mode,
        "evidence": truth.evidence,
        "capture_version_limit": c.capture_version_limit,
    }


def _write_drafts(drafts: list[dict]) -> None:
    with _DRAFT_JSONL.open("w", encoding="utf-8", newline="\n") as f:
        for d in drafts:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def _write_review_csv(drafts: list[dict]) -> None:
    cols = [
        "candidate_id",
        "source_choose_case",
        "step",
        "goal_family",
        "goal",
        "criteria",
        "truth_method",
        "achieved",
        "check_id",
        "negative_mode",
        "suggested_achieved",
        "suggested_negative_mode",
        "prompt_exact",
        "image_bound",
        "evidence",
    ]
    with _REVIEW_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in drafts:
            row = {k: d.get(k, "") for k in cols}
            row["achieved"] = (
                "" if d["achieved"] is None else ("true" if d["achieved"] else "false")
            )
            row["suggested_achieved"] = (
                ""
                if d["suggested_achieved"] is None
                else ("true" if d["suggested_achieved"] else "false")
            )
            row["evidence"] = "; ".join(f"{e['locator']}: {e['summary']}" for e in d["evidence"])
            w.writerow(row)


def _write_coverage(drafts: list[dict]) -> None:
    n = len(drafts)
    prompt_exact = sum(1 for d in drafts if d["prompt_exact"])
    image_bound = sum(1 for d in drafts if d["image_bound"])
    mechanical = sum(1 for d in drafts if d["truth_method"] == "mechanical")
    mech_true = sum(1 for d in drafts if d["achieved"] is True)
    mech_false = sum(1 for d in drafts if d["achieved"] is False)
    pending_human = n - mechanical
    suggested = sum(1 for d in drafts if d["suggested_achieved"] is not None)
    unsuggested = pending_human - suggested
    families = Counter(d["goal_family"] for d in drafts)
    neg_modes = Counter(d["negative_mode"] for d in drafts if d["negative_mode"])
    runs = {d["run_id"] for d in drafts}
    episodes = {d["episode_id"] for d in drafts}
    tasks = {(d["run_id"], d["episode_id"], d["task_id"]) for d in drafts}

    lines: list[str] = []
    lines.append("# brain_judge CP2 覆盖报告\n")
    lines.append(f"- 总候选：{n}")
    lines.append(f"- 唯一 run / episode / task：{len(runs)} / {len(episodes)} / {len(tasks)}")
    lines.append(f"- 请求重建（prompt 精确）：{prompt_exact}/{n}")
    lines.append(f"- 图片帧绑定（逐帧哈希一致）：{image_bound}/{n}")
    lines.append(f"- 机械判定（自动真值）：{mechanical}（达成 {mech_true}、未达成 {mech_false}）")
    lines.append(f"- 待人工审阅：{pending_human}（建议标签 {suggested}、未能建议 {unsuggested}）")
    lines.append("\n## goal family 分布\n")
    lines.append("| family | 候选数 |")
    lines.append("|---|---:|")
    for fam, cnt in sorted(families.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {fam} | {cnt} |")
    lines.append("\n## negative mode 分布（仅机械判负）\n")
    lines.append("| negative_mode | 数量 |")
    lines.append("|---|---:|")
    for nm, cnt in sorted(neg_modes.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {nm} | {cnt} |")
    lines.append("\n## 采集版本限制\n")
    lines.append(
        "- 原批 `task_capture_20261018_102238`：代码连续性无法证明（无采集前后源码摘要）。"
    )
    lines.append(
        "- 补采 `supplement_20261018_172952`：before/after HEAD 与 production SHA-256 一致"
        "（`73463bb` / `898a2504`）。"
    )
    lines.append(
        "\n> 本报告为 CP2 草稿覆盖，未经人工逐条审阅，不冻结 v2、不切换默认版本。"
        "建议标签仅为工具推测，不计入已审真值。\n"
    )
    _COVERAGE_MD.write_text("\n".join(lines), encoding="utf-8")


def run() -> list[dict]:
    candidates = dedupe(load_candidates())
    drafts: list[dict] = []
    for c in candidates:
        rec = reconstruct(c)
        truth = truth_for(rec)
        drafts.append(_draft_record(rec, truth))
    _write_drafts(drafts)
    _write_review_csv(drafts)
    _write_coverage(drafts)
    return drafts


if __name__ == "__main__":
    run()
