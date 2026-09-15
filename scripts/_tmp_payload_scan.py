"""临时：按 (type, payload.kind) 统计真机事件的字段形状（对齐审计第二步）。"""

from __future__ import annotations

import collections
import itertools
import json
import pathlib

ROOTS = [
    pathlib.Path("_to_delete/0914-bool-normalization"),
    pathlib.Path("_to_delete/0914-realcheck-cleanup/trace_data"),
    pathlib.Path("_to_delete/0914-smoke-crashes"),
    pathlib.Path("trace_data"),
]

by: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
files = 0
for root in ROOTS:
    if not root.exists():
        continue
    for p in root.rglob("*.json"):
        if p.parent.name != "events":
            continue
        try:
            e = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        files += 1
        pl = e.get("payload") or {}
        by[(str(e.get("type")), str(pl.get("kind")))].append(pl)

print(f"扫描文件 {files} 条，分 {len(by)} 种账\n")
print("=" * 100)

GROUP_ORDER = [
    ("memory_io", "写"),
    ("memory_io", "读"),
    ("lifecycle", ""),
    ("view", ""),
    ("llm_outcome", ""),
    ("act", ""),
    ("model_call", ""),
    ("error", ""),
]

for group, label in GROUP_ORDER:
    rows = [(k, v) for k, v in by.items() if k[0] == group]
    if group == "memory_io":
        rows = [(k, v) for k, v in rows if (label == "读") == k[1].startswith("read_")]
    if not rows:
        continue
    print(f"\n### {group}  {label}")
    for k, pls in sorted(rows, key=lambda kv: kv[0][1]):
        n = len(pls)
        cnt: collections.Counter = collections.Counter()
        for pl in pls:
            cnt.update(pl.keys())
        partial = {f: c for f, c in sorted(cnt.items()) if c < n}
        uniq = {f: {str(p.get(f)) for p in pls} for f in cnt}
        const = [f for f, v in uniq.items() if f != "kind" and len(v) == 1]
        keys = sorted(cnt)
        same = [
            (a, b)
            for a, b in itertools.combinations(keys, 2)
            if all(str(p.get(a)) == str(p.get(b)) for p in pls)
        ]
        print(f"\n{k[0]}/{k[1]}  n={n}")
        print(f"  键({len(keys)}): {keys}")
        if partial:
            print(f"  ⚠ 部分出现: {partial}")
        if const:
            print("  ⚠ 恒定值: " + ", ".join(f"{f}={sorted(uniq[f])[0][:40]!r}" for f in const))
        if same:
            print(f"  ⚠ 逐字恒等: {same}")
        for f in keys:
            vals = uniq[f]
            if len(vals) <= 3:
                print(f"    {f:<20} ∈ {sorted(vals)[:3]}")
            else:
                sample = sorted(vals)[:2]
                print(f"    {f:<20} {len(vals)} 种，如 {[s[:50] for s in sample]}")
