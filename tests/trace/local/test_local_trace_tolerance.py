"""`LocalTrace.read_events` 对坏文件的容忍：残文件、旧格式、`.tmp`、非 dict 的 `meta`。

**为什么这个文件值钱**：落盘根是"人也会往里丢东西"的目录——进程被 kill 会留下半个
json，改形之前的旧账还在，原子写的 `.tmp` 可能没 rename 掉。这些**都是预期内的
运行期情况**：跳过、不报错、也不许混进查询结果。反过来，坏文件不能把好文件带下水
——每一条的 Assert 都是"好账照常读得出 + 坏账没混进来"。

**G1–G5 在 CP1**；G6（非 UTF-8）、G7（同名目录）、G8（读不动要抛而不是吞）属
CP2——G8 先红再改 `store.py`，那一条不在这里。

**离线**：坏文件都是手写的，落盘根一律 `tmp_path`。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from _doubles.trace import signed_meta

from pokemon_agent.trace import LocalTrace


def _good_event(root: pathlib.Path) -> str:
    """先落一笔好账——后面每条都要证明坏文件没把它带下水。"""
    return LocalTrace(root=root).append("lifecycle", "advance_step", signed_meta(), {"ok": True})


def _record(**overrides: Any) -> dict[str, Any]:
    """一份形状合法的落盘记录（`uuid` 故意与好账不同，方便断言"没混进来"）。"""
    record: dict[str, Any] = {
        "uuid": "00000000-0000-7000-8000-000000000000",
        "seq": 999,
        "kind": "advance_step",
        "type": "lifecycle",
        "started_at": 1.0,
        "ended_at": 2.0,
        "meta": json.dumps(signed_meta(step=9), ensure_ascii=False),
        "content": "{}",
    }
    record.update(overrides)
    return record


def _write(root: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_truncated_json_file_is_skipped(tmp_path: pathlib.Path) -> None:
    """进程被 kill 留下的半个 json：跳过，其余照常读出。"""
    good = _good_event(tmp_path)
    _write(tmp_path, "truncated.json", '{"uuid": "00000000-0000-7000-8000-000000000000", "seq": 9')

    assert [event.uuid for event in LocalTrace(root=tmp_path).read_events()] == [good]


def test_a_file_in_the_pre_seq_format_is_skipped(tmp_path: pathlib.Path) -> None:
    """合法 JSON 但缺 `seq` 的旧格式账：解析当场失败 → 跳过（不兼容旧账是拍板过的）。"""
    good = _good_event(tmp_path)
    pre_seq = _record()
    del pre_seq["seq"]
    _write(tmp_path, "pre-seq.json", json.dumps(pre_seq, ensure_ascii=False))

    assert [event.uuid for event in LocalTrace(root=tmp_path).read_events()] == [good]


def test_a_leftover_tmp_file_is_ignored(tmp_path: pathlib.Path) -> None:
    """原子写中断留下的 `.json.tmp`：内容就算合法也不许被当成事件。"""
    good = _good_event(tmp_path)
    leftover = _record(uuid="00000000-0000-7000-8000-000000000001")
    _write(tmp_path, "leftover.json.tmp", json.dumps(leftover, ensure_ascii=False))

    assert [event.uuid for event in LocalTrace(root=tmp_path).read_events()] == [good]


def test_a_file_with_unknown_extra_fields_is_still_read(tmp_path: pathlib.Path) -> None:
    """新记录多挂了字段（改形之后加的）：照常读出——`extra="allow"` 那一半契约。"""
    good = _good_event(tmp_path)
    extra = _record(uuid="00000000-0000-7000-8000-000000000002", extra_field="legacy")
    _write(tmp_path, "extra.json", json.dumps(extra, ensure_ascii=False))

    assert sorted(event.uuid for event in LocalTrace(root=tmp_path).read_events()) == sorted(
        [good, "00000000-0000-7000-8000-000000000002"]
    )


def test_a_file_whose_meta_is_not_an_object_matches_no_condition(tmp_path: pathlib.Path) -> None:
    """`meta` 不是 dict（解出来是个 list）：不筛选时列得出来，任何非空筛选都不命中。"""
    good = _good_event(tmp_path)
    _write(tmp_path, "list-meta.json", json.dumps(_record(meta="[1, 2]"), ensure_ascii=False))

    store = LocalTrace(root=tmp_path)

    assert len(store.read_events()) == 2, "不筛选时它仍是一条可读事件"
    assert len(store.read_events({})) == 2
    assert [event.uuid for event in store.read_events({"run_id": "run-1"})] == [good]
    assert [event.uuid for event in store.read_events({"step": 9})] == []
