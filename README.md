# Pokemon_Agent

用一套通用 harness（脚手架）驱动一个**无状态大脑**去玩《宝可梦 红》，验证「结构化 episodic 记忆
+ 状态表在线归并 + 蒙特卡洛信用分配」在长程任务里的价值。全程不更新任何模型权重。

真实 Game Boy 模拟器（PyBoy）+ 视觉模型读屏幕 + 文本模型做决策 + 独立的判定模型判断目标是否
达成，控制循环用 LangGraph 实现为两张显式的状态图（run 图 + episode 图）。设计上贯穿全项目的
主张：**分层清楚、契约显式、trace 是唯一的事实来源**。

设计文档在 Obsidian：`AI Infra/Harness-Engineering/Projects/项目B-Harness驱动神奇宝贝Agent设计文档.md`。
代码与文档冲突时，架构约束以文档为准，实现细节以代码为准。规范见 `AGENTS.md`；
**模块规格（活文档）索引见 `docs/spec/README.md`**；路线图只有一份权威版本：`docs/ROADMAP.md`。

**当前阶段：原型已接上真实模拟器与真实模型。** 大脑的 ReAct 循环、语义记忆、独立判定器都在真实
环境里跑，并有四个维度的真机核对脚本（`experiment/real_check/`）；状态表在线归并（机制一）与
MC 回填（机制三）仍未做（见 `AGENTS.md` 第十一节）。

## 模块地图

```
pokemon_agent/
├── schemas/     跨层 Pydantic 契约：信封（harness ↔ 各门面）、domain 实体、记忆记录形状
├── brain/       纯决策层（可整体拷走复用）：只依赖自己声明的 provider 契约与 errors
├── harness/     控制循环本体（LangGraph 两张图），全项目唯一写 trace 的地方
├── world/       WorldPort 的唯一实现：PyBoy + 视觉模型的粘合层 + 世界语义常量
├── memory/      记忆子系统整块：统一记录存储 + 混合检索（BM25 + 向量 + RRF + reranker）
├── trace/       独立记账模块：TracePort 契约 + LocalTrace（一条事件一个 json）+ 事件类型词表
├── tools/       桥层：四张门面 + 五个接线工厂 + prompt 素材；跨模块转换只在这一层
├── build.py     唯一的装配点（全项目唯一 new 具体实现的地方）
├── config.py    唯一的策略常量集中地（重试预算 / 动作输出上限 / 循环控制 / 召回与判定）
└── errors.py    AgentError 异常族

experiment/              实验与真机核对（仓库根级，不在包内）
├── tasks.py                 预置任务定义
├── experiment_states/       钉死存档
└── real_check/              四个维度的真实链路核对

docs/spec/               模块规格（活文档，索引见 docs/spec/README.md）
docs/ROADMAP.md          路线图（单一权威版本）
tests/                   pytest（不许连网、不许调真实模型）
```

## 快速开始

```bash
pip install -e ".[dev]"

# 真机核对。只有 check_harness 驱动 PyBoy 与真实模型，其余三个读它留下的产物
# （check_memory_roundtrip 例外：它自带临时目录，不依赖产物）
python -m experiment.real_check.check_harness
python -m experiment.real_check.check_trace
python -m experiment.real_check.check_memory
python -m experiment.real_check.check_memory_roundtrip
```

`check_harness` 支持 `--goal` / `--criteria` / `--steps` 注入这一次的任务（不传则用
`common.py` 里的缺省目标），`--review` 打开「文件信箱」人在环。厂商密钥由
`common.load_env_file()` 从仓库根 `.env` 读取（已在外部环境设过同名变量则以外部为准）；
需要 `DASHSCOPE_API_KEY` / `ARK_API_KEY` / `DEEPSEEK_API_KEY` / `ANTHROPIC_AUTH_TOKEN`
里的相应几个。

需要 Python ≥ 3.11（`enum.StrEnum`）。

## 铁律（节选，完整版见 AGENTS.md）

1. 大脑**不持有任何跨步骤状态**。
2. `brain` / `memory` / `trace` / `world` 是四个独立第三方模块，各自只暴露一个 Port；
   跨模块的数据交换**只能发生在 tool 层**。
3. 模块层的 Port **收裸字段**，不认识本项目的 `*Req` 信封。
4. mock 与真实实现必须实现同一个 Protocol。
5. 跨层传递的数据一律是 Pydantic 模型，不用裸 dict。
6. 每一步都必须产出 trace 事件。

## Roadmap

**只有一份**：`docs/ROADMAP.md`（分期表、已知问题、待讨论方案、业界对照都在那里）。
本文件不再维护它的副本——两份必然漂移。
