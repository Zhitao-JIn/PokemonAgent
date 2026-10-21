"""`BrainLlmConfig`：`Brain` 四个 provider 的**选型与超参**，纯数据。

**为什么它住 `brain/interface/`**（0913 深夜九定案）：它跟 `Action`/`Goal` 一样是零重依赖的
纯数据；只想说"这次用什么型号"的调用方不该连带进口厂商实现面（`providers.py` 与 `PIL`）。

**每个位置一份 `LinkSpec`**：型号、温度、输出上限、单请求超时、思考开关都是调用方（装配点经
tool 层）给的纯数据，本模块不替它们做主——哪个值是多少只看配置文件，不在 brain 里写死。
`None` = 这个位置这次不装配（按需实例化：每层只造它要的链路，`Brain` 对应方法的入口 assert
会把"没配就调"拦下）。`frozen=True`：装配期构造一次、此后只读。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LinkSpec:
    """一个位置（决策 / 判定 / 校验 / 规划）的 provider 选型与超参。

    `model`：型号名，前缀决定厂商（表在 `providers.py`）；`temperature`：采样温度；
    `max_tokens`：输出上限（思考 token 与正文共用这份额度）；`timeout_s`：单请求超时秒数
    （总时长硬闸是它 +15）；`thinking`：是否开思考模式，只有规划位置会用到。
    """

    model: str
    temperature: float
    max_tokens: int
    timeout_s: float
    thinking: bool = False


@dataclass(frozen=True)
class BrainLlmConfig:
    """`Brain` 四个 provider 的选型表；与 `Brain.__init__` 的四个形参一一对应。

    - `text`：`choose()` 的决策模型；
    - `judge`：`judge()` 的判定模型，**跟 `text` 分开是硬要求**（判定与决策误差同源会让
      "读错画面 → 以为达成 → 判成功"越走越顺，见 `Brain` 模块 docstring），同型号也不共用实例；
    - `verify`：`verify()` / `summarize()` 的模型；
    - `plan`：`plan()` 与 `decompose()` 共用的规划模型；
    - `json_mode`：四个 provider 共用的 JSON 输出开关（请求体带 `response_format: json_object`）；
    - `vision_dump_dir`：非空时把实际送出的图落到该目录，排查用。
    """

    text: LinkSpec | None = None
    judge: LinkSpec | None = None
    verify: LinkSpec | None = None
    plan: LinkSpec | None = None
    json_mode: bool = False
    vision_dump_dir: str | None = None


__all__ = ["BrainLlmConfig", "LinkSpec"]
