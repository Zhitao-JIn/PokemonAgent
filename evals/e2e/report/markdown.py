"""把一份报告渲染成给人读的 `report.md`（spec §十）。每个比例旁注分子分母；k=1 时区间列写 n/a。

口径：成功率的分母 = 有效且可机械判定的样本；红线命中的样本记为判负。
judge 假阳率 = FP / judge 说成的样本数；假阴率 = FN / judge 说没成的样本数（与 0827 复核同口径）。
"""

from __future__ import annotations

from collections import Counter, defaultdict

from evals.e2e.schemas import ReportHeader, SampleResult, TokenUse


def render(header: ReportHeader, results: list[SampleResult], bad_cases: int) -> str:
    """整份报告。"""
    valid = [r for r in results if not r.invalid]
    parts = [
        _header(header),
        _outcomes(valid, results),
        _red_lines(valid),
        _path_layer(valid),
        _efficiency(valid),
        _judge(valid),
        _sense(valid),
        f"## bad case\n\n本次新登记与既有记录见 `bad_cases.jsonl`；本份报告触发 {bad_cases} 条。\n",
    ]
    return "\n".join(parts)


def _ratio(num: int, den: int) -> str:
    """`x%（num/den）`；分母为 0 写 n/a。"""
    return f"{num / den:.0%}（{num}/{den}）" if den else "n/a（0/0）"


def _header(h: ReportHeader) -> str:
    """口径头。"""
    rows = [
        ("report_id", h.report_id),
        ("时间", h.created_at),
        ("git", f"{h.git_commit}{'（工作区有改动）' if h.git_dirty else ''}"),
        ("模型", "，".join(f"{k}={v}" for k, v in sorted(h.models.items()))),
        ("数据集", f"{h.dataset_version}（样本哈希 {h.samples_sha256[:12]}）"),
        ("rubric", h.rubric_version),
        ("知识库", h.knowledge[:12]),
        ("k", str(h.k)),
    ]
    table = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"# 测评报告 {h.report_id}\n\n| 口径 | 值 |\n|---|---|\n{table}\n"


def _outcomes(valid: list[SampleResult], results: list[SampleResult]) -> str:
    """结果层：成功率、按类别、不可机械判定与无效样本。"""
    judgeable = [r for r in valid if r.final != "unjudgeable"]
    passed = [r for r in judgeable if r.final == "pass"]
    lines = [
        "## 结果层",
        "",
        f"- 成功率：{_ratio(len(passed), len(judgeable))}；pass@k / pass^k / 区间：n/a（k=1）",
        f"- 有效样本 {len(valid)} / 全部 {len(results)}；可机械判定 {len(judgeable)}",
        "",
        "| 类别 | 成功 | 可判 | 不可判 |",
        "|---|---|---|---|",
    ]
    by_cat: dict[str, list[SampleResult]] = defaultdict(list)
    for r in valid:
        by_cat[r.category].append(r)
    for cat, rs in sorted(by_cat.items()):
        ok = sum(r.final == "pass" for r in rs)
        judged = sum(r.final != "unjudgeable" for r in rs)
        lines.append(f"| {cat} | {ok} | {judged} | {len(rs) - judged} |")
    lines += ["", "| 样本 | 结论 | 机械判据理由 | run 收尾 |", "|---|---|---|---|"]
    for r in valid:
        reason = r.verdict.reason if r.verdict else ""
        lines.append(f"| {r.sample_id} | {r.final} | {reason} | {r.termination} |")
    invalid = [r for r in results if r.invalid]
    if invalid:
        lines += ["", "**无效样本**（不进任何分母）：", ""]
        lines += [f"- {r.sample_id}：{r.invalid}" for r in invalid]
    return "\n".join(lines) + "\n"


def _red_lines(valid: list[SampleResult]) -> str:
    """红线命中清单。"""
    hits = [(r.sample_id, h) for r in valid for h in r.red_lines]
    if not hits:
        return "## 红线\n\n无命中。\n"
    rows = "\n".join(f"| {sid} | {h.line_id} | {h.reason} |" for sid, h in hits)
    return f"## 红线\n\n| 样本 | 红线 | 说明 |\n|---|---|---|\n{rows}\n"


def _path_layer(valid: list[SampleResult]) -> str:
    """路径层：③ 的原始量（v1 未折档），① ② 的人工打分进度。"""
    lines = [
        "## 路径层",
        "",
        "| 样本 | 按键 | 回到旧格 | 无效按键 | ① 拆解 | ② 换策略 |",
        "|---|---|---|---|---|---|",
    ]
    for r in valid:
        scores = {s.item_id: s for s in r.rubric}
        red = scores.get("redundant_path")
        detail = red.detail if red else {}

        def human(item: str, scores: dict = scores) -> str:
            s = scores.get(item)
            return "—" if s is None else ("待打分" if s.score is None else str(s.score))

        lines.append(
            f"| {r.sample_id} | {int(detail.get('presses', 0))} | {int(detail.get('revisits', 0))} "
            f"| {int(detail.get('stalled_keys', 0))} | {human('decompose_quality')} "
            f"| {human('strategy_switch')} |"
        )
    lines.append("\n③ 的 0 / 1 / 2 档阈值待第一批数据标定（plan E9），本表只给原始量。")
    return "\n".join(lines) + "\n"


def _efficiency(valid: list[SampleResult]) -> str:
    """效率层：按链路合计，再按样本列局数与总 token。"""
    total: dict[str, TokenUse] = defaultdict(TokenUse)
    calls: Counter[str] = Counter()
    for r in valid:
        for link, use in r.efficiency.tokens_by_link.items():
            t = total[link]
            t.input += use.input
            t.output += use.output
            t.cached += use.cached
            t.reasoning += use.reasoning
        calls.update(r.efficiency.calls_by_link)
    lines = [
        "## 效率层",
        "",
        "| 链路 | 调用 | 输入 | 输出 | 缓存 | 推理 |",
        "|---|---|---|---|---|---|",
    ]
    for link, t in sorted(total.items()):
        lines.append(
            f"| {link} | {calls[link]} | {t.input} | {t.output} | {t.cached} | {t.reasoning} |"
        )
    lines += [
        "",
        "| 样本 | 局数 | task 数 | 按键 | 调用失败 | 重试耗尽 | 墙钟秒 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in valid:
        e = r.efficiency
        lines.append(
            f"| {r.sample_id} | {e.episodes} | {e.tasks} | {e.presses} | {e.call_failed} "
            f"| {e.call_exhausted} | {e.wall_seconds:.0f} |"
        )
    return "\n".join(lines) + "\n"


def _judge(valid: list[SampleResult]) -> str:
    """judge 一致性：run 层与目标局 episode 层四格；task 层终止分布。"""
    lines = [
        "## judge 一致性",
        "",
        "| 层 | TP | FP | FN | TN | 假阳率 | 假阴率 |",
        "|---|---|---|---|---|---|---|",
    ]
    for layer in ("run", "episode"):
        c = Counter(cell.cell for r in valid for cell in r.judge if cell.layer == layer)
        lines.append(
            f"| {layer} | {c['TP']} | {c['FP']} | {c['FN']} | {c['TN']} "
            f"| {_ratio(c['FP'], c['TP'] + c['FP'])} | {_ratio(c['FN'], c['FN'] + c['TN'])} |"
        )
    dist: Counter[str] = Counter()
    for r in valid:
        dist.update(r.task_terminations)
    shown = "，".join(f"{k} {v}" for k, v in sorted(dist.items())) or "无"
    lines.append(f"\ntask 层 judge 终止分布（无机械对照）：{shown}")
    return "\n".join(lines) + "\n"


def _sense(valid: list[SampleResult]) -> str:
    """感知一致率。"""
    frames = sum(r.sense.frames for r in valid)
    agree = sum(r.sense.agree for r in valid)
    return (
        "## 感知一致率\n\n"
        f"看档帧上视觉 `scene=battle` 与内存战斗标志一致：{_ratio(agree, frames)}。"
        "人工标注的感知评测见 `experiment/observation_check/`。\n"
    )


__all__ = ["render"]
