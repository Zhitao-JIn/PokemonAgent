# Pokemon_Agent

用一套通用 harness（脚手架）驱动一个**无状态大脑**去玩《宝可梦 红》，验证「结构化 episodic 记忆
+ 状态表在线归并 + 蒙特卡洛信用分配」在长程任务里的价值。全程不更新任何模型权重。

真实 Game Boy 模拟器（PyBoy）+ 视觉模型读屏幕 + 文本模型做决策 + 独立的判定模型判断目标是否
达成，控制循环用 LangGraph 实现为一张显式的状态图。设计上贯穿全项目的主张：**分层清楚、契约
显式、trace 是唯一的事实来源**。

设计文档在 Obsidian：`AI Infra/Harness-Engineering/Projects/项目B-Harness驱动神奇宝贝Agent设计文档.md`。
代码与文档冲突时，架构约束以文档为准，实现细节以代码为准。规范见 `AGENTS.md`；模块规格索引在
`docs/spec/README.md`。

**当前阶段：快速原型。** 只做大脑的 ReAct 循环，其余逐步从 mock 换成真实实现。

## 模块地图

```
pokemon_agent/
├── schemas/       跨层数据契约（Pydantic 模型）
├── memory/        语义记忆的纯存储层（episode/ 情景记忆，semantic/ 语义记忆）
├── tools/         Harness 伸向环境和记忆的两只手（GameTools / MemoryTool）
├── interfaces/    Protocol 定义（"港口"）—— 解耦 Harness 与具体实现
├── world/         WorldPort 的唯一实现：PyBoy + 视觉模型的粘合层
├── brain/         纯决策层：LLM 怎么变成一个合法的 Action
├── harness/       控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方
├── prompts/       所有 prompt 模板 + 组装辅助函数
├── providers/     具体的 LLM/视觉模型接入（DashScope/Qwen）
├── vision/        图像预处理（网格叠加等）
├── trace/         TracePort 的实现 + 事件 payload 组装
├── experiment/    实验 manifest、任务定义、跑批入口（run_experiment.py / run_all_tasks.py）
└── build.py       唯一的装配点（全项目唯一出现具体实现 `new` 的地方）

docs/experiments/  每批实验数据的分析文档
```

## 快速开始

```bash
pip install -e ".[dev]"
python -m pokemon_agent.experiment.run_all_tasks --repeat 10
```

需要 Python ≥ 3.11，且启动目录下存在 `config/context.json` 与 `config/permissions.json`
（`agent-permission` 的权限切面要求）。

## 铁律（节选，完整版见 AGENTS.md）

1. 大脑不持有任何跨步骤状态。
2. 大脑只能通过 `interfaces/`（Protocol）与外界交互，不直接依赖 `harness/` 的具体实现。
3. mock 与真实实现必须实现同一个 Protocol。
4. 跨层数据一律是 Pydantic 模型，不用裸 dict。
5. 每一步都必须产出 trace 事件。

## Roadmap

项目目前还在验证「记忆机制能不能带来可衡量的收益」这个阶段，判定器的假阳性/假阴性问题
（见 `docs/experiments/0827-false-positive-analysis.md`）也还有修复项未落地。除此之外，
下面两个方向是主干功能里还没做的：

- **MC（蒙特卡洛）写回与聚类**：情景记忆目前只有存取，还没有「跑完一批 episode 之后，
  把结果做信用分配、写回到记忆里，并对相似的失败/成功模式做聚类」这条链路。这是
  「状态表在线归并 + 蒙特卡洛信用分配」里蒙特卡洛那一半，目前完全空缺。
- **episode 后自动定目标**：现在每条任务的目标（goal / criteria）是人工写在
  `experiment/experiment_states` 里的静态任务定义。还没有「每个 episode 结束后，
  根据全局记忆（语义记忆里积累的游戏知识）自动生成下一个目标」的机制——也就是让
  agent 自己决定"接下来该干什么"，而不是每次都喂一个预置任务。

这两项都还没有对应的 `interfaces/` Protocol 或实现代码，动工前应先按项目规范在
`interfaces/` 里把接口设计清楚，再补实现。
