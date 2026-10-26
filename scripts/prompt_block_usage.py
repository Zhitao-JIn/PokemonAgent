"""离线分析 prompt 块；估计 token 是回归估计，不是供应商分块计数。
字符先统一 CRLF 为 LF；块均值覆盖全部调用，token 均值仅覆盖成功有效账。
小节均值按出现次数计算，prompt 占比按累计字符计算。断点命中率是比较对
后一次成功调用 cached/input 的算术均值，输入零不参与。模型 c 无法分离图片。
校准无截距，列归一化 Gram 条件数上限 1e6；常量图片列不单独拟合。
混合 provider/model 各自校准后汇总；存在未校准项时汇总估计留空。
unknown 身份的旧账合并为未知组，不能视为同一真实型号；图片系数也只是回归项。
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import re
import statistics
import struct
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from os.path import commonprefix
from pathlib import Path

if __package__:
    from .token_usage_by_provider import TOKENS, discover, object_value, token_value
else:
    from token_usage_by_provider import TOKENS, discover, object_value, token_value

BLOCKS = (
    "规则",
    "本次输入",
    "目标",
    "检索知识",
    "背景索引",
    "地图交互事实",
    "本层历史",
    "状态与反馈",
    "当前现场",
    "预算与进度",
    "人类插话",
)
SECTIONS = ("节点概览", "块构成", "规则小节", "检索知识条目", "token 校准", "共同前缀断点", "异常")
CJK = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f"
    "\U00030000-\U000323af\u3000-\u303f\uff01-\uff0f\uff1a-\uff20"
    "\uff3b-\uff40\uff5b-\uff65\u2014\u2018-\u201f\u2026]"
)
Row = dict[str, object]


@dataclass
class Call:
    sample: Path
    seq: int
    node: tuple[str, ...]
    identity: tuple[str, ...]
    prompt: str
    blocks: list[tuple[str, str]]
    images: list[str | None]
    total: int | None
    cached: int | None
    failed: bool


def pieces(text: str, pattern: str, opening: str) -> list[tuple[str, str]]:
    starts = [(0, opening), *((m.start(), m[1]) for m in re.finditer(pattern, text, re.M))]
    return [
        (name, text[start:end])
        for (start, name), (end, _) in zip(starts, [*starts[1:], (len(text), "")], strict=True)
        if start < end
    ]


def split_blocks(prompt: str) -> tuple[list[tuple[str, str]], int]:
    text, seen, repeats = prompt.replace("\r\n", "\n"), set(), 0
    starts = [(0, "(前导)")]
    for match in re.finditer(r"^## (" + "|".join(BLOCKS) + r")$", text, re.M):
        if match[1] in seen:
            repeats += 1
        else:
            seen.add(match[1])
            starts.append((match.start(), match[1]))
    blocks = [
        (name, text[start:end])
        for (start, name), (end, _) in zip(starts, [*starts[1:], (len(text), "")], strict=True)
        if start < end
    ]
    assert sum(len(body) for _, body in blocks) == len(text), "Block character conservation"
    return blocks, repeats


def image_size(uri: object) -> str | None:
    try:
        if not isinstance(uri, str) or not uri.startswith("data:image/png;base64,"):
            return None
        data = base64.b64decode(uri.partition(",")[2], validate=True)
        if data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" or len(data) < 33:
            return None
        width, height = struct.unpack(">II", data[16:24])
        return f"{width}x{height}" if width and height else None
    except (ValueError, struct.error):
        return None


def read_calls(paths: Sequence[Path]) -> tuple[list[Call], Counter[str]]:
    calls, anomalies = (
        [],
        Counter(
            dict.fromkeys(
                ["同名块标题", "非空前导", "块长度不守恒", "无法解析图片", "缺少provider/model"], 0
            )
        ),
    )
    for path in discover(paths):
        event = object_value(json.loads(path.read_text(encoding="utf-8-sig")))
        if event.get("type") != "model_call":
            continue
        if not str(event.get("kind", "")).endswith("_call"):
            raise ValueError("model_call kind must end in _call")
        content = object_value(event.get("content", {}))
        object_value(event.get("meta", {}))
        prompt = str(content.get("prompt", "")).replace("\r\n", "\n")
        blocks, repeats = split_blocks(prompt)
        images = [image_size(uri) for uri in content.get("images", [])]
        identity = tuple(str(content.get(k) or "unknown") for k in ("provider", "model"))
        tokens = [token_value(content.get(key)) for key in TOKENS]
        failed = str(content.get("ok", "true")).lower() == "false" or None in tokens
        anomalies.update(
            {
                "同名块标题": repeats,
                "非空前导": int(bool(blocks and blocks[0][0] == "(前导)")),
                "无法解析图片": images.count(None),
                "缺少provider/model": int(any(not content.get(k) for k in ("provider", "model"))),
            }
        )
        calls.append(
            Call(
                path.parent.parent,
                int(event.get("seq", 0)),
                tuple(
                    str(content.get(k) or "unknown")
                    for k in ("thinking_node", "prompt_task", "prompt_version")
                ),
                identity,
                prompt,
                blocks,
                images,
                tokens[0],
                tokens[1],
                failed,
            )
        )
    return calls, anomalies


def features(text: str, images: int = 0) -> list[float]:
    count = len(CJK.findall(text))
    return [float(count), float(len(text) - count), float(images)]


def fit(matrix: list[list[float]], target: list[float]) -> list[float] | None:
    size = len(matrix[0])
    scales = [math.sqrt(sum(row[j] ** 2 for row in matrix)) for j in range(size)]
    if not all(scales):
        return None
    x = [[v / scales[j] for j, v in enumerate(row)] for row in matrix]
    gram = [[sum(r[i] * r[j] for r in x) for j in range(size)] for i in range(size)]
    work = [row + [float(i == j) for j in range(size)] for i, row in enumerate(gram)]
    for j in range(size):
        pivot = max(range(j, size), key=lambda i: abs(work[i][j]))
        work[j], work[pivot] = work[pivot], work[j]
        if abs(work[j][j]) < 1e-10:
            return None
        work[j] = [v / work[j][j] for v in work[j]]
        for i in range(size):
            if i != j:
                work[i] = [a - work[i][j] * b for a, b in zip(work[i], work[j], strict=True)]
    inverse = [r[size:] for r in work]
    if max(map(lambda r: sum(map(abs, r)), gram)) * max(sum(map(abs, r)) for r in inverse) > 1e6:
        return None
    rhs = [sum(r[j] * t for r, t in zip(x, target, strict=True)) for j in range(size)]
    result = [
        sum(a * b for a, b in zip(r, rhs, strict=True)) / scales[i] for i, r in enumerate(inverse)
    ]
    return result if all(math.isfinite(v) and v >= 0 for v in result) else None


def calibrate(calls: list[Call]) -> Row:
    valid = [c for c in calls if not c.failed]
    xs, ys = [features(c.prompt, len(c.images)) for c in valid], [float(c.total) for c in valid]
    result: Row = {
        "fit": "未校准",
        "samples": len(valid),
        "coefficients": {},
        "r_squared": None,
        "median_abs_residual_percent": None,
    }
    for name, keys in (
        ("a", ("cjk", "other", "images")),
        ("b", ("chars", "images")),
        ("c", ("chars",)),
    ):
        if len(valid) < 3 * len(keys) or (name != "c" and len({x[2] for x in xs}) < 2):
            continue
        matrix = xs if name == "a" else [[sum(x[:2]), *([x[2]] if name == "b" else [])] for x in xs]
        coefficients = fit(matrix, ys)
        if coefficients is not None:
            residuals = [
                sum(a * b for a, b in zip(x, coefficients, strict=True)) - y
                for x, y in zip(matrix, ys, strict=True)
            ]
            variance = sum((y - statistics.mean(ys)) ** 2 for y in ys)
            rates = [abs(r) / y * 100 for r, y in zip(residuals, ys, strict=True) if y]
            result.update(
                fit=name,
                coefficients=dict(zip(keys, coefficients, strict=True)),
                r_squared=1 - sum(r * r for r in residuals) / variance if variance else None,
                median_abs_residual_percent=statistics.median(rates) if rates else None,
            )
            break
    return result


def average(values: Sequence[float | None]) -> float | None:
    return statistics.mean(values) if values and None not in values else None


def estimate(text: str, calibration: Row, images: int = 0) -> float | None:
    weights = calibration["coefficients"]
    if not weights or (images and not text and "images" not in weights):
        return None
    cjk, other, count = features(text, images)
    return (
        weights.get("cjk", 0) * cjk
        + weights.get("other", 0) * other
        + weights.get("chars", 0) * len(text)
        + weights.get("images", 0) * count
    )


def details(members: list[Call], block: str, pattern: str) -> list[Row]:
    grouped, result = defaultdict(list), []
    for call in members:
        text = dict(call.blocks).get(block, "")
        if block != "规则":
            text = text.partition("\n")[2]
        parts = [(t, b) for t, b in pieces(text, pattern, f"({block}开头)") if b.strip()]
        if block not in {"规则", "检索知识"}:
            parts = [(t, b) for t, b in parts if t != f"({block}开头)"]
        hashes = [
            hashlib.sha256(b.partition("\n")[2].strip().encode()).hexdigest()[:8] for _, b in parts
        ]
        titles = [t for t, _ in parts]
        for (title, body), digest in zip(parts, hashes, strict=True):
            grouped[title].append(
                (len(body), digest, titles.count(title) > 1, hashes.count(digest) > 1)
            )
    for title, rows in grouped.items():
        row = dict(
            title=title, mean_chars=statistics.mean(r[0] for r in rows), occurrences=len(rows)
        )
        row.update(char_counts=dict(sorted(Counter(r[0] for r in rows).items())))
        row.update(
            prompt_percent=sum(r[0] for r in rows) / sum(len(c.prompt) for c in members) * 100
        )
        row.update(hashes=sorted({r[1] for r in rows}), duplicates=sum(r[2] or r[3] for r in rows))
        row.update(
            duplicate_titles=sum(r[2] for r in rows), duplicate_hashes=sum(r[3] for r in rows)
        )
        result.append(row)
    return sorted(result, key=lambda r: (-r["mean_chars"], r["title"]))


def node_tables(
    members: list[Call], fits: dict[tuple[str, ...], Row], tables: dict[str, list[Row]]
) -> None:
    valid = [c for c in members if not c.failed]
    node = dict(
        zip(("thinking_node", "prompt_task", "prompt_version"), members[0].node, strict=True)
    )
    orders = Counter(" → ".join(n for n, _ in c.blocks) for c in members)
    common = min(orders, key=lambda k: (-orders[k], k))
    predictions = [estimate(c.prompt, fits[c.identity], len(c.images)) for c in valid]
    total = average([c.total for c in valid])
    row = dict(node, calls=len(members), failed=len(members) - len(valid))
    row.update(mean_chars=statistics.mean(len(c.prompt) for c in members))
    row.update(mean_estimated_tokens=average(predictions), mean_recorded_input=total)
    row.update(
        common_order=common, common_order_count=orders[common], orders=dict(sorted(orders.items()))
    )
    row.update(identities=sorted({"/".join(c.identity) for c in members}))
    row.update(image_counts=dict(sorted(Counter(len(c.images) for c in members).items())))
    row.update(resolutions=sorted({s for c in members for s in c.images if s}))
    row.update(unparseable_images=sum(c.images.count(None) for c in members))
    tables[SECTIONS[0]].append(row)
    block_rows(members, fits, tables, node, valid, predictions, total)
    for section, block, pattern in ((2, "规则", r"^### (.+)$"), (3, "检索知识", r"^## (.+)$")):
        tables[SECTIONS[section]].extend({**node, **r} for r in details(members, block, pattern))


def block_rows(
    members: list[Call],
    fits: dict[tuple[str, ...], Row],
    tables: dict[str, list[Row]],
    node: Row,
    valid: list[Call],
    predictions: list[float | None],
    total: float | None,
) -> None:
    for name in dict.fromkeys(n for c in members for n, _ in c.blocks):
        texts = [dict(c.blocks).get(name, "") for c in members]
        estimates = [estimate(dict(c.blocks).get(name, ""), fits[c.identity]) for c in valid]
        value = average(estimates)
        row = dict(node, block=name, mean_chars=statistics.mean(map(len, texts)))
        row.update(mean_estimated_tokens=value)
        row.update(prompt_percent=sum(map(len, texts)) / sum(len(c.prompt) for c in members) * 100)
        row.update(token_percent=value / total * 100 if value is not None and total else None)
        row.update(
            subheadings=details(members, name, r"^#{2,3} (.+)$")
            if name in {"本层历史", "状态与反馈", "当前现场"}
            else []
        )
        tables[SECTIONS[1]].append(row)
    adjustment_rows(fits, tables, node, valid, predictions, total)


def adjustment_rows(
    fits: dict[tuple[str, ...], Row],
    tables: dict[str, list[Row]],
    node: Row,
    valid: list[Call],
    predictions: list[float | None],
    total: float | None,
) -> None:
    images = [estimate("", fits[c.identity], len(c.images)) for c in valid]
    residuals = [
        c.total - p if p is not None else None for c, p in zip(valid, predictions, strict=True)
    ]
    for name, values in (("(图片)", images), ("(残差)", residuals)):
        value = average(values)
        row = dict(node, block=name, mean_chars=0, mean_estimated_tokens=value, prompt_percent=0)
        row.update(token_percent=value / total * 100 if value is not None and total else None)
        row.update(subheadings=[])
        tables[SECTIONS[1]].append(row)


def analyze(paths: Sequence[Path]) -> dict[str, list[Row]]:
    calls, anomalies = read_calls(paths)
    tables, identities, nodes, sequences = (
        {s: [] for s in SECTIONS},
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    for call in calls:
        identities[call.identity].append(call)
        nodes[call.node].append(call)
        sequences[(call.sample, call.node[0])].append(call)
    fits = {key: calibrate(group) for key, group in sorted(identities.items())}
    tables[SECTIONS[4]] = [{"provider": k[0], "model": k[1], **v} for k, v in fits.items()]
    for _, members in sorted(nodes.items()):
        node_tables(members, fits, tables)
    tables[SECTIONS[5]] = prefix_rows(sequences)
    tables[SECTIONS[6]] = [{"category": k, "count": v} for k, v in sorted(anomalies.items())]
    return tables


def prefix_rows(sequences: dict[tuple[Path, str], list[Call]]) -> list[Row]:
    comparisons, rows = defaultdict(list), []
    for (_, node), members in sorted(sequences.items()):
        ordered = sorted(members, key=lambda c: c.seq)
        comparisons[node]
        for before, after in zip(ordered, ordered[1:], strict=False):
            length = len(commonprefix([before.prompt, after.prompt]))
            end, block = 0, "(末尾)"
            for name, body in after.blocks:
                end += len(body)
                if length < end:
                    block = name
                    break
            rate = after.cached / after.total if not after.failed and after.total else None
            ratio = length / len(after.prompt) if after.prompt else 0
            comparisons[node].append((ratio, block, length == len(before.prompt), rate))
    for node, pairs in sorted(comparisons.items()):
        row = dict(
            thinking_node=node, pairs=len(pairs), mean_prefix_ratio=average([p[0] for p in pairs])
        )
        row.update(break_blocks=dict(sorted(Counter(p[1] for p in pairs).items())))
        row.update(pure_append_pairs=sum(p[2] for p in pairs))
        row.update(mean_cache_hit_rate=average([p[3] for p in pairs if p[3] is not None]))
        rows.append(row)
    return rows


def display(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    try:
        if any(
            p.resolve().is_relative_to(r.resolve())
            for p in (args.csv, args.json)
            if p
            for r in args.paths
        ):
            raise ValueError("Refusing to write inside input directory")
        tables = analyze(args.paths)
        if args.json:
            args.json.write_text(
                json.dumps({"policy": __doc__, "tables": tables}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
        if args.csv:
            fields = list(
                dict.fromkeys(
                    ["section", *(k for rows in tables.values() for r in rows for k in r)]
                )
            )
            with args.csv.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(
                    {"section": s, **{k: display(v) for k, v in r.items()}}
                    for s, rows in tables.items()
                    for r in (rows or [{}])
                )
        print(__doc__)
        for section, rows in tables.items():
            print(f"\n### {section}\n")
            if rows:
                keys = list(rows[0])
                print("| " + " | ".join(keys) + " |\n| " + " | ".join("---" for _ in keys) + " |")
                for row in rows:
                    print("| " + " | ".join(display(row[k]) for k in keys) + " |")
            else:
                print("(none)")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
