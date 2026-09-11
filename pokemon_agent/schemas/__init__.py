"""schemas 包：跨层信封。**先按产出地分包，每个产出模块内部再按种类分子目录。**

四个产出模块各自一个包、各自一个统一出口：

- `frontend`：前端产出——前端发起的第一跳信封（启动 run、提交目标编辑、取帧）
- `harness`：编排层产出——harness 发起的全部第一跳信封（brain_tool / checkpoint_tool /
  game_tool / memory_tool / reviewer / trace_tool 六个门面，外加 run → episode）与人工复核实体
- `brain`：决策层产出——对外接口模型（`ChooseOnceReq` 等裸名）
- `providers`：模型接入层产出——文本与视觉补全的接口模型、一次调用的账

**`world`/`memory`/`trace` 不在这里**——它们原来各有一个 `schemas/<模块>/`
子包，装着"跨层领域实体"（`domain/`）或"被持久化的形状"（`datastore/`）；
按"模块间零依赖，只靠裸函数和 tool 层交互"这条原则，这些数据物理上归回了
产出它们的模块自己（`pokemon_agent.world`/`pokemon_agent.memory`/
`pokemon_agent.trace`），`schemas/` 只留真正的信封。

**信封只覆盖第一跳**（外壳 → 编排层、编排层 → 各门面），命名带 From/To、归发起方；
门面再往里调具体模块走裸参数、返回模块自己的类型，那一跳不造信封。模块对外的接口
模型一律裸名、归产出方（`ChooseOnceReq` / `LlmCompleteReq`）。

每包内部按种类落到 `communication/`（协议信封 Req / Resp）子目录，子目录不对外。

**本文件不是出口，不 re-export 任何名字。** 出口做在每个产出模块一级：消费方写
`from pokemon_agent.schemas.<产出模块> import X`。不设根出口是为了让 import 行
本身说明这个文件跟哪几个协作者的契约打交道，也避免同一个名字有两条 import 路径。
"""
