"""schemas 包：跨层契约，三个子包各自有自己的统一出口。

- `domain`：跨层传递的领域实体（出口 `pokemon_agent.schemas.domain`）
- `datastore`：被持久化的数据形状——记忆与 trace 记录（出口 `pokemon_agent.schemas.datastore`）
- `communication`：协议信封 Req / Resp（出口 `pokemon_agent.schemas.communication`）

消费方从对应子包出口 import，不深到模块文件。
"""
