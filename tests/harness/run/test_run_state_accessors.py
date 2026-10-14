"""机械核对：run 图里每一格只访问 `RunState` 上**真实存在**的字段。

**为什么需要这条判据**：`RunState` 是 Pydantic 模型，`state.<写错的字段>` 既不会在
import 期报错、也不会被类型检查拦下（本仓不跑 mypy），只会在**那一格真跑起来**时
抛 `AttributeError`。而 run 图的测试用**假 episode 节点**替掉了唯一真驱动模拟器的
那一格（`test_run_graph_termination.py` 的 `fake_episode`），于是"某格读了已删的
字段"这种错可以一路活到真机——**测试全绿，真机第一局就崩**。

0914 就是这么炸的：控制台改造把 `RunState.goals` 拆成 `plan` + `episode_goals`，
`nodes/episode.py` 里那行 `stack=state.goals` 没人发现。真机 `harness.run` 第一局：

    AttributeError: 'RunState' object has no attribute 'goals'

**判据取"静态读源码"而不是"跑一遍"**：跑一遍需要 PyBoy + 真实模型（贵且慢），
而"字段名拼错"是一个**只读源码就能定案**的问题。AST 扫出来的每一条都是确定的
事实，不依赖任何 mock 的行为——**这正是那次事故里缺的东西**。

**覆盖面**：`harness/run/` 整个包（四个节点 + 骨架三个文件）。同名的局部变量
（`runtime`、lambda 里的 `s`）不参与，只认形参叫 `state` 的那种。
"""

from __future__ import annotations

import ast
import pathlib

import pokemon_agent.harness.run as run_pkg
from pokemon_agent.harness.run.run_state import RunState

_RUN_DIR = pathlib.Path(run_pkg.__file__).parent


def _state_attrs(path: pathlib.Path) -> set[str]:
    """源码里所有 `state.<attr>` 形式的属性名（只看名字叫 `state` 的那个对象）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "state"
    }


def test_every_run_node_touches_only_real_run_state_fields() -> None:
    """每个节点读的字段都必须在 `RunState` 上存在。

    `state.goals[0].model_copy(...)` 这类**不是**在读 state 的字段（那是读列表元素
    的方法），不会进这个集合——判据只认"直接挂在 `state` 上的属性"。
    """
    fields = set(RunState.model_fields) | {"done", "success"}  # `Settled` 的两个派生读法

    for path in sorted(_RUN_DIR.rglob("*.py")):
        unknown = _state_attrs(path) - fields
        assert not unknown, (
            f"{path.relative_to(_RUN_DIR)} 读了 RunState 上没有的字段：{sorted(unknown)}"
            f"\nRunState 现有字段：{sorted(fields)}"
            "\n（字段被改名/拆开之后，读它的地方要一起改——0914 的 `state.goals` 就是这么漏的）"
        )


def test_the_guard_is_not_vacuous(tmp_path: pathlib.Path) -> None:
    """判据本身不许空转：伪造一个读已删字段的节点，它必须被抓出来。

    没有这一条的话，`_state_attrs` 哪天被改坏成"永远返回空集"，上面那条测试
    仍然全绿——**一条不会失败的核对等于没有核对**。
    """
    fake = tmp_path / "some_node.py"
    fake.write_text(
        "def some_node(state, runtime):\n    return {'x': state.outcomes}\n",
        encoding="utf-8",
    )

    assert _state_attrs(fake) - set(RunState.model_fields) == {"outcomes"}


def test_the_scan_reaches_the_nodes() -> None:
    """覆盖面本身也要核：扫到的文件里必须包含那五个节点。

    否则目录一改名（`nodes/` → 别的），这条核对会**静默变空**。
    """
    scanned = {path.relative_to(_RUN_DIR).as_posix() for path in _RUN_DIR.rglob("*.py")}

    assert {
        "begin/__init__.py",
        "perceive/__init__.py",
        "plan_run/plan_run.py",
        "act/dispatch.py",
        "act/__init__.py",
        "review_and_judge/review_and_judge.py",
        "run_done/__init__.py",
    } <= scanned
