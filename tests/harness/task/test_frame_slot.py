"""帧槽的用法示范：写（`remember_frame`）与读（`frame_b64`）的两级语义。

**为什么这个文件值钱**：帧槽只有两个具名位（`TaskRuntime.frame_before` /
`frame_after`），能同时端住"这一步"与"下一步"两张图，靠的是**写新帧时把旧的
`after` 挪进 `before`** 这个动作，加上"两个读者都贴在这两步之内"这个时序假设——
两者都没有类型系统保护。这条测试把它们钉住。

**0914 封套改造删掉了第二级取法**：原先槽没命中还能回盘按 `deps.frame_event_ids`
读事件自带的 `frame_png`；封套不再带图，登记表、`read_event`、`frame_png` 互为唯一
消费者，一起下线。于是**帧槽成了画面唯一的取用通道**——这个文件后半段换成在证
"它确实一次都不碰 trace"。

**不连网、不碰模拟器、不调模型、不往仓库的 `tracelog/` 写**：落盘根用 `tmp_path`
（`LocalTrace(root=…)`）。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.harness.task.frames import frame_b64, remember_frame
from pokemon_agent.harness.task.task_runtime import TaskRuntime


class _NoTrace:
    """碰一下就炸——用来证明帧的取用**根本不经过 trace**。

    `deepcopy`、`hasattr` 这类内省会让 `__getattr__` 在正常路径上被意外触发，
    所以这里不覆盖 `__getattr__` 的哨兵名（`_`开头的那几个由 Python 自己走）。
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"帧的取用不该碰 trace（它要的是 {name}）")


def _deps() -> TaskRuntime:
    """只用到帧槽的最小 runtime；其余 Port 传 `None`。

    `TaskRuntime` 是 dataclass、不校验字段类型，传 `None` 是刻意的——比造几根假 Port
    更能说明"本测试只关心帧槽"。（帧槽 0923 188 起住 `TaskRuntime`——键级执行在
    task 层，槽跟着链走。）
    """
    return TaskRuntime(  # type: ignore[arg-type]
        game=None,
        chooser=None,
        judger=None,
        memory=None,
        reflector=None,
        verifier=None,
        task_summarizer=None,
        trace=_NoTrace(),
        reviewer=None,
    )


def _slot(deps: TaskRuntime) -> tuple[Any, Any]:
    """两位的当前值，按 `(episode_id, step, png)` 三元组比——断言读起来更直白。"""
    return deps.frame_before, deps.frame_after


def test_writing_a_frame_is_a_shift() -> None:
    """**挪**：写新帧时旧的 `after` 进 `before`，新帧落 `after`——只有两个位。"""
    deps = _deps()

    remember_frame(deps, "ep", 0, "F0")
    assert _slot(deps) == (("ep", 0, "F0"), None), "本局第一帧落 before（此时还没有下一步）"

    remember_frame(deps, "ep", 1, "F1")
    assert _slot(deps) == (("ep", 0, "F0"), ("ep", 1, "F1")), "第 2 帧落空着的 after"

    remember_frame(deps, "ep", 2, "F2")
    assert _slot(deps) == (("ep", 1, "F1"), ("ep", 2, "F2")), "再往后：旧的 after 挪进 before"

    remember_frame(deps, "ep", 3, "F3")
    assert _slot(deps) == (("ep", 2, "F2"), ("ep", 3, "F3")), "两步之外自动出槽，体积恒定"


def test_slot_is_cross_episode_and_none_safe() -> None:
    """换局时两位整对清空；`None`（没产出图）既不占位、也不推动挪动。"""
    deps = _deps()

    remember_frame(deps, "ep-1", 7, "F7")
    remember_frame(deps, "ep-1", 8, "F8")
    remember_frame(deps, "ep-2", 0, "G0")

    assert _slot(deps) == (("ep-2", 0, "G0"), None), "上一局的帧不该活着当新局的 before"

    remember_frame(deps, "ep-2", 1, None)
    assert _slot(deps) == (("ep-2", 0, "G0"), None), "缺帧不占槽位"


def test_slot_survives_a_missing_frame() -> None:
    """**缺帧之后挪不脱轨**：`None` 不写槽，但"当前这一步"的判定不受影响。

    时序：F0 落 `before` → 第 1 步的帧缺（感知那一档没产出图）→ F2 落 `after`。
    第 1 步本该查不到（它确实没图），第 2 步必须查得到。
    """
    deps = _deps()

    remember_frame(deps, "ep", 0, "F0")
    remember_frame(deps, "ep", 1, None)
    remember_frame(deps, "ep", 2, "F2")

    assert frame_b64(deps, "ep", 0) == "F0", "缺帧不挤掉 before"
    assert frame_b64(deps, "ep", 1) is None, "第 1 步本来就没有图"
    assert frame_b64(deps, "ep", 2) == "F2"


def test_frame_b64_never_touches_trace() -> None:
    """**帧只经这一个槽取**：命中给图、没命中给 `None`，两条路都不碰 trace。

    封套改造前这里有第二级（回盘读事件自带的 `frame_png`）；那一级删掉之后，
    "槽是唯一通道"这句话必须由测试说，而不是靠 `deps.trace` 恰好没被用到。
    """
    deps = _deps()
    remember_frame(deps, "ep", 0, "F0")

    assert frame_b64(deps, "ep", 0) == "F0"
    assert frame_b64(deps, "ep", 1) is None, "两位都不匹配 → None（没有回盘那一级）"
    assert frame_b64(deps, "ep-other", 0) is None, "别局的帧不串台"


def test_the_store_reads_both_frames_across_three_keys() -> None:
    """端到端时序：task 的 `sense` 每圈写一帧，`store_step_episode_memory` 每键读 before / after。

    首圈 `sense` 写开局帧 F0；之后每按一键 `sense` 写下一帧，store 要这一键前后两张。
    `deps.trace` 是个一碰就炸的替身，"读到了图"顺带证明整条路没碰 trace。
    """
    deps = _deps()
    ep = "ep"

    remember_frame(deps, ep, 0, "F0")  # 首圈 sense：开局帧
    for step in range(3):
        remember_frame(deps, ep, step + 1, f"F{step + 1}")  # 按键后 sense 取的新帧
        assert frame_b64(deps, ep, step) == f"F{step}"  # store 的 before_frame
        assert frame_b64(deps, ep, step + 1) == f"F{step + 1}"  # store 的 after_frame
