"""检查活动 prompt 是否照搬了 e2e 评测样本里的特定内容。

评测样本是"题面"，prompt 是"解题方法"：题面里的目标措辞、判据措辞和初始现场
描述一旦出现在 prompt 里，评测就在背答案，后续调优也分不清是真改进还是记住了题。

两条机械规则（都按"被检文本"= 活动版本目录里的 prompt.md / assemble.py / 其他 .md）：

- 规则 A：两侧都去掉空白与 markdown 符号（`` ` `` `*` `#` `>` `-` `|`）后，存在
  长度 ≥ 10 个字符的公共连续子串即命中。抓的是成句照搬。
- 规则 B：样本文本里的 ASCII 短语（至少两个英文单词，或以 `!` 结尾，长度 ≥ 6）
  在被检文本里大小写不敏感出现即命中。抓的是台词这类短句照搬。

命中即退出码 1；零命中退出码 0；用法或配置错误退出码 2。

允许清单（默认 `scripts/lint_prompt_allow.txt`）每行一个子串，`#` 开头是注释；
**每个条目必须紧跟在一条注释之后**，注释里写清为什么它不算泄漏——清单只给协议
字段名和泛用句式开口子，游戏文字不许进。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

MARKDOWN_NOISE = frozenset("`*#>-|")
"""规则 A 归一化时要去掉的 markdown 符号（空白另按 `str.isspace` 处理）。"""

MIN_COMMON = 10
"""规则 A 的公共连续子串下限（字符数）。"""

MIN_PHRASE = 6
"""规则 B 的 ASCII 短语长度下限。"""

ASCII_RUN = re.compile(r"[ -~]+")
"""可打印 ASCII 的极大连续段——台词与字段片段都在这些段里。"""


@dataclass(frozen=True)
class Hit:
    """一次命中：哪个文件、命中了什么、来自哪条样本。"""

    rule: str
    path: Path
    match: str
    sample_id: str


def normalize(text: str) -> str:
    """去掉空白与 markdown 符号，只留用于比对的内容字符。"""
    return "".join(
        character
        for character in text
        if not character.isspace() and character not in MARKDOWN_NOISE
    )


def sample_strings(path: Path) -> Iterator[tuple[str, str]]:
    """逐条样本产出 (sample_id, 字符串)：goal、success_criteria 与 hint 里的全部字符串。"""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        sample_id = str(record.get("sample_id", f"{path.name}:{number}"))
        for field in ("goal", "success_criteria"):
            value = record.get(field)
            if isinstance(value, str) and value:
                yield sample_id, value
        yield from ((sample_id, text) for text in nested_strings(record.get("initial_state_hint")))


def nested_strings(value: object) -> Iterator[str]:
    """递归取出 hint 里的所有字符串（hint 可能是字符串、列表或对象）。"""
    if isinstance(value, str):
        if value:
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from nested_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from nested_strings(item)


def phrase_words(phrase: str) -> list[str]:
    """按空白切出的英文词；`map_id` 这类单个标识符算一个词，不算两个。"""
    return [word for word in phrase.split() if any("a" <= c.lower() <= "z" for c in word)]


def ascii_phrases(text: str) -> Iterator[str]:
    """抽出像台词的 ASCII 短语：至少两个英文单词，或以 `!` 结尾，长度 ≥ 6。"""
    for run in ASCII_RUN.findall(text):
        phrase = run.strip(" `'\"()[]{}.,;:")
        if len(phrase) < MIN_PHRASE:
            continue
        if phrase.endswith("!") or len(phrase_words(phrase)) >= 2:
            yield phrase


def rule_a(text: str, samples: Iterable[tuple[str, str]], path: Path) -> Iterator[Hit]:
    """归一化后找 ≥ 10 字符的公共连续子串，按极大匹配报告。"""
    haystack = normalize(text)
    windows = {
        haystack[index : index + MIN_COMMON] for index in range(len(haystack) - MIN_COMMON + 1)
    }
    seen: set[tuple[str, str]] = set()
    for sample_id, raw in samples:
        needle = normalize(raw)
        for start in range(len(needle) - MIN_COMMON + 1):
            if needle[start : start + MIN_COMMON] not in windows:
                continue
            position = haystack.find(needle[start : start + MIN_COMMON])
            left = start
            while left > 0 and position > 0 and needle[left - 1] == haystack[position - 1]:
                left -= 1
                position -= 1
            end = start + MIN_COMMON
            while (
                end < len(needle)
                and position + end - left < len(haystack)
                and needle[end] == haystack[position + end - left]
            ):
                end += 1
            match = needle[left:end]
            key = (match, sample_id)
            if key not in seen:
                seen.add(key)
                yield Hit("A", path, match, sample_id)


def rule_b(text: str, samples: Iterable[tuple[str, str]], path: Path) -> Iterator[Hit]:
    """找样本里的 ASCII 短语在被检文本中的大小写不敏感出现。"""
    lowered = text.casefold()
    seen: set[tuple[str, str]] = set()
    for sample_id, raw in samples:
        for phrase in ascii_phrases(raw):
            key = (phrase.casefold(), sample_id)
            if key in seen:
                continue
            seen.add(key)
            if phrase.casefold() in lowered:
                yield Hit("B", path, phrase, sample_id)


def read_allow(path: Path) -> list[str]:
    """读允许清单；每个条目必须紧跟在至少一行注释之后，否则视为配置错误。"""
    if not path.is_file():
        return []
    entries: list[str] = []
    commented = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            commented = True
            continue
        if not commented:
            print(f"{path}:{number}: 允许条目缺少注释理由：{stripped}", file=sys.stderr)
            raise SystemExit(2)
        entries.append(stripped)
        commented = False
    return entries


def allowed(hit: Hit, entries: list[str]) -> bool:
    """命中子串整个落在某条允许条目里（或与之相同）时放行。"""
    return any(hit.match in entry or hit.match == entry for entry in entries)


def unit_directories(registry: Path) -> list[Path]:
    """取注册表里每个 kind=task 单元的活动版本目录；fragment 不在本检查范围。"""
    data = json.loads(registry.read_text(encoding="utf-8"))
    directories: list[Path] = []
    for task, version in sorted(data["tasks"].items()):
        candidates = (
            registry.parent / "tasks" / task,
            registry.parent / "tasks" / "fragments" / task,
        )
        for base in candidates:
            directory = base / version["active"]
            if not directory.is_dir():
                continue
            meta = directory / "meta.json"
            kind = "task"
            if meta.is_file():
                kind = json.loads(meta.read_text(encoding="utf-8")).get("kind", "task")
            if kind != "task":
                break
            directories.append(directory)
            break
        else:
            print(f"注册表里的版本目录不存在：{task} {version['active']}", file=sys.stderr)
            raise SystemExit(2)
    return directories


def inspected_files(directory: Path) -> list[Path]:
    """活动版本目录里的 prompt.md、assemble.py 与其它 .md。"""
    names = [directory / "prompt.md", directory / "assemble.py"]
    names += sorted(path for path in directory.glob("*.md") if path.name != "prompt.md")
    return [path for path in dict.fromkeys(names) if path.is_file()]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查活动 prompt 是否照搬了 e2e 评测样本。")
    parser.add_argument("--samples", action="append", required=True, help="samples.jsonl，可重复")
    parser.add_argument(
        "--registry", default="pokemon_agent/prompt/registry.json", help="注册表路径"
    )
    parser.add_argument("--allow", default="scripts/lint_prompt_allow.txt", help="允许清单路径")
    arguments = parser.parse_args()
    registry = Path(arguments.registry)
    samples = [item for path in map(Path, arguments.samples) for item in sample_strings(path)]
    entries = read_allow(Path(arguments.allow))
    hits = [
        hit
        for directory in unit_directories(registry)
        for path in inspected_files(directory)
        for hit in [
            *rule_a(path.read_text(encoding="utf-8"), samples, path),
            *rule_b(path.read_text(encoding="utf-8"), samples, path),
        ]
        if not allowed(hit, entries)
    ]
    print(f"检查 {len(samples)} 条样本文本，命中 {len(hits)} 处")
    for hit in hits:
        print(f"  [{hit.rule}] {hit.path.as_posix()}")
        print(f"      命中：{hit.match}")
        print(f"      样本：{hit.sample_id}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
