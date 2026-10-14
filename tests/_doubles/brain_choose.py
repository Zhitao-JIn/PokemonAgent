"""`brain/choose` 测试共用的常量：一次决策的输入与两个脚本签名。

`PROMPT` / `KEYS` / `SCRIPTS` / `IMAGE` 是四条 choose 用例都用的形状——放这里而不是
每个测试各写一份，保证「输入空间」只有一处定义。
"""

from __future__ import annotations

from pokemon_agent.brain import ScriptArg, ScriptSignature

PROMPT = "怎么选下一步动作"

KEYS = ["up", "down", "a"]

WALK_TO = ScriptSignature(
    name="walk_to",
    params=[ScriptArg(name="x", type="int"), ScriptArg(name="y", type="int")],
)

USE_ITEM = ScriptSignature(
    name="use_item",
    params=[
        ScriptArg(name="item", type="str"),
        ScriptArg(name="quantity", type="int", required=False),
    ],
)

SCRIPTS = [WALK_TO, USE_ITEM]

IMAGE = "data:image/png;base64,AAAA"
