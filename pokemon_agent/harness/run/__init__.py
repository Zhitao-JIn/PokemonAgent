"""run 图（一个 run = 完整一局游戏）——episode 图是它的子图。

步 0 建立本包时只有 `run_state.py`（状态载体）与 `run_graph.py`（装配）；步 2 把
`dispatch` 拆出"接子图"的 `episode` 节点；步 4 把 6 个节点搬成自由函数、`RunHarness`
收成薄类（`harness.py`）、图外侧门落 `run_entry.py`。

**包根只放骨架，节点统一住 `nodes/`**（v16 订正，`PLAN_graph_composition.md` §3.1）：
run 图只有 6 格、没有 episode 那种"七个功能域"可分，所以不按域切，而是用一层不分域的
`nodes/` 包住——**run 下两层**（骨架 / 节点），与 `episode/<功能域>/<节点>.py` 同深，
包根一眼看去全是骨架：

- 结构性文件带 `run_` 前缀（`run_graph.py` / `run_state.py` / `run_entry.py`）；
- 外部调用面 `harness.py`（`RunHarness` 薄类）；
- 节点在 `nodes/`，**文件名 = 节点名**（§5.3-⑤）：`begin.py` / `plan.py` /
  `dispatch.py` / `episode.py` / `reflect.py` / `review.py`。

（原取舍"节点平铺在包根、只多一跳 import"已被这一层目录取代：跳的那一跳换成
"包根从此不必先分辨某个名字是骨架还是节点"。）
"""

from __future__ import annotations

from . import run_entry
from .run_graph import compile_run_graph
from .run_state import RunState

__all__ = [
    "RunState",
    "compile_run_graph",
    "run_entry",
]
