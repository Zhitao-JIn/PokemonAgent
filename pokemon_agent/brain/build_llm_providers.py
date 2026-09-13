"""brain 的**厂商接线工厂**：从 `BrainLlmConfig` 造出 `Brain` 要的四个 provider。

**为什么这个函数住在 brain 而不是 build.py**（2026-09-13，S6）：`Brain` 的四个
provider 参数各自该配哪家厂商、温度多少、哪个位置必须用豆包型号名——这些是
**brain 这条链路的接线知识**，不是"全项目怎么拼"的知识。放在 `build.py` 里时，
`build.py` 要认识 `QwenProvider`/`ArkProvider` 两个具体类、还要记得
"verify/plan 的 model 缺省值必须是豆包后缀名"这条只对 brain 成立的规则；
放在这里则装配点只做一件事：**把 config 递进来，把结果注入下去**。

**它不是"某个供应商的适配器"**：函数体里确实 new 了厂商实现，但装配点是全项目
唯一允许 new 具体实现的地方（CLAUDE.md 第三节第 3 条）之外的**唯一豁免**——
豁免的理由是本函数**本身就是装配点的一部分**，只是被搬到离消费者更近的地方。
它仍然只依赖 `interfaces` 的协议做返回类型，`Brain` 拿到的还是 Protocol 类型。

**它读 config 但不算 config**：`BrainLlmConfig`（0913 深夜九起住
`brain/interface/llm_config.py`）是 `build.py` 从模型名打包好的纯数据
（哪个位置用什么型号、max_tokens），这里不做任何"选型决策"——
选型的入口在 `BrainLlmConfig` 的字段上，一眼能看见。

**温度分层留在本模块**（0913 深夜九）：`temperature` 是**常量不是旋钮**
（judge/verify/plan 恒 0、decide 恒 0.3），所以它写在下面的构造语句里，
不进 `BrainLlmConfig` 的字段。config 只回答"选哪个型号"。
"""

from __future__ import annotations

from .interface import JudgeProvider, LLMProvider
from .interface.llm_config import BrainLlmConfig
from .providers import ArkProvider, QwenProvider


def build_llm_providers(
    config: BrainLlmConfig,
) -> tuple[LLMProvider, JudgeProvider, JudgeProvider, LLMProvider]:
    """造 `Brain` 的四个 provider，返回 `(decide, judge, verify, plan)`。

    返回顺序**就是** `Brain.__init__` 的形参顺序，调用方可以
    `Brain(*build_llm_providers(config))`。

    后置条件：四个返回值的类型与 `Brain.__init__` 的四个形参逐一匹配——
    `decide`/`plan` 是纯 `LLMProvider`（这两条链路本来就不该看图），
    `judge`/`verify` 是 `JudgeProvider`（带得到图时走多模态）。
    **四个是不同的实例**：哪怕型号相同，共用实例会让 manifest 里看不出
    "这两个位置其实可以分别选型"。`ArkProvider` 那条路径额外保证型号名非空
    （它的 `__init__` 有 assert），空串在这里就炸，不会拖到第一次调用。

    `Brain` 只认识 `LLMProvider`/`JudgeProvider` 两个协议，**不认识
    `QwenProvider`/`ArkProvider`**——厂商名字只出现在本函数里。
    """
    # 步骤 1：DashScope 侧两个（文字/视觉两用，`QwenProvider` 两个方法都实现）。
    # temperature 分层：judge 是判定任务、确定性优先 → 0；decide 保留 0.3 的
    # 少量随机，完全归零会让同一局面反复交出同一动作（探索多样性靠它兜底，
    # 死循环另有 stall 检测与 judge 兜底）。
    decide: LLMProvider = QwenProvider(
        model=config.text, temperature=0.3, max_tokens=config.max_tokens
    )
    judge: JudgeProvider = QwenProvider(
        model=config.judge, temperature=0.0, max_tokens=config.max_tokens
    )

    # 步骤 2：火山方舟侧两个（豆包）。verify 单独一个实例是因为它跟 judge 走的
    # 是不同供应商、不同计费方式（见 `build.py` 的供应商分岗注释）；型号名缺省
    # 回退在调用方，这里是"给定就用给定的"。
    verify: JudgeProvider = ArkProvider(
        model=config.verify, temperature=0.0, max_tokens=config.max_tokens
    )
    plan: LLMProvider = ArkProvider(
        model=config.plan, temperature=0.0, max_tokens=config.max_tokens
    )

    # 出口断言（postcondition）：四条链路没有退化成同一个对象。
    assert len({id(p) for p in (decide, judge, verify, plan)}) == 4, (
        "build_llm_providers() must return four distinct provider instances"
    )
    return decide, judge, verify, plan


__all__ = ["build_llm_providers"]
