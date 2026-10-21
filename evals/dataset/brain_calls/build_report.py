"""把采集审计与独立标签覆盖写成可审阅报告，不重新调用模型。"""

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from .dataset_contract import InputCase, ReferenceCase


def read_lines(path: Path) -> list[dict]:
    """读取已验证 JSONL。"""
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def coverage(root: Path) -> tuple[list[str], dict]:
    """按五族、三层和已确定标签列出实际分母。"""
    lines = ["| 类别 | 完整输入 | 分层数量 | 独立标签 | 待审 rubric |", "|---|---:|---|---:|---:|"]
    facts = {}
    for family in ("judge", "plan", "decompose", "choose", "summary"):
        inputs = [
            InputCase.model_validate(row) for row in read_lines(root / family / "inputs.jsonl")
        ]
        refs = [
            ReferenceCase.model_validate(row)
            for row in read_lines(root / family / "references.jsonl")
        ]
        kinds = Counter(ref.evaluation for ref in refs)
        layers = dict(Counter(case.layer for case in inputs))
        labelled = kinds["mechanical"] + kinds["action_set"]
        facts[family] = {"cases": len(inputs), "layers": layers, "evaluation": dict(kinds)}
        lines.append(
            f"| {family} | {len(inputs)} | {layers} | {labelled} | "
            f"{kinds['source_grounded_rubric']} |"
        )
    return lines, facts


def timings(batch: Path) -> tuple[list[str], dict]:
    """完整 Port 耗时含等待、重试和解析，不冒称模型服务器延迟。"""
    grouped = defaultdict(list)
    completed = {path.stem for path in (batch / "reports").glob("*.json")}
    for path in (batch / "runs").glob("*/brain_calls/*/*/*.end.json"):
        if path.parents[3].name not in completed:
            continue
        record = json.loads(path.read_text("utf-8"))
        grouped[f"{path.parent.parent.name}/{path.parent.name}"].append(record["elapsed_s"])
    values = {}
    lines = ["| Port | 调用数 | 总耗时秒 | 中位数秒 | P95 秒 |", "|---|---:|---:|---:|---:|"]
    for port, elapsed in sorted(grouped.items()):
        elapsed.sort()
        p95 = elapsed[min(len(elapsed) - 1, int((len(elapsed) - 1) * 0.95))]
        values[port] = {
            "calls": len(elapsed),
            "total_s": sum(elapsed),
            "median_s": median(elapsed),
            "p95_s": p95,
        }
        lines.append(
            f"| {port} | {len(elapsed)} | {sum(elapsed):.2f} | {median(elapsed):.2f} | {p95:.2f} |"
        )
    return lines, values


def report_text(
    completed: int,
    attempts: int,
    missing: int,
    endings: Counter,
    table: list[str],
    waits: list[str],
) -> str:
    """拼可审阅报告；真实计数由调用方传入。"""
    text = [
        "# 二十场景全脑调用采集",
        "",
        f"完成 {completed}/20；模型尝试 {attempts}；双向对账缺失 {missing}。",
        "",
        f"Harness 终止类型：{dict(endings)}。goal_done 是运行时结论，不代替独立机械真值。",
        "",
        *table,
        "",
        "完整请求未抽样、未去重；错误和业务失败保留。summary 含 task、episode、run。",
        (
            "所有旧响应仅作 baseline 审计，未用于生成参考答案。独立标签子集可用已有运行器；"
            "其余 rubric 仍需独立评分或审阅，不计入二元/动作命中率分母。"
        ),
        "",
        "baseline_scores.json 保留原始机械诊断与独立标签下的 baseline 分数。",
        "旧机械规则存在已知数量框漏判：商品列表解码未变时，也可能已在原屏幕弹出数量框。",
        "数量确认独立标签以原屏幕为准；旧规则失败不直接等同真实未完成。",
        "投球例的 Aww! It appeared to be caught! 也是结算结果；旧规则只列部分话语，可能漏判。",
        "",
        "## 等待与耗时",
        "",
        "Port 耗时包含模型等待、重试、退避和解析；具体尝试起止见 sources.zip。",
        "",
        *waits,
        "",
        "## 范围与限制",
        "",
        "L0：本 run 全部 episode；背景其他 run。L1：本局全部 task；背景同 run、同 g"
        "oal_id 的其他 episode。L2：本 task 全部 act；背景本局同目标文本的此前 task。",
        "每例从独立空 memory 恢复，所以跨 run 背景为空；这批数据不能证明长程记忆收益。",
        (
            "budget_skipped 原账单列，不制造未发生的模型调用。"
            "来源包保留所有九方法的实际录制与 trace；"
            "五族导出不包含 verify/reflect 评分任务。"
        ),
        "二十个起点不是独立留出测试集。重复现场、模型生成的差目标和预算耗尽均反映采集分布，不能当作整套能力的泛化结论。",
        "",
    ]
    return "\n".join(text)


def write_report(batch: Path, output: Path) -> None:
    """报告只消费本批报告、冻结数据与耗时账。"""
    rows = [
        json.loads(path.read_text("utf-8")) for path in sorted((batch / "reports").glob("*.json"))
    ]
    table, families = coverage(output)
    waits, latency = timings(batch)
    attempts = sum(row["audit"]["recorded_attempts"] for row in rows)
    missing = sum(
        row["audit"][key]
        for row in rows
        for key in ("missing_from_trace", "missing_from_recording")
    )
    endings = Counter((row.get("run_result") or {}).get("termination", "no_result") for row in rows)
    text = report_text(len(rows), attempts, missing, endings, table, waits)
    (output / "REPORT.md").write_text(text, encoding="utf-8")
    (output / "statistics.json").write_text(
        json.dumps(
            {
                "families": families,
                "ports": latency,
                "attempts": attempts,
                "missing": missing,
                "terminations": dict(endings),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
