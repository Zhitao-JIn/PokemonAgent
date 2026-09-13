# brain 与 harness 脱钩、brain 独立成模块：全流程经验原则

- 日期：2026-09-13
- 关联 Issue：`AGENTS.md` 第 2 条铁律（四模块按独立第三方对待）
- 关联 commit：本次改动（brain 对外依赖归零，CHANGELOG 0913（50）～（56））
- 系统状态：brain 已可整体拷走（`pokemon_agent.*` 外部 import 为零）

## 一、目标

**"brain 可以作为第三方整体替换"**——把它整个目录拷进另一个项目，不欠任何
同项目文件就能跑。这条判据是全部动作的总纲，下文每条原则都是它的推论。

## 二、原则清单（互相独立，各有反例）

### P1 划分模块的判据是「能不能整个拷走」，不是「谁在消费」

**错误判据**：某类被多个模块 import（多消费者）⇒ 留在共用层。

**为什么错**："谁消费"回答的是**这东西归谁维护**，回答不了**这东西能不能跟着
模块走**。两类东西长得像、判据相反：

| | 跨模块共用的**数据形状** | 模块的**内部协议 / 内部词汇** |
|---|---|---|
| 例（本项目） | `Action` / `Goal` / `Task` / 结果袋 | 四封补全信封、`ParseFailure` 家族、`ImageNotDelivered` |
| 多消费者 | 常见 | 常见 |
| 归属 | 留共用层（或各自持有同构副本） | **归模块**，拷走时跟着走 |
| 判据 | 形状是"接口方言"，本就该跨模块 | **拷走它，跑得起来吗** |

**本项目踩的坑**：前两轮用"多消费者 ⇒ 留共用层"，把
`AgentError` 与 `schemas.providers` 论证成了"brain 该有的依赖"。用户一句
"我要的是 brain 可以作为第三方替换"直接推翻。

### P2 依赖分三类，处理方式完全不同

| 类别 | 判据 | 处理 | 本项目实例 |
|---|---|---|---|
| **实现依赖** | 会 `new` / 调它的具体函数 | 只允许出现在 tool 层 | `tools/brain_tool.py`、`tools/vision_factory.py` |
| **内部协议 / 内部词汇** | 拷走这个模块后它是必需品 | **跟着模块走** | 四封补全信封、brain 异常家族 |
| **实现依赖** 以外的形状引用 | 只是类型标注 / 字段类型 | 可接受，登记即可 | 33 处 `Action`/`Goal` 等 |

**关键**：第一类和第三类**用 AST 审不出区别**（都是 import）。区别在**用途**——
`import X` 后面跟的是 `X()` 还是 `: X`。人工核对 + 登记表（`AGENTS.md` 第十二节第 4 条）。

### P3 异常继承判据：「有没有跨过 tool 层这座桥」

**不是**"谁抛谁接"，**不是**"多模块共用"。是**它会不会真的走到 harness 的捕获点**。

- brain 的异常 → 被 `BrainTool._attempt_loop` 的 `except AttemptFailed` 接住、
  翻译成 `MaxRetriesExceeded` 才上抛 → **走不到 harness**，继承 `AgentError`
  是纯仪式 → **不继承**，自成一根 `BrainError`。
- world 的异常 → `perceive_after_action.py` 直接捕获 → **要继承**。

**收益**：继承关系变成了"这条异常有没有跨过 tool 层"的可核对事实，不再是含糊的
"共同祖先"。

### P4 桥只建在 tool 层，且翻译点唯一

harness 不认识 brain 的异常根，brain 不认识 harness 的捕获点。
**两个模块谁都不认识对方的异常**，中间那层是 tool：

```
brain 抛 AttemptFailed ──► BrainTool 捕获、重试 ──► 耗尽抛 MaxRetriesExceeded ──► harness 捕获
```

**反例**：让 brain 的异常继承 `AgentError`，就是让 translation 在"继承关系"里
偷偷发生——tool 层看起来不重要了，而实际重试逻辑还在 tool 层。**两处表达同一件事 =
两处都可以被改坏。**

### P5 「同形不同约」：长得像的两个协议，各自声明、靠鸭子类型桥接

`world.VisionProvider` 与 `brain.JudgeProvider` 描述同一个物理能力（会 `describe()`
的模型），但分属两家。做法：

1. 两边各自声明 `Protocol`，谁都不 import 对方。
2. 实现（`brain/providers.py::_MultimodalMixin`）**同时满足两个协议**。
3. 装配点把实例递进去时，靠**字段结构对得上**（鸭子类型）打通。

**同构怎么守**：不靠 import 同一个类，靠**两边从同一份原始定义复制 + 字段名核对**。
（本项目实测逐字段同构：annotation + `is_required()` 全同。）

### P6 信封本地化：两边各持一份副本，漂移就是运行时错误

四封补全信封从顶层搬进 `brain/schemas/`，world 复制一份自己的
`world/interface/domain/vision_describe.py`（只复制它要的两封）。

- **代价**：两个副本可能漂移。
- **收益**：两个模块都能独立拷走。
- **兜底**：docstring 明写"必须保持同构"，且副本的字段差异**只在运行时**才炸——
  所以要**在改动时人工核对**，不能靠编译器。

### P7 包初始化要分层：数据形状立即加载，实现懒加载

`brain/__init__.py` 里 `BrainLlmConfig`（纯数据）立即导入，`Brain` /
`build_llm_providers`（会连带拉进厂商实现面 + `PIL`）走 `__getattr__` 懒加载。

**理由**：**"只想声明用什么型号"的调用方不该背上网关客户端。** 一个 import 的代价
不是它自己，是它所在模块的顶部。

## 三、可复现的核对方法

```bash
# ① 逐模块独立解释器导入（唯一抓得到循环导入的方法；同解释器里别的 import 顺序会掩盖环）
python -c "import pokemon_agent.<每个模块>"

# ② AST 依赖审计（ast.walk 全树，能收函数内 import；grep '^from' 会漏）
#    输出 brain 的 pokemon_agent.* 依赖应只剩自己的子包

# ③ 协议桥 + 信封同构（类级 isinstance/issubclass + model_fields 逐字段比对）

# ④ 实现依赖清点（全项目对 brain 的 import 应只在 tools/）
```

**教训**：`grep` 会漏函数内 import（`build.py:71`、`brain_tool.py:115` 都是），
**必须用 AST**。

## 四、全流程节奏（三轮，每轮的产出与推翻）

| 轮次 | 判据 | 产出 | 被下一轮推翻的 |
|---|---|---|---|
| 54 | 谁消费 | `providers/` 整包解散，实现跟协议走 | — |
| 55 | 谁消费 | `BrainLlmConfig` 进 `interface/`，工厂收进 tool 层 | — |
| **56** | **能不能整体拷走** | **brain 对外依赖归零** | **54/55 的"多消费者 ⇒ 留共用层"** |

**规律**：判据是分层推进的——先"谁消费"（所有权），后"拷得走吗"（自治性）。
**所有权判据不蕴含自治性判据**，会留下"归我但我跑不起来"的中间态。

## 五、最容易犯的三个错

1. **把经验外推。** "多消费者 ⇒ 留共用层"只在**数据形状**上成立，被外推到
   **内部协议/内部词汇**上就成了错的。**用判据前先问它管的是哪一类。**
2. **把半截搬迁当完整方案。** 协议搬走了、实现还在原地 → 原本靠"同住一包"天然
   消解的循环导入立刻显形。（54 轮踩过）
3. **为剩下的依赖写辩护材料。** 发现横向依赖后，论证"它横跨两个模块、故不属于
   任何单一层"——听起来对，其实是在给债找理由。**正确动作是问"它能不能跟着走"。**

## 六、验证（本轮）

- AST 审计：brain 的 `pokemon_agent.*` 依赖只剩 `brain.errors` /
  `brain.interface` / `brain.schemas`；非项目 import 只有标准库 + `pydantic` + `PIL`。
- 逐模块独立解释器导入：**197/197，0 失败**。
- `ParseFailure.__mro__ = [ParseFailure, BrainError, Exception, BaseException, object]`，
  `issubclass(ParseFailure, AgentError) == False`。
- `QwenProvider` 对 `world.VisionProvider` / `brain.interface.JudgeProvider`
  两个 `issubclass` 均为真；两封信封逐字段同构为真。
- 对 brain 的实现依赖只在 `tools/`（`brain_tool.py` 3 处 + `vision_factory.py` 1 处）。
- 未跑真实 harness（按规矩由用户运行）；未发真实 API 请求。
