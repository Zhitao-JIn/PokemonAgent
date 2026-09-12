# `pokemon_agent/tools/` 模块技术规格

本规格覆盖 `pokemon_agent/tools/game_tools.py`（`GameTools`）与
`pokemon_agent/tools/memory_tool.py`（`MemoryTool`），并结合它们各自实现的协议
（`interfaces/tools.py` 的 `GameToolPort`/`MemoryToolPort`）、`GameTools` 包装的
`interfaces/world.py`（`WorldPort`）、`MemoryTool` 包装的 `memory/port.py`
（`SemanticObjectStore`）说明其契约与设计动机。所有结论均来自源码与源码内的
中文 docstring，不做额外引申。

---

> ## 现状（2026-09-12）—— 读之前先看这段
>
> **本文件有两层滞后，成因不同，都不是靠重写本文档来修的。**
>
> **① 协议住址（2026-09-12 的改动，本文档未同步）**：上面那段的
> `interfaces/tools.py` **今天不存在**。五张工具协议搬过两次（**今为四张**——`CheckpointToolPort` 已于步 5b 解散，见下）：
> 顶层 `pokemon_agent/interfaces/tools/` → `tools/ports.py`（协议与实现同住
> 一层）→ **`tools/interface/ports.py`**（协议与实现分家）。**全篇凡指
> `interfaces/tools.py` 处，读作 `tools/interface/ports.py`**，出口是
> `tools/interface/__init__.py`；同理 `interfaces/world.py` 读作
> `world/interface/world_port.py`。
>
> 第三次搬家的理由**不是"文件该放哪一级"**（前两次都是这么理解的，都不够）：问题在
> **出口**——`tools/__init__.py` 一旦同时导出协议与实现，Python 的包初始化就决定了
> "只想拿一张协议"也会把五个插件全加载（实测累计 146 个 `pokemon_agent` 模块）。
> 分家后降到 116，且 `tools.*` 只剩 `tools` / `tools.interface` /
> `tools.interface.ports` 三个。理由、验收与迁移顺序见
> [`PLAN_tool_interface.md`](PLAN_tool_interface.md)。
>
> **② 更早的、与本次无关的滞后（只标注，未修）**：本文档写于 envelope 化之前，
> 所以 §2/§3/§5 的**方法签名还是裸参时代**的（如 `reset(task: Task) ->
> PerceptionResult`）——今天门面收发的是 `FromHarnessTo*Req`/`Resp` 信封，
> **权威签名以 `tools/interface/ports.py` 的 docstring 为准**（迁移见
> [`PLAN_harness_decoupling.md`](PLAN_harness_decoupling.md)）。另外这几处引用的
> 文件今天也都不存在：
>
> | 本文档写的 | 今天实际是 |
> |---|---|
> | `memory/port.py` | `memory/ports.py`（`MemoryStorePort`） |
> | `memory/semantic/semantic_store.py`、`SemanticObjectStore` | 已收敛进 `memory/store.py` 的 `MemoryStore`（四类记忆各一个实例） |
> | §5 说的 `self._episodes: list[StepMemory]` | 不成立：`MemoryTool` 今天持有四个 `MemoryStore`（`_steps`/`_objects`/`_summaries`/`_knowledge`） |
> | `MemoryTool` 构造参数 `objects: SemanticObjectStore \| None` | 改为 `embedding_provider` + `reranker_provider` + `memory_root`/`max_summaries`/`knowledge_root` |
>
> **为什么不重写本文档**：它记录的是**设计论证**（为什么拆两个 Port、为什么掩码归
> `GameTools`、为什么大脑不持有任何工具实例），那些论证**没有过期**，是本文档最值钱
> 的部分。按本仓惯例**只加现状块、就地标注过期，不动历史论证**。

---

## 1. 模块定位：Harness 伸向环境和记忆的两只手

`tools/` 目录下只有两个类，各自实现一个协议：

| 类 | 实现的协议 | 只碰什么 |
|---|---|---|
| `GameTools` | `GameToolPort` | 只碰 `WorldPort`（环境），**不碰任何记忆** |
| `MemoryTool` | `MemoryToolPort` | 只碰 `memory/` 包（记忆），**不碰世界** |

`interfaces/tools.py`（**现 `tools/interface/ports.py`**）的模块 docstring 把这个拆分讲得很直接：以前只有一个
`ToolHost`（另外还有一个更小的 `ToolPort` 给大脑用），"感知世界"和"记忆"混在
同一个协议、同一个实现类（`GameTools`）里。现在大脑不再持有任何工具实例——
`Brain.choose()` 需要的情景记忆由 Harness 先查好、当参数传进去，大脑不再有机会
主动调用 `GameToolPort`/`MemoryToolPort` 的任何方法，所以给大脑看的 `ToolPort`
协议也就没有存在必要了。

拆成 `GameToolPort`/`MemoryToolPort` 两个协议而不是一个，是因为它们的实现本来
就该是两个不相关的类（`GameTools` 只碰 `WorldPort`，`MemoryTool` 只碰 `memory/`
包），揉进一个协议会让人误以为它们必须由同一个对象同时实现。`Harness.__init__`
因此收两个参数：`game: GameToolPort` 和 `memory: MemoryToolPort`。

`game_tools.py` 的模块 docstring 补充了这次拆分之前的坑：`GameTools` 以前还叫
`Harness`，那个名字盖住了两件不同的事——"怎么碰环境"（这里）和"一局怎么跑"
（`harness/harness.py`）。合在一个类里的时候，`perceive()` 同时是"看一眼"和
"新的一步"，于是需要按步去重来调和两种身份，而那个去重制造了**步号回退**和
**判定重复计费**这两类实测出现过的 bug。拆开之后 `GameTools` **没有任何跨步骤
状态**（曾经还留着"上一次给出的动作空间"，即 `_last_space`，后来也删了，见 2.1）；
它不写 trace、不认识 LLM、不知道 episode 是谁。

同样地，早先 `GameTools` 还持有一份 `ObjectMemory` 的引用，`perceive()` 顺手把
语义记忆拼进 `facts["known_objects"]`；这条耦合已被拆掉。`GameTools` 现在没有
任何字段指向记忆，`memory/` 包整个是它看不见的东西。`known_objects`/`knowledge`
现在由 `Harness._retrieve_memory()`（**不是** `_observe()`——两者都是语义记忆的
读，属于图上专门的"查记忆"节点，不属于"看一眼"）在观测盖完章、判定跑完之后，
**另外**调 `MemoryToolPort.query_objects()`/`query_knowledge()` 拼上去——两个协议各管各的，组合是 Harness 的活。

---

## 2. `GameTools`：`GameToolPort` 的唯一实现

### 2.1 构造函数与字段

```python
class GameTools:
    def __init__(self, world: WorldPort) -> None:
        self._world = world
```

- `_world: WorldPort` —— 唯一的依赖，持有世界。构造后不再改变。
- **没有别的字段。这个对象没有状态。**

这里曾经有一个 `_last_space: tuple[ActionSpace, str]`，存着上次交出去的动作空间
和当时的帧哈希，用来在 `execute()` 里验动作合法、并判断那份掩码有没有过期。
两件事现在都由参数回答：`execute(action, obs)` 收下"这个动作是按哪份观测选的"，
就地用同一个纯函数重算掩码去校验。**攒起来再回头取，就得额外发明一个办法判断
攒的那份还新不新**——而调用方本来就知道答案，让它说出来即可（见 2.6）。

### 2.2 `reset(task: Task) -> PerceptionResult`

直接转发 `self._world.reset(task)`。曾经还要清空 `_last_space`，那个字段已经没有了。

### 2.3 这里曾经有一个 `perceive() -> PerceptionResult`

转发 `world.observe()`。Harness 每步开头调它看一眼，而它和上一步 `step()` 结尾
感知的是同一帧。删掉了，理由见 2.7。

### 2.4 这里曾经有一个 `inspect(focus: str)`

它对同一帧再问一次感知（转发 `world.inspect(focus)`，前置 assert `focus`
非空），换的是 prompt 不是画面。**现在这条路整条删掉了**：`GameToolPort`、
`WorldPort`、`GameTools` 三处都没有 `inspect`。

留下来的经验有两条。一是它让 `observe()` 的"帧内稳定"变成**有条件成立**
（见 2.3），而一条要靠调用方自己记住前提的幂等承诺，用起来和没有幂等差不多。
二是它多花的那一次视觉调用，换回来的是同一帧的另一段描述——而感知正是每步
花钱的那一项。要更细的信息，代价该花在**把一次感知做好**上，不是在同一帧上
再买一次。

### 2.5 `get_action_space(obs: Observation) -> ActionSpace`

**掩码发生在这里，只看 overlay。** 完整逻辑：

```python
overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
names = [a for a in OVERLAY_ACTIONS[overlay] if a in self._world.all_actions()]

assert names, f"action space must never be empty (overlay={overlay})"
space = ActionSpace(
    names=names,
    descriptions=dict(BUTTON_HELP[overlay]),
    note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
)
return space
```

**它是纯函数，不碰 world。** 曾经它自己去 `world.observe()` 取一份观测，只为读
`facts["overlay"]` 这一个字段——那次感知完全多余，靠帧缓存挡住才没花钱（见 2.7）。
现在依据由调用方交出来：它按哪份观测做的决策，就拿哪份观测算动作空间。

**掩码规则的具体算法**：从 `obs.facts["overlay"]`（缺省 `Overlay.NONE.value`）
读出当前的 `Overlay` 枚举值，用它去查常量表 `OVERLAY_ACTIONS[overlay]` 得到
"这个 overlay 下理论上可用的动作名列表"，再和 `all_actions`
（世界支持的全部动作名，由 `GameTools` 从 world 取来传入）取交集——即 `names = [a for a in OVERLAY_ACTIONS[overlay]
if a in self._world.all_actions()]`。`descriptions` 同样按 overlay 从
`BUTTON_HELP[overlay]` 取。

为什么掩码挂在 overlay 上而不是别的信号，docstring 给出了明确理由：**掩码是
策略，所以在这一层；`overlay` 是感知的产物，所以由 world 交出来**。两边通过
`Observation.facts` 这个公开字段衔接，谁也不认识谁的内部。而且 `overlay` 在
熔断测试里 **23/23 全对**，是整条感知链里最可靠的一维——把动作空间挂在它上面
是刻意的：分类错一次的代价是大脑看到一组不该有的动作，比字段读错严重得多。

后置条件用 assert 硬守：`names` 绝不能为空——走投无路也必须给至少一个动作，
空动作空间是这一层的 bug，不能推给大脑处理。

**`ActionSpace` 就在这里定型，Harness 不再覆写它。** 这里曾经留空一个 `intents`
字段交给 Harness 填（能不能拆子目标取决于目标栈有多深，那是循环的账），
intent 分派删掉之后那个字段也没了。

**实现放在模块级的 `_mask(obs, all_actions)` 里**，`get_action_space()` 和
`execute()` 共用它，而不是让后者去调前者——那会在一次权限守卫调用里再触发一次守卫，
审计流多一条没有意义的记录。掩码本身不是需要授权的动作，需要授权的是"向外交出
动作空间"。

方法末尾曾经把 `(space, world.last_frame_sha)` 存入 `_last_space`，用来在
`execute()` 里判断掩码有没有过期。`_last_space` 已经删掉，见 2.6。

### 2.6 `execute(action: Action, obs: Observation) -> ToolResult`

```python
def execute(self, action: Action, obs: Observation) -> ToolResult:
    space = _mask(obs, self._world.all_actions())
    for segment in action.segments():
        assert space.contains(segment.name), (
            f"execute() got {segment.name!r} outside {space.names}"
        )
    if action.sequence:
        assert len(action.sequence) == 1 or all(
            segment.name in {"up", "down"} for segment in action.sequence
        ), (
            "multi-step action sequence may contain only up/down"
        )
    result = self._world.step(action)

    assert result.observation is not None, "world.step() must return the new observation"
    return result
```

**动作现在是一条链**（`Action.sequence: list[ActionSegment]`，见
`schemas/action.py`），所以校验是按段做的，两条：

1. **每一段**的 `space.contains(segment.name)`：防止大脑幻觉出不存在的动作名。
   链里有一段越界，整条链就不该按下去。
2. **多段链的链体只能是移动键，链尾可以带一个 `a`**（单段不受此限）：多段链的中间帧
   是看不到的（见下），能这样闭眼走的只有移动键；而**链尾那一帧本来就会被感知**，
   所以把 `a` 放在末尾不丢证据——「走过去再按一下」于是能一次决策做完。
   `a` 最多出现一次、且必须是最后一段（`times` 恒为 1）。

**依据由调用方交出来，所以"用过期的掩码"在结构上不可能发生。** 这里曾经有第三条
校验：`frame == world.last_frame_sha`，比对帧哈希，防止拿上一帧算的动作空间去按键。
它存在的原因是掩码被攒在 `_last_space` 这个实例变量里——攒起来再回头取，就得额外
发明一个办法判断攒的那份还新不新。现在 `execute(action, obs)` 收下"这个动作是按
哪份观测选的"，就地用同一个纯函数重算掩码去校验，`_last_space` 整个删掉。

那条 docstring 的论点仍然成立、而且正是这么做的理由：只查名字是不够的，`a` 在野外、
对话框、选择框里都可用，**名字对得上不代表语境对得上**——所以校验必须绑定到具体
哪一份观测，而不是"最近一次"。

**整条链交给 world 一次执行完——这一层不再自己拆。** `execute()` 只调一次
`self._world.step(action)`，world 按 `action.segments()` 依次按完，**在链的
结尾只感知一次**。

这里曾经拆过两版，两版都是错的：

- 第一版展开成 `times` 次 `step(times=1)`，于是 `up×4` 变成**四次视觉调用**——
  实测一步 17k input token、6.6 秒。
- 第二版改成一段一次 `step(times=str(segment.times))`，好一些，但
  `up×4 -> down×2` 仍然是两次感知。

为什么最后收敛到一次：感知是每步花钱的那一项，而按第 3 条规则，多段链里
只可能是移动键（链尾可带一个 `a`）——中间那几帧没有任何会被用到的信息。**一次决策就该是一次
感知**。中间帧看不见是有意的取舍，不是遗漏。

连按次数也不再经过 `args["times"]` 这条字符串通道：world 直接读
`action.segments()`，次数在 `ActionSegment.times`（1-8）解析期就已经校验过。

`execute()` 推进世界后曾经把 `_last_space` 置回 `None`（世界推进了，上一次的动作
空间自然失效）——那个字段已经删掉，失效问题由"依据随参数传入"从结构上消掉了。最后
assert `result.observation is not None` 作为后置条件——`world.step()` 必须
返回新观测。

**返回值直接就是 `world.step()` 的那个 `ToolResult`，这一层不再拼装。**
`ToolResult` 里曾经有一个 `message` 字段（world 给的一句"结果描述"），
现在已经删了：它的字段说明写着"给 LLM 读的"，而**没有任何一条路径把它交给
LLM**——全仓库唯一的消费方是 trace 的 ACT 事件，内容也只是
`observation.status`，紧接着又会作为下一条 OBSERVE 的 `status` 出现，
观测台上纯属复读。动作之后世界变成什么样，答案是**下一条完整的观测**，
不是一句转述。（同一段历史里还删过一个恒为 `True` 的 `ok`，理由同类，
见 `schemas/action.py` 的 `ToolResult` docstring。）

### 2.7 一帧只感知一次，所以这一层没有帧哈希、也没有 `perceive()`

**曾经同一帧被感知四次**，每步都走一遍：

| # | 路径 | 结果 |
|---|---|---|
| A | `Harness._look` → `GameTools.perceive()` → `world.observe()` | 缓存命中 |
| B | `Harness._look` → `get_action_space()` → `world.observe()` | 缓存命中 |
| C | `Harness._press` → `execute()` → `world.step()` 结尾的 `observe()` | **真调模型** |
| D | 下一步的 A | 缓存命中 |

world 内部按帧哈希缓存，把 B/C/D 三条挡掉，稳态下每步只花一次感知的钱。
**但缓存是在补一个结构问题**——同一帧本来就不该被问四遍。而且它掩盖了另一件事：
「记忆里的 `after` 和下一步的观测相等」当时只是碰巧成立（靠"中间没人 tick 世界"），
没有任何断言，`press` 和 `look` 之间插一个会推进世界的节点就会静默不一致。

**现在只留 C。** 观测由 world 在 `reset()` / `step()` 的结尾产出，沿返回值往上传：

- **A 删掉**：`_look` 不再感知，用上一步传下来的 `pending_observation`；
  开局那一帧由 `reset()` 给。`after` 和下一步的观测因此是**同一个对象**，
  不是"相等"——不需要保证的东西才不会漂。
- **B 删掉**：`get_action_space()` 曾经自己去 `world.observe()`，只为读
  `facts["overlay"]` 这一个字段。掩码是 `Observation` 的纯函数
  （`all_actions()` 按其 docstring 与状态无关），依据应该由调用方交出来。
- **缓存删掉**：一帧只感知一次，没有东西可缓存。
- **帧哈希删掉**：它的两个用途——当缓存的键、在 trace 里标"这是哪一帧"——
  一个随缓存消失，另一个随"同一帧不会被问第二遍"消失。
  `ToolPort.last_frame_sha`、`WorldPort.last_frame_sha`、`PerceptionResult.frame_sha`、
  MODEL_CALL 里的 `frame_sha` 键，全部没有了。
- **`ToolPort.perceive()` 删掉**：没有调用方了。连带 `read:game:perceive` 这条权限。

**代价，写在这里**：trace 里少了"这两条观测是不是同一帧"这个信息。它曾经用来诊断
两件事——「模型在同一张图上给了不同答案」（以后不可能发生，同一帧不会被问两遍）
和「卡住了」（换判据：比 `place` + `status` 有没有变）。

**感知调用的账因此记在产生它的那一步**：第 N 步的观测由第 N-1 步的 `press` 感知出来，
那条 MODEL_CALL 记在 `step=N-1` 下。这是对的——那次调用确实发生在第 N-1 步。

### 2.8 感知归 world，这一层只是转发

模块 docstring 说明了这一分工的边界：用户定的分工是**感知是"tool 调用
world"**。`VisionProvider` 留在 `PyBoyWorld` 里，理由是 `Observation` 是跨层
契约，谁产出谁负责完整性；而且"一帧只感知一次"的缓存依赖它在 world 内部实现。
`GameTools` 这一层只把 `observe()` 转出来，不掺杂任何自己的逻辑。

---

## 3. `MemoryTool`：`MemoryToolPort` 的唯一实现

### 3.1 构造函数与字段

```python
class MemoryTool:
    def __init__(
        self,
        trace_port: TracePort,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider,
        objects: SemanticObjectStore | None = None,
    ) -> None:
```

**从单参数长到了五个**，因为这一层现在管四类记忆，其中两类要检索、一类要调模型：

- `trace_port` / `llm_provider` —— 蒸馏跨局摘要那条路要用（`EpisodeMemoryGenerator`
  自己会写一条 trace 事件，所以它也要 trace）。
- `embedding_provider` / `reranker_provider` —— 知识库和跨局摘要的混合检索要用
  （BM25 + 向量 + rerank）。
- `objects` —— 语义记忆（object）存储，默认 `ObjectMemory()`，但接受注入。
  **类型标成协议**（`SemanticObjectStore`）：测试可以喂假实现，换存储后端也不用
  碰这个类的任何一行。

字段：`_episodes: list[StepMemory]`（本局单步流水）、`_episode_memories:
list[EpisodeMemory]` 和 `_episode_memory_vectors`（跨局摘要及其 embedding，
**写入时算好、缓存住**）、`_knowledge_chunks` / `_knowledge_vectors` 加一个 mtime
（知识库索引，见 3.4）、`_objects`。

模块 docstring 说明为什么这几类记忆不合并成一套方法：它们的**检索单元和读写语义
完全不同**（一步 / 一整局 / 一格 / 一段先验）。并且明确职责边界：**这一层做编排，
`memory/semantic/object_store.py` 只做存储**。"一次按键该查哪几格候选""朝向算不算数"
"多段链要不要跳过"这些游戏规则性质的判断都在 `MemoryTool`——`ObjectMemory` 只知道
怎么按坐标存取一条 `ObjectFact`，不知道"按键"是什么。

程序记忆（procedural）还未实现，docstring 特意说明**不为其预留空方法**：协议和实现
都不该为一个还不存在的东西预留形状。

### 3.2 单步情景记忆（step memory）

四个方法，名字全部按"一条 = 一步"改过（`schemas/memory_episodic.py` → `step_memory.py`，
`MemoryEntry` → `StepMemory`；旧名字 `query_episodic` / `recent` / `write_episodic` /
`episodic_size` 里的 "episodic" 和跨局摘要的 "episode" 只差一个词尾，读的人分不出
"一条=一步"和"一条=一整局"）。

#### 3.2.1 `query_episode_steps(episode_id: str) -> list[StepMemory]`

```python
assert episode_id, "query_episode_steps() needs a non-empty episode_id"
return sorted((m for m in self._episodes if m.episode_id == episode_id),
              key=lambda m: m.step)
```

**这一局的全部单步记忆，按 `step` 升序，不排序、不截断、不打分。**

**这里曾经有一套字符重叠检索**（`_overlap(query, m.render())` 打分、按
`(重叠分, step)` 降序、只留 >0 的前 `limit` 条）。那一版有一条判断今天仍然成立、
必须留下：**打分对着的必须是 `render()`——和喂进 prompt 的是同一份文本**，
分开算就会出现"按 A 的内容选中，却把 B 的内容喂进去"，而且不报错。

检索被拿掉的理由是它选错了作用域：本局的步骤是**流水**，它要回答的是"我这一局
到现在做过什么"，全量按顺序给才对；"按相关性挑几条"是跨局摘要那一层的问题，
现在由 `query_episode_summaries()` 用真正的混合检索来做（3.2.5）。

#### 3.2.2 `query_recent_steps(episode_id: str, limit: int) -> list[StepMemory]`

最近 `limit` 步，按 `step` 升序返回。判定器的历史用它（**订正 2026-09-12**：不再是 `JUDGE_HISTORY` 条，而是按 `JUDGE_HISTORY_KEY_CAP` 取回、再由 harness 侧 `last_chains()` 按链裁到 `JUDGE_CHAIN_HISTORY` 条）——
判定要的是"最近发生了什么"，而且**必须有界**：无界的历史会让判定器在第 0 步
就拿着上一局的证据判完成。

#### 3.2.3 `store_episode_step(entry: StepMemory) -> None`

追加一条。写在 `Harness._remember` 那一格。

#### 3.2.4 `episode_step_count` —— 现在是方法不是 property

`episode_step_count()`：库里一共多少条单步记忆。step 记忆生命周期收紧后
（按 episode 隔离、蒸馏后即弃，见 CHANGELOG 2026-08-31），开局时这个数恒为 0，
不能反映"带着多少经验开局"。

#### 3.2.5 跨局摘要记忆（episode memory）

和上面四个方法**不共用存储**，这是第三类记忆：

- `query_episode_summaries(scene, query, limit=3) -> list[EpisodeMemory]`：
  先按 `scene` 过滤（`applicable_scenes` 为空或含 `*` 视为通用经验，见
  `schemas/episode_memory.py` 的 `SCENE_ANY`），再按相关性 + 质量 + 成功与否加权排序。
- `store_episode_summary(...)`：一局结束时调 `EpisodeMemoryGenerator` 蒸馏一条落库。

### 3.3 语义记忆（object）

#### 3.3.1 `query_objects(obs: Observation) -> str`

```python
if obs.place is None:
    return ""
blocks = [fact.render() for fact in self._objects.query_map(obs.place.map_id)]
return "\n\n".join(sorted(blocks))
```

拿这张地图（`obs.place.map_id`）上"我互动过的那些格子分别给了什么"拼成
`known_objects` 用的文字，按 `sorted()` 排序后拼接。

**条与条之间空一行（`\n\n`），不是单换行。** 这里曾经是 `"\n".join(...)`，
当时一条 `ObjectFact.render()` 就是一行，怎么拼都不会歧义；现在 `render()`
自己就是多行（抬头 + 缩进的明细），单换行连起来的话，上一条的明细和下一条的
抬头之间没有任何视觉边界。空行还是另一件事的依据：trace / 观测台数"这一屏
有几条档案"（`known_object_count`）靠的就是它，用单换行拼会让整段被数成一条。

**只筛当前地图，不筛当前屏幕**：地图内的条目一共也没几条，而"屏幕外那扇门
我进去过"恰恰是它规划路线时最需要的一条；筛屏幕反而把最有用的滤掉了。

坐标和 `landmarks` 是同一套（全局 `x= y=`），所以模型不需要做任何换算就能把
两边对上——**它做不好的正是换算**。

#### 3.3.2 这里曾经有一个 `see_objects(obs, stamp)`

它把这一帧看到的地标全部记进语义记忆（`self._objects.see(parse_landmarks(obs), stamp)`），
**没互动过的也记**，由 `Harness._observe()` 一步调一次。方法在 `MemoryTool` 和
`MemoryToolPort` 上都已经没有了（`parse_landmarks` 还留在 `memory/semantic/util.py`，
现在只有 `kind_in_frame()` 在用它）——建档改由 `Harness` 在 `_observe` 那一格直接
操作 object store。

**它的理由必须留下，因为那条理由没有过期**：为什么没互动过的也要建档——这份档案
最有价值的一类条目正是"**这里有一扇门，我见过 7 次，一次都没进去过**"。没有它，
agent 只能从 `landmarks` 看到那里有扇门，**分不出哪扇是探索过的、哪扇是新的**，
而那正是它规划下一步要去哪的依据。同样，`seen` 是"进过几次视野"，所以**一步只能
记一次**——这条约束现在落在调用点上。

#### 3.3.3 `INTERACTIVE` 常量

```python
INTERACTIVE = ("人", "招牌", "门")
```

模块级常量，注释：哪些地标值得记一条语义记忆。走得过去的空地按 `a` 什么也不
会发生，记了是噪声。它在 `_kind_at` 中用于过滤 `kind_in_frame(...)` 的候选
地标种类，也用于判断从语义记忆里查到的兜底条目 (`fact.landmark.kind`) 是否
属于"值得当作交互对象"的种类。

#### 3.3.4 `store_objects_interactions(before, action, after) -> list[ObjectFact]` —— 详细拆解

这是本类中最复杂的方法。它回答"这一步碰到了什么，记进语义记忆"，返回被
更新的条目（可能为空）。docstring 先说明为什么把三件事合成一个方法：**互动**
（按 `a`）、**姿势**（按方向键：从旁边推过去 / 站在它上面朝外按）、**穿门**
（姿势的结果是换了地图）——它们共用同一个触发点（走完一步之后）。

**核心洞察——姿势是这一步唯一新增的一维**：用户的原话是"有的门走上前就行，
有的要踩在门上撞墙，有些坡只有一个方向能走"。这三件事的差别只有两维——
**我人在它旁边还是在它上面**、**按的哪个方向**——两维本身就是"角色当时的
坐标"和"按了哪个键"，不用再翻译成专门的姿势名字，所以存成
`attempts[x=.. y=..→按键] = 结果`。结果也是算的：`before.place` 和
`after.place` 一减，换图 / 无效果。

**面朝哪一格是算出来的，不是认的**：`place`（内存读的全局坐标）+ `facing`
（我们自己的动作历史推的）→ `place.step_toward(facing)`。两个输入都是确定
量，所以这条记忆的键是确定的。

**先过一道链长闸门：多段动作链一律不记。**

```python
if not self._should_store_interactions(before, action, after):
    return []

segments = action.segments()
if len(segments) != 1:
    return []
segment = segments[0]
```

理由和这份档案的键是什么直接相关：键是「**在哪一格、按了哪个键**」，而一条链的
`before` / `after` 是**整条链的两头**——中间路过了哪些格子、哪一次按键才是撞在
门上的那一次，这里全看不到（world 在链的结尾只感知一次，见 2.6）。把
`up×4 -> down×2` 记成"在起点按了一次 up"，写进去的是一条**假的尝试记录**，
而这份档案的全部价值就在于"哪些碰法试过了"可信。**少记一条只是慢一点，记错
一条会让它以后永远不再试那个正确的碰法。**

链长的判断刻意**没有**放进 `_should_store_interactions()`：那个静态方法只管
"有没有位置、有没有按键"这两件事，把链长混进去会让人以为多段链是**无效输入**——
它不是，它是合法动作，只是不适合写进这份按格子索引的档案。所以它是
`store_objects_interactions` 里带着理由的一处提前返回。

单段之后的判断全部对着 `segment`（`ActionSegment`），不再读 `action.name` /
`action.args["times"]`——那两个字段是 `Action` 的旧单按键形态，`segments()`
才是现在唯一该问的入口。

**完整分支逻辑**（对照代码）：

```python
facing = BUTTON_FACING.get(segment.name, before.facts.get("facing", ""))
if not facing or before.place is None or after.place is None:
    return []

ahead = before.place.step_toward(facing)
key_desc = f"x={before.place.x} y={before.place.y}→{segment.name}"
```

第一步先算 `facing`：如果 `segment.name` 是方向键，`BUTTON_FACING` 能直接查出
按这次键会朝向哪个方向——**用的是这一次按键决定的朝向**；否则（比如 `a` 键）
用 `before.facts.get("facing", "")`，即**执行前**已知的朝向。docstring 特别
强调这个区别不能反：`before.facts["facing"]` 是走这一步**之前**的朝向，方向
键要用它去算"我走到了哪格"会指向完全无关的一格；而 `a` 相反，它作用在**当前**
朝向上，所以用 `before` 的那个是对的。

若 `facing` 算不出（开局、过场之后朝向未知）、或 `before.place`/`after.place`
任一为 `None`，直接返回 `[]`——**朝向未知时宁可不记也不能记错格子**。

否则算出 `ahead = before.place.step_toward(facing)`（面朝的那一格坐标）和
`key_desc`（"x=.. y=..→按键名" 的姿势描述字符串）。

**分支一：`segment.name == INTERACT_KEY`（按 `a` / 交互键）**

```python
if segment.name == INTERACT_KEY:
    kind = self._kind_at(before, ahead)
    if kind is None:
        return []
    text = after.facts.get("dialog_text", "")
    fact = self._objects.touch(ahead, kind, text)
    self._objects.record_attempt(
        ahead, kind, key_desc, RESULT_DIALOG if text.strip() else RESULT_NONE
    )
    return [fact]
```

- 用 `_kind_at(before, ahead)` 判断面朝的那一格是什么。若 `kind is None`
  （面朝的不是人/招牌/门，对着空地按 `a` 什么也不会发生），**不记**，返回
  `[]`。
- 否则取 `after.facts["dialog_text"]`（交互后弹出的对话文本，缺省空串），
  调 `self._objects.touch(ahead, kind, text)` 建档/取档并记一句话，再调
  `record_attempt` 记一次尝试：结果是 `RESULT_DIALOG`（有对话文本）或
  `RESULT_NONE`（没有）。
- 返回 `[fact]`（`touch()` 的返回值，被更新的那条 `ObjectFact`）。

**分支二：方向键**

```python
if segment.times != 1:
    return []
moved = self._outcome(before, after, facing)
if not moved:
    return []
```

- **连按方向键（`segment.times > 1`）跳过**。判断已经从字符串
  `action.args["times"] != "1"` 换成整数 `segment.times != 1`——次数在
  `ActionSegment.times`（1-8）解析期就校验过，这里不必再跟字符串打交道。
  理由和多段链是同一条：走了 4 步之后停在哪、是被墙挡住还是走到了别处，
  中间没有感知，这里同样分不出来；结果挂不到确定的一格上。
- 调 `_outcome(before, after, facing)`（见 3.3.6 节）算出这一步的结果字符串
  （`"warp"`/`"moved"`/`"stay"`/`""`）。若为空串（算不准，包括"原地转身"的
  情况，见下），返回 `[]`。

```python
candidates = [
    (place, self._kind_at(before, place))
    for place in surrounding_cells(before.place)
]
known = [kind for _, kind in candidates if kind is not None]
changed = before.place.map_id != after.place.map_id
if changed and len(known) > 1:
    return []

result = f"{RESULT_WARP_PREFIX}{after.place.map_id}" if changed else RESULT_NONE
touched: list[ObjectFact] = []
for place, kind in candidates:
    if kind is None:
        continue
    touched.append(self._objects.record_attempt(place, kind, key_desc, result))
return touched
```

- 用 `surrounding_cells(before.place)`（`memory/util.py`）枚举**脚下 + 周围
  一圈**的候选格子，对每格调 `_kind_at(before, place)` 得到该格是什么
  （或 `None`）。docstring 解释为什么不只查面朝的 `ahead` 一格：这一次按键
  可能碰到的候选不只是 `ahead`——**脚下这格尤其要留**，人物精灵盖住了它，
  当帧的 `landmarks` 已经不再报告那里有扇门（踩在门上朝外按是室内出口
  唯一的走法）。
- `known` 是所有非 `None` 的候选种类列表；`changed` 表示这一步是否换了地图
  （`before.place.map_id != after.place.map_id`）。
- **两个候选同时存在且换了图（`changed and len(known) > 1`）时整步作废**，
  返回 `[]`——算不出是哪一个把地图换掉的。
- 否则算出统一的 `result`：换图则是 `RESULT_WARP_PREFIX + after.place.map_id`
  （即 `warp:<map_id>` 一类字符串），没换图则是 `RESULT_NONE`。
- 遍历全部候选，跳过 `kind is None` 的格子，对其余每格调
  `record_attempt(place, kind, key_desc, result)`，把返回的 `ObjectFact`
  收进 `touched` 列表，最终整体返回。

**关于"原地转身"这条不记的规则**，体现在 `_outcome` 里（见 3.3.6）：宝可梦里
朝向不同时按方向键，第一帧只转向不移动，所以只有**本来就朝着那个方向**时
才把 `RESULT_NONE` 记下来；否则 `_outcome` 返回空串，`store_objects_interactions` 在
`if not moved: return []` 处直接短路，不落入后面的候选枚举逻辑。

**完整的"什么情况下不记"清单**：

1. **多段动作链**（`len(action.segments()) != 1`）：链的两头之间没有感知，
   记成"在起点按了一次 up"就是往档案里写假的尝试记录。
2. 面朝的不是人/招牌/门：对着空地按 `a` 什么也不会发生。
3. 朝向未知（开局、过场之后）：算不出面朝哪一格，宁可不记也不能记错格子。
4. **连按方向键**（`segment.times > 1`）：中途经过哪些格子算不出来，结果挂不
   到确定的一格上——和第 1 条是同一个原因的两种形态。
5. **原地转身**：只有本来就朝着那个方向时才把 `RESULT_NONE` 记下来。
6. **两个候选同时存在且换了图**：算不出是哪一个把地图换掉的，整步作废。

#### 3.3.5 `_kind_at(obs: Observation, place: Place) -> str | None`

```python
def _kind_at(self, obs: Observation, place: Place) -> str | None:
    kind = kind_in_frame(obs, place, INTERACTIVE)
    if kind is not None:
        return kind
    fact = self._objects.query(place)
    if fact is not None and fact.landmark.kind in INTERACTIVE:
        return fact.landmark.kind
    return None
```

先查**当帧 `landmarks`**（`kind_in_frame(obs, place, INTERACTIVE)`，来自
`memory/util.py`，只在 `INTERACTIVE` 范围内匹配）；若认不出（`None`），再查
**语义记忆**（`self._objects.query(place)`），如果查到的条目的 `landmark.kind`
属于 `INTERACTIVE`，则用它兜底；否则返回 `None`。

两个来源不是冗余：`landmarks` 是内存给的当帧真相，但它**看不见被主角踩住的
那一格**（人物精灵挡住）；语义记忆里存的是"我以前见过那里有什么"，正好补上
这个盲区。

#### 3.3.6 `_outcome(before, after, facing) -> str`（静态方法）

```python
@staticmethod
def _outcome(before: Observation, after: Observation, facing: str) -> str:
    assert before.place is not None and after.place is not None
    if after.place.map_id != before.place.map_id:
        return "warp"
    if (after.place.x, after.place.y) != (before.place.x, before.place.y):
        return "moved"
    if before.facts.get("facing", "") == facing:
        return "stay"
    return ""
```

这一步动没动，判定顺序：

1. `map_id` 变了 → `"warp"`。
2. `map_id` 没变但坐标 `(x, y)` 变了 → `"moved"`。
3. `map_id`、坐标都没变，且**执行前的朝向本来就等于这次按键的朝向**
   （`before.facts["facing"] == facing`）→ `"stay"`（真的原地不动，没有效果）。
4. 否则（坐标没变，但执行前朝向 ≠ 这次按键方向——即这一按只是**转身**，
   不是撞墙）→ 返回空串 `""`，表示算不准，`store_objects_interactions` 据此不记录。

前置断言：`before.place is not None and after.place is not None`（调用方已经
在 `store_objects_interactions` 里检查过）。

docstring 记录了一个真实踩过的坑：早一版这里返回的是给模型看的字，那句字是
"过去了"（表示撞墙无效），实测直接把 agent 卡死——它站在 `x=2 y=7` 的门上，
档案写着「站在上面按right→过去了」，于是按 right 走到 `x=3 y=7` 的另一扇门
上，那扇门也写着「站在上面按left→过去了」，于是按 left 走回去，**两格之间
来回踱步**。现在这个歧义在**渲染层**解决：门的成功判据是固定的
（`map_id` 变了），所以 `ObjectFact.leads_to` 直接把"哪次尝试换了图"算出来，
剩下的一律归进 `RESULT_NONE`；`_outcome` 这里只要如实报"动没动"就够了。全部
来自两个 `place` 相减——**没有一个字是模型说的**。

### 3.4 通用先验（`query_knowledge`）

```python
def query_knowledge(self, query: str, limit: int = 5) -> KnowledgeQueryResult:
    assert query, "query_knowledge() needs a non-empty query"
    self._refresh_knowledge_index()
    if not self._knowledge_chunks:
        return KnowledgeQueryResult(contents=[], sources=[])
    ...  # hybrid_retrieve(BM25 + 向量, RRF 融合, reranker)
```

第二类语义记忆，和 3.3 节的 `object` 类（按坐标存取）**不共用存储**。返回
`KnowledgeQueryResult(contents, sources)`——`sources` 单独给出来是为了 trace：
`memory_read` 事件记的是**命中了哪几个文件**，而不是几千字的正文。

**这里曾经是 `knowledge_base() -> str`：直接转发 `store.load_all()`，把整个目录
拼成一大段全量塞进 prompt，不缓存、每次调用都重新读盘。** 当时的理由是两条：

1. 内容量小（个位数文件）时，"漏掉一条相关先验"比"多花几百 token 全读进去"更贵；
2. 知识库是要**运营**的东西，要能一边跑着 episode 一边改 `.md` 文件、不重启就生效。

第一条随内容量增长失效了，于是加了检索。第二条**被保住了**：
`_refresh_knowledge_index()` 按目录 mtime 判断要不要重新分片、重新 embed，
**mtime 没变就不重算**——改文件仍然下一次查询就生效，只是不再每步读盘。
这是一个"新需求来了、旧理由还成立"的典型：加索引的时候要专门去接住第二条，
不然运营就得重启进程。

消费方：`Harness._retrieve_memory()`（不是 `_observe()`），和 `query_objects()` 的
结果一起折进 `obs.facts`，见 `harness/SPEC.md` 4.5 节。

---

## 4. Port 方法签名总表

### 4.1 `GameToolPort`（`GameTools` 实现）

| 方法 | 签名 | 要点 |
|---|---|---|
| `get_action_space` | `(obs: Observation) -> ActionSpace` | 纯函数，不碰 world。后置：`names` 非空。**这一层给出的就是完整动作空间** |
| `execute` | `(action: Action, obs: Observation) -> ToolResult` | 前置：`obs` 是这个动作据以选出的那份观测，**每一段**（`action.segments()`）的按键都属于 `get_action_space(obs)` 的结果，需 assert；多段链链体只能是移动键、链尾可带一个 `a`；后置：`result.observation` 非空。整条链交给 `world.step()` **一次**执行，链尾只感知一次 |
| `reset` | `(task: Task) -> PerceptionResult` | 前置：`task.max_steps > 0`；后置：`observation.done` 为 False |
| `save_state` | `(path: str) -> None` | 把模拟器状态存到 `path`。**每局开局存一次**，用于事后复现某一局的起点；权限 `execute:game:save_state`（`config/permissions.json` 里 `approval_required: false`）|

### 4.2 `MemoryToolPort`（`MemoryTool` 实现）

| 方法 | 签名 | 要点 |
|---|---|---|
| `query_episode_steps` | `(episode_id: str) -> list[StepMemory]` | 前置：`episode_id` 非空；后置：全部来自该 episode，按 `step` 升序，**全量、不截断** |
| `query_recent_steps` | `(episode_id: str, limit: int) -> list[StepMemory]` | 前置：`limit > 0`；后置：条数 ≤ limit，最新在最后。判定器的历史用它，**必须有界** |
| `store_episode_step` | `(entry: StepMemory) -> None` | 前置：`entry.rationale` 非空 |
| `episode_step_count` | `() -> int` | 库里单步记忆条数（本局内，蒸馏后即弃，不再跨局累积）|
| `query_episode_summaries` | `(scene: str, query: str, limit: int = 3) -> list[EpisodeMemory]` | 跨局摘要：先按 `scene` 过滤（空或含 `*` 视为通用），再按相关性 + 质量 + 成功加权排序 |
| `store_episode_summary` | `(...) -> EpisodeMemory` | 一局结束时蒸馏一条落库；蒸馏失败抛 `ValueError`（内部已留一条 ERROR 事件）|
| `query_objects` | `(obs: Observation) -> str` | 后置：`obs.place` 为 None 或无已知条目时返回空串；条与条之间**空一行**（`\n\n`），因为一条档案本身是多行 |
| `query_knowledge` | `(query: str, limit: int = 5) -> KnowledgeQueryResult` | 和坐标无关的通用先验；混合检索（BM25 + 向量 + rerank），按目录 mtime 增量重建索引；返回 `contents` 和 `sources`（trace 只记后者）|
| `store_objects_interactions` | `(before: Observation, action: Action, after: Observation) -> list[ObjectFact]` | 前置：`before`/`after` 都有 `place`；算不出确定格子时不记（**多段链**、连按、原地转身、两个候选同时存在），宁可漏记不可记错 |

（以上签名与前置/后置条件汇总自 `interfaces/tools.py`——**现
`tools/interface/ports.py`**，且**这批签名本身也已过期**（裸参时代，见文首现状块②）；
因为这是 `GameTools`/
`MemoryTool` 两个类的对外契约，本文件重复列出以便与上文的实现细节对照阅读。）

---

## 5. 与 `memory/` 包、`world/` 包的关系（组合关系）

- **`GameTools` 组合 `WorldPort`**：构造函数持有一个 `world: WorldPort` 字段
  （`self._world`），是纯粹的组合关系——`GameTools` 不了解 `world/` 包内部
  实现（当前唯一实现是 `PyBoyWorld`），只通过 `WorldPort` 协议交互
  （`reset`/`observe`/`all_actions`/`step`；`last_frame_sha` 与 `inspect` 都已删除，前者见 2.7）。
  `interfaces/world.py`（**现 `world/interface/world_port.py`**）明确指出：`GameToolPort` 是"Harness 能拿世界做什么"，
  `WorldPort` 是"世界本身能做什么"，两者职责不同且变化速度不同；换模拟器时
  **`GameToolPort` 和大脑一行都不用改**——这就是分层的收益。掩码这类策略
  不在 `WorldPort` 里：世界只回答"全部动作是什么"和"执行这个动作会怎样"，
  masking 是 harness（即 `GameTools.get_action_space()`）的策略。

- **`MemoryTool` 组合 `SemanticObjectStore`（并直接持有情景记忆列表）**：
  构造函数持有 `self._objects: SemanticObjectStore`（默认 `ObjectMemory()`，
  可注入其他实现），是通过协议类型标注实现的组合，`memory/port.py` 明确这是
  "底层协议，不是大脑看到的接口"：大脑连"语义记忆"这个词都不该知道；
  `MemoryTool` 组合这个协议、翻译成 Harness 能用的方法，
  `interfaces/tools.py`（**现 `tools/interface/ports.py`**）的 `MemoryToolPort` 才是 Harness 真正认识的那一层。
  情景记忆（`self._episodes: list[StepMemory]`）则没有额外协议层，直接是
  `MemoryTool` 自己管理的列表。

- **`MemoryTool.query_knowledge()` 走 `memory/semantic/semantic_store.py` 的 `KnowledgeStore`（经 `SemanticKnowledgeStore` 接口注入）**，
  不经过 `SemanticObjectStore`（那是 object 半身的协议）；它自己的读端接口是
  `SemanticKnowledgeStore`，只读两方法。这类记忆**只读**（内容是人手工
  维护的 `.md`，不是 agent 跑出来的），`Reader`/`Writer`/`Store` 三件套对它是过度设计。
  它在 `MemoryTool` 这一侧确实多了几个字段——分片、向量和一个 mtime，
  那是检索索引的缓存（见 3.4）；早一版"每次调用直接读盘全量返回"没有任何字段。

- **Harness 是组合两者的地方**：`Harness.__init__` 收 `game: GameToolPort` 和
  `memory: MemoryToolPort` 两个独立参数；`facts["known_objects"]` 这类需要
  同时用到世界观测和语义记忆的信息，由 `Harness._retrieve_memory()` 拿着手上那份
  `Observation`（来自上一步 `execute()` 或开局 `reset()`），调
  `memory.query_objects(obs)` 拼接，
  两个协议各管各的，跨协议的组合逻辑全部留在 Harness 一层，`GameTools` 与
  `MemoryTool` 彼此互不知道对方的存在。
