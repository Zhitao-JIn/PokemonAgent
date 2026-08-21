# Brain 模块技术规格

> 源码：`pokemon_agent/brain/brain.py`
> 接口：`pokemon_agent/interfaces/brain.py`（`BrainPort`）
> 辅助：`pokemon_agent/prompts/brain_hints.py`
> 模板：`pokemon_agent/prompts/decide_action.md`、`intent_help.md`、`judge_success.md`、`retry_note.md`

---

## 1. 模块定位：纯决策层

`Brain` 是 `BrainPort` 的唯一实现，回答"一切需要 LLM 才能回答的问题"。它把自己当成**一组互不通气的模型技能的容器**，而不是"一个模型"：

| 方法 | 做什么 | 用哪个 provider |
|---|---|---|
| `choose` | 看当前画面和可用动作，选下一步 | `decide_llm` |
| `judge` | 看当前画面和任务目标，判达成没达成 | `judge_llm` |
| `reflect` | 把这一步整理成一条可检索的经验 | 无模型调用（本版纯格式化） |

### 1.1 不持有 tools / memory 的约束，以及它的由来

`Brain` 的构造函数只接收 `decide_llm`、`judge_llm`、`max_retries` 三样，**不收任何 `tools` 或记忆实例**。`choose()` 需要的情景记忆（`memories` 参数）由 Harness 检索好之后当参数传进来；`reflect()` 也只返回整理好的 `MemoryEntry`，写库这一步同样不在 Brain 内部发生，由 Harness 完成。

`interfaces/brain.py` 的 docstring 明确记录了这条约束的来历——**旧设计的问题**：

> 早一版是大脑自己持有 `tools` 去调 `memory_query`——"大脑自己决定检索什么"听起来是给它自由度，实际效果是**记忆检索这件"循环控制的事"混进了大脑的构造函数**，而且这条通道再也没被用来做别的事。

收回这个通道之后，`Brain` 连一个 `Protocol` 类型的协作者都不用持有，"大脑该看到什么，完全由方法的参数表决定，不给它一个能自己去翻记忆库的通道"这条铁律因此在**类型层面**更容易守住，而不只是靠约定维持。

### 1.2 不写 trace、不知道自己在哪一局

`choose`/`judge`/`reflect` 三个方法都不收 `episode_id` / `step`，构造函数里也没有 `TracePort`。每次模型调用产生的账（`ModelCall`）跟着方法的返回值一起交给 Harness，由 Harness 翻译成事件写入 trace。

同样是在对照"旧设计的问题"：上一版是 brain 自己写 `MODEL_CALL` / `THINK` / `ERROR` / `MEMORY_READ` 事件，harness 写其余的（`ACT` / `MEMORY_WRITE` / `OBSERVE` / `EPISODE_*`），于是"某类事件归谁写"要一条条记忆规则；而且为了让判定器碰不到自己的账，还专门给 `judge` 开了一个不写 trace 的例外——**用一个例外去弥补一条本来就不统一的规则**。现在规则收敛成一句：**谁控制循环，谁记账。** 大脑连 `episode_id` 都拿不到，它想影响自己在实验数据里的样子，连入口都没有。

### 1.3 无状态

`Brain` 没有任何跨步骤的实例变量（对应 CLAUDE.md 铁律 1）。构造函数里存的都是不可变的协作者（两个 provider、`max_retries`、两份加载好的 prompt 模板）。判据是：**连续两次用相同参数调用 `choose()`，行为必须完全一致**。

它也不认识 `Harness` 和 `world`，只认识 `Protocol`（对应 CLAUDE.md 铁律 2）。

---

## 2. 构造函数：`decide_llm` / `judge_llm` / `max_retries`

```python
def __init__(
    self,
    decide_llm: LLMProvider,
    judge_llm: LLMProvider,
    *,
    max_retries: int = 3,
) -> None:
```

- 两个依赖都以接口类型（`LLMProvider`）注入，而不是具体实现类型。
- 前置条件：`max_retries >= 1`（用 `assert` 校验）。
- 构造时**加载一次**两份 prompt 模板（`decide_action`、`judge_success`），保存下来是为了拿到各自的 `sha`：每一条产生的事件都要带上它，实验数据才说得清"这批结果是哪一版 prompt 跑出来的"——改了 prompt 不记版本，前后两批数字就没法比较。这两份 sha 通过 `prompt_shas` 属性对外暴露，供写入 manifest。

### 2.1 为什么决策和判定必须是两个独立的 provider 实例，即使型号相同

这是本模块最核心的设计论证，`brain.py` 模块 docstring 和 `interfaces/brain.py` 都各自完整地记录了一遍：

**问题的起点：成功率是这个项目唯一要报的硬数字。** 如果让做决策的那个模型顺便回答"我成功了吗"，就构成**误差同源**：它把画面读错了 → 因此以为目标已经达成 → 判成功——而且它读错得越离谱，这个数字反而越好看（因为它更可能"看到"自己想看到的完成证据）。

拆开之后，至少能做到三件事：

1. **各自记账**——判定产生的 token 走独立的 `Source.JUDGE`，不会和决策的账混在一起；
2. **各自换型**——判定可以随时切换成更强或更便宜的模型，不影响决策链路；
3. **各自标定**——将来拿人工标注的真值去核对判定结果，才能算出"判定器本身的准确率"。没有这一步，成功率就只是一个无法证伪的数字。

**合进一个类之后，这条隔离从"类型层面"降到了"约定层面"**，所以靠两条硬约束维持：

1. `judge()` 拿不到决策者的**任何说辞**——它能看到最近几步**发生了什么**（证据可能在三步前的对话框里），但看不到那几步的 `rationale`、看不到 `thought`、看不到当前这一步的候选动作。**"发生过的事"和"它对那件事的主张"是两样东西，只给前者。**
2. `judge_llm` 是**另一个 provider 实例**，哪怕型号相同也不能共用同一个对象。共用的话，将来想单独给判定换模型就要改两处；而且 manifest 里两条链路会指向同一个对象，从数据上根本看不出它们本来是可以分别选型的。

模块也坦承了这条隔离的局限：**这仍然不是真正独立的真值**——判定看到的画面来自和决策相同的一条感知链路，感知本身错了，两边会一起错。真正独立的真值要么读游戏内部的事件旗标，要么靠人工标注；这一版先把"决策/判定分离"的结构立起来。

---

## 3. `choose()`：选下一步动作

### 3.1 完整签名

```python
def choose(
    self, goals: list[Goal], obs: Observation, space: ActionSpace,
    memories: list[MemoryEntry],
) -> Decision:
```

四个参数：

- **`goals`**：整个目标栈（`list[Goal]`），**栈顶（列表最后一个）是这一轮要完成的那条**。下面几层也要传入——见 3.3 节 `_render_goals` 的论证。
- **`obs`**：当前观察（`Observation`），含 `summary`、`facts`、`done` 等字段。
- **`space`**：`ActionSpace`，给出这一轮允许哪些 intent（`space.intents`）、哪些具体按键（`space.names`/`space.descriptions`）、以及可选的 `space.note`。**它由 Harness 填**，因为"还能不能再拆一层子目标"取决于当前栈有多深。
- **`memories`**：Harness **已经检索好**的情景记忆，直接进 prompt。**检索策略（按什么查、查几条）不是大脑的事**——大脑只回答"给了我这些，我选哪个动作"。

前置条件（`assert`）：`space.names` 非空、`space.intents` 非空、`obs.done` 为 `False`、`goals` 非空。空动作空间被明确定性为"工具层的 bug，大脑不为它兜底"。

后置条件：`action` 非 `None` 时，它必属于 `space`（`intent` 在 `space.intents` 里，且若为 `PRESS` 则 `name` 在 `space.names` 里）；`calls` 至少一条。

**重试用尽时返回 `action=None`，不抛异常。** 这是一类要被统计的失败模式，"这一局要不要因此终止"是 Harness 的判断，大脑只如实汇报结果。

重试策略之所以放在 `Brain` 里而不是 `LLMProvider` 里，是因为"什么算失败"是**大脑的判断**：解析不出来算失败、选了不存在的动作也算失败，而这两件事底层的 provider 都判断不了。

### 3.2 内部重试循环

`choose()` 本质是一个 `for attempt in range(1, max_retries + 1)` 循环：

1. 用当前 `prompt`（首轮是 `base = self._build_prompt(...)`）调用 `self._decide.complete(prompt)`，同时用 `time.perf_counter()` 记录延迟。
2. 先检查 `completion.truncated`——**截断检查必须先于解析检查**：如果不这样做，截断会以"少了个右括号"的形式表现成一条 `ParseFailure`，把排查方向指向完全错误的地方（以为是格式问题，实际是输出长度不够）。截断时抛 `OutputTruncated`。
3. 否则调用 `self._parse(completion.text, space)` 尝试解析出 `Action`。
4. 捕获三类异常：
   - `ParseFailure` / `IllegalAction` / `OutputTruncated`：这些是"外部输入不合法"，属于预期内情况，走异常而非 `assert`。记下 `kind`（异常类名）和 `reason`（异常信息）。
   - `pydantic.ValidationError`：`Action` 的 `model_validator` 抛的是 `ValueError`，pydantic 会把它包装成 `ValidationError`——它**不是** `AgentError` 的子类，如果不特别捕获会穿透重试循环，直接让整局崩溃。正常路径下走不到这里，因为 `_parse` 在构造 `Action` 之前已经把每条约束手工验证过一遍；但这意味着**同一套校验写了两份、且没有机制保证两边同步**——哪天 `Action` 上新增一条约束而 `_parse` 没跟上，症状会从"一次可统计的重试"退化成"整局崩溃"。这里兜住它，转换成 `kind="ParseFailure"`，让它退化回一次可统计的解析失败。
5. **无论成功失败，每次调用都追加一条 `ModelCall`**——"一次模型调用 = 一条账"。`payload` 里带 `prompt_sha`、`input_tokens`、`output_tokens`、`latency_ms`、`attempt`、`ok`（是否解析成功）、以及**原始文本 `raw`**。保留 `raw` 的用意是：以后改进解析器可以**离线用历史数据重算**，不需要再花 token 重新跑一遍。失败的那几次调用同样消耗了 token，因此也要留痕。
6. 若 `parsed is None`：把 `prompt` 更新为 `base + _retry_note(attempt + 1, reason, completion.text[:400])`，用于下一轮尝试。
7. 若 `parsed is not None`：先用 `assert` 复核 `intent` 在 `space.intents` 内、且 `PRESS` 时 `name` 在 `space.names` 内（这两条本应由 `_parse` 内部保证，这里是双重确认），然后返回 `Decision(action=parsed, calls=calls, recalled=refs)`，循环提前结束。
8. 循环耗尽仍未成功：返回 `Decision(action=None, calls=calls, recalled=refs)`。

**重试是"带着上次错误重问"，不是原样再问一遍。** 原样重问等价于把三次模型调用当一次用：最常见的失败是系统性的（比如子目标判据里写了屏幕坐标），换一次随机种子照样会犯同样的错。纠正块被追加在 prompt **末尾**而不是开头或中间，是为了让前缀完全不变，三次尝试可以共享同一段 prompt 缓存。

### 3.3 `_build_prompt`：组装 prompt

```python
def _build_prompt(self, goals, obs, space, memories) -> str
```

每次调用都从传入的参数**完整重新组装**，不保留任何跨调用的历史——这是"大脑无状态"在代码层面的直接体现。组装的各部分：

- `facts`：把 `obs.facts` 逐条渲染成 `- key: value`，为空时填"（无）"。
- `recalled`：把 `memories` 逐条 `render()` 后用两个换行拼接，为空时填"（无相关记忆）"。
- `actions`：把 `space.names` 逐个渲染成 `- name: 说明`（说明取自 `space.descriptions`，缺失则显示"（无说明）"），若 `space.note` 非空则追加在后面。
- `goals`：调用 `_render_goals(goals)`（见下）。
- `intents`：把 `space.intents` 中每个 intent 渲染成 `` - `value`：说明 `` ，说明文字来自 `INTENT_HELP[i]`（`brain_hints.py`）。

最终用 `self._decide_prompt.render(...)` 把这些字段代入 `decide_action.md` 模板，同时传入 `max_rationale=MAX_RATIONALE`（来自 `schemas.action`）。

#### `_render_goals`：目标栈的渲染规则

```python
@staticmethod
def _render_goals(goals: list[Goal]) -> str
```

**倒序渲染，栈顶在最上面。** 理由很直接：模型阅读 prompt 是从上往下的，把"你现在要做的那一条"放在最先读到的位置。每一行的格式是：

```
{depth}. [{任务目标 或 子目标（第 N 层）}] {goal.goal}
   判据：{goal.criteria} {← 你现在要完成的，仅栈顶}
```

**下面几层（非栈顶的目标）仍然要给出来**，原因是：如果不给，模型不知道自己为什么在做当前这个子目标，也就无法判断"这个子目标是不是已经偏离了任务"——目标栈的下层是当前子目标存在的理由和边界。

### 3.4 解析失败时的处理：`_parse` 与重试

`_parse(self, text, space) -> Action` 把 LLM 的原始文本解析成一个校验过的 `Action`：

1. 去除首尾空白；若以 ` ``` ` 开头，容忍 ` ```json ` 包裹形式，取出内层内容——这是模型最常见的格式偏差，为它单独重试一轮不划算。
2. `json.loads`；失败抛 `ParseFailure(text, "not valid json (...)")`。
3. 顶层若不是对象，抛 `ParseFailure`。
4. `_parse_intent`：取出 `intent`：
   - 若字段缺失但存在 `action` 字段（旧格式），容忍并回退为 `Intent.PRESS`——语义无歧义,为此单独重试不划算。
   - 若两者都没有，不去猜——猜错会让模型做一件它本来没打算做的事，直接 `ParseFailure`。
   - 若给出的值不在 `Intent` 枚举里，`ParseFailure`。
   - **回退出来的 `PRESS` 同样要过 `space.intents` 掩码检查**，不允许直接 `return`：早一版是直接返回，将来一旦出现"只准思考不准动"这类状态把 `press` 掩掉，症状会变成 `choose()` 出口处的 `assert` 直接崩溃，而不是一次可重试、可统计的 `IllegalAction`。
   - 若不在允许集合内，抛的是 `IllegalAction` 而非 `ParseFailure`——因为这不是格式问题，是模型在**幻觉一个此刻不可用的能力**（比如目标栈已满仍想 `push_goal`）。两者在 replay 时是不同的失败模式，需要改的地方也不同（`ParseFailure` 该改 prompt/上约束解码；`IllegalAction` 该改动作说明或收紧掩码）。
5. 按 `intent` 分支取字段：
   - `PRESS`：需要 `action`（字符串，且必须在 `space.contains(name)` 内，否则 `IllegalAction`）；`args` 需为 dict（缺省为空 dict），所有值转为字符串。
   - `PUSH_GOAL`：需要非空的 `goal` 和 `criteria` 字符串。**`criteria` 不能省**——没有它判定器只能凭"看起来差不多了"回答，那正是成功率被污染的地方，缺失时打回去重试而不是替它编一个。随后用 `SCREEN_COORD` 正则检查 `goal`+`criteria` 拼接文本，命中屏幕坐标类写法（"屏幕格"、"屏幕坐标"、`walk_map`、"第N行/列"、裸括号坐标对）时抛 `ParseFailure`，并给出详细的纠正说明（位置只能写 `x=.. y=..`，因为 `walk_map` 的行列号已经就是全局坐标，且判定器根本看不到 `walk_map`）。
   - `INSPECT`：需要非空的 `focus` 字符串。
6. `_parse_thought`：取出 `thought`，缺失或空则单独抛 `ParseFailure("missing 'thought' field")`——用独立的 reason 字符串（而非新增异常类型）区分"格式坏"和"不肯推理"这两类失败，足够 replay 时按 reason 聚合分析，不值得为此多开一个异常类。
7. `_parse_rationale`：取出 `rationale`。容忍裸字符串写法（自动包成单元素列表）。非 list 则 `ParseFailure`。过滤空字符串后若为空列表，`ParseFailure`。**若条数超过 `MAX_RATIONALE`，走 `ParseFailure` 而不是静默截断**——模型认为需要 4 条论据是有分量的，悄悄丢掉第 4 条等于替它做了一个没有留痕的决定；打回去重试至少留下痕迹，代价是这类重试会多花 token（如果实测占比很高，未来可以改成截断）。
8. 最终用取出的字段构造 `Action(intent=..., thought=..., rationale=..., **fields)`。

`SCREEN_COORD` 正则本身有专门的设计记录：它拦的是"残留的旧习惯"——旧版本 walk_map 的行列号和全局坐标是两套系统，混用坐标造成过一整局的损失（目标写成"移动到屏幕格(7,4)"，因为旧版主角在屏幕上恒定显示在 `(4,4)`，走过去后位置依旧是 `(4,4)`，判据永不成立，模型于是一层层拆出永不完成的子目标）。现在两套坐标已经合并成一套，但拦截没有跟着删掉，因为它防的是习惯性错误，而不是当前坐标系是否统一。此外它还有独立理由：判定器看不到 `walk_map`/`landmarks`（见 `JUDGE_BLIND`），判据里提这张图对判定器来说等于没说。**这条只在 `push_goal` 的 `goal`/`criteria` 上拦截**，`thought`/`rationale` 不受限——那两个字段是模型自己的草稿纸。

**失败后的重试循环**：解析出的异常在 `choose()` 里被捕获，转换成 `(kind, reason)`，随后 `prompt = base + _retry_note(attempt + 1, reason, completion.text[:400])`（见 3.2 节和 4.1 节）。

### 3.5 返回值 `Decision` 的三个字段

`Decision(action=..., calls=..., recalled=...)`：

- **`action`**：解析并校验通过的 `Action`，或者重试全部耗尽后的 `None`。
- **`calls`**：`list[ModelCall]`，本次 `choose()` 调用中每一轮尝试各留一条账（无论成功失败），供 Harness 记入 trace 和统计 token/延迟。
- **`recalled`**：`[f"({m.episode_id}, {m.step})" for m in memories]`，直接从传入的 `memories` 参数派生，标记这一步实际用到了哪些记忆条目。不需要大脑自己另外记"我刚才翻了哪几条"，因为检索本来就是 Harness 做的，`memories` 参数本身就是"这一步给了它哪些记忆"的完整记录。

---

## 4. prompt 模板体系

### 4.1 `decide_action.md`：决策 prompt 的完整结构

按顺序包含以下部分：

1. **开场**：说明这是在玩宝可梦，按 ReAct 方式思考并选下一个动作。
2. **目标栈**（`$goals`）：来自 `_render_goals` 的渲染结果，并提示"你只需要完成栈顶那一条，完成后自动出栈"。
3. **当前状态**（`$summary`）：`obs.summary`。
4. **已知事实**（`$facts`）：`obs.facts` 逐条列出。
5. **相关记忆**（`$memories`）：Harness 检索好的 `memories` 渲染结果。
6. **这一轮你可以做三类事之一**（`$intents`）：来自 `INTENT_HELP`，按 `space.intents` 过滤。
7. **可用按键**（`$actions`）：`space.names`（及其说明）+ 可选的 `space.note`。
8. **输出格式**：要求只输出一个 JSON 对象，并按 `intent` 给出三种示例（`press`/`push_goal`/`inspect`）。
9. **各字段的要求**：
   - `thought`：完整推理，只用于记录，不进入后续决策。
   - `rationale`：1 到 `$max_rationale` 条，要求写"为什么这个动作在当前状态下成立"的依据，不要复述动作本身；强调**这些会被存进记忆、以后在相似状态下取回**，所以要写成"以后还能判断真假"的样子（例如"地上有药水而我手上没有"而非"我觉得这样比较好"）。
   - `args.times`（press）：1 到 8，press 时必须出现，默认 `"1"`；只有"沿直线走几格"是唯一正当的调大场景，因为连按期间看不到中间画面；`a` 键永远是 1（写大了会被夹成 1），因为对话是逐句出现的，连按会吞掉中间的句子而判据往往就要那句话。
   - `goal`（push_goal）：强调是**里程碑不是路径点**，达成时画面要明显不同；拆错成本是"白烧一步且每步都要多花一次判定调用"。
   - `criteria`（push_goal）：必须只看一帧画面就能判断真假；明确告诉模型"判定的人看不到你的推理，也看不到 `walk_map` 和 `landmarks`，只有 `where`/`map_id`/`scene`/对话框文字/`overview`"；位置一律 `x=.. y=..`。
   - `focus`（inspect）：要求是具体问题，不是"再看看"。

### 4.2 `intent_help.md`：`INTENT_HELP` 的内容来源

以 `## press` / `## push_goal` / `## inspect` 三个 section 组织，被 `brain_hints.py` 的 `load_sections("intent_help")` 拆开、按 `Intent` 分类装进 `INTENT_HELP: dict[Intent, str]`。

- **press**：唯一会改变世界、唯一不可逆的一类；按错了只能想办法走回来。
- **push_goal**：把栈顶目标拆出一个更近、更容易验证的子目标，必须同时给出判据；重申"子目标是里程碑不是路径点"、位置写法要求；额外给出一条策略提示——碰到 `known_objects` 里还没互动过的门/招牌/人时，先拆子目标去"够到它"，具体按哪个键、试哪个朝向不用现猜，那部分已经有 `known_objects` 里"试过"和"还剩几种"的记录，子目标只管够到，怎么碰是更低层的事。
- **inspect**：对当前这一帧再问一个具体问题，游戏不动；强调问题必须是新的，问"再看看"得不到新内容。

### 4.3 `judge_success.md`：判定 prompt 的组织方式

结构：

1. **角色设定**：独立判定员，唯一工作是判断给定目标是否已达成；不出主意、不评价、不猜下一步。
2. **怎么判**：默认"没完成"，只有出现能直接支持"已完成"的证据才判 `true`；"看起来快完成了/大概率完成了"仍然是 `false`；显式指出"判错成完成的代价远大于判错成没完成"（完成会立刻终止目标并进入实验数据，没完成只是多跑几步）。
3. **输出格式**：`{"done": bool, "why": "..."}`，`why` 要求引用画面里的具体内容，不能只是复述"尚未完成目标"。
4. **"说完话了"怎么判**：单独一节处理"对话类判据"的时序陷阱——对话框消失本身不代表没完成，因为判据问的可能是"发生过没有"而非"此刻是否正在发生"；给出判定规则：历史里最近几步的对话框出现过对方的话 **且** 这一帧对话框已经消失，两者同时成立才算完成；同时警告反向陷阱：历史里从未出现过对方的话，只是这一帧碰巧没有对话框，那仍然是 `false`；并区分"事件类"判据（看历史）和"状态类"判据（只看当前这一帧，历史不算数）。
5. **"你手里没有地图，这是故意的"**：明确告知判定器看不到 `walk_map`/`landmarks`，理由同 `JUDGE_BLIND` 的说明——防止它去数格子、把行列号错当全局坐标；位置类判据直接读 `where` 字段即可，坐标推理不算证据。
6. **历史**（`$history`）：最近几步的流水（画面、按了什么、之后变成什么），明确标注"这里面没有他的想法和理由，只有发生过的事"——他自己说"已经和母亲说过话了"不算数，对话框里真的出现过那句话才算数。
7. **当前画面**（`$observation`）、**目标**（`$goal`）、**判据**（`$criteria`）。

### 4.4 `retry_note.md`

作为纠正块被追加在原 prompt 末尾（前置两个换行由 `retry_note()` 函数拼接，不属于模板文件本身）。内容：

- 告知这是第 `$attempt` 次尝试，上次输出不合法。
- 给出失败原因（`$reason`）和上次的原始输出（`$raw`）。
- 要求"别再输出同样的东西"。
- 针对"不在 action space 里"这类原因给出专门的解释：这一帧当前只有"可用按键"里列出的键能按，通常是因为画面被对话框/选择框挡住，应先按可用键清掉挡着的东西，原目标仍在栈上，等画面恢复再继续。

### 4.5 `brain_hints.py`：组装层

这个文件不是 prompt 文字本身的来源（文字在 `.md` 文件里），而是**组装逻辑**，理由是"怎么拼接"和"prompt 文字"是两件事，都不该留在 `brain.py` 里（那里该管"怎么决策"）：

- **`retry_note(attempt, reason, raw) -> str`**：返回 `"\n\n" + _RETRY_PROMPT.render(...)`。两个换行是刻意的，给和上文留出视觉分隔；`retry_note.md` 的内容从 `---` 开始正是为此设计。追加在**末尾**而非重新组织整个 prompt，是为了让前缀完全不变，三次尝试共享同一段缓存。
- **`INTENT_HELP: dict[Intent, str]`**：由 `load_sections("intent_help")` 拆分 `intent_help.md` 得到,按 `Intent.PRESS`/`PUSH_GOAL`/`INSPECT` 建立字典。被记录为"接口的一部分"而非"prompt 模板的一部分"：大脑能做哪几类事由 `ActionSpace.intents` 决定,说明文字必须跟着实际下发的那几类走——如果写死在模板里,某个 intent 被掩掉后说明还留着,模型会去选一个用不了的东西。

---

## 5. `reflect()`：把一步整理成一条记忆

```python
def reflect(
    self, before: Observation, action: Action, after: Observation
) -> MemoryEntry:
```

前置条件：`action.rationale` 非空（`assert`）。

组装的字段：

- `before` = `Snapshot.of(before)`（动作执行前的快照）。
- `rationale` = `list(action.rationale)`——**写进去的是 `rationale`，不是 `thought`**。完整的推理过程留在 trace 里，进入记忆的只有论据本身。这使得这条记忆是**自带标签**的："我以为 P，结果 R"——取回这条记忆时,反例会直接贴在同一行,一条错误的论据不会被当成可靠知识继续使用。若单纯记录"结论"（比如判断成功/失败），未来的检索者拿到的就只是一个标签,看不到当初支撑这个结论的依据是否仍然成立。
- `action` = `f"{action.name}{times}"`，其中连按次数 `times` 从 `action.args.get("times", "1")` 取，非 `""`/`"1"` 时格式化成 `" ×N"`。连按次数**从动作本身取，不从观测里找**——因为"发出了几次这个按键"是我们自己确定的动作参数,不需要也不应该从观测结果里反推。
- `after` = `Snapshot.of(after)`——**是一个完整观察，不是一句话结果**。早期版本只存"结果：你在野外"这类压缩过的标签，取回十条记忆全都长一个样，无法回答"那一下到底改变了什么"，而这正是这条记忆存在的唯一价值。
- `key` = `snapshot.position or str(before.step)`——本阶段用位置作为占位符（比用 `step` 更好，因为位置是可复用的作用域,同一位置的经验对未来路过此处仍然有用,而 `step` 编号本身没有复用价值）。文档标注：机制抽象接入后会换成状态语义 key，但**这个方法的签名不变**。
- `step` = `before.step`。
- `episode_id` = `""`——**由 Harness 盖章**，和 `Observation.step` 一样,大脑本身不知道自己身处哪一局。

### 5.1 为什么这一版没有模型调用

按方法的理想形态,"存入前的修饰"（改写措辞、抽出可复用结论、判断这条经验值不值得存）应该发生在 `reflect()` 里,这个方法留出了这个挂载点，**但本版是纯格式化,不调用任何 LLM**。理由是成本核算：加一次修饰意味着每一步多一次（第三次）模型调用，而目前没有任何证据表明修饰过的条目能检索得更准——检索本身现在还只是字符重叠匹配（见 `MemoryTool.query_episodic`）。设计选择是先把结构立起来,等检索机制换成向量检索、能够量化"修饰是否提升命中率"之后再开启这部分逻辑；到那时只需要改这一个方法体，签名和所有调用方都不需要变。

`reflect()` 之所以仍然放在 `Brain` 里而不是 `Tools` 层，是因为**记忆的措辞是大脑的产物**——今天恰好不需要模型调用，不代表这件事本质上属于工具层。

---

## 6. `judge()`：判断一个目标是否达成

```python
def judge(
    self, goal: Goal, obs: Observation, history: Sequence[MemoryEntry] = ()
) -> Verdict:
```

**永远返回 `Verdict`，不抛异常**——这是和 `choose()` 的一个刻意差别（见 6.4）。

**任务目标和子目标走同一个方法**，只是 `goal` 从目标栈的不同层取；判定这件事在两种粒度上是同一回事——拿着一句判据去看一帧画面。分成两个方法只会得到两份要各自标定的 prompt，没有实质好处。区分究竟在判哪一层是**调用方（Harness）的事**，Harness 会在 trace 里标 `depth`。

**更要紧的规则：只有栈底那一层决定 episode 成败。** 子目标完成时只弹栈，不写 `success`。理由：如果子目标完成也能写 `success`，agent 就可以主动压一个"我已经到家了"的子目标，让判定器判定它完成，从而使成功率变成"agent 自己发给自己的奖状"。

### 6.1 `history` 给的是证据，不是说辞

`judge()` 现在有一个 `history: Sequence[MemoryEntry]` 参数（默认空元组，不传也要能判——多一份历史是多一份证据，不是必需品）。它是**本局最近几步**、按时间顺序、**不含 `rationale`** 的记录。

需要它的原因：判定器需要看到最近几步，因为证据可能出现在三步之前那一帧的对话框里——尤其是子目标场景：一条第 10 步才被压入栈的子目标，前 9 步根本没有人问过它，那几帧画面因此永远丢失（如果只让判定器看当前这一帧）。旧版本靠"每一步都重新问一次"来兜底，但兜不住这个"证据已经翻篇"的洞。

但历史里危险的部分是 `rationale`——被评价者自己的说辞。所以渲染 `history` 时一律使用 `m.render(reason=False)`：**发生过的事给判定器看，它对那件事的主张不给判定器看。**

### 6.2 实现细节

`judge()` 内部把渲染和调用都包在 `try/except Exception` 里，理由被明确记录：`render()` 用的是 `Template.substitute`，模板少一个占位符就会抛 `KeyError`，而 prompt 是改动最频繁的一类文件；如果渲染放在 `try` 外面，"判定器永不抛异常"这条契约就会有一个缺口——而 `_judge_all`（Harness 侧）是并发调用 `judge()` 的，一个 worker 抛出异常会穿透整个循环,把一次本该记成"判定失败"的事件变成一整局丢失的数据。

流程：

1. 渲染 `rendered`：把 `obs.facts` 中**排除 `JUDGE_BLIND`** 字段后的部分逐条列出；若为空则回退用 `obs.summary`。
2. 渲染 `past`：`history` 中每条 `m.render(reason=False)` 用两个换行拼接；为空时填"（这是第一步，之前什么都没发生）"。
3. 用 `self._judge_prompt.render(goal=goal.goal, criteria=goal.criteria, observation=rendered, history=...)` 得到最终 prompt。
4. 调用 `self._judge_llm.complete(prompt)`。
5. 任何异常（渲染失败、网络问题等）被捕获，返回 `Verdict(done=False, why=f"判定调用失败：{类型名}", call=...)`——`call.error_kind` 记异常类型名，`call.error` 记异常信息前 200 字符。
6. 正常路径：调用 `_parse_verdict(completion.text)` 得到 `(done, why, kind)`，包装成 `Verdict(done=done, why=why, call=ModelCall(...))`。

### 6.3 `_parse_verdict`：解析 fail closed

```python
@staticmethod
def _parse_verdict(text: str) -> tuple[bool, str, str]
```

- 容忍 ` ```json ` 包裹。
- `json.loads` 失败 → `(False, "判定输出不是合法 JSON：...", "ParseFailure")`。
- 顶层不是 dict 或 `done` 不是布尔值 → `(False, "判定输出缺少布尔 done：...", "ParseFailure")`。
- 否则返回 `(bool(raw["done"]), str(why) if why else "（未说明）", "")`——第三项空串代表解析成功。

**解析不出来时 `done` 一律为 `False`——fail closed。** 理由是代价不对称：判成"完成"会立刻终止这一局并直接进入实验数据；判成"没完成"只是多跑几步。所有不确定性都应该往"没完成"倒。

第三个返回值（失败类型字符串）让调用方能把"判定得出了没完成的结论"和"根本没判出来（解析失败）"这两件事分开统计——如果混在一起，判定器的失效会变得**不可见**，表现为成功率悄悄跌到 0 而没人知道原因。

### 6.4 和 `choose()` 的差别：判定器不该让一局崩掉

`judge()` 永不抛异常，`choose()` 在重试耗尽后返回 `None` 也不抛异常，但两者对"模型调不通"（网络、鉴权类错误）的处理是不同的：`judge()` 把这类错误也吞掉、转成 `Verdict(done=False, ...)`；而 `choose()` 对"调不通"这类错误没有特殊吞掉逻辑（只吞了预期内的解析/校验失败），模型真的连不上时会直接向上抛出。

原因：判定器坏掉不该让一整局崩掉——那会把一次"可以标记为判定失败"的事件，变成一整局数据的丢失；而决策模型真的调不通时，这一局本来就跑不下去了，硬撑着继续跑只会产出一串没有意义的步骤。

### 6.5 `JUDGE_BLIND`：判定器看不到的字段

```python
JUDGE_BLIND: frozenset[str] = frozenset({
    "known_objects", "walk_map", "landmarks", "inspected",
})
```

这是一份**黑名单**（不是白名单），在渲染 `obs.facts` 给判定器时被排除。四个字段各自的理由：

- **`known_objects`**：**跨 episode 的流水**（"见过 7 次，互动 1 次""他说过 XXX"）。上一局说过的那句话会残留在里面；如果目标是"和母亲对话"，这个字段足以让判定器在**第 0 步**就误判完成，而这一局其实什么都还没发生。`history` 参数之所以是安全的，正因为它两头都有界（只有本局、只有最近几步）；`known_objects` 没有这个界。
- **`walk_map` / `landmarks`**：**堵掉坐标推理的原料**。仅在 prompt 里写"别做坐标换算"不够——实测判定器仍然会做：把 `walk_map` 的行号当成全局 y 坐标，得出"他还没进屋"的错误结论，而 `map_id` 已经明写着他在屋内。拿不到原料，判定器就用不了这套错误推理。位置证据改由 `where` 字段直接给出——那是答案，不是需要推理的原料。
- **`inspected`**：这是**决策者自己挑的问题**得到的回答，跟着决策者当时的注意力走。让判定器读它，等于让被评价者向评价者递材料。

设计上刻意选择"黑名单"而不是"白名单"，因为两种失效模式不对称：漏进一个不该给的新字段，代价是判定器多看一眼（可能造成误判，但可发现、可修）；漏掉一个该给的字段，代价是判定器直接瞎掉——文档提到 `dialog_text` 曾经因白名单式思路被漏掉，判定器一路回答"对话框内容未提供"，导致一局本该成功的 episode 被静默记成失败。两种失败代价不对称，所以宁可默认多给（黑名单只挡明确有害的字段）。

---

## 7. Brain 如何被 Harness 使用

`Brain` 是 `BrainPort` 的实现，被 Harness 通过 Protocol 类型持有和调用；Harness 负责控制主循环、检索并传入 `memories`/`history`、把 `Decision.calls` 和 `Verdict.call` 翻译成 trace 事件、把 `reflect()` 返回的 `MemoryEntry` 落库、以及决定 `choose()` 返回 `action=None` 或 `judge()` 判定失败时这一局该如何处理。Harness 内部的循环控制、记账翻译、检索策略、`JUDGE_HISTORY` 窗口大小等具体机制属于 Harness 模块自身的规格范围，本文档不展开。
