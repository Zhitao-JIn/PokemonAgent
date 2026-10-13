"""列出脚本成功、已登记失败码和中途干扰覆盖；源码未登记出口需人工审核。"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from evals.world_script_execute.dataset import ScriptCase, load
from pokemon_agent.world.scripts.catalog import SCRIPT_FUNCS

from .failure_codes import FAILURE_CODES

INTERRUPT_SCRIPTS: frozenset[str] = frozenset(
    {
        "walk_to",
        "walk_to_adjacent",
        "circle_walk",
        "bounce_in_tall_grass",
        "exit_map",
        "heal_at_center",
        "talk_to_adjacent_npc",
        "advance_dialog",
        "wait_until_scene",
    }
)


class CoverageRow(BaseModel):
    """一个脚本的声明覆盖；计数不代替真实执行通过率。"""

    script: str
    success: int = 0
    failures: dict[str, int] = Field(default_factory=dict)
    interrupt: int = 0
    missing: list[str] = Field(default_factory=list)


def coverage(
    cases: Sequence[ScriptCase],
    scripts: Sequence[str],
    required_failures: Mapping[str, Sequence[str]] | None = None,
) -> list[CoverageRow]:
    """返回 C1–C3 计数与缺口。

    调用方保证脚本名单无重复、用例 kind 已解析；未知脚本或矛盾分类抛 ValueError。
    required_failures 是人工审核的源码出口补充；未提供时只核已登记失败码。
    """
    assert len(set(scripts)) == len(scripts)
    rows = {name: CoverageRow(script=name) for name in scripts}
    for case in cases:
        if case.script not in rows or case.kind is None:
            raise ValueError(f"未知脚本或缺少 kind：{case.case_id}")
        row = rows[case.script]
        if case.kind == "success":
            if not case.expect.ok:
                raise ValueError(f"success 用例期望失败：{case.case_id}")
            row.success += 1
        elif case.kind == "failure":
            if case.expect.ok:
                raise ValueError(f"failure 用例期望成功：{case.case_id}")
            row.failures[case.expect.code] = row.failures.get(case.expect.code, 0) + 1
        else:
            row.interrupt += 1
    for name, codes in (required_failures or {}).items():
        if name not in rows:
            raise ValueError(f"失败出口登记了未知脚本：{name}")
        for code in codes:
            rows[name].failures.setdefault(code, 0)
    for row in rows.values():
        if not row.success:
            row.missing.append("C1 success")
        row.missing.extend(f"C2 {code}" for code, count in row.failures.items() if not count)
        if row.script in INTERRUPT_SCRIPTS and not row.interrupt:
            row.missing.append("C3 interrupt")
    return list(rows.values())


def render(rows: Sequence[CoverageRow]) -> str:
    """返回 Markdown 覆盖表与缺口列表，失败码按字典序输出。"""
    lines = ["| 脚本 | success | failure code: count | interrupt |", "|---|---:|---|---:|"]
    for row in rows:
        failures = ", ".join(f"{code}: {count}" for code, count in sorted(row.failures.items()))
        lines.append(f"| {row.script} | {row.success} | {failures or '—'} | {row.interrupt} |")
    lines.extend(["", "缺口："])
    lines.extend(f"- {row.script}: {', '.join(row.missing)}" for row in rows if row.missing)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """核对指定版本；覆盖不足退出 1，数据错误由 DatasetError 明确报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args(argv)
    rows = coverage(load(args.version), list(SCRIPT_FUNCS), FAILURE_CODES)
    print(render(rows))
    print("\nC2 含人工审核的源码出口（failure_codes.py）；源码变更后须同步审核。")
    return int(any(row.missing for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
