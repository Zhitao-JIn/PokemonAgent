"""费用护栏的合成离线测试。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts.cost_guard import BalanceUnavailable, CostGuard, fetch_cny_balance, run
from scripts.model_prices import estimate


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


@pytest.mark.parametrize("value", ["110.00", 110.0])
def test_fetch_cny_balance_accepts_string_and_number(value: object) -> None:
    response = FakeResponse(
        json.dumps({"balance_infos": [{"currency": "CNY", "total_balance": value}]}).encode()
    )

    balance = fetch_cny_balance("fake-secret", opener=lambda *args, **kwargs: response)

    assert balance == 110.0


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b'{"balance_infos":[{"currency":"USD","total_balance":"1"}]}', "CNY"),
        (b"not-json", "JSON"),
    ],
)
def test_fetch_cny_balance_rejects_missing_cny_and_bad_json(body: bytes, error: str) -> None:
    with pytest.raises(BalanceUnavailable, match=error):
        fetch_cny_balance("fake-secret", opener=lambda *args, **kwargs: FakeResponse(body))


@pytest.mark.parametrize(
    "failure", [HTTPError("https://example.test", 503, "bad", {}, None), TimeoutError()]
)
def test_fetch_cny_balance_hides_key_on_transport_errors(failure: Exception) -> None:
    with pytest.raises(BalanceUnavailable) as captured:
        fetch_cny_balance(
            "fake-secret", opener=lambda *args, **kwargs: (_ for _ in ()).throw(failure)
        )

    assert "fake-secret" not in str(captured.value)


def test_cost_guard_uses_minimum_and_inclusive_threshold() -> None:
    guard = CostGuard(100.0)
    guard.observe(80.01)
    assert guard.spent() == pytest.approx(19.99)
    assert not guard.exceeded()

    guard.observe(80.0)
    guard.observe(90.0)
    assert guard.spent() == pytest.approx(20.0)
    assert guard.exceeded()


class FakeProcess:
    pid = 123

    def __init__(self, polls: list[int | None]) -> None:
        self.polls = iter(polls)
        self.return_code = 0

    def poll(self) -> int | None:
        return next(self.polls, self.return_code)

    def wait(self) -> int:
        return self.return_code


def args_for(tmp_path: Path, fallback: Path | None = None) -> object:
    from argparse import Namespace

    return Namespace(
        command=["python", "run.py", "--api-key", "fake-secret"],
        report=tmp_path / "report.json",
        limit_cny=20.0,
        interval=0.01,
        fallback_trace_root=fallback,
        usd_cny=7.2,
        model="deepseek-flash",
    )


def test_polling_caps_at_threshold_and_redacts_report_and_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-secret")
    process = FakeProcess([None, None])
    balances = iter([100.0, 80.0, 80.0])
    ticks = iter([10.0, 11.0])
    killed: list[int] = []

    code = run(
        args_for(tmp_path),
        balance_reader=lambda key: next(balances),
        popen=lambda *args, **kwargs: process,
        sleeper=lambda _: None,
        clock=lambda: next(ticks),
        terminator=lambda child: killed.append(child.pid),
    )
    report_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    output = capsys.readouterr()

    assert code == 75
    assert killed == [123]
    assert json.loads(report_text)["capped"] is True
    assert json.loads(report_text)["elapsed_seconds"] == 1.0
    assert "***" in report_text
    assert "fake-secret" not in report_text + output.out + output.err


def test_polling_does_not_cap_below_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-secret")
    process = FakeProcess([None, 0])
    balances = iter([100.0, 80.01, 80.01])
    killed: list[int] = []

    code = run(
        args_for(tmp_path),
        balance_reader=lambda key: next(balances),
        popen=lambda *args, **kwargs: process,
        sleeper=lambda _: None,
        terminator=lambda child: killed.append(child.pid),
    )

    assert code == 0
    assert killed == []
    assert json.loads((tmp_path / "report.json").read_text())["spent_cny"] == pytest.approx(19.99)


def test_estimate_fallback_uses_shared_prices_and_marks_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-secret")
    trace_root = tmp_path / "traces"
    call_dir = trace_root / "runs" / "sample" / "trace"
    call_dir.mkdir(parents=True)
    content = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "input_tokens": "1000000",
        "cached_tokens": "0",
        "output_tokens": "0",
        "ok": "true",
    }
    (call_dir / "one.json").write_text(
        json.dumps({"type": "model_call", "content": json.dumps(content)})
    )
    process = FakeProcess([0])
    args = args_for(tmp_path, call_dir)

    code = run(
        args,
        balance_reader=lambda key: (_ for _ in ()).throw(BalanceUnavailable("offline")),
        popen=lambda *args, **kwargs: process,
        sleeper=lambda _: None,
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert code == 0
    assert report["spent_cny"] == pytest.approx(estimate("deepseek-flash", 1_000_000, 0, 0) * 7.2)
    assert report["cost_source"] == "estimate"
    assert "费用来自估算，不是余额" in report["note"]


def test_unavailable_balance_without_fallback_does_not_start_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-secret")
    started: list[bool] = []

    code = run(
        args_for(tmp_path),
        balance_reader=lambda key: (_ for _ in ()).throw(BalanceUnavailable("offline")),
        popen=lambda *args, **kwargs: started.append(True),
    )

    assert code == 1
    assert started == []
    report = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "offline" in report
    assert "fake-secret" not in report
