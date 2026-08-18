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
