"""跨 run 的每链路（Source）token/延迟聚合报表——`evaluation/SPEC.md` 第十节实现。

# 为什么延迟不额外记字段，而是拿 ts 差近似（Δt 归本事件）

`ModelCall.payload` 是 `dict[str,str]`（`schemas/domain/model_call.py`）——历史上
短暂出现过 `payload["latency_ms"]`（旧版 `trace_data/` 样本里还能看到），后来去掉
了。给每类事件塞专门的耗时字段是给 trace 加一处新的维护面；而 `ts` 本来就是每
条事件都有的字段，事件的写入顺序已经隐含了"这段时间花在哪一步"。这里用相邻
事件的 `ts` 差近似延迟，不新增字段——归因不准的地方就是 trace 记录密度不够，
根治方向是以后补事件边界，不是现在给每类事件都加时间戳字段
（详见 `evaluation/SPEC.md` 十·3）。

# 为什么这个模块不 import pokemon_agent

只解析 trace JSONL 的字面结构，`evaluation/` 才能独立于主包的重依赖
（`agent-permission`/`fastembed`）被测试和运行。
`EventType`/`Source` 在这里以字符串字面量出现，跟 `schemas/datastore/__init__.py`
的枚举值如果漂移，读到未知值时按"计入总数但归类为其字面值"处理，不假装认识。
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
from dataclasses import dataclass, field

STORAGE_ROOT = pathlib.Path("trace_data")
REPORTS_ROOT = pathlib.Path("experiment_results/eval_reports")


# =====================================================================
# 读侧：read_run_events —— evaluation/SPEC.md 十·2
# =====================================================================


@dataclass(frozen=True)
class Event:
    """trace 事件的字面切片——只留聚合用得到的字段，不是 `TraceEvent` 的完整翻译。"""

    event_id: int
    run_id: str
    episode_id: str
    step: int
    type: str
    source: str
    payload: dict[str, str]
    ts: float


def read_run_events(run_id: str, storage_root: pathlib.Path = STORAGE_ROOT) -> list[Event]:
    """扫 `trace_data/<run_id>/episodes/*.jsonl`，按 `event_id` 升序返回。

    前置：`run_id` 非空。
    后置：返回列表按 `event_id` 严格升序；解析失败的残行（进程被杀留下的半行
    JSON）直接跳过，不中断——`trace/store.py` 的 `_episode_is_complete` 已有
    跳过残行的先例，这里对齐同样的宽容度。run 级事件（`episode_id == run_id`）
    和局级事件（`episode_id == f"{run_id}-epN"`）落在同一个目录，一次 glob
    就能扫全，`event_id` 在同一个 run 内本来就唯一、跨文件全局单调
    （`trace/store.py::LocalTrace`），排序即完成"归并"，不需要多路归并逻辑。
    """
    assert run_id, "run_id 不能为空"
    episodes_dir = storage_root / run_id / "episodes"
    if not episodes_dir.is_dir():
        return []

    events: list[Event] = []
    for path in sorted(episodes_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                events.append(
                    Event(
                        event_id=raw["event_id"],
                        run_id=raw["run_id"],
                        episode_id=raw["episode_id"],
                        step=raw["step"],
                        type=raw["type"],
                        source=raw["source"],
                        payload=raw.get("payload", {}),
                        ts=raw["ts"],
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue  # 残行：写到一半被杀的进程留下的半条 JSON，不计入、不报错

    events.sort(key=lambda e: e.event_id)
    return events


# =====================================================================
# 聚合核心：aggregate_events —— evaluation/SPEC.md 十·3 / 十·4
# =====================================================================


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _percentile(values: list[float], pct: float) -> float | None:
    """最近秩（nearest-rank）分位数——报表读数用，不需要插值精度。"""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


@dataclass
class SourceMetrics:
    """一条链路（`Source`）的聚合结果——字段对应 `evaluation/SPEC.md` 十·4 的表。"""

    calls: int = 0
    ok: int = 0
    failed: int = 0
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    """`payload["cached_tokens"]`（0905 新增，DashScope/火山方舟隐式缓存
    命中的 token 数）之和——**缺这个字段不算 `malformed`**，跟
    `tokens_in`/`tokens_out` 不是同一种缺失：老事件（这次改动之前落盘的）
    压根没有这个键，那是"这条数据比这个字段年长"，不是"这条数据本该有
    却读不出来"，缺了就当 0，不计入失效统计。"""
    malformed: int = 0
    """token 字段解析失败的次数——不是"没调用"，是"调用记了、token 数读不出"。"""
    error_kinds: dict[str, int] = field(default_factory=dict)
    degraded: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    """Δt 样本（十·3 口径）。渲染报表时才取分位数，聚合阶段不折叠掉明细。"""
    verify_total: int = 0
    """`Source.VERIFY` 的 `payload["verdicts"]`（`tools/trace_render.py::verify_call` 结构化
    落的那份，`StepVerifyVerdict` 列表）里数出来的判定条数——只对 `source ==
    "verify"` 有意义，其余链路恒为 0。"""
    verify_unreliable: int = 0
    """上面 `verify_total` 条判定里 `reliable == False` 的条数——校验器自己的
    失效率 = `verify_unreliable / verify_total`（`Source.VERIFY` 枚举注释里
    "算得出校验器自己的失效率"这句期望，在这里第一次被兑现，
    见 `docs/ROADMAP.md` P2"可审计"）。"""
    verify_parse_errors: int = 0
    """`payload["verdicts"]` 存在但解析失败（不是合法 JSON，或不是列表）的次数
    ——跟 `malformed`（token 字段）是并列的另一种"记了账但读不出细节"。"""
    tokens_reasoning: int = 0
    """`payload["reasoning_tokens"]`（0907 新增，思考模型的推理 token）
    之和——它包含在 `tokens_out` 里（completion_tokens 的一部分），单列是
    为了把"输出成本"拆成"结论 + 思考"两块：思考模型的 out 大头往往是思考
    （实测 max_tokens=8 挡不住 reasoning 跑到 1.9k）。缺字段当 0，
    同 `tokens_cached` 的口径（老事件比字段年长，不算 malformed）。"""

    @property
    def verify_unreliable_rate(self) -> float | None:
        return self.verify_unreliable / self.verify_total if self.verify_total else None

    @property
    def p50(self) -> float | None:
        return _percentile(self.latencies, 50)

    @property
    def p90(self) -> float | None:
        return _percentile(self.latencies, 90)

    @property
    def max_latency(self) -> float | None:
        return max(self.latencies) if self.latencies else None


@dataclass
class RunSummary:
    """一个 run 的收尾快照：episode 数、成败、token、时长。"""

    run_id: str
    episodes: int = 0
    succeeded: int = 0
    failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_reasoning: int = 0
    duration: float | None = None
    """`RUN_END.ts − RUN_START.ts`；这次 run 跑在这两个事件补上之前，留空
    （`docs/ROADMAP.md` 第 4 条 a，0902 之前的 run 没有这两条事件）。"""


@dataclass
class AggregateResult:
    by_source: dict[str, SourceMetrics]
    runs: list[RunSummary]


def aggregate_events(events: list[Event]) -> AggregateResult:
    """按 `Source` 聚合 token/延迟/失败/降级，按 `run_id` 汇总 episode 数与成败。

    调用方可以把多个 run 的事件直接拼接传入——**Δt 只在同一个 run 内部的相邻
    事件间计算**：先按 `run_id` 分组、组内按 `event_id` 排序再算 Δt，不会把
    "上一个 run 最后一条事件"和"下一个 run 第一条事件"错当成相邻去算延迟
    （`evaluation/SPEC.md` 十·3：Δt 是"归本事件"的相对量，跨 run 没有意义）。
    组间顺序不影响结果——聚合只做计数与分布，不依赖 run 间相对顺序。
    """
    by_source: dict[str, SourceMetrics] = {}
    runs: list[RunSummary] = []

    by_run: dict[str, list[Event]] = {}
    for event in events:
        by_run.setdefault(event.run_id, []).append(event)

    for run_id, run_events in by_run.items():
        run_events = sorted(run_events, key=lambda e: e.event_id)
        summary = RunSummary(run_id=run_id)
        run_start_ts: float | None = None
        run_end_ts: float | None = None
        prev_ts: float | None = None

        for event in run_events:
            dt = None if prev_ts is None else event.ts - prev_ts
            prev_ts = event.ts

            kind = event.payload.get("kind", "") if event.type == "lifecycle" else ""
            if event.type == "lifecycle" and kind == "run_start":
                run_start_ts = event.ts
            elif event.type == "lifecycle" and kind == "run_end":
                run_end_ts = event.ts
            elif event.type == "lifecycle" and kind == "episode_start":
                summary.episodes += 1
            elif event.type == "lifecycle" and kind == "episode_end":
                if event.payload.get("success") == "True":
                    summary.succeeded += 1
                elif event.payload.get("success") == "False":
                    summary.failed += 1

            metrics = by_source.setdefault(event.source, SourceMetrics())

            if event.type == "model_call":
                metrics.calls += 1
                ok = event.payload.get("ok")
                if ok == "True":
                    metrics.ok += 1
                elif ok == "False":
                    metrics.failed += 1
                attempt = _parse_int(event.payload.get("attempt"))
                if attempt is not None:
                    metrics.retries += max(0, attempt - 1)
                tokens_in = _parse_int(event.payload.get("input_tokens"))
                tokens_out = _parse_int(event.payload.get("output_tokens"))
                if tokens_in is None:
                    metrics.malformed += 1
                else:
                    metrics.tokens_in += tokens_in
                    summary.tokens_in += tokens_in
                if tokens_out is None:
                    metrics.malformed += 1
                else:
                    metrics.tokens_out += tokens_out
                    summary.tokens_out += tokens_out
                # 缺 cached_tokens 不计 malformed——见 SourceMetrics.tokens_cached
                # 的字段文档，缺字段是"数据比字段年长"，不是解析失败。
                tokens_cached = _parse_int(event.payload.get("cached_tokens")) or 0
                metrics.tokens_cached += tokens_cached
                summary.tokens_cached += tokens_cached
                # reasoning_tokens 同 cached 口径：缺字段当 0（老事件/非思考模型）。
                tokens_reasoning = _parse_int(event.payload.get("reasoning_tokens")) or 0
                metrics.tokens_reasoning += tokens_reasoning
                summary.tokens_reasoning += tokens_reasoning
                if dt is not None:
                    metrics.latencies.append(dt)
                verdicts_raw = event.payload.get("verdicts")
                if verdicts_raw is not None:
                    try:
                        verdict_list = json.loads(verdicts_raw)
                        if not isinstance(verdict_list, list):
                            raise ValueError("verdicts 不是列表")
                        metrics.verify_total += len(verdict_list)
                        metrics.verify_unreliable += sum(
                            1 for v in verdict_list if not v.get("reliable", True)
                        )
                    except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
                        metrics.verify_parse_errors += 1
            elif event.type == "error":
                kind = event.payload.get("kind", "unknown")
                if kind == "PermissionSkipped":
                    permission = event.payload.get("permission", "?")
                    metrics.degraded[permission] = metrics.degraded.get(permission, 0) + 1
                else:
                    metrics.error_kinds[kind] = metrics.error_kinds.get(kind, 0) + 1

        summary.duration = (
            run_end_ts - run_start_ts
            if run_start_ts is not None and run_end_ts is not None
            else None
        )
        runs.append(summary)

    runs.sort(key=lambda r: r.run_id)
    return AggregateResult(by_source=by_source, runs=runs)


# =====================================================================
# 报表 CLI：evaluation/eval_report.py —— evaluation/SPEC.md 十·5
# =====================================================================


def resolve_run_ids(
    prefix: str | None,
    run_ids: str | None,
    storage_root: pathlib.Path = STORAGE_ROOT,
) -> list[str]:
    """按 `--prefix`（同一批次的重复 run）或 `--run`（显式清单）选出要读的 run_id。

    `--prefix` 匹配规则抄自 `run_experiment.py`：`base_run_id` 本身，或
    `base_run_id-r{N}`（`--repeat` 展开的重复次数）——不做子串模糊匹配，
    否则批次之间前缀稍有重叠就会互相串号（`evaluation/SPEC.md` 十·5）。
    """
    if run_ids:
        return [r.strip() for r in run_ids.split(",") if r.strip()]
    assert prefix, "必须指定 --prefix 或 --run"
    if not storage_root.is_dir():
        return []
    pattern = re.compile(rf"^{re.escape(prefix)}(-r\d+)?$")
    return sorted(p.name for p in storage_root.iterdir() if p.is_dir() and pattern.match(p.name))


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"


def render_markdown(label: str, result: AggregateResult) -> str:
    """按 `evaluation/SPEC.md` 六节的草案渲染，十·5 扩展了每链路的列。"""
    lines = [
        f"# 测评报表 {label}",
        "",
        "## 每链路聚合（token / 延迟 / 失败 / 降级）",
        "",
        "| 链路 | 调用次数 | 成功 | 失败 | 重试 | tokens_in | tokens_out | "
        "降级 | 错误 | p50延迟(s) | p90延迟(s) | max延迟(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    detail_sections: list[str] = []
    for source in sorted(result.by_source):
        m = result.by_source[source]
        degraded_total = sum(m.degraded.values())
        error_total = sum(m.error_kinds.values())
        lines.append(
            f"| {source} | {m.calls} | {m.ok} | {m.failed} | {m.retries} | "
            f"{m.tokens_in} | {m.tokens_out} | {degraded_total} | {error_total} | "
            f"{_fmt(m.p50)} | {_fmt(m.p90)} | {_fmt(m.max_latency)} |"
        )
        if m.degraded:
            detail_sections.append(
                f"- **{source} 降级明细**："
                + "、".join(f"{k}×{v}" for k, v in sorted(m.degraded.items()))
            )
        if m.error_kinds:
            detail_sections.append(
                f"- **{source} 错误明细**："
                + "、".join(f"{k}×{v}" for k, v in sorted(m.error_kinds.items()))
            )
        if m.malformed:
            detail_sections.append(
                f"- **{source}**：{m.malformed} 次 token 字段解析失败，未计入 tokens_in/out"
            )
        if m.verify_total or m.verify_parse_errors:
            rate = m.verify_unreliable_rate
            rate_text = f"{rate:.1%}" if rate is not None else "-"
            detail_sections.append(
                f"- **{source} 审计失效率**：{m.verify_unreliable}/{m.verify_total} 条 step 记忆"
                f"判不可靠（{rate_text}）"
                + (
                    f"，另有 {m.verify_parse_errors} 次判定解析失败"
                    if m.verify_parse_errors
                    else ""
                )
            )

    if detail_sections:
        lines.append("")
        lines.extend(detail_sections)

    lines += [
        "",
        "## Run 汇总",
        "",
        "| run_id | episode数 | 成功 | 失败 | tokens_in | tokens_out | 时长(s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result.runs:
        lines.append(
            f"| {r.run_id} | {r.episodes} | {r.succeeded} | {r.failed} | "
            f"{r.tokens_in} | {r.tokens_out} | {_fmt(r.duration)} |"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    """跑一次跨 run 聚合报表，打印到终端并落一份 markdown。

    python -m evaluation.eval_report --prefix 0902-153000-abcdef
    python -m evaluation.eval_report --run run-20260901-195813-c9dd14,run-20260901-191527-a1e037
    """
    parser = argparse.ArgumentParser(
        description="按 Source 聚合 token/延迟/失败/降级，跨 run 出一份报表"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prefix", help="实验批次的 base_run_id（run_experiment.py 的 --run-id）")
    group.add_argument("--run", help="显式 run_id 清单，逗号分隔")
    args = parser.parse_args()

    run_ids = resolve_run_ids(args.prefix, args.run)
    if not run_ids:
        print("[EVAL] 没有匹配到任何 run_id，检查 --prefix/--run 或 trace_data/ 是否存在")
        return

    events: list[Event] = []
    missing: list[str] = []
    for run_id in run_ids:
        run_events = read_run_events(run_id)
        if not run_events:
            missing.append(run_id)
            continue
        events.extend(run_events)

    result = aggregate_events(events)
    label = args.prefix or args.run.replace(",", "_")
    report = render_markdown(label, result)

    print(report)
    if missing:
        print(f"[EVAL] {len(missing)} 个 run 找不到 trace，未计入：{', '.join(missing)}")

    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_ROOT / f"{label}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"[EVAL] 报表已写入 {out_path}")


if __name__ == "__main__":
    main()
