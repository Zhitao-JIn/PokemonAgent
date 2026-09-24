"""`compose_units`：把一组 `(state, runtime) -> dict` 单元**按序组合成一个格**。

三层同构压格后的公共组合器（episode 的 perceive / act / episode_done 与 task 的
act 都用它；带分支的格在短路处自行串接）。单元间用
`state.model_copy(update=增量)` 串接（**浅拷贝**，字段引用共享，成本可忽略），
保证后一个单元读到前一个单元的增量——与图引擎在两节点之间合并增量的语义
**完全一致**；返回值是全部增量的扁平合并，作为本格增量交回图引擎。
所以"合并成格"只改变图的形状，不改变任何单元的读写语义。
（三层各自的 state/runtime 形状不同，这里只按鸭子类型组合，不标具体类型。）
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Unit = Callable[..., dict[str, Any]]


def compose_units(
    state: Any,  # noqa: ANN401  (三层 state 形状不同，鸭子类型组合)
    runtime: Any,  # noqa: ANN401  (三层 runtime 形状不同)
    units: tuple[Unit, ...],
) -> dict[str, Any]:
    """按序执行 `units`，返回全部增量的扁平合并。

    前置条件：`units` 里每个都是 `(state, runtime) -> dict` 形状的图节点单元；
    单元间的数据依赖必须能经 state 字段传递（它们原本就是图节点，天然满足）。
    后置条件：返回 dict 可直接作为本格的增量——逐键合并后与"单元仍是独立
    节点"的终态逐字段相同。
    """
    updates: dict[str, Any] = {}
    current = state
    for unit in units:
        inc = unit(current, runtime)
        if inc:
            updates.update(inc)
            current = current.model_copy(update=inc)
    return updates


__all__ = ["Unit", "compose_units"]
