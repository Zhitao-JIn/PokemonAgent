"""brain 的**厂商接线工厂**：从 `BrainLlmConfig` 造出 `Brain` 要的四个 provider。

**为什么这个函数住在 brain 而不是 build.py**（2026-09-13，S6）：哪条链路接哪家厂商是 brain 这条
链路的接线知识；装配点只负责把配置递进来、把结果注入下去，不认识任何厂商类。

**它读选型表但不做选型**：`BrainLlmConfig` 里每个位置的型号、温度、输出上限、单请求超时、
思考开关都是纯数据（来自配置文件，经 tool 层转成 `LinkSpec`），这里一个数字都不写死。

**厂商由型号名前缀决定**（0914 起）：四个 `provider_for()` 调用按前缀选类（表在
`providers.py` 的 `_PROVIDER_PREFIXES`），四个位置可以任意混搭；前缀不认识时在装配期抛
`ValueError`，不拖到第一次调用才 404。
"""

from __future__ import annotations

from .interface import JudgeProvider, LLMProvider
from .interface.llm_config import BrainLlmConfig, LinkSpec
from .providers import _OpenAICompatibleBase, provider_for


def build_llm_providers(
    config: BrainLlmConfig,
) -> tuple[LLMProvider | None, JudgeProvider | None, JudgeProvider | None, LLMProvider | None]:
    """造 `Brain` 的 provider，返回 `(decide, judge, summary, plan)`——**按需**。

    返回顺序**就是** `Brain.__init__` 的形参顺序，调用方可以
    `Brain(*build_llm_providers(config))`。

    后置条件：返回值的类型与 `Brain.__init__` 的四个形参逐一匹配——`decide`/`plan` 是
    `LLMProvider`，`judge`/`summary` 是 `JudgeProvider`（带得到图时走多模态）。
    **config 里为 None 的位置返回 None**（按需实例化：每层 BrainTool 只造它要的链路）。
    **造出来的是不同的实例**：哪怕两个位置填同一个型号名，共用实例也会让 manifest
    里看不出"这两个位置其实可以分别选型"。

    失败：某个型号名的前缀不在 `provider_for()` 的选型表里时抛 `ValueError`
    ——**在装配期炸**，不是拖到第一次调用收到一个指不回型号名的 404。
    """
    # 步骤 1：四个位置各按自己的 LinkSpec 造 provider。
    decide = _build(config.text, config)
    judge = _build(config.judge, config)
    summary = _build(config.summary, config)
    plan = _build(config.plan, config)

    # 步骤 2：出口断言（postcondition）：造出来的链路没有退化成同一个对象。
    built = [p for p in (decide, judge, summary, plan) if p is not None]
    assert len({id(p) for p in built}) == len(built), (
        "build_llm_providers() must return distinct provider instances"
    )
    return decide, judge, summary, plan


def _build(spec: LinkSpec | None, config: BrainLlmConfig) -> _OpenAICompatibleBase | None:
    """按一个位置的 `LinkSpec` 造 provider；`spec` 为 None 返回 None。"""
    if spec is None:
        return None
    return provider_for(
        spec.model,
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        json_mode=config.json_mode,
        timeout=spec.timeout_s,
        thinking=spec.thinking,
        cache_marker=spec.cache_marker,
        vision_dump_dir=config.vision_dump_dir,
    )


__all__ = ["build_llm_providers"]
