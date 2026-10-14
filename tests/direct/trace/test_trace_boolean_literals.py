"""payload 里的布尔字段：**生产者必须写小写**（`true`/`false`）——全项目一套字面量。

这个文件守的是**生产侧**：`render.py` / `brain/brain.py` / `world/perceive_frame.py`
三处直接往账 payload 里写布尔的地方。核对侧（`tests/_harness_fixtures/node_io.py`
的 `BOOLEAN_FIELDS`）也能发现同一种错，但那要**跑完真机**才报得出来——而那时
PyBoy 启动费与一整局的模型钱已经付了。这里用 AST 在**离线**把同一件事拦住。

**为什么扫源码而不是调函数**：三处生产者里有两处要真实模型才走得到
（`brain.choose()` 要一次补全、`pyboy_world` 要一张真帧），而这条规则讲的是
**写法**——裸 `str(x)` 就是错的写法，不管当时有没有测试跑到它。

*（由来：0914 之前账本里同时存在两套布尔字面量——账单的 `ok` 与两条收尾账的
`success` 是大写。判据曾为此长出一个"按账查表"的特例，见 `CHANGELOG.md` 第 86 条。）*
"""

from __future__ import annotations

import ast
import pathlib

from _harness_fixtures import node_io

ROOT = pathlib.Path(__file__).resolve().parents[3]

PRODUCERS: tuple[pathlib.Path, ...] = (
    ROOT / "pokemon_agent" / "direct" / "trace" / "render.py",
    ROOT / "pokemon_agent" / "brain" / "brain.py",
    ROOT / "pokemon_agent" / "world" / "visual_perception.py",
)
"""三个**直接往 payload 里写布尔**的文件。它们是这条规则的全体生产者。

第四处若将来出现（比如 `trace` 之外又有人自己拼账单），核对侧一样会拦——
所以这里只列当下这三处，不假装穷举。
"""

ALLOWED_LITERALS: frozenset[str] = frozenset({"'true'", '"true"', "'false'", '"false"'})
"""写死的布尔字面量允许的样子（`ast.unparse` 给字符串常量加单引号，两种都放行）。"""


def _boolean_values(path: pathlib.Path) -> list[tuple[int, str]]:
    """扫出所有「键是布尔字段名」的字典项，返回 `(行号, 值表达式的源码)`。

    只看字典字面量里的键——**不看注释、不看 docstring**：说明文字里出现
    `success` 是完全正常的，而"payload 里那个字段写成了什么"只有字典项回答得了。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in node_io.BOOLEAN_FIELDS:
                found.append((node.lineno, ast.unparse(value)))
    return found


def test_every_boolean_payload_value_is_written_lowercase():
    """三个生产者写的布尔值，只能是 `str(...).lower()` 或小写字面量。

    允许的两种写法：`str(x).lower()`（算出来的）与 `'true'`/`'false'`（写死的）。
    其余一律不行，尤其是**裸 `str(x)`**——它会写出 `True`，而那正是这个项目
    曾经有过、后来被收掉的东西。
    """
    for path in PRODUCERS:
        values = _boolean_values(path)
        # 防空转：扫描逻辑写偏（字段名改了、路径错了）时，这条守卫会静默通过
        # ——那比没有守卫更糟，所以先要求"每个文件都真扫到了东西"。
        assert values, f"{path.relative_to(ROOT)} 里一个布尔 payload 字段都没扫到"
        for line, rendered in values:
            allowed = rendered.endswith(".lower()") or rendered in ALLOWED_LITERALS
            assert allowed, (
                f"{path.relative_to(ROOT)}:{line} 的布尔字段写成 {rendered}——"
                "账本只有小写一套字面量，用 `str(x).lower()` 或小写字面量"
            )


def test_the_scan_actually_catches_a_bare_str():
    """守卫自己也要被守卫：拿一段**故意写错**的源码喂进去，它必须报出来。

    这条测试防的是"扫描写了但恒真"——`test_every_boolean_payload_value_is_written_lowercase`
    的失败模式不是误报，是**它悄悄什么都没扫到**。
    """
    source = 'payload = {"ok": str(parsed is not None), "done": str(req.done).lower()}'
    tree = ast.parse(source)

    rendered: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in node_io.BOOLEAN_FIELDS:
                    rendered[key.value] = ast.unparse(value)

    assert rendered == {"ok": "str(parsed is not None)", "done": "str(req.done).lower()"}
    assert not rendered["ok"].endswith(".lower()"), "裸 str() 必须被判为不合规"
    assert rendered["done"].endswith(".lower()")
