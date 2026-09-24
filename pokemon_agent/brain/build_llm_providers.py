"""brain 的**厂商接线工厂**：从 `BrainLlmConfig` 造出 `Brain` 要的四个 provider。

**为什么这个函数住在 brain 而不是 build.py**（2026-09-13，S6）：`Brain` 的四个
provider 参数各自该配哪家厂商、温度多少——这些是**brain 这条链路的接线知识**，
不是"全项目怎么拼"的知识。放在 `build.py` 里时，`build.py` 要认识
`QwenProvider`/`ArkProvider` 两个具体类；放在这里则装配点只做一件事：
**把 config 递进来，把结果注入下去**。

**它不是"某个供应商的适配器"**：函数体里确实 new 了厂商实现，但装配点是全项目
唯一允许 new 具体实现的地方（CLAUDE.md 第三节第 3 条）之外的**唯一豁免**——
豁免的理由是本函数**本身就是装配点的一部分**，只是被搬到离消费者更近的地方。
它仍然只依赖 `interfaces` 的协议做返回类型，`Brain` 拿到的还是 Protocol 类型。

**它读 config 但不算 config**：`BrainLlmConfig`（0913 深夜九起住
`brain/interface/llm_config.py`）是 `build.py` 从模型名打包好的纯数据
（哪个位置用什么型号、max_tokens），这里不做任何"选型决策"——
选型的入口在 `BrainLlmConfig` 的字段上，一眼能看见。

**0914 起"哪个型号名属于哪家厂商"不再写死在这里**：四个 `provider_for()` 调用
按**型号名前缀**选类（表在 `providers.py` 的 `_PROVIDER_PREFIXES`）。在此之前
这个文件把 decide/judge 钉成 `QwenProvider`、verify/plan 钉成 `ArkProvider`，
于是"把 plan 换成 DeepSeek"要改的是这里的 new 语句，而"型号名与厂商类必须配套"
这条约束只存在于注释里——现在它是一张表：**传豆包型号名就造豆包类、传 deepseek
型号名就造 DeepSeek 类**，四个位置可以任意混搭。

**温度分层留在本模块**（0913 深夜九）：`temperature` 是**常量不是旋钮**
（judge/verify/plan 恒 0、decide 恒 0.3），所以它写在下面的构造语句里，
不进 `BrainLlmConfig` 的字段。config 只回答"选哪个型号"。
"""

from __future__ import annotations

from .interface import JudgeProvider, LLMProvider
from .interface.llm_config import BrainLlmConfig
from .providers import provider_for

DECIDE_TEMPERATURE = 0.3
"""决策链（`decide`）的温度：**刻意不为 0**。

完全归零会让同一局面反复交出同一动作，探索多样性靠它兜底。死循环另有
`detect_stall` 与 `judge` 兜底，所以这 0.3 不构成风险敞口。
"""

DETERMINISTIC_TEMPERATURE = 0.0
"""判定与结构化输出（`judge` / `verify` / `plan`）的温度：**确定性优先**。

这三个位置要的是可复现的结论与稳定的 JSON，不是创意。它们的输出会直接改
state（`done`/`success`）或决定"哪些记忆可信"，同一输入两次给出不同结论是纯噪声。
"""


THINKING_TIMEOUT_SECONDS = 420
"""开了思考模式的位置的单请求超时（秒；总时长硬闸是它 +15）。

缺省 45s 是按"不思考"的实测（决策 max 8.24s）定的；思考模式的单次请求要慢一个量级，
不放宽的话会被总时长闸当成 `ToolTimeout` 掐掉，重试预算白烧。随 plan 位置的输出上限
（`BrainLlmConfig.plan_max_tokens`）同比放大，拿到真机的 `reasoning_tokens` 与耗时账再收。
"""


def build_llm_providers(
    config: BrainLlmConfig,
) -> tuple[LLMProvider | None, JudgeProvider | None, JudgeProvider | None, LLMProvider | None]:
    """造 `Brain` 的 provider，返回 `(decide, judge, verify, plan)`——**按需**。

    返回顺序**就是** `Brain.__init__` 的形参顺序，调用方可以
    `Brain(*build_llm_providers(config))`。

    后置条件：返回值的类型与 `Brain.__init__` 的四个形参逐一匹配——
    `decide`/`plan` 是 `LLMProvider`（纯文本；`decide` 的带图路由由
    `Brain.choose` 查 provider 的 `multimodal` 标志分派，0915 129——
    当前在用型号全为多模态、标志默认真），
    `judge`/`verify` 是 `JudgeProvider`（带得到图时走多模态）。
    **config 里为 None 的位置返回 None**（0922 185 按需实例化：每层 BrainTool
    只造它要的链路；`Brain` 对应方法的入口 assert 把"没配就调"拦下）。
    **造出来的是不同的实例**：哪怕两个位置填同一个型号名，共用实例也会让 manifest
    里看不出"这两个位置其实可以分别选型"。

    失败：某个型号名的前缀不在 `provider_for()` 的选型表里时抛 `ValueError`
    ——**在装配期炸**，不是拖到第一次调用收到一个指不回型号名的 404。
    """
    # 步骤 1：决策链与判定链。温度分层见上面两个常量的说明。
    decide: LLMProvider | None = (
        provider_for(
            config.text,
            temperature=DECIDE_TEMPERATURE,
            max_tokens=config.max_tokens,
            json_mode=config.json_mode,
        )
        if config.text
        else None
    )
    judge: JudgeProvider | None = (
        provider_for(
            config.judge,
            temperature=DETERMINISTIC_TEMPERATURE,
            max_tokens=config.max_tokens,
            json_mode=config.json_mode,
        )
        if config.judge
        else None
    )

    # 步骤 2：verify 与 plan 各一个实例——它们走的链路、看的材料、产出的东西都不同
    # （verify 判"哪些记忆可信"、plan 维护目标表），共用一个实例会让 manifest 失真，
    # 也会让"这两个位置其实可以分别选型"这件事看不出来。
    verify: JudgeProvider | None = (
        provider_for(
            config.verify,
            temperature=DETERMINISTIC_TEMPERATURE,
            max_tokens=config.max_tokens,
            json_mode=config.json_mode,
        )
        if config.verify
        else None
    )
    plan: LLMProvider | None = (
        provider_for(
            config.plan,
            temperature=DETERMINISTIC_TEMPERATURE,
            max_tokens=config.plan_max_tokens,
            json_mode=config.json_mode,
            thinking=config.plan_thinking,
            timeout=THINKING_TIMEOUT_SECONDS if config.plan_thinking else 45,
        )
        if config.plan
        else None
    )

    # 出口断言（postcondition）：造出来的链路没有退化成同一个对象。
    built = [p for p in (decide, judge, verify, plan) if p is not None]
    assert len({id(p) for p in built}) == len(built), (
        "build_llm_providers() must return distinct provider instances"
    )
    return decide, judge, verify, plan


__all__ = [
    "DECIDE_TEMPERATURE",
    "DETERMINISTIC_TEMPERATURE",
    "build_llm_providers",
]
