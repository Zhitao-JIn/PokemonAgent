"""settings 模块的错误词汇：自成一根 `SettingsError`，不继承全局根。

三类失败都是**预期内**的运行时情况（配置文件是外部输入，不是调用方），
所以走具名异常，不用 assert。
"""

from __future__ import annotations


class SettingsError(Exception):
    """settings 模块所有失败的根。"""


class ConfigFileError(SettingsError):
    """配置文件读不到、不是合法 JSON，或顶层不是对象。"""


class ConfigValidationError(SettingsError):
    """合并后的配置未通过 schema 校验。

    `issues` 每条形如 `models.plan.timeout_s: Input should be greater than 0`，
    `sources` 是参与合并的文件（保底在前、覆盖在后），用来回答"这个值可能是谁改的"。
    """

    def __init__(self, issues: tuple[str, ...], sources: tuple[str, ...]) -> None:
        self.issues = issues
        self.sources = sources
        detail = "\n  ".join(issues)
        origin = " <- ".join(reversed(sources))
        super().__init__(f"配置校验失败（来源 {origin}）：\n  {detail}")
