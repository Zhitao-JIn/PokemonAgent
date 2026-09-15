"""world 自己的 prompt 素材：**"拥有这次 LLM 调用的那个类"自己的东西**。

**它为什么不在 `tools/prompts/`**（0913 定案）：`tools/` 是桥层——它的存在意义是
"被 harness 依赖、去依赖各模块"。`perceive_screen` 这条链跟 `tools/` 的另外三份
（`decide_action`/`judge_success`/`run_plan`/`verify`/`summarize`）不是一回事：
那几份由 harness/brain 的链路消费，留在 `tools/prompts/` 是对的；
**这一份的消费者是 `PyBoyWorld`**——它不经过 `Brain`、也不经过任何 Harness
节点，是 `PyBoyWorld` 自己 `load()` 并渲染的。

于是 `world → tools.prompts` 曾经是一条**真实的环**（`tools/prompts/__init__.py`
→ `decide_action.py` → `pokemon_agent.world`），现在不炸只是因为
`world/__init__.py` 的 `interface/` 是 eager、`pyboy_world` 是 lazy 恰好错开。
按 P1「把 `world/` 拷进另一个项目，感知还跑得起来吗」这条判据，拷走之后
`PyBoyWorld.__init__` 第一句就 `ImportError`——**跑不起来**。所以素材跟着
world 走，这条出边就此归零。

**跟 `tools/prompts/` 的关系**：两份读取器**各自声明、互不 import**——
与 `world/interface/domain/vision_describe.py` 那两封副本同一条判据（P6
"两边各持一份，漂移就是运行时错误"）。语义逐字对齐（`string.Template`
的 `$var`、递归找 `<name>.md`、重名当场炸），但**不是同一份代码**：
world 拷走后不该欠 `tools/` 任何东西。

**为什么用 `string.Template` 而不是 `str.format`**：prompt 里必然有 JSON 示例，
`format` 会把 `{` 当占位符（这跟 `tools/prompts/` 的取舍同源）。
"""

from __future__ import annotations

import pathlib
import string
from dataclasses import dataclass

__all__ = ["PromptTemplate", "load"]

_DIR = pathlib.Path(__file__).parent


@dataclass(frozen=True)
class PromptTemplate:
    """一份 prompt 模板。"""

    name: str
    text: str

    def render(self, **kw: object) -> str:
        """替换 `$var` 占位符。

        前置条件：模板里出现的每个占位符都必须给值。
        用 `substitute` 而不是 `safe_substitute`：漏传一个变量应当当场炸，
        而不是把字面量 `$foo` 悄悄发给模型——那会得到一个看似正常的错误结果。

        把占位符替换成实参，返回完整 prompt。
        """
        return string.Template(self.text).substitute(**kw)


def _find(name: str) -> pathlib.Path | None:
    """在整棵 `world/prompts/` 目录树里递归找 `<name>.md`。

    不写死分类目录名——目录结构以后再拆，这里不用跟着改。两个不同位置出现
    同名文件是设计上不该有的歧义（一份 prompt 只该有一个物理位置），
    当场炸出来比默默取第一个匹配更安全。
    """
    matches = sorted(_DIR.rglob(f"{name}.md"))
    assert len(matches) <= 1, f"prompt 名字 {name!r} 在多个位置重复：{matches}"
    return matches[0] if matches else None


def load(name: str) -> PromptTemplate:
    """按名字加载 `world/prompts/` 目录树下的 `<name>.md`，不用管它在哪层子目录。

    失败：文件不存在直接抛。prompt 缺失不是可以兜底的情况。

    按名字读出一份 prompt 模板。
    """
    path = _find(name)
    if path is None:
        available = sorted(p.stem for p in _DIR.rglob("*.md"))
        raise FileNotFoundError(f"没有 prompt {name!r}；现有：{available}")

    return PromptTemplate(name=name, text=path.read_text(encoding="utf-8"))
