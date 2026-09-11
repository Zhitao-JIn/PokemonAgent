"""集中管理的 prompt。

**prompt 在这个项目里是实验变量，不是配置。** 所以它们单独放文件、单独版本化，
而不是散在各模块里当字符串常量：

- **可 review**：改 prompt 显示为干净的 diff，不是转义过的 Python 字符串
- **可归因**：`PromptTemplate.sha` 进 trace。跑出来的准确率是哪一版 prompt 的结果，
  必须说得清；否则改完 prompt 再跑一遍，两组数字没法比
- **无花括号冲突**：用 `string.Template` 的 `$var` 而不是 `str.format` 的 `{}`。
  prompt 里必然有 JSON 示例，`format` 会把 `{` 当占位符，逼你到处写 `{{`

用 `string.Template` 不算引入模板引擎（CLAUDE.md 拒绝的是引擎），
它是标准库里的字符串替换，模板内容依然一眼可见。

## 目录结构（物理边界体现"谁只服务谁"）

- **`calls/`**：直接拼成一次完整 LLM 请求、真的会发出去的模板——
  `judge_success`/`run_plan`/`verify_and_summarize`/`perceive_screen`
  四份是没有复用片段的独立文件，平铺在 `calls/` 下；`decide_action` 比较特殊，
  自己单独一个子目录 `calls/decide_action/`：
  - `decide_action.md`——真正会发出去的模板本体；
  - `button_help.md`/`map_hint.md`/`repeat_hint.md`/`retry_note.md`——**只服务
    `decide_action.md` 这一个模板**的内容块（查过：没有任何一份被别的模板复用，
    包括看起来最可能共用的 `retry_note`——`run_plan` 的重试是原样重问，不带纠正
    说明，跟 `decide_action` 的重试策略不是一回事）。物理上放进同一个目录，
    这个"只服务谁"的事实不用靠读代码才知道，打开文件夹就是答案。
- **每个需要拼装逻辑的模板，配一个同名的同级 `.py`**：`decide_action.py`/
  `judge_success.py`/`verify_and_summarize.py`/`run_plan.py`——对外只提供
  `build_prompt()`（`decide_action` 额外提供 `retry_prompt()`，`decide_action.md`
  独有重试纠正说明这个概念）。
  `decide_action.py` 的拼装内容（`BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT`
  三个常量 + 重试纠正说明 + 最终拼装）集中在这一个文件，三个常量仍对外暴露
  （给 `game_tools.py` 构造 `ActionSpace` 用）。`judge_success.py`
  服务 `Brain.judge()`——渲染搬出来给调用方（`EpisodeHarness`），`Brain`
  只收现成的 `prompt: str`；`verify_and_summarize.py` 同理服务
  `Brain.verify_and_summarize()`；`run_plan.py` 服务 `RunHarness.plan()`——
  `RunHarness` 只组装结构化的 `PlanOnceReq`，struct→text 一律在这层做。
  `perceive_screen` 没有配 `.py`：它不经过 `Brain` 也不经过任何 Harness 节点
  ——`PyBoyWorld` 自己 `load()` 并渲染，是"拥有这次 LLM 调用的那个类"自己的事。
  （`episode_summary.md` 已删除——蒸馏并入了 `Brain.verify_and_summarize()`
  的合并调用；结构演进史见 `CHANGELOG.md` 2026-09-04/05/06 条目。）

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
    "load",
    "load_nested_sections",
    "render_object_events",
]
import hashlib
import pathlib
import string
from dataclasses import dataclass

_DIR = pathlib.Path(__file__).parent


@dataclass(frozen=True)
class PromptTemplate:
    """一份 prompt 及其版本标识。

    `sha` 是内容哈希而不是手工维护的版本号：改了内容忘记改版本号是必然会发生的，
    而这里一旦对不上，整批实验数据的归因就废了。
    """

    name: str
    text: str
    sha: str

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
    sha = hashlib.sha256(text.encode()).hexdigest()[:12]
    return PromptTemplate(name=name, text=text, sha=sha)


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


from .decide_action import BUTTON_HELP, MAP_HINT, REPEAT_HINT  # noqa: E402
from .object_render import render_object_events  # noqa: E402
