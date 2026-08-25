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

用法：
    from pokemon_agent.prompts import load
    tpl = load("perceive_screen")
    text = tpl.render(scene_fields="...")
    trace.append(..., {"prompt_sha": tpl.sha})
"""

from __future__ import annotations

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
        """
        return string.Template(self.text).substitute(**kw)


def load(name: str) -> PromptTemplate:
    """按名字加载 `prompts/<name>.md`。

    失败：文件不存在直接抛。prompt 缺失不是可以兜底的情况。
    """
    path = _DIR / f"{name}.md"
    if not path.is_file():
        available = sorted(p.stem for p in _DIR.glob("*.md"))
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


def load_sections(name: str) -> dict[str, str]:
    """按 `## 名字` 切块加载 `prompts/<name>.md`。

    有些 prompt 片段不是一整块文字，而是**按情形分叉**的——每个按键一段、
    每个 overlay 一段。这类内容照样该放进这个目录，理由和模块 docstring 里那三条一样：
    可 review、可归因、无花括号冲突；只是它们在代码里原来是 dict 字面量，
    不是单一模板。Markdown 的标题天然就是"分叉"的写法，不用发明新格式，
    也不用为了塞进一个 `PromptTemplate` 就把结构拍扁成一整块文字。

    **目前零调用方**：唯一的用户 `INTENT_HELP` 随 intent 分派一起删了
    （两层版本 `load_nested_sections()` 还在被按键说明用着）。留着是因为它和
    `load_nested_sections()` 是一对，删一个留一个更怪；拆解机制在别处重写时
    如果不再用分节 prompt，它该跟着删。
    """
    return _split(load(name).text, "## ")


def load_nested_sections(name: str) -> dict[str, dict[str, str]]:
    """两层版本：`## 外层` 下面再按 `### 内层` 切块（例如「overlay → 按键说明」）。"""
    return {
        outer: _split(body, "### ")
        for outer, body in _split(load(name).text, "## ").items()
    }
