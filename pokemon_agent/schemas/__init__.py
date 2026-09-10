"""schemas 包：跨层契约。**先按产出地分包，每个产出模块内部再按种类分子目录。**

七个产出模块各自一个包、各自一个统一出口：

- `frontend`：前端产出——前端发起的第一跳信封（启动 run、提交目标编辑、取帧）
- `harness`：编排层产出——harness 发起的全部第一跳信封（brain_tool / checkpoint_tool /
  game_tool / memory_tool / reviewer / trace_tool 六个门面，外加 run → episode）与人工复核实体
- `brain`：决策层产出——对外接口模型（`ChooseOnceReq` 等裸名）、规划与校验结论、动作实体
- `world`：世界层产出——感知返回、观测与地点实体、动作空间、世界模型常量
- `memory`：记忆层产出——三类被持久化的记忆形状
- `trace`：记账层产出——落盘的事件记录与事件种类
- `providers`：模型接入层产出——文本与视觉补全的接口模型、一次调用的账

**信封只覆盖第一跳**（外壳 → 编排层、编排层 → 各门面），命名带 From/To、归发起方；
门面再往里调具体模块走裸参数、返回模块自己的类型，那一跳不造信封。模块对外的接口
模型一律裸名、归产出方（`ChooseOnceReq` / `LlmCompleteReq` / `PerceiveOnceResp`）。

每包内部按种类落到 `communication/`（协议信封 Req / Resp）、`domain/`（跨层
领域实体）、`datastore/`（被持久化的形状）三类子目录，子目录不对外。

**本文件不是出口，不 re-export 任何名字。** 出口做在每个产出模块一级：消费方写
`from pokemon_agent.schemas.<产出模块> import X`。不设根出口是为了让 import 行
本身说明这个文件跟哪几个协作者的契约打交道，也避免同一个名字有两条 import 路径。
"""
