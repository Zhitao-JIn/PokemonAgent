"""schemas 包：跨层信封。**先按产出地分包，每个产出模块内部再按种类分子目录。**

**磁盘上的现况**（2026-09-15 以磁盘为准）：

正在动的只有 `harness/` 与 `memory/` 两个子包：

- `harness/`：编排层产出——harness 发起的全部第一跳信封（brain_tool / game_tool /
  memory_tool / reviewer / trace_tool 五个门面，外加 run → episode），
  外加 `domain/` 里三个实体：`GoalEntry` / `TraceEvent` / `TraceKind`
- `memory/`：记忆层产出的**契约形状**（`datastore/` 下四个记录模型）。它们**不在**
  `pokemon_agent/memory/` 里，理由见 `schemas/memory/__init__.py`

**`trace` / `world` / `brain` / `providers` / `frontend` 五个子包都已不在**：

- `trace/`、`world/`：这两个的数据按"模块间零依赖、数据形状归产出它的模块自己"这条
  原则物理归回了各自的模块，目录一度只剩空骨架，**2026-09-15 空目录也清掉了**
  （移进 `_to_delete/0915-empty-schemas-skeleton/`）。**新代码不要往这两个目录放东西。**
- `brain/`：补全协议是 brain 的内部协议，随之搬进了 `brain/schemas/`
- `providers/`：厂商实现不再有独立 schema 包
- `frontend/`：观测台已移出仓库，整包随之消失

**信封只覆盖第一跳**（外壳 → 编排层、编排层 → 各门面），命名带 From/To、归发起方；
门面再往里调具体模块走裸参数、返回模块自己的类型，那一跳不造信封。模块对外的接口
模型一律裸名、归产出方（如 brain 的 `Action` / `RunPlan`，住
`pokemon_agent/brain/interface/domain/`）。

每包内部按种类落到 `communication/`（协议信封 Req / Resp）子目录，子目录不对外。

**本文件不是出口，不 re-export 任何名字。** 出口做在每个产出模块一级：消费方写
`from pokemon_agent.schemas.<产出模块> import X`。不设根出口是为了让 import 行
本身说明这个文件跟哪几个协作者的契约打交道，也避免同一个名字有两条 import 路径。
"""
