"""真实生产摘要门面加假 provider/grader，跑完三层冻结集合而不启动模拟器。"""

import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from _doubles.llm import ScriptedJudge, vision_reply
from _harness_fixtures.app_config import call_policy
from inspect_ai import eval
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessage, ContentImage

from evals.brain_summary import dataset, solver, task
from evals.brain_summary.contract import DIMENSIONS
from evals.dataset.errors import DatasetError
from pokemon_agent.brain import Brain
from pokemon_agent.brain.interface import EpisodeSummary
from pokemon_agent.direct.brain_tool import RunSummarizer, Summarizer, TaskSummarizer
from pokemon_agent.prompt import PromptGateway


class Grader:
    """固定评分员，记录实际输入以核对证据口径。"""

    def __init__(self) -> None:
        self.messages: list[list[ChatMessage]] = []

    async def generate(self, messages: list[ChatMessage]) -> SimpleNamespace:
        self.messages.append(messages)
        evidence = {"source_evidence": "当前输入", "candidate_evidence": "summary", "reason": "r"}
        result = {
            "dimensions": [{"name": n, "score": 0.75, **evidence} for n in DIMENSIONS],
            "major_distortion": {"present": False, **evidence},
        }
        return SimpleNamespace(completion=json.dumps(result))


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_summary_dataset_freezes_inputs_rubric_and_layer_counts() -> None:
    cases = dataset.load()

    assert len(cases) == len({case.case_id for case in cases}) == 81
    assert Counter(case.layer for case in cases) == {"task": 41, "episode": 20, "run": 20}
    assert all(
        [item.name for item in case.reference.criteria] == list(DIMENSIONS) for case in cases
    )


def test_summary_dataset_detects_rubric_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = dataset.DEFAULT_VERSION
    source = dataset.ROOT / version
    target = tmp_path / version
    target.mkdir()
    (target / "manifest.json").write_bytes((source / "manifest.json").read_bytes())
    (target / "rubric.json").write_bytes((source / "rubric.json").read_bytes() + b" ")
    monkeypatch.setattr(dataset, "ROOT", tmp_path)

    with pytest.raises(DatasetError, match="manifest/source mismatch"):
        dataset.load()


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_all_summary_layers_use_production_prompts_and_independent_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = EpisodeSummary(
        summary="具体总结",
        reason="结论",
        quality_score=0.1,
        quality_rationale="原料有限",
        markdown="记忆正文",
    )
    provider = ScriptedJudge(
        *[vision_reply(answer.model_dump_json()) for _ in range(81)], multimodal=True
    )
    brain = Brain(summary_llm=provider)
    prompt_gateway = PromptGateway(None)
    tools = SimpleNamespace(
        summarizer=Summarizer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        task_summarizer=TaskSummarizer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
        run_summarizer=RunSummarizer(brain, policy=call_policy(), prompt_gateway=prompt_gateway),
    )
    built: list[dict[str, object]] = []
    monkeypatch.setattr(
        solver,
        "single_link_brain",
        lambda link, model: built.append({link: model}) or tools,
    )
    cases = dataset.load()
    cases[0].reference.criteria[0].instruction += " REF_ONLY_SENTINEL"
    monkeypatch.setattr(task, "load", lambda version: cases)
    grader = Grader()
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr("evals.common.grader_model.get_model", lambda model, **kwargs: grader)
    log = eval(
        task.brain_summary(model="fake-summary", grader_model="fake-grader"),
        log_dir=str(tmp_path),
        display="none",
    )[0]

    assert log.status == "success" and log.results is not None
    assert log.results.total_samples == 81
    assert not [sample for sample in log.samples or [] if sample.error]
    assert built == [{"summary": "fake-summary"}]
    assert len(provider.described) == len(grader.messages) == 81
    assert all("REF_ONLY_SENTINEL" not in request.prompt for request in provider.described)
    assert any("REF_ONLY_SENTINEL" in messages[1].content[0].text for messages in grader.messages)
    assert_real_contexts_and_metrics(provider, grader.messages, log)


def assert_real_contexts_and_metrics(
    provider: ScriptedJudge, messages: list[list[ChatMessage]], log: EvalLog
) -> None:
    """真实发送的所有 prompt 逐个出现在评分输入，来源章没有混进候选。"""
    expected = {hashlib.sha256(r.prompt.encode()).hexdigest(): r.images for r in provider.described}
    actual = set()
    for pair in messages:
        text = pair[1].content[0].text
        prompt = text.split("生产上下文：\n", 1)[1].split("\n候选输出：\n", 1)[0]
        key = hashlib.sha256(prompt.encode()).hexdigest()
        actual.add(key)
        assert [
            item.image for item in pair[1].content if isinstance(item, ContentImage)
        ] == expected[key]
        body = text.split("\n候选输出：\n", 1)[1].split("\n独立 reference：\n", 1)[0]
        assert set(json.loads(body)) == set(EpisodeSummary.model_fields)
    assert actual == set(expected)
    assert log.results is not None
    scores = next(score for score in log.results.scores if "quality_mean" in score.metrics)
    assert scores.metrics["quality_mean"].value == 0.75
    assert scores.metrics["quality_n"].value == 81
    assert scores.metrics["major_distortion_rate"].value == 0
    assert [scores.metrics[f"{layer}_quality_n"].value for layer in ("task", "episode", "run")] == [
        41,
        20,
        20,
    ]
