"""`LocalTrace` 的落盘根：缺省位置、`str` 与 `Path` 同等对待、目录自动创建、跨实例可见。

**为什么这个文件值钱**：`root` 是"数据落在哪"的唯一开关。缺省值曾经从 `__file__`
回溯仓库根，改成"进程启动目录"之后**由启动方决定**（`--trace-root` → `build_real`
→ `TraceTool.build` → `LocalTrace`）。这条链断在哪一环都会让账落到别处，而落错
地方不会报错——只会让人以为"没记账"。另三条钉的是参数归一与目录创建：命令行进来
的是 `str`，路径可以多级不存在。

**不往仓库写 `tracelog/`**：缺省根那条用 `monkeypatch.chdir(tmp_path)` 模拟"从别处启动"。
"""

from __future__ import annotations

import pathlib

import pytest
from _doubles.trace import signed_meta

from pokemon_agent.trace import LocalTrace


def test_default_root_is_tracelog_under_the_startup_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不传 `root`：落盘根 = **启动目录**下的 `tracelog/`，事件就平铺在里面。"""
    monkeypatch.chdir(tmp_path)

    store = LocalTrace()
    store.append("lifecycle", "advance_step", signed_meta(), {})

    assert (tmp_path / "tracelog").is_dir()
    assert len(store.read_events()) == 1


def test_a_str_root_is_accepted(tmp_path: pathlib.Path) -> None:
    """`str` 与 `Path` 同等对待——命令行传进来的就是字符串，不归一就会 `TypeError`。"""
    root = tmp_path / "x"

    store = LocalTrace(root=str(root))
    store.append("lifecycle", "advance_step", signed_meta(), {})

    assert root.is_dir()
    assert [path.name for path in root.glob("*.json")] == [f"{store.read_events()[0].uuid}.json"]


def test_missing_root_directories_are_created_recursively(tmp_path: pathlib.Path) -> None:
    """多级不存在的根由构造器建好——调用方不必先 `mkdir -p`。"""
    root = tmp_path / "a" / "b" / "c"

    LocalTrace(root=root).append("lifecycle", "advance_step", signed_meta(), {})

    assert root.is_dir()
    assert len(list(root.glob("*.json"))) == 1


def test_events_written_earlier_are_visible_to_a_new_instance(tmp_path: pathlib.Path) -> None:
    """先写后建实例：新实例不扫盘、不缓存，照样读得到之前那笔账。"""
    event_uuid = LocalTrace(root=tmp_path).append("lifecycle", "advance_step", signed_meta(), {})

    assert [event.uuid for event in LocalTrace(root=tmp_path).read_events()] == [event_uuid]
