"""探针的预算、脱敏、汇总与离线入口；不访问网络。"""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from pokemon_agent.brain.errors import ProviderRejected, ToolTimeout
from pokemon_agent.brain.schemas import LlmCompleteResp, VisionDescribeResp
from scripts import probe_models as probe


class FakeProvider:
    """按固定 usage 回答，保存调用数与单次超时。"""

    def __init__(self) -> None:
        self.calls = 0

    def config(self) -> dict[str, str]:
        return {"provider": "fake"}

    def complete(self, request: object, *, timeout_s: float) -> LlmCompleteResp:
        self.calls += 1
        assert timeout_s > 0
        return LlmCompleteResp(
            text='{"action":"a"}',
            prompt_tokens=1500,
            completion_tokens=10,
            cached_tokens=1000,
            reasoning_tokens=3,
        )

    def describe(self, request: object, *, timeout_s: float) -> VisionDescribeResp:
        self.calls += 1
        return VisionDescribeResp(
            text="左半边是红色，右半边是蓝色", input_tokens=300, output_tokens=10
        )


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in probe.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    def no_network(*args: object, **kwargs: object) -> None:
        pytest.fail("network forbidden")

    monkeypatch.setattr("urllib.request.urlopen", no_network)


def test_args_enforce_paths_and_authorized_limits(tmp_path: object) -> None:
    args = probe.parse_args(["--out", str(tmp_path), "--dry-run"])
    assert args.max_requests == 60
    assert args.max_cost_usd == 0.3
    assert args.dry_run
    for options in (
        ["--out", "relative"],
        ["--out", str(tmp_path), "--max-requests", "61"],
        ["--out", str(tmp_path), "--max-cost-usd", "0.4"],
    ):
        with pytest.raises(SystemExit):
            probe.parse_args(options)


def test_env_file_preserves_existing_values_and_prints_nothing(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    path = tmp_path / "env"
    path.write_text('# comment\n\nOPENAI_API_KEY="fake-new"\nCUSTOM=one=two\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-existing")
    monkeypatch.delenv("CUSTOM", raising=False)

    probe.load_environment(path)

    import os

    assert os.environ["OPENAI_API_KEY"] == "fake-existing"
    assert os.environ["CUSTOM"] == "one=two"
    assert capsys.readouterr().out == ""
    monkeypatch.delenv("CUSTOM")


def test_redaction_removes_env_secrets_and_key_shaped_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-unique-secret")
    text = probe.redact("fake-unique-secret sk-other-secret Bearer opaque-credential")
    assert "fake-unique-secret" not in text
    assert "sk-other-secret" not in text
    assert "opaque-credential" not in text


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-haiku-5-5", 0.000054),
        ("gpt-6-luna", 0.000054),
        ("qwen3.8-flash", 0.0000724),
        ("deepseek-flash", 0.0001752),
    ],
)
def test_price_table_counts_cached_input_and_output_once(model: str, expected: float) -> None:
    assert probe.estimate(model, 1000, 600, 16) == pytest.approx(expected)


def test_cost_gate_stops_at_eighty_percent() -> None:
    budget = probe.Budget(cost=0.239999)
    assert budget.stopped() == ""
    budget.cost = 0.24
    assert budget.stopped() == "因费用闸提前停止"


def test_summary_uses_min_median_max_and_weighted_cache_rate() -> None:
    item = probe.candidates("c2")[0]
    records = [
        probe.Record(
            name=item.name,
            kind="text",
            index=n,
            latency=float(n),
            prompt_tokens=100,
            cached_tokens=50,
            json_valid=True,
            reasoning_tokens=3,
        )
        for n in range(1, 7)
    ]

    report = probe.summary([item], records, {}, probe.Budget(requests=6), "")

    assert "1.000/3.500/6.000" in report
    assert "50.0%" in report
    assert "6/6" in report
    assert "p95" not in report


def test_png_has_expected_dimensions_and_colors() -> None:
    png = base64.b64decode(probe.image_uri().split(",", 1)[1])
    image = Image.open(io.BytesIO(png))
    assert image.size == (160, 144)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((159, 143)) == (0, 0, 255)


def test_dry_run_never_sends_or_creates_output(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(probe.Candidate, "build", lambda self: FakeProvider())
    output = tmp_path / "results"

    assert probe.run(probe.parse_args(["--out", str(output), "--dry-run"])) == 0

    assert not output.exists()
    assert len(json.loads(capsys.readouterr().out)["configs"]) == 7


def test_missing_keys_are_unavailable_without_sending(tmp_path: object) -> None:
    output = tmp_path / "results"

    probe.run(probe.parse_args(["--out", str(output)]))

    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(result["unavailable"]) == 8
    assert result["budget"]["requests"] == 0


def test_request_limit_truncates_schedule(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeProvider()
    monkeypatch.setattr(probe.Candidate, "build", lambda self: fake)
    output = tmp_path / "results"

    probe.run(probe.parse_args(["--out", str(output), "--max-requests", "3"]))

    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert fake.calls == result["budget"]["requests"] == 3
    assert result["stop_reason"] == "达到请求数上限"


def test_all_first_calls_failing_stops_before_second_calls(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(self: FakeProvider, request: object, *, timeout_s: float) -> None:
        self.calls += 1
        raise ToolTimeout("offline")

    fake = FakeProvider()
    monkeypatch.setattr(probe.Candidate, "build", lambda self: fake)
    monkeypatch.setattr(FakeProvider, "complete", failed)
    output = tmp_path / "results"

    probe.run(probe.parse_args(["--out", str(output)]))

    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert fake.calls == 4
    assert "首次调用失败" in result["stop_reason"]


def test_auth_failure_skips_rest_of_that_model(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(candidate: probe.Candidate) -> FakeProvider:
        if candidate.model == "gpt-6-luna":
            raise RuntimeError("missing key")
        return FakeProvider()

    monkeypatch.setattr(probe.Candidate, "build", build)
    output = tmp_path / "results"
    probe.run(probe.parse_args(["--out", str(output)]))
    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert "c2_off" in result["unavailable"]
    assert result["budget"]["requests"] <= 60


def test_first_auth_error_is_classified_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(self: FakeProvider, request: object, *, timeout_s: float) -> None:
        raise ProviderRejected("OpenAIProvider HTTP 401: sk-private")

    monkeypatch.setattr(FakeProvider, "complete", failed)

    result = probe.call(probe.candidates("c2")[0], FakeProvider(), "text", 1)

    assert result.status == 401
    assert result.error == "ProviderRejected"
    assert "sk-private" not in result.message


def test_accumulated_cost_gate_stops_the_run(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe.Candidate, "build", lambda self: FakeProvider())

    def costly(candidate: probe.Candidate, provider: object, kind: str, index: int) -> probe.Record:
        return probe.Record(name=candidate.name, kind=kind, index=index, estimated_cost=0.12)

    monkeypatch.setattr(probe, "call", costly)
    output = tmp_path / "results"

    probe.run(probe.parse_args(["--out", str(output)]))

    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert result["budget"]["requests"] == 2
    assert result["budget"]["cost"] == pytest.approx(0.24)
    assert result["stop_reason"] == "因费用闸提前停止"


def test_initial_auth_rejection_skips_both_modes(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Rejected(FakeProvider):
        def complete(self, request: object, *, timeout_s: float) -> None:
            raise ProviderRejected("ClaudeProvider HTTP 403: denied")

    def build(candidate: probe.Candidate) -> FakeProvider:
        return Rejected() if candidate.model == "claude-haiku-5-5" else FakeProvider()

    monkeypatch.setattr(probe.Candidate, "build", build)
    output = tmp_path / "results"

    probe.run(probe.parse_args(["--out", str(output)]))

    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len([r for r in result["records"] if r["name"].startswith("c1")]) == 1


def test_factory_forwards_claude_cache_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    from _doubles.http import FakeUrlopen

    from pokemon_agent.brain.providers import provider_for

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    fake = FakeUrlopen(body={"content": [{"type": "text", "text": "ok"}]})
    monkeypatch.setattr("urllib.request.urlopen", fake)

    provider_for("claude-haiku-5-5", temperature=0, cache_marker="<tail>").complete(
        probe.LlmCompleteReq(prompt="rules<tail>dynamic")
    )

    assert fake.calls[0]["json"]["messages"][0]["content"] == [
        {"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "<tail>dynamic"},
    ]


def test_suite_defaults_preserve_base_and_limit_supplement(tmp_path: object) -> None:
    base = probe.parse_args(["--out", str(tmp_path)])
    extra = probe.parse_args(["--out", str(tmp_path), "--suite", "supplement"])
    assert (base.suite, base.max_requests, base.max_cost_usd) == ("base", 60, 0.3)
    assert (extra.max_requests, extra.max_cost_usd) == (30, 0.08)
    for option in (["--max-requests", "31"], ["--max-cost-usd", "0.081"], ["--cache-only"]):
        with pytest.raises(SystemExit):
            probe.parse_args(["--out", str(tmp_path), "--suite", "supplement", *option])


def test_green_yellow_png_keeps_default_red_blue_unchanged() -> None:
    for uri, left, right in (
        (probe.image_uri(), (255, 0, 0), (0, 0, 255)),
        (probe.image_uri((0, 255, 0), (255, 255, 0)), (0, 255, 0), (255, 255, 0)),
    ):
        image = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        assert image.size == (160, 144)
        assert image.getpixel((79, 72)) == left
        assert image.getpixel((80, 72)) == right


@pytest.mark.parametrize(
    "text,count,expected",
    [
        ('{"images":[{"left":"红色","right":"蓝"}]}', 1, True),
        ('{"images":[{"left":"RED","right":"blue"},{"left":"green","right":"黄色"}]}', 2, True),
        ('{"images":[{"left":"红","right":"蓝"}]}', 2, False),
        ('{"images":[{"left":"蓝","right":"红"}]}', 1, False),
        ("not JSON", 1, False),
        ('```json\n{"images":[{"left":"red","right":"blue"}]}\n```', 1, False),
        ("[]", 1, False),
        ('{"images":[null]}', 1, False),
    ],
)
def test_image_answer_requires_json_count_and_true_colors(
    text: str, count: int, expected: bool
) -> None:
    assert probe.image_answer_correct(text, count) is expected


@pytest.mark.parametrize("position", [0, 1, 2])
def test_supplement_image_instances_disable_token_floor_only_locally(
    position: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from _doubles.http import FakeUrlopen, ok_body

    for name in probe.KEY_NAMES[:3]:
        monkeypatch.setenv(name, "fake-key")
    item = probe.supplement_candidates()[position]
    body = (
        {
            "content": [{"type": "text", "text": '{"images":[{"left":"red","right":"blue"}]}'}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        if position == 0
        else ok_body(text='{"images":[{"left":"red","right":"blue"}]}', prompt_tokens=1)
    )
    fake = FakeUrlopen(body=body)
    monkeypatch.setattr("urllib.request.urlopen", fake)

    result = probe.supplement_call(item, item.build(), 1)

    assert result.error == ""
    assert result.image_correct is True
    assert result.prompt_tokens == 1
    assert result.old_floor == 100
    assert fake.calls[0]["json"].get("max_tokens", 2048) == 2048


def test_supplement_schedule_is_twenty_five_requests_and_waits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = probe.supplement_candidates()
    providers = {item.name: FakeProvider() for item in items}
    waits = []
    monkeypatch.setattr(probe.time, "sleep", waits.append)

    records, reason = probe.execute_supplement(
        items, providers, probe.Budget(max_requests=30, max_cost=0.08)
    )

    assert len(records) == 25
    assert sum(r.kind == "image" for r in records) == 12
    assert sum(r.name == "luna_cache_long" for r in records) == 7
    assert sum(r.name == "claude_cache_long" for r in records) == 6
    assert waits == [15]
    assert records[18].waited_seconds == 15
    assert all(r.cache_creation_input_tokens is None for r in records)
    assert reason == ""


def test_supplement_request_and_cost_gates_prevent_later_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = probe.supplement_candidates()
    providers = {item.name: FakeProvider() for item in items}
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: pytest.fail("must stop before wait"))
    records, reason = probe.execute_supplement(
        items, providers, probe.Budget(max_requests=3, max_cost=0.08)
    )
    assert len(records) == 3
    assert reason == "达到请求数上限"
    records, reason = probe.execute_supplement(
        items, providers, probe.Budget(cost=0.064, max_cost=0.08)
    )
    assert records == []
    assert reason == "因费用闸提前停止"


def test_supplement_dry_run_never_sends_and_requires_every_key(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    for name in probe.KEY_NAMES[:3]:
        monkeypatch.setenv(name, "fake-key")
    args = probe.parse_args(["--suite", "supplement", "--out", str(tmp_path / "out"), "--dry-run"])

    assert probe.run(args) == 0

    result = json.loads(capsys.readouterr().out)
    assert len(result["configs"]) == 5
    assert result["unavailable"] == {}
    assert not args.out.exists()
    monkeypatch.delenv("OPENAI_API_KEY")
    assert probe.run(args) == 1
    assert "fake-key" not in capsys.readouterr().out
