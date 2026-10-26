"""Read-only, reproducible token accounting from runs/*/trace/*.json (standard library).
Input total = input_tokens (includes hits); uncached = input_tokens - cached_tokens.
Claude uncached includes cache_creation: trace cannot separate cache writes.
Output = output_tokens, already including thinking/reasoning; reasoning is informational,
never added again. Failed calls (ok=false or missing/invalid required token fields) are
counted separately and excluded from sums; genuine zero is valid. Missing reasoning is
left blank if absent; cache hits > input are reported without correction.
Comparison = comparison-directory minus inputs; percent uses inputs, blank when zero.
Calls includes successful and failed calls.
Identity: recorded provider/model win; --models overrides ONLY missing records, never facts.
Fallback: thinking_node + nearest snapshot (run_config.json before baseline_context.json).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from pathlib import Path

PROVIDER_PREFIXES = (
    ("qwen", "dashscope"),
    ("dashscope", "dashscope"),
    ("deepseek", "deepseek"),
    ("claude", "anthropic"),
)
NODE_LINKS = {
    "task.choose": "text",
    "run.plan": "plan",
    "episode.decompose": "plan",
    "run.judge": "judge",
    "episode.judge": "judge",
    "task.judge": "judge",
    "episode.verify": "verify",
    "task.verify": "verify",
    "run.summarize": "verify",
    "episode.summarize": "verify",
    "task.summarize": "verify",
}
POLICY = (__doc__ or "").split("\nIdentity:")[0]
CLAUDE_NOTE = "Claude: uncached includes cache_creation; trace cannot separate cache writes."
Row = dict[str, str | int | float | None]
Tables = dict[str, list[Row]]
TOKENS = ("input_tokens", "cached_tokens", "output_tokens")


def object_value(value: object) -> dict[str, object]:
    """Decode trace objects, accepting JSON strings as persisted by LocalTrace."""
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("Expected a JSON object")
    return decoded


def provider_for(model: str) -> str:
    """Map known model prefixes in one place; preserve unknown model names."""
    for prefix, provider in PROVIDER_PREFIXES:
        if model.lower().startswith(prefix):
            return provider
    return model if model == "unknown" else f"unknown:{model}"


def model_snapshot(sample: Path) -> dict[str, str]:
    """Find the nearest ancestor snapshot; at the same depth prefer run_config.json."""
    for directory in (sample, *sample.parents):
        for name in ("run_config.json", "baseline_context.json"):
            path = directory / name
            if path.is_file():
                models = object_value(json.loads(path.read_text(encoding="utf-8-sig")))
                models = object_value(models.get("models", {}))
                result = {}
                for link in ("text", "judge", "verify", "plan"):
                    value = models.get(link if name == "run_config.json" else f"{link}_model")
                    value = value.get("model") if isinstance(value, dict) else value
                    if isinstance(value, str) and value:
                        result[link] = value
                return result
    return {}


def discover(paths: Sequence[Path]) -> list[Path]:
    """Find only runs/<sample>/trace/*.json, deduplicating overlapping inputs."""
    found: set[Path] = set()
    for root in paths:
        if not root.is_dir():
            raise ValueError(f"Not a directory: {root}")
        matches = root.rglob("trace/*.json")
        found.update(p.resolve() for p in matches if p.parent.parent.parent.name == "runs")
    return sorted(found)


def token_value(value: object) -> int | None:
    """Accept nonnegative integers and digit strings; missing is distinct from zero."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def read_calls(paths: Sequence[Path], overrides: dict[str, str]) -> tuple[list[Row], list[Row]]:
    """Decode calls without importing production code or writing input directories."""
    calls: list[Row] = []
    violations: list[Row] = []
    snapshots = {}
    for path in discover(paths):
        event = object_value(json.loads(path.read_text(encoding="utf-8-sig")))
        if event.get("type") != "model_call":
            continue
        content = object_value(event.get("content", {}))
        sample = path.parent.parent
        recorded_provider, recorded_model = (content.get(key) for key in ("provider", "model"))
        recorded = bool(recorded_provider and recorded_model)
        if not recorded and sample not in snapshots:
            snapshots[sample] = model_snapshot(sample)
        models = snapshots.get(sample, {})
        node = str(content.get("thinking_node", "unknown"))
        link = NODE_LINKS.get(node)
        model = recorded_model or overrides.get(link, models.get(link, "unknown"))
        if link is None:
            node = "unknown"
        task = str(content.get("prompt_task", "unknown"))
        row: Row = {
            "sample": sample.as_posix(),
            "provider": recorded_provider or provider_for(model),
            "model": model,
            "node": f"{node.split('.')[0]}/{task}",
            "prompt_version": str(content.get("prompt_version", "unknown")),
            "trace": path.name,
        }
        row.update({key: token_value(content.get(key)) for key in (*TOKENS, "reasoning_tokens")})
        missing = any(row[key] is None for key in TOKENS)
        row["failed_calls"] = int(str(content.get("ok", "true")).lower() == "false" or missing)
        total, cached = row["input_tokens"], row["cached_tokens"]
        if isinstance(total, int) and isinstance(cached, int) and cached > total:
            violations.append(dict(row))
        calls.append(row)
    return calls, violations


def aggregate(calls: list[Row], dimensions: tuple[str, ...]) -> list[Row]:
    """Sum only successful calls, retaining model identity and missing reasoning."""
    grouped: dict[tuple[str, ...], list[Row]] = {}
    for call in calls:
        grouped.setdefault(tuple(str(call[key]) for key in dimensions), []).append(call)
    rows: list[Row] = []
    for key, members in sorted(grouped.items()):
        valid = [call for call in members if not call["failed_calls"]]
        row: Row = dict(zip(dimensions, key, strict=True))
        row.update(calls=len(members), failed_calls=len(members) - len(valid))
        for metric in (*TOKENS, "reasoning_tokens"):
            values = [call[metric] for call in valid if isinstance(call[metric], int)]
            row[metric] = sum(values) if values or metric != "reasoning_tokens" else None
        total, cached = int(row["input_tokens"]), int(row["cached_tokens"])
        row.update(uncached_tokens=total - cached, hit_rate=cached / total if total else None)
        row["note"] = CLAUDE_NOTE if row["provider"] in {"anthropic", "claude"} else ""
        rows.append(row)
    return rows


def usage_tables(calls: list[Row], by_sample: bool) -> Tables:
    """Build the same stable groups for Markdown, CSV and JSON."""
    keys = ("provider", "model")
    groups = {"provider": keys, "model": keys, "node": (*keys, "node", "prompt_version")}
    if by_sample:
        groups.update({f"sample_{name}": ("sample", *keys) for name, keys in list(groups.items())})
    return {name: aggregate(calls, keys) for name, keys in groups.items()}


def compare_tables(before: Tables, after: Tables) -> Tables:
    """Union groups; delta is after minus before, percent is delta / before * 100."""
    tables: Tables = {}
    for name in ("provider", "node"):
        dimensions = ("provider", "model", *(("node", "prompt_version") if name == "node" else ()))
        indexes = [
            {tuple(str(row[k]) for k in dimensions): row for row in data[name]}
            for data in (before, after)
        ]
        rows: list[Row] = []
        for key in sorted(indexes[0].keys() | indexes[1].keys()):
            row: Row = dict(zip(dimensions, key, strict=True))
            for metric in ("uncached_tokens", "cached_tokens", "output_tokens"):
                old, new = (int(index.get(key, {}).get(metric, 0)) for index in indexes)
                row[f"{metric}_before"], row[f"{metric}_after"] = old, new
                row[f"{metric}_delta"] = new - old
                row[f"{metric}_percent"] = (new - old) / old * 100 if old else None
            rows.append(row)
        tables[f"compare_{name}"] = rows
    return tables


def markdown(tables: Tables) -> str:
    """Render explicit accounting rules and stable tables, including violations last."""
    lines = [POLICY.strip(), ""]
    for name, rows in tables.items():
        lines.extend([f"### {name}", ""])
        if not rows:
            lines.extend(["(none)", ""])
            continue
        keys = list(rows[0])
        lines.extend(
            ["| " + " | ".join(keys) + " |", "| " + " | ".join("---" for _ in keys) + " |"]
        )
        for row in rows:
            values = []
            for key in keys:
                value = row[key]
                rendered = "" if value is None else str(value)
                if isinstance(value, float):
                    rendered = f"{value * 100:.2f}%" if key == "hit_rate" else f"{value:.2f}%"
                values.append(rendered.replace("|", "\\|").replace("\n", " "))
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    return "\n".join(lines)


def parse_models(value: str) -> dict[str, str]:
    """Validate comma-separated link=model overrides without silently ignoring typos."""
    result = {}
    for item in value.split(","):
        link, separator, model = item.partition("=")
        if not separator or link not in {"text", "judge", "verify", "plan"} or not model:
            raise argparse.ArgumentTypeError("--models requires text/judge/verify/plan=model")
        if link in result:
            raise argparse.ArgumentTypeError(f"Duplicate model link: {link}")
        result[link] = model
    return result


def export_tables(tables: Tables, json_path: Path | None, csv_path: Path | None) -> None:
    """Write the shared tables and accounting metadata in both machine-readable formats."""
    if json_path:
        payload = json.dumps(
            {"policy": POLICY.strip(), "tables": tables}, ensure_ascii=False, indent=2
        )
        json_path.write_text(payload + "\n", encoding="utf-8")
    if csv_path:
        keys = (key for rows in tables.values() for row in rows for key in row)
        fields = list(dict.fromkeys(["section", "policy", *keys]))
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerow({"section": "policy", "policy": POLICY.strip()})
            for name, rows in tables.items():
                writer.writerows({"section": name, **row} for row in rows)


def main(argv: Sequence[str] | None = None) -> int:
    """Print Markdown and optionally export identical tables; reject input-tree writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--models", type=parse_models, default={})
    parser.add_argument("--by-sample", action="store_true")
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    roots = [*args.paths, *([args.compare] if args.compare else [])]
    try:
        for output in (args.csv, args.json):
            if output and any(output.resolve().is_relative_to(root.resolve()) for root in roots):
                raise ValueError(f"Refusing to write inside input directory: {output}")
        calls, violations = read_calls(args.paths, args.models)
        tables = usage_tables(calls, args.by_sample)
        if args.compare:
            other, other_violations = read_calls([args.compare], args.models)
            after = usage_tables(other, args.by_sample)
            tables.update({f"comparison_{name}": rows for name, rows in after.items()})
            tables.update(compare_tables(tables, after))
            violations.extend(other_violations)
        tables["violations"] = violations
        export_tables(tables, args.json, args.csv)
        print(markdown(tables))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
