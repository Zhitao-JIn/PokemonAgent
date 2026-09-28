"""跑一遍：每帧算解码直出的分；给了模型就再问一次模型、算模型读后的分。只落盘，报表另算。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Template

from pokemon_agent.brain.providers import provider_for
from pokemon_agent.brain.schemas.completion import LlmCompleteReq

from .build import REPO_ROOT, load_samples, wram_bytes
from .grade import grade
from .observe import bucket, decoded_answer, observation_text, screen_text, task_facts
from .schemas import TAKEOVER_SCENES, SampleScore, ScreenAnswer, ScreenHeader, ScreenSample

RESULTS_ROOT = REPO_ROOT / "eval_results" / "screen"
PROMPT = Path(__file__).with_name("prompt.md")
HEADER, RESULTS = "header.json", "results.jsonl"


def run_suite(
    version: str,
    *,
    model: str | None,
    limit: int | None,
    workers: int,
    sample_ids: list[str] | None,
) -> Path:
    """跑一批，返回报告目录。`model=None` 只算解码直出（不调模型、不要密钥）。"""
    samples = load_samples(version)
    if sample_ids:
        samples = [s for s in samples if s.sample_id in set(sample_ids)]
    samples = samples[:limit] if limit else samples
    report_dir = RESULTS_ROOT / time.strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True)
    template = PROMPT.read_text(encoding="utf-8")

    # 步骤 1：口径头。
    header = ScreenHeader(
        report_id=report_dir.name,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        git_commit=_git("rev-parse", "HEAD"),
        git_dirty=bool(_git("status", "--porcelain", "--untracked-files=no")),
        model=model or "",
        prompt_sha256=hashlib.sha256(template.encode()).hexdigest(),
        samples_sha256=hashlib.sha256(
            "".join(s.model_dump_json() for s in samples).encode()
        ).hexdigest(),
        dataset_version=version,
    )
    (report_dir / HEADER).write_text(header.model_dump_json(indent=2), encoding="utf-8")

    # 步骤 2：逐帧打分（模型调用并发）。
    provider = provider_for(model, temperature=0.0, json_mode=True) if model else None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        scores = list(pool.map(lambda s: _score(s, template, provider), samples))
    (report_dir / RESULTS).write_text(
        "".join(s.model_dump_json() + "\n" for s in scores), encoding="utf-8"
    )
    return report_dir


def _score(sample: ScreenSample, template: str, provider: object | None) -> SampleScore:
    """一帧：解码直出 + （可选）模型读后。模型出错只记在这一帧上，不中断整批。"""
    text = screen_text(sample)
    decoded = decoded_answer(text, wram_bytes(sample))
    score = SampleScore(
        sample_id=sample.sample_id,
        source=sample.source,
        category=sample.category,
        bucket=sample.label.scene or bucket(text),
        decoded=decoded,
        decoded_ok=grade(decoded, sample.label, with_scene=True),
    )
    if provider is None or sample.label.scene in TAKEOVER_SCENES:
        return score
    prompt = Template(template).substitute(observation=observation_text(task_facts(text)))
    try:
        resp = provider.complete(LlmCompleteReq(prompt=prompt))  # type: ignore[attr-defined]
        answer = ScreenAnswer.model_validate(json.loads(_strip_fence(resp.text)))
    except Exception as exc:  # noqa: BLE001 —— 调用 / 解析失败都记成这一帧的错误
        return score.model_copy(update={"model_error": f"{type(exc).__name__}: {exc}"})
    return score.model_copy(
        update={
            "model": answer,
            "model_ok": grade(answer, sample.label, with_scene=False),
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
        }
    )


def _strip_fence(text: str) -> str:
    """容忍 ```json 包裹。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1].removeprefix("json").strip()
    return t


def _git(*args: str) -> str:
    """跑一条 git 只读命令（不加锁）取输出；没有 git 时给空串。"""
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return out.stdout.strip()


__all__ = ["HEADER", "RESULTS", "RESULTS_ROOT", "run_suite"]
