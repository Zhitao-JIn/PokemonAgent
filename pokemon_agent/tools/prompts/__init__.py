"""集中管理的 prompt。

**prompt 在这个项目里是实验变量，不是配置。** 所以它们单独放文件、单独版本化，
而不是散在各模块里当字符串常量：

- **可 review**：改 prompt 显示为干净的 diff，不是转义过的 Python 字符串
- **无花括号冲突**：用 `string.Template` 的 `$var` 而不是 `str.format` 的 `{}`。
  prompt 里必然有 JSON 示例，`format` 会把 `{` 当占位符，逼你到处写 `{{`

用 `string.Template` 不算引入模板引擎（CLAUDE.md 拒绝的是引擎），
它是标准库里的字符串替换，模板内容依然一眼可见。

## 目录结构（物理边界体现"谁只服务谁"）

- **`calls/`**：直接拼成一次完整 LLM 请求、真的会发出去的模板——
  `judge_success`/`run_plan`/`verify`/`summarize`/`extract`
  五份是没有复用片段的独立文件，平铺在 `calls/` 下；`decide_action` 比较特殊，
  自己单独一个子目录 `calls/decide_action/`：
  - `decide_action.md`——真正会发出去的模板本体；
  - `button_help.md`/`map_hint.md`/`repeat_hint.md`/`retry_note.md`——**只服务
    `decide_action.md` 这一个模板**的内容块（查过：没有任何一份被别的模板复用，
    包括看起来最可能共用的 `retry_note`——`run_plan` 的重试是原样重问，不带纠正
    说明，跟 `decide_action` 的重试策略不是一回事）。物理上放进同一个目录，
    这个"只服务谁"的事实不用靠读代码才知道，打开文件夹就是答案。
- **每个需要拼装逻辑的模板，配一个同名的同级 `.py`**：`decide_action.py`/
  `judge_success.py`/`verify.py`/`summarize.py`/`extract.py`/`run_plan.py`——对外只提供
  `build_prompt()`（`decide_action` 额外提供 `retry_prompt()`，`decide_action.md`
  独有重试纠正说明这个概念）。
  `decide_action.py` 的拼装内容（`BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT`
  三个常量 + 重试纠正说明 + 最终拼装）集中在这一个文件，三个常量仍对外暴露
  （给 `game_tools.py` 构造 `ActionSpace` 用）。`judge_success.py`
  服务 `Brain.judge()`——渲染搬出来给调用方（`EpisodeHarness`），`Brain`
  只收现成的 `prompt: str`；`verify.py`/`summarize.py`/`extract.py` 同理服务
  `Brain.verify()`/`Brain.summarize()`/`Brain.extract()`（**各占一个模块**：前两个
  原本合并成一次调用，拆开后模板与装配模块都跟着一分为二；`extract` 从一出生就是
  独立的一条链路——它跟 `summarize` 收同一类素材，但产物归属完全不同）；`run_plan.py` 服务
  `RunHarness.plan()`——`RunHarness` 只组装结构化的 `PlanOnceReq`，
  struct→text 一律在这层做。
  `perceive_screen` **已经不在这一层了**（0913 定案，CHANGELOG 同日条目）：
  它不经过 `Brain` 也不经过任何 Harness 节点——`PyBoyWorld` 自己 `load()` 并渲染，
  是"拥有这次 LLM 调用的那个类"自己的事，所以素材跟着 world 走
  （现居 `world/prompts/perceive_screen.md`，读取器 `world/prompts/__init__.py`）。
  它曾经还构成一条**反向依赖**（`world → tools.prompts → world` 的环），
  只是被 `world/__init__.py` 的"interface eager / 实现 lazy"恰好错开——
  那份保护是脆的，所以按 P1「拷走 world 后感知还跑得起来吗」把它移回去了。
  （`episode_summary.md` 与 `verify_and_summarize.md` 都已删除——前者并进了那次
  合并调用，后者又随 `verify`/`summarize` 拆成两次独立调用而退役，各由
  `calls/verify.md` + `calls/summarize.md` 接手；结构演进史见 `CHANGELOG.md`
  2026-09-04/05/06 与 2026-09-12 第 39 条。）

**调用方不需要关心某个 prompt 到底在哪一层子目录下**：`load(name)` 在整棵
`prompts/` 目录树里递归找 `<name>.md`，`load("decide_action")` 和
`load("button_help")` 写法完全一样——这正是"统一读取入口"的意义：新增/挪动
一份 prompt 只用改它在哪个目录下，不用动任何调用点。两份不同目录下重名会
当场报错（`assert`），不会默默取第一个匹配。

用法：
    from pokemon_agent.prompts import load
    tpl = load("perceive_screen")
    text = tpl.render(scene_fields="...")
"""

from __future__ import annotations

__all__ = [
    "BUTTON_HELP",
    "MAP_HINT",
    "PromptTemplate",
    "REPEAT_HINT",
    "append_human_note",
    "load",
    "load_nested_sections",
    "render_object_events",
]
import pathlib
import string
from dataclasses import dataclass

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
    """在整棵 `prompts/` 目录树里递归找 `<name>.md`。

    不写死分类目录名——目录结构以后再拆（比如某个模板也长出自己的子目录），
    这里不用跟着改。两个不同位置出现同名文件是设计上不该有的歧义（一份
    prompt 只该有一个物理位置），当场炸出来比默默取第一个匹配更安全。
    """
    matches = sorted(_DIR.rglob(f"{name}.md"))
    assert len(matches) <= 1, f"prompt 名字 {name!r} 在多个位置重复：{matches}"
    return matches[0] if matches else None


def load(name: str) -> PromptTemplate:
    """按名字加载 `prompts/` 目录树下的 `<name>.md`，不用管它在哪层子目录。

    失败：文件不存在直接抛。prompt 缺失不是可以兜底的情况。

    按名字读出一份 prompt 模板。
    """
    path = _find(name)
    if path is None:
        available = sorted(p.stem for p in _DIR.rglob("*.md"))
        raise FileNotFoundError(f"没有 prompt {name!r}；现有：{available}")

    text = path.read_text(encoding="utf-8")
    return PromptTemplate(name=name, text=text)


def _split(text: str, marker: str) -> dict[str, str]:
    """按 `marker + 名字`（独占一行）切块，返回 `{名字: 块内容}`（去掉首尾空行）。"""
    sections: dict[str, str] = {}
    name: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith(marker):
            if name is not None:
                sections[name] = "\n".join(buf).strip()
            name = line.removeprefix(marker).strip()
            buf = []
        elif name is not None:
            buf.append(line)
    if name is not None:
        sections[name] = "\n".join(buf).strip()
    return sections


def load_nested_sections(name: str) -> dict[str, dict[str, str]]:
    """两层版本：`## 外层` 下面再按 `### 内层` 切块（例如「overlay → 按键说明」）。"""
    return {outer: _split(body, "### ") for outer, body in _split(load(name).text, "## ").items()}


def append_human_note(prompt: str, note: str) -> str:
    """把人类插话**拼在 prompt 的最末尾**（空串则原样返回）。

    **为什么在最末尾，而不是插在某个"插话小节"里**（用户 0914 定调）：
    这是一条**临时覆盖指令**，它的效力来自"刚说完、就在眼前"。
    模型是按顺序读 prompt 的，把它放在中间某处，它就会和那些讲规则的长段落
    混在一起被当成"又一个背景说明"；放在最后，它紧贴着"现在输出 JSON"那句话，
    是所有约束里最后读到的、也是唯一一条"针对这一次"的。

    **为什么放这里而不是两份 prompt 各自写一遍**：`decide_action` 与
    `judge_success` 都要它，而"插话压过一切"这条语义**必须两边一致**——
    各自写一份，改了一处忘了另一处，症状是人说话之后有的链路听、有的不听。

    措辞刻意短：它是覆盖指令，不是又一节规范。写长了会被模型当成需要权衡的
    材料，而这里要的是"照做"。

    **必须在下面那两个子模块 import 之前定义**：`decide_action` /
    `judge_success` 都要 `from . import append_human_note`——本模块 import
    它们时若这个名字还没绑定，会当场炸成部分初始化的 `ImportError`
    （与 `harness/interface/` 那次循环是同一类形状）。
    """
    note = note.strip()
    if not note:
        return prompt
    return (
        prompt
        + "\n\n---\n\n## 人类刚刚插的话（最高优先级，压过上面所有规则）\n\n"
        + f"> {note}\n\n"
        + "照这句话办。如果它和你原本的判断冲突，改听人类，并在输出里如实说明"
        + "「人类指示：{原话摘要}，因此改为……」——不要既听人类的又假装是自己原来的结论。\n"
    )


from .decide_action import BUTTON_HELP, MAP_HINT, REPEAT_HINT  # noqa: E402
from .object_render import render_object_events  # noqa: E402
