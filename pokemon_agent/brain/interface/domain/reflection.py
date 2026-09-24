"""`reflect()` 的产物：`Reflection`。

**三段结构**：看到什么 → 做了什么 → 变成什么。这是大脑对"一步经历"
自己的表达方式，跟 `memory` 的 `ActMemory` 是两个独立模块各自的方言——
两边字段今天恰好重合，是巧合，不是契约。谁要用谁自己转换（`tools/brain_tool.py`）。

**为什么两帧是字符串**：`before`/`after` 是**素材**，不是大脑要做逻辑运算的东西。
把观测渲染成文本是调用方（tool）的事——观测里有 `known_objects`/`knowledge`
这类"不该进经验"的字段该不该剪、按什么顺序渲染、对齐怎么做，全是**渲染策略**，
随世界和存储策略变。大脑只负责"把这一段文本当成本步的`当时看到`收下"，然后
原样交出去。跨模块零依赖靠这条：`brain` 不认识 `world.Observation`，
也不认识 `ActMemory.Observation`。

**没有 `episode_id`/`step`**：这两个是**轨迹坐标**，由 Harness/tool 盖章——
大脑不知道自己在哪一局、第几步，正如它不知道自己是第几次重试。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Reflection(BaseModel):
    """一条整理好的经验：**我看到这样，做了这个动作，然后变成这样。**

    ## 为什么两头都是完整文本

    只记"结果：你在野外"这种一句话，等于把结果压成一个没有信息量的标签
    （十条全长一个样）。**结果本身也是一次观察**，只有完整记下来，
    这条经验才回答得了"那一下到底改变了什么"。

    代价是上一条的 `after` 和下一条的 `before` 内容重复。这是有意接受的：
    **每条自成一体**，取回时不用去拼上下文，也不依赖别的条目还在不在。

    ## 这仍然只是 episodic

    "这次尝试里发生了什么"，是自己跑出来的轨迹，有时效。不要和**语义记忆**
    混淆：那是"世界是什么样"（"水克火"、"map 0 的 (5,5) 通往 map 37"），
    自带作用域、在作用域内永远为真；也不要和**目标**混淆：目标有完成态，
    凡是有完成态的都不是知识，它属于运行时状态。
    """

    before: str = Field(description="执行前那一帧观测的渲染文本")
    action_text: str = Field(description="这一步做了什么（按键链的文本，见 `Action.describe()`）")
    after: str = Field(description="执行后那一帧观测的渲染文本")
