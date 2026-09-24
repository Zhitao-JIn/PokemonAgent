"""`BrainLlmConfig`：`Brain` 四个 provider 的**选型与超参**，纯数据。

**为什么它住 `brain/interface/` 而不是 `brain/build_llm_providers.py`**
（0913 深夜九定案）：它跟 `Action`/`Goal` 一样是**零重依赖的纯数据**，
但原先住在工厂模块里时，任何只想拿这个 dataclass 的调用方
（`build.py` 只为了 `BrainLlmConfig(...)` 造一份选型表）都要连着进口
`build_llm_providers.py` 顶部的 `from .providers import ArkProvider, QwenProvider`
——**实测连带拉进 25 个 brain 模块 + `PIL`**。"我想说这次用什么型号"
和"我要一个 HTTP 客户端"是两件事，不该被一个 import 绑在一起。

放进 `interface/` 之后，`from pokemon_agent.brain import BrainLlmConfig`
只走到这一层（`brain/interface/__init__.py` 的立即加载面），
`providers`/`build_llm_providers` 一个都不碰。

**它为什么属于 `interface` 而不是 `providers`**：它描述的是**契约参数**
（`Brain` 要四个什么样的 provider），而不是**某个厂商的接线细节**——
厂商名（`qwen`/`doubao`）只出现在字段的**默认值**里，字段本身是型号名字符串。
"哪家厂商"这个知识仍然留在 `build_llm_providers.py`（它才知道
`verify` 那个位置必须是豆包型号名）。

**搬运后不变的约束**：这里**只放数据、不放逻辑**，`frozen=True`，
四个字段给默认值使 `BrainLlmConfig()` 就是一个能直接跑的真实链路配置。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrainLlmConfig:
    """`Brain` 四个 provider 的**选型与超参**，全是纯数据。

    `frozen=True`：装配期构造一次、此后只读——它描述的是"这次 run 用哪些模型"，
    中途改它没有任何语义（provider 实例已经造出去了）。

    字段分成两组，跟 `Brain.__init__` 的四个参数一一对应：

    - `text` / `judge`：走 DashScope（`QwenProvider`）。`text` 是 `choose()` 的
      决策模型（`temperature=0.3`，保留少量随机做探索多样性）；`judge` 是
      `judge()` 的判定模型（`temperature=0.0`，确定性优先）。
    - `verify` / `plan`：走火山方舟（`ArkProvider`，豆包）。两者都
      `temperature=0.0`；模型名**必须是带日期后缀的豆包型号名**——`ArkProvider`
      收到 Qwen 型号名会直接 404，不是"退化成纯文本"这种优雅失败
      （`ArkProvider.__init__` 里有 assert 兜住空串，但型号名对错它验不了）。

    四个字段都是 `str | None`，**缺省 `None` = 这个位置这次不装配**（0922 185
    按需实例化：每层 BrainTool 只造它要的链路，`build_llm_providers()` 对 None
    位置返回 None、`Brain` 对应方法的入口 assert 会把"没配就调"拦下）。
    全部给型号名时就是一个能直接跑的完整配置。想换型号只改这里。

    **温度分层的知识不在这里**（0913）：`temperature` 是**常量**不是旋钮
    （judge/verify/plan 恒 0、decide 恒 0.3），所以它写在
    `brain/build_llm_providers.py` 的构造语句里，本类只带"选哪个型号"。
    """

    text: str | None = None
    """`choose()` 的模型（DashScope）。`None` = 这次不装配决策链。"""

    judge: str | None = None
    """`judge()` 的模型（DashScope）。**跟 `text` 分开是硬要求**：判定与决策
    误差同源会让"读错画面 → 以为达成 → 判成功"这条错路越走越顺
    （`Brain` 模块 docstring 有论证），所以哪怕同型号也不共用实例。
    `None` = 这次不装配判定链。"""

    verify: str | None = None
    """`verify()`/`summarize()` 的模型（火山方舟，豆包）。`None` = 这次不装配。"""

    plan: str | None = None
    """`plan()` 的模型（火山方舟，豆包）。`None` = 这次不装配规划链。"""

    max_tokens: int = 25600
    """四个 provider 共用的输出上限。

    **共用是判断不是偷懒**：上限该多大只取决于"这条链路要写多少字"
    （`Action.thought` 不设上限，一次决策的推理长度就是它的算力），
    与"打的哪家供应商"无关，四条链路没有证据支持该有不同的数。
    """


__all__ = ["BrainLlmConfig"]
