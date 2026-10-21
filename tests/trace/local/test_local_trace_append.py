"""`LocalTrace.append` 的落盘形状：一事件一文件、八字段、JSON 字符串、双时刻缺省。

**为什么这个文件值钱**：`append` 是 trace 唯一的写点，盘上那份 json 是所有读方的
共同底座——文件名是不是 uuid、封套是不是正好八个字段、`meta`/`content` 是不是
JSON 字符串、没记起止的账怎么补时刻、中文会不会被转义成 `\\uXXXX`。这些全都没有
编译器保护，只有"写一笔、读回来、对一遍"能钉住。

**只经公开面说话**：`LocalTrace(root=…)` 与 `append` 的返回值，加 `tmp_path` 下的
文件。不碰 `_scan_events` / `_dir` / `_Event`。

**计时不依赖精确值**：需要"现在"就用调用前后各取一次 `time.time()` 夹住，不 sleep。
"""

from __future__ import annotations

import json
import pathlib
import re
import time
from typing import Any

import pytest
from _doubles.trace import signed_meta

from pokemon_agent.trace import LocalTrace

_EIGHT_FIELDS = {
    "uuid",
    "seq",
    "kind",
    "type",
    "started_at",
    "ended_at",
    "meta",
    "content",
}

# 时间递增 uuid（v7 布局）：版本位 7、变体位 8/9/a/b。
_UUID_V7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json")


def _only_file(root: pathlib.Path) -> pathlib.Path:
    (path,) = root.glob("*.json")
    return path


def _only_record(root: pathlib.Path) -> dict[str, Any]:
    return json.loads(_only_file(root).read_text(encoding="utf-8"))


def test_append_writes_one_json_file_named_by_the_returned_uuid(tmp_path: pathlib.Path) -> None:
    """返回的 uuid 就是文件名：一条事件一个文件，全平铺在落盘根下。"""
    store = LocalTrace(root=tmp_path)

    event_uuid = store.append("lifecycle", "advance_step", signed_meta(), {})

    assert [path.name for path in tmp_path.glob("*.json")] == [f"{event_uuid}.json"]


def test_file_name_is_a_time_ordered_uuid_v7(tmp_path: pathlib.Path) -> None:
    """文件名是 v7 uuid——版本位 7、变体位 8/9/a/b，跨毫秒字典序即时间序。"""
    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", signed_meta(), {})

    assert _UUID_V7.fullmatch(_only_file(tmp_path).name), _only_file(tmp_path).name


def test_stored_record_has_exactly_the_eight_contract_fields(tmp_path: pathlib.Path) -> None:
    """盘上的键**正好**是那八个：多一个是有人在封套外面另挂东西，少一个是漏了字段。"""
    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", signed_meta(), {})

    assert set(_only_record(tmp_path)) == _EIGHT_FIELDS


def test_meta_and_content_are_stored_as_json_strings(tmp_path: pathlib.Path) -> None:
    """`meta` / `content` 在盘上是**字符串**（需要一层转义），`json.loads` 回来是原对象。"""
    meta = signed_meta(step=2)
    content = {"next_step": 3}

    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", meta, content)

    record = _only_record(tmp_path)
    assert isinstance(record["meta"], str)
    assert isinstance(record["content"], str)
    assert json.loads(record["meta"]) == meta
    assert json.loads(record["content"]) == content


def test_meta_is_stored_verbatim_without_stamping_or_requiring_any_key(
    tmp_path: pathlib.Path,
) -> None:
    """`meta` 原样透传：不补 `run_id` / `branch`，也不因缺键报错——盖章是 tool 层的事。"""
    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", {"source": "s"}, {})

    assert json.loads(_only_record(tmp_path)["meta"]) == {"source": "s"}


def test_none_meta_is_stored_as_an_empty_object(tmp_path: pathlib.Path) -> None:
    """`meta` 缺省落成 `{}`，不是 `null`——读端解出来必须是 dict。"""
    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", None, {})

    assert _only_record(tmp_path)["meta"] == "{}"


def test_none_content_is_stored_as_json_null(tmp_path: pathlib.Path) -> None:
    """`content` 缺省落成 `null`（`json.dumps(None)`）——"没有正文"与"空对象"不是一回事。"""
    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", signed_meta(), None)

    assert _only_record(tmp_path)["content"] == "null"


def test_non_ascii_content_is_written_unescaped(tmp_path: pathlib.Path) -> None:
    """中文直接以 UTF-8 落盘（`ensure_ascii=False`），嵌套结构往返无损。"""
    content = {"文本": "中文内容", "嵌套": [1, {"深层": "值"}], "空": None}

    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", signed_meta(), content)

    raw = _only_file(tmp_path).read_text(encoding="utf-8")
    assert "中文内容" in raw, "盘上不该是 \\uXXXX 转义"
    assert json.loads(_only_record(tmp_path)["content"]) == content


def test_missing_times_default_to_the_same_append_moment(tmp_path: pathlib.Path) -> None:
    """两个时刻都不给：`start == end ==` 记账时刻（这笔账没有时长语义）。"""
    store = LocalTrace(root=tmp_path)

    before = time.time()
    event_uuid = store.append("lifecycle", "advance_step", signed_meta(), {})
    after = time.time()

    (event,) = store.read_events()
    assert event.uuid == event_uuid
    assert event.started_at == event.ended_at
    assert before <= event.started_at <= after


def test_given_start_and_end_pass_through_exactly(tmp_path: pathlib.Path) -> None:
    """两个时刻都给了就逐值透传——落盘层不改写调用方记的真实起止。"""
    store = LocalTrace(root=tmp_path)

    store.append(
        "lifecycle",
        "advance_step",
        signed_meta(),
        {},
        started_at=1000.5,
        ended_at=1002.25,
    )

    (event,) = store.read_events()
    assert event.started_at == 1000.5
    assert event.ended_at == 1002.25


def test_only_a_given_start_leaves_the_end_at_the_append_moment(tmp_path: pathlib.Path) -> None:
    """只给开始时刻：`started_at` 原样，`ended_at` 补记账时刻。"""
    store = LocalTrace(root=tmp_path)

    before = time.time()
    store.append("lifecycle", "advance_step", signed_meta(), {}, started_at=1000.5)
    after = time.time()

    (event,) = store.read_events()
    assert event.started_at == 1000.5
    assert before <= event.ended_at <= after


def test_unserializable_content_raises_type_error_and_writes_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """不可 JSON 化的正文当场抛 `TypeError`，且**不留半个文件**（原子写之前就失败了）。"""
    store = LocalTrace(root=tmp_path)

    with pytest.raises(TypeError):
        store.append("lifecycle", "advance_step", signed_meta(), {1, 2})

    assert list(tmp_path.iterdir()) == [], "失败的一笔不许留下任何文件（含 .tmp）"
