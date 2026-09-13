# memory 模块按「brain 脱钩原则」审计：如何移出

- 日期：2026-09-13
- 判据来源：`docs/experiences/2026-09-13-brain-decoupling-principles.md`
- 关联铁律：`AGENTS.md` 第 2 条（四模块各自只暴露一个 Port，按独立第三方对待）
- 系统状态：**memory 已基本符合 P1～P7，真正待改只有 1 处（装配点的造型 import）**
- 验证环境：`C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe`
  （managed 3.13 与仓库内 `.venv` linux 均无依赖，见 §5 附录）
- **未跑真实 harness**（按项目规矩由用户自行运行）

---

## 一、总判据（P1）落地：memory 拷得走吗

P1 的唯一判据是「**把目录整个拷进另一个项目，欠不欠同项目文件**」。
用 AST 审计（不用 grep，见 P3 教训）memory/ 全部 7 个 py 文件的 import：

```
附 A：memory/ 对 pokemon_agent.* 的依赖（AST 全树，含函数内）
  retrieval.py:26    [TYPE_CHECKING]  pokemon_agent.memory          ← 环内自指
  store.py:45                         pokemon_agent.memory.retrieval ← 环内自指
  store.py:50        [TYPE_CHECKING]  pokemon_agent.memory          ← 环内自指
```

**结论：memory 对外依赖归零。** 3 处 import 全部指向 `memory` 包自己，
没有一处指向 `brain` / `harness` / `schemas` / `tools` / `world`。

对照 P1 判据逐条核对：

| P1 判据 | memory 实测 | 判定 |
|---|---|---|
| 拷走后跑得起来吗 | 第三方 import 仅 `rank_bm25` / `fastembed` / 标准库 | **通过** |
| 有没有指向兄弟模块的 import | 3 处全是包内自指 | **通过** |
| 数据形状（StepMemory 等）在哪 | 在 `schemas.memory`，**不在** memory 包里 | **符合边界** |
| 内部协议/内部词汇跟不跟着走 | `ports.py` + `embedding_provider.py` + `reranker_provider.py` 同住包内 | **符合 P2 第二类** |

第三行是这套设计里最漂亮的一笔。`schemas/memory/__init__.py` 的说明和
`memory/__init__.py` 第 22-31 行的 docstring 已经把边界讲清楚了：

> `MemoryStorePort` 完全不透明——只认 `metadata: dict[str,str]` + `payload: dict`
> 两个裸字段……按"数据形状只有在某个模块的 Port/实现真的需要构造或消费它的
> 具体样子时，才归那个模块自己"这条边界，`StepMemory`/`EpisodeMemory`/
> `ObjectFactEvent` 这三个类因此**不在**这个包里。

这正是 P1 表格的判据：`StepMemory` 是**多消费者（harness 7 处 + tools 5 处 +
schemas 内部 16 处）的数据形状**，按 P1 归共用层；memory 的实现不消费它的具体
样子，所以它不该跟 memory 走。**没有犯"多消费者 ⇒ 留共用层"那个坑，因为
memory 本来就不需要它们。**

---

## 二、P2 依赖三分类：memory 的账本

按 P2 的三类，逐类清点：

### 第一类 实现依赖（会 `new` / 调具体函数）——只允许出现在 tool 层

全项目对 memory 的**实现依赖**：

```
tools/memory_tool.py:38   from pokemon_agent.memory import EmbeddingProvider, MemoryStore, RerankerProvider
                          ↑ MemoryStore() 在这里被 new（第 127/128/129/133 行，四个 kind 各一个实例）
experiment/real_check/check_memory_roundtrip.py:31   ← 实验脚本，非生产链路
```

`MemoryStore` 只在 `tools/memory_tool.py` 被 new，**恰好一次**。
`EmbeddingProvider`/`RerankerProvider` 是注入进来的协议（类型标注用途），
不算实现依赖。

**判定：符合 P2 第一类。** 可以更严格一点说——memory 的"实现依赖"比 brain
还干净：brain 的实现依赖是 `tools/brain_tool.py` 3 处 + `vision_factory.py` 1 处
（含工厂），memory 是 1 处且没有工厂。

### 第二类 内部协议 / 内部词汇——跟着模块走

| 文件 | 内容 | 归属判定 |
|---|---|---|
| `ports.py` | `MemoryStorePort` | 0910 就拍板（ROADMAP §24）与实现同住包内；拷 memory/ 即得 |
| `embedding_provider.py` | `EmbeddingProvider` | 0913 从 `providers/interface/` 搬来，**只被本层检索链路消费** |
| `reranker_provider.py` | `RerankerProvider` | 同上 |

**判定：符合 P2 第二类。** 三个协议全是"拷走 memory/ 后它还是必需品"的那类，
所以都跟着走。这里做对了一个关键动作：**没有沿用"多消费者 ⇒ 留共用层"**。
`EmbeddingProvider`/`RerankerProvider` 只被 memory 自己消费，判"跟 memory 走"；
如果哪天 world 也要一个 embedding 能力，按 P5「同形不同约」应当**两边各自声明
一份 + 鸭子类型桥接**，而不是把协议提到共用层。

### 第三类 形状引用（只是类型标注 / 字段类型）——可接受，登记即可

memory 包里第三类依赖是 **0 处**（`retrieval.py`/`store.py` 的 3 处自指属环内）。
换句话说 memory 连"登记表"都不用进。

---

## 三、P3 异常继承判据：memory 的情况

P3 的判据是「**这条异常有没有跨过 tool 层这座桥**」。

memory 包里**没有任何自定义异常**。`store.py` 的失败路径（文件不存在、
索引损坏、embedding 调用失败）走的是标准库异常或**原样上抛**——见
`ports.py::put` 的显式约定：

> 前置条件：text 非空时会调用注入的 `EmbeddingProvider`，**失败原样抛出**
> （不静默降级成"这条没有向量"）。

**判定：无需处理。** 没有自成家族的异常，就不存在"该不该继承 `AgentError`"
的问题。这是"零债务"而不是"漏了"——P3 只在模块**需要**自己的异常词汇时才生效。

需要注意的是 `ports.py::get` 的后置条件写的是"不存在返回 None"，
`archive_many` 写的是"不存在的 uuid 跳过（不报错）"——这些是**契约化的静默**，
不是异常吞掉，OK。

---

## 四、P4 桥只建在 tool 层：memory 的桥在哪、翻了几次

P4 要求"翻译点唯一"。memory 这条链的桥是 `tools/memory_tool.py`，
桥的形状是 **req/resp 信封转换**而不是异常翻译：

```
harness 组 FromHarnessToMemoryToolStoreEpisodeStepReq
   └─► MemoryTool.store_episode_step()   ← 桥在这：信封 → 裸 metadata/payload/text
          └─► MemoryStore.put(metadata, payload, text)  ← memory 只认裸字段
```

**判定：符合 P4，且比 brain 那条链更干净。**

- 桥只有一座：`tools/memory_tool.py`。
- 信封只有一层：`schemas/harness/communication/FromHarnessToMemoryTool*.py`（14 个），
  全部由 harness 组装、tool 拆解，**memory 从来看不到信封**。
- 契约铁律 3 也守住了：`MemoryStorePort` 收 `dict[str,str]` / `dict` / `str` /
  `Sequence[str]` / `Path`——**裸字段**，不认识任何 `*Req`。

---

## 五、P5 / P6：同形不同约与信封本地化——memory 的适用情况

**P5（同形不同约）**：memory 现在没有第二个模块声明同形的 embedding/reranker
协议，所以 P5 暂时**不适用**，无需动作。但要记住这条备用判据——
如果将来 world 或 brain 需要一个"把文本转向量"的能力，**不要**把
`EmbeddingProvider` 提到共用层，按 P5 各自声明 + 鸭子类型桥。

**P6（信封本地化）**：memory 侧**没有需要本地化的信封**。
memory 只在 `ports.py` 声明裸字段契约（P2 第二类），信封留在
`schemas/`（多消费者的数据形状，P1 判据归共用层）。**这是正确的**，
因为 MemoryStorePort 的字段本身就是 `dict[str,str]` + `dict`，
不存在"信封形状漂移"的风险面。

---

## 六、P7 包初始化分层：memory 的 `__init__.py` 反而可能是**唯一要改的地方**

P7 的判据是「**只想声明用什么型号的调用方不该背上网关客户端**，
一个 import 的代价不是它自己，是它所在模块的顶部」。

### memory/__init__.py 现状：全部立即加载

```python
__all__ = [...]                                  # 12 个名字
from .embedding_provider import EmbeddingProvider   # 52 行，轻
from .fastembed_reranker import FastEmbedReranker   # 53 行，轻（函数内 import fastembed.rerank）
from .fastembed_text import FastEmbedText           # 54 行，轻（函数内 import fastembed）
from .ports import MemoryStorePort                  # 55 行，轻
from .reranker_provider import RerankerProvider     # 56 行，轻
from .retrieval import (...)                        # 57 行，**顶部 import rank_bm25**
from .store import MemoryStore                      # 64 行，**顶部拖进 retrieval → rank_bm25**
```

按 P7 的措辞逐条核：

- **不背"网关客户端"。** memory 的 `__init__` 不拖 `PIL`、不拖 openai 客户端
  ——因为 memory 的实现（fastembed）把重依赖放在**函数内**（`fastembed_text.py:44`
  的 `import fastembed` 在函数体里、`fastembed_reranker.py:33` 同理）。
  这是好设计。
- **但 `rank_bm25` 在模块顶部。** `retrieval.py:23` 与 `store.py` 都从顶部
  拉进来，所以 `import pokemon_agent.memory` 会连带拉起 `rank_bm25`。

### 这里实测出了一个值得记录的坑

```bash
$ python -c "import pokemon_agent.memory"
ModuleNotFoundError: No module named 'rank_bm25'    # ← 无依赖的解释器直接炸
```

也就是说 **memory 的独立导入屏障是 `rank_bm25`，不是 fastembed**。
`rank_bm25` 是纯 Python 小包（无 C 扩展、无客户端），代价远小于 PIL，
所以**这不构成 P7 违规**——P7 针对的是"背上网关客户端"，`rank_bm25` 只是个
分词打分库。**结论：`__init__.py` 无需改动。**

真正的动作在下面一处。

---

## 七、唯一待改项：装配点 `build.py:25` 的造型 import

按 P2 的分类，`build.py:25` 对 memory 的 import 是**第一类（实现依赖）**：

```
build.py:25    from pokemon_agent.memory import FastEmbedReranker, FastEmbedText
build.py:106       embedding_provider=FastEmbedText(),
build.py:107       reranker_provider=FastEmbedReranker(),
```

对照 brain 已经做过的收口（0913 深夜九 + 56 轮）：

```
build.py        对 brain 的 import：**零**
build.py:138    brain_tool = BrainTool.build(text=…, judge=…, …)   ← 只递型号名
说明文字        「协议归属、实现归属、接线归属三者对齐」
```

**两边的形状一模一样**：`FastEmbedText` / `FastEmbedReranker` 就是 memory 的
"厂商实现"，`build.py` 现在直接伸手进去 `new` 了它们。而 brain 那条链已经
把这步收进了 tool 层工厂。**memory 这条链漏做了同一步。**

同时实测确认这个 import 有真实代价（P7 的"一个 import 的代价是它所在模块的顶部"）：

```
装配点 build.py 顶层拖进 pokemon_agent.* 子模块：
  {'brain': 19, 'build': 1, 'config': 1, 'errors': 1,
   'harness': 54, 'memory': 8, 'schemas': 66, 'tools': 16,
   'trace': 6, 'world': 20}

  memory 的 8 个：memory, memory.embedding_provider, memory.fastembed_reranker,
                  memory.fastembed_text, memory.ports, memory.reranker_provider,
                  memory.retrieval, memory.store
```

`build.py` 顶层 import 一旦拉起，memory 整包 8 个模块（含 `rank_bm25`）
全部在 import 期加载。

### 建议改法：加 `MemoryTool.build(...)`，与 `BrainTool.build` 同形

**最小改动、形状与 brain 完全对齐**：把 factory 收进 `MemoryTool`，
`build.py` 只递参数、对 memory 零 import。

```python
# tools/memory_tool.py —— 新增类方法，与 BrainTool.build 同形
@classmethod
def build(
    cls,
    *,
    memory_root: str | Path | None = None,
    knowledge_root: str | Path | None = None,
    max_summaries: int = 50,
) -> MemoryTool:
    """按落盘位置造一个**接了本地 provider** 的 tool——装配点唯一的入口。

    **为什么把"造 FastEmbedText / FastEmbedReranker"收在这一处**：
    与 `BrainTool.build()` / `build_vision_provider()` 同一条判据——
    "这个技能接哪个实现"是这条链路的接线知识，装配点不该 import
    具体 provider 类。
    """
    # 导入放函数内：`memory` 包顶部拖着 rank_bm25，
    # 不该在 import 本模块时就连带拉起来。
    from pokemon_agent.memory import FastEmbedReranker, FastEmbedText

    return cls(
        embedding_provider=FastEmbedText(),
        reranker_provider=FastEmbedReranker(),
        memory_root=memory_root,
        knowledge_root=knowledge_root,
        max_summaries=max_summaries,
    )
```

```python
# build.py —— 删掉第 25 行，改成一行工厂调用
memory = MemoryTool.build()      # 原先 4 行的 MemoryTool(embedding_provider=…, reranker_provider=…)
```

**验收判据（改完后跑）**：
- `build.py` 对 `pokemon_agent.memory` 的顶层 import **为 0**；
- 顶层拖进的 `pokemon_agent.memory.*` 子模块数 **从 8 降到 0**；
- `import pokemon_agent.build` 不再拉起 `memory` 包（`rank_bm25` 不进 import 期）。

**取舍（照 CHANGELOG 的四段格式）**：
- *为什么这么改*：与 brain 那条链对齐，"谁依赖 memory"从"装配点 + tool 层"
  收敛到"只有 tool 层"，与 P4「桥只建在 tool 层」一致。
- *取舍*：多一个类方法。但它与 `__init__` 的关系和 `BrainTool.build` 一样是
  "糖不是第二套逻辑"——没有任何额外判断，不引入第二个真源。
- *是否值得*：`MemoryTool.build()` **确实更弱一点**——它只是转手 new 两个类，
  不像 `BrainTool.build()` 要构造 config、分派四个厂商、钉 temperature 分层。
  **如果你更看重"少一层间接"，保持现状也说得过去**：memory 的 provider 没有
  型号选型、没有厂商分派，`build.py` 那两行本身就是"型号名"级别的信息量。

---

## 八、可复现的核对方法（含本项目特有的坑）

照 P3 的四步，逐条实测（环境见文首）：

```bash
PY="C:/Users/GummiGu/AppData/Local/Programs/Python/Python312/python.exe"

# ① 逐模块独立解释器导入（唯一抓得到循环导入的方法）
for m in memory brain harness world tools schemas trace; do
  $PY -c "import pokemon_agent.$m" && echo "OK $m"
done
# 实测：7/7 全 OK。
#   api / build 报 UserWarning: SDL2 —— 那是 PyBoy/pysdl2 的告警不是失败
#   （用 2>&1 | grep -v SDL2 过滤后 exit 0），不属循环导入问题。

# ② AST 依赖审计（ast.walk 全树，能收函数内 import；grep '^from' 会漏）
#    输出 memory 的 pokemon_agent.* 依赖应只剩 memory 自己 → 见附 A

# ③ 实现依赖清点：全项目对 memory 的 import 位置
#    → tools/memory_tool.py:38（唯一生产依赖）+ experiment/ 脚本

# ④ 装配面实测：import pokemon_agent.build 后统计 sys.modules 增量
#    → 顶层拖进 memory 8 个子模块（本轮唯一不达标项，见 §7）
```

### 本轮踩到的环境坑（值得记下）

| 解释器 | 结果 |
|---|---|
| managed 3.13.12 | ✗ 无 pydantic / rank_bm25 |
| 仓库内 `.venv` | ✗ **是 linux 版**（symlink 指向 `/sessions/.../cpython-3.14-linux-x86_64-gnu`），Windows 下不可用 |
| Python310 | ✗ 无 rank_bm25 |
| **Python312** | ✓ **依赖齐全，用它** |

另一个坑：查 `sys.modules` 增量时，`m.split('.')[1]` 对顶层模块名
`pokemon_agent.brain`（只有一段）会 **IndexError**——必须先判
`m.count('.')>=1`，或统一用 `startswith` 判断。

---

## 九、结论表：memory 逐条对账

| 原则 | memory 实测 | 判定 | 动作 |
|---|---|---|---|
| **P1** 拷得走 | `pokemon_agent.*` 外部依赖为 0（3 处皆包内自指） | ✅ | 无 |
| **P2** 依赖三分类 | 实现依赖仅 `memory_tool.py:38` 一处；协议三件同住包内；第三类 0 处 | ✅ | 无 |
| **P3** 异常继承 | 无自定义异常家族，失败路径原样上抛 | ✅ | 无 |
| **P4** 桥只建在 tool 层 | 桥唯一（`memory_tool.py`），信封不穿透到 memory，裸字段契约 | ✅ | 无 |
| **P5** 同形不同约 | 暂无第二个同形协议 | — | 备用判据 |
| **P6** 信封本地化 | memory 侧无信封（留在 `schemas/` 是对的） | ✅ | 无 |
| **P7** 包初始化分层 | 不背包网关客户端；`rank_bm25` 在顶部但代价可忽略 | ✅ | 无 |
| **装配点造型 import** | `build.py:25` `from pokemon_agent.memory import FastEmbed*` | ⚠️ | **唯一待改**，见 §7 |

**一句话结论**：memory 的脱钩程度已经**与 brain 同级**——P1～P7 八条里七条
直接通过，剩下一条是装配点 `build.py:25` 还在直接 new 两个 provider，
和 brain 收进 `BrainTool.build()` 之前的状态同形。改法就是照抄那一步，
加 `MemoryTool.build()`,让"谁依赖 memory"也收敛到 tool 层唯一一处。

---

## 附 A：AST 审计原始输出

```
### memory/ 对 pokemon_agent.* 的依赖
  pokemon_agent\memory\retrieval.py:26    [TYPE_CHECKING]  pokemon_agent.memory
  pokemon_agent\memory\store.py:45                         pokemon_agent.memory.retrieval
  pokemon_agent\memory\store.py:50        [TYPE_CHECKING]  pokemon_agent.memory

### memory/ 的非项目 import（第三方/标准库）
  ['__future__', 'collections', 'json', 'math', 'os', 'pathlib',
   'rank_bm25', 'typing', 'uuid']        ← 纯第三方 + 标准库

### TYPE_CHECKING 块内的 import
  retrieval.py:26   pokemon_agent.memory.{EmbeddingProvider, RerankerProvider}
  store.py:50       pokemon_agent.memory.{EmbeddingProvider, RerankerProvider}
  ↑ 都是为了给注入参数做类型标注；运行期不 import（注释已写明理由）

### 全项目对 pokemon_agent.memory（=memory 包）的 import
  memory/retrieval.py:26          ← 包内
  memory/store.py:45,50           ← 包内
  build.py:25                     ← ⚠️ 装配点（§7 唯一待改项）
  tools/memory_tool.py:38         ← ✅ 唯一的生产实现依赖
  experiment/real_check/check_memory_roundtrip.py:31   ← 实验脚本
  schemas/__init__.py:14          ← 注释文字，非 import
```
