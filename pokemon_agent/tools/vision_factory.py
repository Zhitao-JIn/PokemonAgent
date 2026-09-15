"""world 侧感知 provider 的**接线工厂**：从选型造出 `PyBoyWorld` 要的 `VisionProvider`。

**为什么这个函数住在 tools 层**（0913 深夜九）：`build.py` 原先在函数体内写
`from pokemon_agent.brain.providers import QwenProvider`——世界的感知实现
（`QwenProvider` 也实现 `describe()`）恰好住在 `brain/providers.py`，于是"给
world 造一个视觉 provider"这件事，让**唯一装配点直接伸手进 brain 的实现面**。
命题"只有 tool 层依赖 brain"因此字面不成立。

**这不是把实现搬走**：`QwenProvider` 的物理位置没错（它服务 brain 的
judge/verify，是 brain 的四个 provider，"谁消费归谁"）。错的是**装配知识**的
位置——"world 的感知怎么造、`temperature` 钉 0"这条接线知识跟
`BrainTool.build()` 里那条是同类的：都是"这个技能接哪家厂商"，
该收在 tool 层、离消费者近，装配点只递选型参数。

**它是 `BrainTool.build()` 的同构兄弟**：`BrainTool.build(text=…, judge=…)` 收
型号名造 brain 的四个 provider；本函数收一个型号名 + 温度造 world 的感知
provider。两个工厂都在 tool 层、都不被 `build.py` 越过——
**装配点那一侧现在只剩一行 `GameTools.build(...)`**（0913 夜：world 本体也
收进了 `GameTools.build()`，此前本函数的产物是 `build.py` 里手交给
`PyBoyWorld(...)` 的）——**协议归属、实现归属、接线归属三者对齐**。

**0914 起"哪个型号名属于哪家厂商"由 `providers.provider_for()` 的选型表回答**：
本函数此前恒造 `QwenProvider`（"世界永远走 DashScope"这条知识写死在 new 语句里），
现在按型号名前缀选类——`vision_model="deepseek-flash"` 就造 DeepSeek 那一个。
**由谁接这条链路因此是纯配置**：改调用方那个字符串即可，本文件不用动。

**它不引入第二个 `new` 实现处**：本函数是装配链的一部分（跟
`brain/build_llm_providers.py` 的地位相同），不是又一个"随便 new 实现"的口子
——全项目能 new 具体实现的地方仍然只有贴着消费者的几处工厂
（`BrainTool.build` / `GameTools.build` / `MemoryTool.build` / `TraceTool.build`
与本函数），**装配点 `build.py` 一个都不 new**。
"""

from __future__ import annotations

from pokemon_agent.world import VisionProvider

__all__ = ["build_vision_provider"]


def build_vision_provider(
    model: str = "qwen3.8-max",
    temperature: float = 0.0,
) -> VisionProvider:
    """造 world 感知要的那一个 `VisionProvider`。

    返回类型是 `world/interface/vision_provider.py` 的协议——调用方
    （`GameTools.build()`，它内部造 `PyBoyWorld`）只认识这张协议，不认识厂商类。

    **温度默认 0 且不给调用方随手改的理由**：感知是抽取不是创作，
    同一张图两次读出不同结果是纯噪声（见 `build.py` 的历史注释）。
    形参留着只是为了"哪天有链路需要不同温度"时不必改签名，现阶段一律 0。

    前置条件：`model` 的型号名前缀在 `providers._PROVIDER_PREFIXES` 里
        （`qwen*` / `doubao*` / `deepseek*`）。
    后置条件：返回实例的 `describe()` 满足 `VisionProvider` 协议——
        `PyBoyWorld` 拿它读帧；图片未送达时抛 `ImageNotDelivered`
        （由各 Provider 继承的 `_MultimodalMixin` 保证）。
    失败：型号名前缀不认识时抛 `ValueError`（`provider_for()` 就地炸，不拖到
        第一次感知才 404）。
    """
    # 导入放在函数内：`brain.providers` 顶部拖着整个厂商实现面（含 PIL），
    # 本模块被 `tools/__init__.py` 懒加载链带进来时不该顺带把它拉起来。
    from pokemon_agent.brain.providers import provider_for

    # 视觉链路的超时**单独收紧到 20s**：trace 实测视觉单次 max 1.16s（决策是
    # 它的 7 倍），且感知每步必调、挂起重试路径最长——20s 是实测的 17 倍裕量，
    # 过载网关的挂起在它面前能更快失败。文本四链用 `provider_for` 缺省 45s。
    return provider_for(model, temperature=temperature, timeout=20)
