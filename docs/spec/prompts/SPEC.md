# Pokemon Agent — `prompts/` 模块技术规格

本文档描述 `pokemon_agent/prompts/` 目录下所有文件的职责、数据流与占位符契约，供修改任一 prompt 之前核对：改一个 `.md` 文件时，必须知道它被谁 `render()`、传的是哪些关键字参数，否则 `Template.substitute` 会直接抛 `KeyError`（详见下文）。

## 目录清单

```
prompts/
├── __init__.py          # PromptTemplate / load / load_sections / load_nested_sections
├── game_hints.py         # BUTTON_HELP / MAP_HINT / REPEAT_HINT（供 tools/game_tools.py 用）
├── brain_hints.py        # retry_note()（供 brain/brain.py 用）
├── perceive_screen.md    # 感知：把一帧画面解析成结构化 JSON
├── decide_action.md      # 决策：大脑的 ReAct 主 prompt
├── judge_success.md      # 判定：独立判定目标是否完成
├── episode_summary.md    # 蒸馏：把一整局蒸馏成一条跨局摘要记忆
├── button_help.md         # 按键说明素材（按 overlay 分类）
├── map_hint.md             # 地图（walk_map）读法说明素材
├── repeat_hint.md          # 按键链（sequence）用法说明素材
└── retry_note.md           # 重试时追加的纠正块素材
```

这里曾经有一个 `inspect_focus.md`（"细看"：对同一帧画面回答一个具体问题，游戏不推进）。
细看整条链路——`PyBoyWorld.inspect()`、`WorldPort.inspect`、`Intent.INSPECT` 分派——已经整条删掉，
这份 prompt 没有任何读者，随之删除。它当时踩到的那个坑值得留下：
**`perceive()` 是帧内缓存的**，同一帧原样再看一遍返回的字节完全一样，
所以"细看"的问题必须是**新问题**，问"再看看"只会得到一份重复的答案却照样花掉一次调用。
拆解 / 追问机制以后要是重写，这条约束依然成立。

另外，`prompts/` 目录和测试里的 `CALLERS` 表是**强制对齐**的：新加或删掉一份 `.md`
而不同步改 `tests/test_prompts.py`，测试直接红（见第六节）。

---

## 一、`__init__.py`：加载与渲染机制

### 1.1 设计动机（来自模块 docstring）

Prompt 在这个项目里被当作**实验变量**而不是配置项，因此三条要求决定了这个模块的形状：

1. **可 review**：prompt 单独存成 `.md` 文件，改动是干净的文本 diff，不是被转义过的 Python 字符串常量。
2. **可归因**：每份 prompt 都带一个内容哈希 `sha`，随调用记入 trace——用来说清楚一次实验的准确率对应的是哪一版 prompt 文字，避免改完 prompt 又跑一遍后两组数字无法比较。
3. **无花括号冲突**：占位符用 `string.Template` 的 `$var` 语法，而不是 `str.format` 的 `{}`。因为 prompt 里大量出现 JSON 示例，`str.format` 会把 JSON 里的 `{` 当成占位符起点，逼着到处写转义的 `{{`。项目认为使用标准库 `string.Template` 不算引入"模板引擎"（CLAUDE.md 明确拒绝的是引擎），因为模板内容本身依然是一眼可见的纯文本，没有条件、循环等控制逻辑。

### 1.2 `PromptTemplate`（`@dataclass(frozen=True)`）

字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `name` | `str` | 模板名（不含 `.md` 后缀），即 `load()` 传入的 `name` |
| `text` | `str` | 从 `.md` 文件原样读出的全文（UTF-8） |
| `sha` | `str` | `text` 的 SHA-256 摘要，取前 12 个十六进制字符 |

**`sha` 的作用**：不是手工维护的版本号，而是内容哈希。理由是"改了内容忘记改版本号"是必然会发生的人为失误；一旦内容和版本号对不上，一批实验数据的归因就废了。`sha` 计算方式固定为 `hashlib.sha256(text.encode()).hexdigest()[:12]`，随模板文本变化自动变化，不需要人工同步。使用方式是把它塞进调用记录（trace/payload），例如 `brain.py` 中判定失败时的 payload 带 `"prompt_sha": self._judge_prompt.sha`。

**`render(self, **kw) -> str`**：内部调用 `string.Template(self.text).substitute(**kw)`。

关键设计点：使用的是 `substitute`，**不是** `safe_substitute`。二者的区别决定了失败行为：
- `substitute`：模板里出现的占位符如果调用方没有通过关键字参数提供对应的值，会**当场抛异常**（`KeyError`，被 `Template.substitute` 包装后表现为 `KeyError`）。
- `safe_substitute`：漏传的占位符会原样保留成字面量 `$foo` 留在渲染结果里发给模型，不会报错。

项目选择 `substitute` 的理由（docstring 原文）：漏传一个变量应当当场炸，而不是把字面量 `$foo` 悄悄发给模型——那样会得到一个看似正常、实际上有缺陷的输出，且这种缺陷不会在调用处报错，只会在下游（模型的回答质量、下游解析）体现出来，难以定位。

**前置条件**：调用 `render()` 时，必须为模板文本中出现的**每一个** `$xxx` 占位符都提供同名关键字参数，一个不少（多传不会报错，`Template.substitute` 会忽略未在模板中出现的多余关键字）。

### 1.3 `load(name: str) -> PromptTemplate`

```python
path = _DIR / f"{name}.md"
```

- 按文件名（不含扩展名）在 `prompts/` 目录下查找同名的 `.md` 文件并整体读入。
- **失败行为**：如果 `path` 不是一个存在的文件（`path.is_file()` 为假），**立即抛出 `FileNotFoundError`**，错误信息里附带当前目录下所有可用的模板名列表（`available = sorted(p.stem for p in _DIR.glob("*.md"))`），不做任何兜底或默认值。设计理由（docstring 原文）：prompt 缺失不是可以兜底的情况——如果一个 prompt 文件应该存在却不存在，说明部署或代码有问题，静默降级只会把问题掩盖到更下游、更难定位的地方。
- 加载成功后：`text = path.read_text(encoding="utf-8")`，`sha` 按 1.2 节所述方式计算，返回一个新的 `PromptTemplate(name, text, sha)` 实例。

### 1.4 `_split(text, marker)`（内部辅助函数）

按照"以 `marker` 开头、独占一行"的规则切分文本，返回 `{片段名: 片段内容}` 的字典（每个片段的内容会去掉首尾空行）。是 `load_sections` / `load_nested_sections` 的公共实现，不直接对外暴露。

### 1.5 `load_sections(name) -> dict[str, str]`

调用 `load(name)` 读入整份 `.md` 文本后，用 `_split(text, "## ")` 按二级标题切块，返回 `{标题名: 该标题下的正文}`。

**用途**：有些 prompt 片段不是一整块文字，而是**按情形分叉**的——例如每个 intent 一段说明、每个按键一段说明。这类内容依旧遵循"放进 `prompts/` 目录、走同一套可 review / 可归因 / 无花括号冲突流程"的原则，只是它们在代码里原本是 dict 字面量而不是单一模板字符串。用 Markdown 的 `##` 标题天然表达"分叉"结构，不需要为此发明新的文件格式，也不必为了塞进单一 `PromptTemplate` 而把结构拍扁成一整块文字。

调用方：**目前没有**。唯一的用户 `INTENT_HELP` 随 intent 分派一起删了。
留着是因为它和 `load_nested_sections()`（还在被按键说明用着）是一对，删一个留一个更怪；
拆解机制在别处重写时如果不再用分节 prompt，它该跟着删。

### 1.6 `load_nested_sections(name) -> dict[str, dict[str, str]]`

两层版本：先按 `## 外层标题` 切一次，再对每个外层片段的正文按 `### 内层标题` 切一次，得到 `{外层名: {内层名: 内容}}`。

调用方：`game_hints.py` 用它加载 `button_help.md`（外层是 `Overlay`：`none`/`dialog`/`choice`，内层是具体按键名，例如 `overlay=dialog` 下面再切出 `a` 这一段）。

---

## 二、`game_hints.py`：按键 / 地图 / 连按提示的组装

模块 docstring 明确了它的定位：内容全部在 `prompts/*.md` 里，这个文件**只做组装**——因为 `.md` 是纯文本，没法自己按 `Overlay` 枚举分类，也没法自己嵌入当前的地图图例。组装逻辑依赖 `schemas.observation` 里的 `Overlay`、`TerrainMap`、`terrain_legend`，所以放在 `prompts/` 包里而不是 `tools/game_tools.py`——后者只该负责"把大脑的输出翻译成游戏动作"，不该同时管"这段说明文字怎么拼出来"。`game_tools.py` 直接 `from pokemon_agent.prompts.game_hints import BUTTON_HELP, MAP_HINT, REPEAT_HINT` 拿到的是已经拼好的常量，调用方不需要知道它们是从 `.md` 文件读出来的。

### 2.1 `BUTTON_HELP: dict[Overlay, dict[str, str]]`

```python
_BUTTON_SECTIONS = load_nested_sections("button_help")
BUTTON_HELP = {
    Overlay.NONE: _BUTTON_SECTIONS["none"],
    Overlay.DIALOG: _BUTTON_SECTIONS["dialog"],
    Overlay.CHOICE: _BUTTON_SECTIONS["choice"],
}
```

来源是 `button_help.md`，其 `##` 外层三段（`none`/`dialog`/`choice`）与 `Overlay` 枚举的三个成员一一对应；每个外层下的 `###` 内层是具体按键（如 `up`/`down`/`left`/`right`/`a`/`start`/`b`）到说明文字的映射。

设计理由：同一个键在不同 overlay 下含义不同——`a` 在野外（`none`）是"互动"，在 `dialog` 里是"推进对话"，在 `choice` 里是"确认选中项"。如果只给大脑一份放之四海的说明，等于让它自己去猜当前语境。`Overlay` 的三个成员和 `.md` 的三个 `##` 段一一对应，这里只是把 Markdown 切分结果搬进一个类型化的 `dict[Overlay, dict[str, str]]`。

### 2.2 `MAP_HINT: str`

```python
MAP_HINT = load("map_hint").render(terrain_legend=terrain_legend(), sample_map=_sample_map())
```

来源是 `map_hint.md`，渲染时填入两个占位符：
- `terrain_legend()`：来自 `schemas.observation`，产出地形图例文字（`.`/`G`/`D`/`S`/`N`/`#` 各代表什么）。
- `_sample_map()`（本文件内部私有函数）：构造一个具体的 `TerrainMap` 实例并调用它的 `.render()` 方法，生成一张给模型看的读图范例。

**关键约束（docstring 明确要求）**：这张示例地图**必须由真正的渲染函数 `TerrainMap.render()` 生成，不能手写**。理由：手写的范例迟早会和 `TerrainMap.render()` 的真实输出格式产生漂移，而这种漂移是"不报错的错误"——模型会照着一份过时格式的范例，去数一张新格式的图，结果读错却没有任何异常抛出。这和 `terrain_legend()` 被两处共用同一份 `TERRAIN_MEANING` 数据源是同一条设计理由：单一数据源，杜绝人工同步产生的偏差。

`MAP_HINT` 的内容重点：把"怎么理解一个可能不准的视觉判断"变成"怎么使用一张准确的地图"——因为地形信息早先是靠视觉模型逐格猜测（准确率约 87%），现在改为直接读模拟器内存（`world/ram.py`），复用游戏自身的碰撞判定表，几何这一维准确率变成 100%，且零延迟、不消耗模型 token。因此这段说明着重讲清 `walk_map`（不会错）和 `landmarks`（会错，因为语义标注仍靠模型）之间可信度的差异，避免模型为了自圆其说去编造"这格是特殊格"之类的解释。文末专门有一句强调地图是**每帧重新生成**的，不存在跨步骤的额度或余量——这是针对实测中模型曾把"north: grass x3"误解为"跨多个步骤的可用次数"（并因此产生约 700 token 的自我拉扯式推理）而加的纠正。

### 2.3 `REPEAT_HINT: str`（按键链说明）

```python
REPEAT_HINT = load("repeat_hint").text
```

来源是 `repeat_hint.md`，**直接取 `.text`，不调用 `.render()`**——即这份内容里没有需要按调用方参数动态填充的占位符，是一段固定文字。

**投放方式**：不是写进 `decide_action.md` 模板本身，而是通过 `ActionSpace.note` 字段随动作空间一起下发给大脑，因此**每一步的决策 prompt 都带着它**。设计理由：这段说明属于**动作接口的一部分**而不是 prompt 文字的一部分——模型能不能交一条按键链、链里允许放什么，取决于工具层（`game_tools.py` / `ActionSpace`）和解析层（`brain.py` 的 `sequence` 校验）认不认，和 prompt 怎么描述无关；如果工具层某次收紧了链的形状，这段说明也应当同步变化，而不是写死在模板里继续误导模型去用一个会被判非法的写法。

另有实现细节：必须放进 `ActionSpace.note`，而不是 `descriptions`——因为渲染 prompt 时只遍历 `space.names` 去渲染各按键的 `descriptions`，塞进 `descriptions` 字典里但没有对应键名的额外条目永远不会被渲染进最终 prompt，等于白写。

内容设计理由（docstring 详述）：实测发现模型已经在推理里把正确路径算出来了（例如 `(4,4)→left→(3,4)→left→(2,4)→down→(2,5)`），却仍然只执行第一步。原因不是不会连按，而是"没有使用它的理由"——只说"可以连按"是一句许可，许可本身不会改变行为。所以这份说明给的是三样东西：**代价**（每一步只花一次感知调用，而链里所有按键都算在这一步里；一条直线拆成五步走就是把同一段路的成本乘五，中间那四次观测什么新东西都看不到）、**规则**（三条硬规则，见 4.8）、**例子**（把规则落在模型自己刚写出来的那种路径形式上）。例子被认为最关键。同时也明确写了"什么时候别拉长链"，避免在一处收紧行为的同时在另一处过度放开。

**这份文件已经整篇重写过一次，重写的理由要记住**：它原来教的是 `"args": {"times": "N"}` 这种顶层 `action` + `args` 的写法。解析层改成按键链之后，那个格式**不再是"次优写法"，而是直接 `ParseFailure`**——一份每步都进决策 prompt 的说明，教的却是一个必然被判非法的格式，代价是每一步都在制造重试。它当时还在教"把开头那段同方向的一次走完，下一步再转弯"，那是**一步只能交一个键**时代的战术：现在 `up`/`down` 之间可以在同一条链里换向，那条战术已经比规则允许的更保守。这两处都是"prompt 说的和代码认的不是一回事"的典型，也正是第六节那道锁存在的原因。

---

## 三、`brain_hints.py`：决策 prompt 的组装层（目前只剩重试提示）

模块 docstring 定位与 `game_hints.py` 一致：内容都在 `.md` 里，本文件只做**组装**——`retry_note()` 需要在渲染结果前面拼接两个换行符，这件"怎么拼接"的逻辑不该留在 `brain/brain.py` 里，因为那个模块该管"怎么做决策"，不该同时管"这段说明文字怎么拼出来"。

### 3.1 `INTENT_HELP` —— **已删除**

曾经由 `load_sections("intent_help")` 拆分 `intent_help.md`，按
`Intent.PRESS`/`PUSH_GOAL`/`INSPECT` 建成字典，在 `decide_action.md` 里渲染进
`$intents` 占位符：只渲染当前 `ActionSpace` 实际开放的那几类。intent 分派删掉之后
（**这一版只有按键一类动作**），它和 `intent_help.md` 一起没了。

当时那条设计理由对**按键说明**（`BUTTON_HELP`）依然成立、重写时也依然成立：
这是**接口的一部分**而不是 prompt 模板固定写死的一部分——大脑能做哪几类事由运行时的
`ActionSpace` 决定，说明文字必须跟着实际下发的那几类走。写死在模板里的话，
某一类被掩掉之后说明还留着，模型就会去选一个实际用不了的选项。

`press` 那一段当时特意点出"这是唯一会改变世界、也是唯一不可逆的一类"：
另外两类选错只是浪费一轮调用，而 `press` 按错键可能要再走十步才纠正得回来。
**代价不对称，就该让模型知道**——这条在只剩一类动作的今天没有对象，
但拆解机制回来时要第一时间捡回来。

### 3.2 `retry_note(attempt: int, reason: str, raw: str) -> str`

```python
_RETRY_PROMPT = load("retry_note")

def retry_note(attempt, reason, raw):
    return "\n\n" + _RETRY_PROMPT.render(attempt=attempt, reason=reason, raw=raw)
```

- 用途：当大脑一次输出不合法（例如不是合法 JSON、字段缺失、选了 action space 之外的按键）需要重试时，把这段纠正内容**追加在原 prompt 末尾**再次发给模型。
- 占位符：`$attempt`（第几次尝试）、`$reason`（不合法的原因）、`$raw`（模型上一次的原始输出）。
- 返回值前缀了两个换行符 `"\n\n"`：这属于"怎么拼接"而不是 prompt 文字本身，所以留在 Python 代码里而不写进 `.md` 文件——`retry_note.md` 本身的内容从一条 `---` 分隔线开始，两个换行是为了在视觉上和上文的原 prompt 留出分隔。
- 设计理由（docstring）：早期版本的重试策略是原样再问一遍，指望模型靠随机性碰对——这等于把三次调用当一次用；而且最常见的一类错误（例如判据里写了屏幕网格坐标而不是全局坐标）是**系统性错误**，不指出具体问题的话重试多少次都会错在同一个地方。追加在末尾而不是改写开头是刻意设计：前缀（原 prompt）一个字不动，三次尝试可以共享同一段 prompt 前缀的缓存（用于降低重试的延迟/成本）。

---

## 四、各 `.md` 模板文件详解

### 4.1 `perceive_screen.md` —— 感知：把一帧画面解析为结构化 JSON

**用途**：这是"看图"阶段的 prompt，把一张 Game Boy 160×144 像素的游戏画面（叠加了 10 列 × 9 行红色网格）交给视觉模型，要求它输出结构化的场景描述 JSON。是整条流水线里唯一处理原始像素输入的模板。

**占位符**：`$known_map`（唯一占位符）—— 一张从模拟器内存读出的、100% 准确的地形图（由调用方传入 `terrain.render()` 的结果）。

**内容结构概要**：
- 强调只输出一个 JSON 对象，不要任何其他文字，不要 ```json 包裹。
- 先给出画面网格坐标系约定：`(列, 行)`，主角固定在 `(4,4)`，这套编号**只在模型与调用方之间使用**，不能写进 `overview` 字段（因为下游读 `overview` 的人用的是另一套全局坐标）。
- "一、判定界面类型"：`scene`（`field`/`indoor`/`battle`/`menu`/`shop`/`transition`）和 `overlay`（`none`/`dialog`/`choice`）是两个独立维度，各自给出详细判别标准（例如战斗必须同时有两个状态框，精灵状态页/列表/背包/START菜单都算 `menu` 不算 `battle`；对话框判据是"白底黑框且能抄出文字"，用以区分和纯黑地图边界的差异）。
- "二、Gen1 战斗界面布局"：判归属的**唯一判据是 HP 数字有无**——右下角那个写着 `当前/最大` 数字 HP 的状态框是我方，左上角只有血条、没有数字的是对手；先在两个框里找哪个有数字，再据此定位置，**不允许用种类/等级/是否御三家做归属推理**（附一条真实翻车过的反面例子：`RATTATA :L2` 只有血条却被填成我方，`BULBASAUR :L5` 写着 `18/20` 却被填成对手）。`foe_hp` 本来就没有数字可抄（Gen1 原版对手状态框只有血条），填血条挡位（满/较高/过半/较低/危险），**不允许编一个 `nn/nn` 出来**；选招式界面下 `TYPE/xxx` + 一组 `nn/nn` 是 PP、不是 HP，判据是"这个框里有没有宝可梦名字和等级"——没有就是 PP，两个状态框在选招式界面上依然显示在原位，`my_hp`/`foe_hp` 任何时候都只从这两个框读。
- "三、野外与室内"：告知 `$known_map` 已经 100% 准确，模型**不需要重新判断地形**，只需要写 `overview`（一两句话描述观感，不是复述地图）；明确指示**不要给门/招牌/人起名字**（因为总览画面里往往没有文字证据支撑，模型会按游戏常识编造）。
- "四、按 scene 填 fields"：列出六种 `scene` 各自要求填哪些字段（`battle` 要 `my_name/my_level/my_hp/foe_name/foe_level/foe_hp`——`my_hp` 是 `当前/最大` 数字，`foe_hp` 是血条挡位，两者格式不同；`menu` 要 `title`，`shop` 要 `money/items`，其余留空对象）。
- "五、抄写规则"：名字原样抄英文不翻译、不猜地名、数字原样抄不计算、`fields` 的值一律写成字符串、读不出来的字段直接不放进去（不要填占位值）、`dialog_text`/`options`/`cursor` 的填法。
- "六、每一类的输出样例"：为 `field`/`indoor`/`battle`/`menu`/`shop`/`transition` 各给一份完整 JSON 示例。

**输出 JSON 顶层字段**（从示例可读出）：`scene`、`overlay`、`overview`、`dialog_text`、`options`、`cursor`、`fields`。

### 4.2 `inspect_focus.md` —— **已删除**

曾经是"细看"用的模板：大脑选择 `intent: inspect` 时，让视觉模型针对**同一帧画面**
回答一个具体、狭窄的问题（游戏不推进）。占位符是 `$focus`（要问的问题）、
`$known_map`（同一张 100% 准确的地形图）、`$legend`（地形图例）。
细看整条链路删掉之后（`PyBoyWorld.inspect()` / `WorldPort.inspect` 都没了），
它没有任何读者，随之删除。

几条当时踩出来的经验值得留着，将来重写追问机制时能省一遍弯路：

- **同一帧再问一遍是没有信息的**：`perceive()` 帧内缓存，同一帧原样再看返回的字节完全一样，
  所以问题必须是新的；"再看看"是纯粹的空调用。
- **视觉观感和地图冲突时以地图为准**，但要把视觉上看到的样子说出来——
  掩掉冲突会让下游以为两边一致。
- **换算不出来就直说看不出来**：画面上叠的红色网格坐标和全局坐标不是同一套，硬凑出来的坐标是最难查的一类错。
- 它是唯一一份**要求自由文本、明确禁止 JSON** 的模板，和其余模板形成对照。

**更正（0902 全项目可观测扫描发现）**：这两句原来说 trace 那边仍保留
`EventType.INSPECT` 和回放分支，但实际代码里没有——`EventType` 枚举和
`trace/store.py` 都不含 `INSPECT`，功能删的时候枚举成员也一起删了，带这类
旧事件的历史 trace 文件回放不了（`docs/spec/README.md`/`docs/spec/DATAFLOW.md`
是准确的版本）；`trace/browser.py` 这个文件本身也已经不存在（被 `pokemon_agent/api.py`
取代，见该文件顶部说明）。

### 4.3 `decide_action.md` —— 决策：大脑的 ReAct 主 prompt

**用途**：大脑每一轮做决策时使用的核心 prompt。开头一句已经从"选出下一个动作"改成**"选出这一步要按的按键链"**——这不是措辞调整，是决策粒度本身变了：一步交出的不是一个键，而是一条会连着按完、中间不重新观察的链，"这一步做多少"由模型自己决定。是整个系统里占位符最多、结构最复杂的模板。

**占位符**：`$goals`（目标栈渲染结果，栈顶在最上）、`$status`（当前状态行，来自 `obs.status`）、`$facts`（已知事实列表）、`$memories`（相关记忆）、`$actions`（可用按键列表及说明，来自 `space.names`/`space.descriptions`，若 `space.note` 存在则追加在后面）、`$max_rationale`（`rationale` 字段最多允许几条论据）。

> 占位符曾经叫 `$summary`，随 `Observation` 的字段一起改名成 `status`。这类改名是
> `Template.substitute` 最容易炸的地方——模板和调用方必须同时改，改一边就是运行期 `KeyError`。
> 现在这一对由 `tests/test_prompts.py` 的 `CALLERS` 表挡着（第六节）。

**内容结构概要**：
- 目标栈规则：只需要完成栈顶那一条，完成后自动出栈。
- 可用按键列表由 `$actions` 动态填入，标题已改成"可用按键（可组成有限按键链）"。
- 输出格式：只输出一个 JSON 对象，示例为
  `{"thought": ..., "rationale": [...], "sequence": [{"action": "up", "times": 4}, ...]}`。
  **顶层 `action` / `args` 不再被接受**：解析层只读 `sequence`，缺了它或不是非空数组直接 `ParseFailure`。
- "各字段的要求"逐项细化：
  - `thought`：仅用于记录，不进入后续决策。
  - `rationale`：1 到 `$max_rationale` 条，要求写成"以后还能验证真假"的具体依据（例如"地上有药水而我手上没有"），而不是主观判断（"我觉得这样比较好"）；因为这些内容会被存入记忆，未来在相似状态下被检索复用。
  - `sequence`：非空数组，每段 `{"action": 键, "times": N}`，N 为 1-8，受三条硬规则约束——
    **长度为 1** 时可以是任意一个当前可用按键；**长度大于 1** 时每一段只能是 `up` 或 `down`
    （要拐弯就把这一步收在拐弯前，`{"action": "right", "times": 3}` 单独成一步完全合法，
    只是不能和别的段拼在一条链里）；**`a` 的 `times` 永远是 1**，写大了会被改成 1。
    怎么数 `times`、什么时候该把链缩短，模板不重复讲，指向 `$actions` 末尾的那段
    （即 `ActionSpace.note` 里的 `REPEAT_HINT`）。

**`a` 恒为 1 的理由（写在 `brain.py` 的解析处，值得在这里记一笔）**：一条链只在结尾感知一次，
连按会把中间那几帧整个吃掉，而 `a` 产出的恰恰是全项目最要紧的证据——对话框文字。
连按三次推完整段对话，那几句一帧都没被看到，最后一次还会把对话框关掉，
判定器看到一个没有对话框的画面，**一局本该成功的 episode 被静默记成失败**。
夹在解析期而不是执行层，是为了让交给 world 的链**就是真正会发生的那条链**——
让非法值一路走到执行层再被悄悄改写，大脑会以为自己按了三次。

**这里曾经有一节「NPC 互动与障碍物」**，讲的是"`#` 只说明走不过去，不说明不能隔着它按 `a`"。
它已经**合并进 `map_hint.md`**（见 4.7）：那件事的判据全部来自 `walk_map` / `landmarks` /
`neighbors` 的读法，属于"怎么读地图"，放在决策模板里等于把同一套坐标语义讲两遍，
两份迟早会说得不一样。

### 4.4 `judge_success.md` —— 判定：独立判断目标是否完成

**用途**：由一个独立的"判定员"角色使用，只回答"这个目标现在是否完成"，不出主意、不评价、不预测下一步。

**占位符**：`$history`（最近几步的流水：画面/按键/结果，作为证据）、`$observation`（当前这一帧的观测，**不含 `walk_map`/`landmarks`**）、`$goal`（要判的目标文字）、`$criteria`（完成判据）。

**内容结构概要**：
- 默认结论是"没完成"：只有出现能直接支持"已完成"的证据才判 `true`；"看起来快完成了"仍然判 `false`；"什么都看不出来"也判 `false`。
- 明确不对称代价：判错成"完成"的代价远大于判错成"没完成"——前者会让目标被永久划掉、后续步骤不再为它发生，且结果会被计入实验统计；后者只是多跑几步、下一步还有机会纠正。因此拿不准一律 `false`。
- 输出格式：只输出一个 JSON 对象 `{"done": bool, "why": "..."}`，`why` 必须引用画面里的具体内容，不能只是复述目标未完成。
- "「说完话了」怎么判"：区分**事件类判据**（"和某人说完话"）和**状态类判据**（"此刻在哪张地图/是否有某物品"）——前者要回看 `$history` 里是否出现过对方说的话、且当前帧对话框已消失，两条同时成立才算完成；不能仅因为"当前帧没有对话框"就直接判 `false`；反过来，历史里从未出现过对话内容，只是当前帧碰巧没有对话框，则应判 `false`。状态类判据不看历史，只看当前帧。
- "你手里没有地图，这是故意的"：`$observation` 里不包含 `walk_map`/`landmarks`，原因是实测发现拿到地图的判定员会去数格子、把行号当全局坐标算错，反而得出与 `map_id`/`scene` 明显矛盾的结论；判据里如果提到位置，应直接读 `where` 字段，它已经是最终答案，不需要换算；坐标推理本身不算证据，证据必须是画面上直接写出来的东西（对话文字、`scene`、`overview`）。
- `$history` 部分明确说明：这里面**没有模型自己的想法和理由**，只有"发生过的事"——模型自称"我已经和母亲说过话了"不算数，对话框里真的出现过那句话才算数。

### 4.5 `button_help.md` —— 按键说明素材（按 overlay 分类）

**用途**：不是独立发给模型的完整 prompt，而是被 `game_hints.py` 用 `load_nested_sections` 解析后拼进 `decide_action.md` 的 `$actions` 段的素材文件。核心命题写在文件开头：同一个键在不同 overlay 下含义不同，说明也得跟着变，否则等于让模型自己去猜当前语境。

**占位符**：无（纯静态文本，按 `##`/`###` 两层结构组织，不经过 `.render()`）。

**结构**：`##` 层是三个 `Overlay`（`none`/`dialog`/`choice`），`###` 层是各自可用的按键：
- `none`：`up`/`down`/`left`/`right`（各自走一格）、`a`（互动，**一次只按一次**，`times>1` 会被强制夹成 1，因为对话是逐句出现的）、`start`（打开主菜单）。
- `dialog`：`a`（推进对话到下一句，**一次一句**，连按会吞掉中间可能正是要找的证据文字；文件特别强调"对话框挡住整个画面时，唯一能做的就是按 a"，不管此前目标是什么，都要先把对话推完）。
- `choice`：`up`/`down`（移动光标）、`a`（确认选中项）、`b`（取消/退回上一层）。

### 4.6 `intent_help.md` —— **已删除**

曾经是三个 `##` 段（`press` / `push_goal` / `inspect`），被 `brain_hints.py` 用
`load_sections` 解析成 `INTENT_HELP`，供 `decide_action.md` 的 `$intents` 段动态拼接。
intent 分派删掉之后没有任何读者，随之删除。

三段里值得在重写拆解机制时捡回来的内容：

- `press`：**唯一会推动游戏世界、也是唯一不可逆的一类**。代价不对称就该让模型知道。
- `push_goal`：子目标是"里程碑不是路径点"；位置一律写 `x=.. y=..`（不要括号对、
  不要行列描述、不要提 `walk_map`——判定的人看不到那张图）；遇到 `known_objects` 里
  还没互动过的门/招牌/人时，先拆一个"够到它"的子目标，**具体按哪个键、试哪个朝向
  不用现猜**，那部分已经在 `known_objects` 的"试过/还剩几种"记录里算好了。
- `inspect`：问题必须是新的，问"再看看"得不到新内容——`perceive()` 是帧内缓存的，
  同一帧原样再看一遍返回的字节完全一样。

### 4.7 `map_hint.md` —— 地图（walk_map）读法说明素材

**用途**：被 `game_hints.py` 渲染为 `MAP_HINT` 常量，说明如何解读 `facts` 里的 `walk_map` 字段（10 列 × 9 行的地形图，来自模拟器内存）。作为一段说明文字整体注入到大脑可读到的"已知事实"相关内容中（具体注入位置由 `decide_action.md` 的 `$facts`/上下文体系决定，`MAP_HINT` 本身是独立于 `decide_action.md` 之外的一段文字常量）。

**占位符**：`$terrain_legend`（地形图例）、`$sample_map`（示例地图，由真实渲染函数生成，见 2.2 节）。

**内容结构概要**：
- "怎么读 walk_map"：给出图例。
- "只有一套坐标"：图上的行号 `y=..` 和 `where`/`landmarks`/`known_objects` 里的 `x= y=` 是同一套数，无需换算；给出示例图；`@` 是玩家自己；`y` 向下增大、`x` 向右增大。
- "图上没有列号，别在图上找东西"：因为一列只有一个字符宽、写不下多位数的 x，所以只标行号；模型不该在图上数格子找东西，门/招牌/人的坐标应直接读 `landmarks`/`known_objects`，四个方向的可通行性应直接读 `neighbors`；地图剩下的作用是看整体形状（哪边通、哪边死路、怎么绕）。
- 格式约束：每行恰好 10 个字符、没有空格；图和 `landmarks` 若对不上，是数错了不是数据错——两者同源，不要花篇幅论证哪边可信，以 `landmarks` 为准。
- "站在 `D` 上的时候，朝地图外面那个方向按"：门格贴着地图边界，`neighbors` 会显示那个方向是 `#`（走不过去），但按下去实际会触发换图；`#` 表示"走路走不过去"，不表示"按了没用"；给出具体操作指引（先试朝向地图边界的那个方向，而不是换一扇门；两扇门挨着时尤其要注意）。
- "地标没有名字，`known_objects` 才有"：`landmarks` 只有类型和坐标，不含名字/文字内容（因为画面里根本没渲染出来，写出来就是编的）；`known_objects` 才是"这张地图上见过的每个门/招牌/人的档案"，格式举例（`地图0 x=13 y=5 的「门」→ 通往地图39（见过 7 次，互动 1 次）`），并强调"还没互动过"是待办清单，应优先去试没试过的。
- "门的「试过」怎么读"：解释门一共有 8 种碰法（站在门上按四个方向之一，或从相邻格朝门推），门只有"`map_id` 变了"才算成功；档案记录格式是"坐标→按键 → 结果"，给出已知门（照做即可）和未打开门（"还剩 N 种没试"，大于 0 说明还有可试的，不要换门；写不出"还剩"说明 8 种全试过了，这扇门打不开）两种记录样式；人和招牌只有"面朝它按 `a`"一种碰法。
- 结尾重申：`walk_map` 和 `landmarks` 都来自模拟器内存、都不会错，且是每帧重新给出的，不存在跨步骤的额度或余量。

### 4.8 `repeat_hint.md` —— 按键链（sequence）用法说明素材

**用途**：被 `game_hints.py` 加载为 `REPEAT_HINT`（不经过 `.render()`，直接用 `.text`），
随 `ActionSpace.note` 下发。**它每一步都进决策 prompt**，所以它和 `decide_action.md`
说的必须是同一套规则。

**占位符**：无（固定文本）。

**内容结构概要**：一步交出的是一条按键链，每段写 `{"action": 键, "times": N}`，N 最多 8；
每一步只花一次感知调用，而链里所有按键都算在这一步里；三条硬规则（链长为 1 时任意可用按键、
链长大于 1 时每段只能是 `up`/`down`、`a` 的 `times` 恒为 1）；怎么规划（先在 `walk_map` 上
数路径，再看开头能一次走掉多少，给了三个例子，包括"拐弯要换步、但 `right×3` 自己单独成一步
完全合法"）；`times` 怎么数（沿该方向连续的 `.`/`G`，数到 `#`、`D`、`S`、`N` 或转弯处为止）；
什么时候别拉长链（路上要穿过 `G`，或预期会触发对话、换图）。

**这份文件是本项目"prompt 漂移"最贵的一次实例**，值得记全：动作格式从
`{"action": ..., "args": {"times": "N"}}` 改成 `sequence` 之后，**这份说明一个字都没改**——
它还在教已经会直接 `ParseFailure` 的旧格式，还在教"把开头那段同方向的一次走完，
下一步再转弯"这个一步一个键时代的战术。结果不是模型不会用链，而是**我们同时给了它两套
互相矛盾的说明**：它规划出 `down×2 → right×3 → up`，然后卡在"多段链只能 up/down"上，
自我说服成"当前只需输出下一步"。改格式时**挂在 `ActionSpace.note` 上的说明和主 prompt
一样要改**——它们进的是同一份 prompt，只是分两个文件写。

### 4.9 `retry_note.md` —— 重试时追加的纠正块素材

**用途**：被 `brain_hints.py` 的 `retry_note()` 函数渲染，在大脑一次输出不合法时追加在原 prompt 末尾，构成第二/第三次重试请求。

**占位符**：`$attempt`（第几次尝试）、`$reason`（不合法的原因）、`$raw`（上一次模型的原始输出）。

**内容结构概要**：以 `---` 分隔线开头（配合 `retry_note()` 在拼接前加的两个换行，形成与上文原 prompt 的视觉分隔）；指出这是第 `$attempt` 次尝试、原因是 `$reason`、并把上次的原始输出 `$raw` 贴出来；要求"别再输出同样的东西"，只输出一个 JSON 对象；针对一种常见失败原因（"不在 action space 里"）给出具体指导——这一帧当前只有"可用按键"里列出的那几个键能按，通常是因为画面被对话框/选择框挡住了，模型原本的目标本身没有错，只是这一帧推不动，应先按可用键里能清除阻挡的那个键，目标继续留在栈上，等画面恢复后再继续做。

### 4.10 `episode_summary.md` —— 蒸馏：把一整局蒸馏成一条跨局摘要记忆

**用途**：被 `memory/episode/episode_store.py` 的 `EpisodeMemoryGenerator` 渲染，
一局结束后调一次文本模型，产出 `EpisodeSummaryResponse`（再转成 `EpisodeMemory` 落库）。

**占位符**：`$goal`、`$result`、`$steps`、`$max_steps`、`$initial_state`、`$final_state`、`$steps_text`。

**内容结构概要**：说明产出的是一条**跨局摘要记忆**（和 `StepMemory` 那种"一条=一步"不是
一回事，别写成流水账）；七条生成要求；一段严格的 JSON 输出格式（`summary` /
`reusable_patterns` / `critical_decisions` / `failure_points` / `quality` /
`applicable_scenes` / `tags` / `filename` / `markdown`）；`applicable_scenes` 只能用一张
固定标签表（`*`、`map:<数字>`、`scene:*`、`overlay:*`、`terrain:grass`、`interaction:*`），
通用经验写 `*`，不许写自然语言长句。

**这里曾经走的是另一套模板引擎。** 它原来用 jinja2 的 `{{ }}` 语法，由
`EpisodeMemoryGenerator` 自己 `jinja2.Template(open(...).read())` 读进来，
**不经过 `prompts.load`**。代价不是多几行代码，是这份 prompt **没有 sha、也进不了
manifest**——某一局的蒸馏用的是哪一版说明，事后查不出来，而 manifest 存在的全部意义
就是回答这个。同一个目录里并存 `$` 和 `{{ }}` 两种语法，改错一个还不会报错。
现在它和别的模板一样走 `load()`，`RunManifest.with_prompts` 收三份：
`decide_action`、`judge_success`、`episode_summary`。
模板里那个 `{{ "成功完成" if success else "未能完成" }}` 的条件表达式挪进了代码
（调用方传 `result=`）——**分支逻辑属于代码，模板只负责放文字**，这也是这个目录
一开始就拒绝"模板引擎"的理由（见 1.1）。

---

## 五、完整调用链：prompt 模板如何被串联进一次模型调用

以下按代码中实际的调用点描述各模板的使用方式（引用文件路径供核对，非本次要求修改的对象）。

### 5.1 感知阶段 —— `perceive_screen.md` 被 `world/pyboy_world.py` 使用

`pyboy_world.py` 第 565 行左右：

```python
terrain = read_terrain(self._pyboy.memory)
prompt = self._prompt.render(known_map=terrain.render())
```

流程：每次需要感知当前画面时，先调用 `read_terrain()` 从模拟器内存读出地形（`world/ram.py`），再调用 `terrain.render()` 得到文本地图，作为 `known_map` 填入 `perceive_screen` 模板（`self._prompt` 即 `load("perceive_screen")` 得到的 `PromptTemplate`），连同截图一起发给视觉模型。返回的 JSON 会被解析并拼入 `facts` 字典（`scene`/`overlay`/`fields`/`dialog_text`/`overview` 等，见 `pyboy_world.py` 中 `overlay/text` 校验及 `facts` 组装逻辑），其中还包含一段"misread"交叉校验：若模型判定 `overlay=dialog` 但 `dialog_text` 为空，会被视为误判，强制降级为 `overlay=none` 并记录 `perception_warning`。

### 5.2 这里曾经有一个"细看阶段"

`inspect_focus.md` 由 `PyBoyWorld.inspect()` 渲染，对**同一帧**再问视觉模型一个具体问题，
世界不推进。整条链路（`WorldPort.inspect`、`PyBoyWorld.inspect/_note/_notes`、
构造参数 `inspect_prompt_name`、`facts["inspected"]`、`trace.inspect()`、模板文件本身）
已经删除，理由见 4.2。

**它留下的一条经验值得记住**：细看和 `observe()` 的区别**不在"再看一次"，而在问的是
不同的问题**——`observe()` 按帧哈希缓存，同一帧再调返回的字节完全一样，没有新信息；
换一份 prompt 去问"那一格到底是门还是窗"才可能得到新答案。哪天要重做这类能力，
这一条仍然成立。

### 5.3 决策阶段 —— `decide_action.md` 被 `brain/brain.py` 使用

`brain.py` 中组装 prompt 的私有方法（约 400-422 行）：

```python
facts = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items()) or "（无）"
recalled = "\n\n".join(m.render() for m in memories) or "（无相关记忆）"
actions = "\n".join(f"- {name}: {space.descriptions.get(name, '（无说明）')}" for name in space.names)
if space.note:
    actions += f"\n\n{space.note}"
return self._decide_prompt.render(
    goals=self._render_goals(goals),
    status=obs.status,
    facts=facts,
    memories=recalled,
    actions=actions,
    max_rationale=MAX_RATIONALE,
)
```

- `goals` 由 `_render_goals()` 把目标栈倒序渲染成文本（栈顶显示在最上面，因为模型是从上往下读 prompt 的）。
- `actions` 遍历 `space.names`，从 `space.descriptions` 取每个按键的说明；若 `space.note` 非空（即 `REPEAT_HINT` 等按键接口层面的补充说明），追加在末尾。这里的 `descriptions` 具体内容来源于 `BUTTON_HELP`（按当前 `Overlay` 索引出的按键说明字典），由更上层的调用逻辑（`tools/game_tools.py` 的 `get_action_space`）构造 `ActionSpace` 时填入。
- 渲染出的完整 prompt 交给决策模型（不带截图——模板本身只依赖文本占位符），模型按 `decide_action.md` 的约定返回 JSON：`thought` / `rationale` / `sequence`。
  **顶层 `action`/`args` 那一版已经不接受了**：一步交出的是一条按键链，`sequence` 里每段写 `{"action": 键, "times": N}`，多段链只能是 `up`/`down`。
- 重试：若这次响应解析失败或不满足契约（如选了 action space 之外的键），调用方会调用 `brain_hints.retry_note(attempt, reason, raw)`，把结果追加在**同一份原 prompt 之后**再次请求，直到成功或达到重试上限。

### 5.4 判定阶段 —— `judge_success.md` 被 `brain.py` 的判定逻辑使用

`brain.py` 约 270-300 行（`judge`/`Verdict.call` 相关逻辑）：

```python
rendered = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items() if k not in JUDGE_BLIND) or obs.status
past = "\n\n".join(m.render(reason=False) for m in history)
prompt = self._judge_prompt.render(
    goal=goal.goal, criteria=goal.criteria, observation=rendered,
    history=past or "（这是第一步，之前什么都没发生）",
)
completion = self._judge_llm.complete(prompt)
```

- `JUDGE_BLIND` 用于从 `obs.facts` 中过滤掉判定器不应看到的字段（对应 `judge_success.md` 里"你手里没有地图，这是故意的"一节所述——`walk_map`/`landmarks`/`known_objects` 不应出现在 `$observation` 里）。**曾经还有第四个字段 `inspected`**，随细看链路一起删了；黑名单里留着一个不存在的字段本身就是有害的，会让人以为那个字段还在产生。
- `history` 由多条历史记录（各自 `render(reason=False)`，即渲染时不带模型的推理/理由，只保留发生过的事实）拼接而成，若是第一步则给出固定占位说明文字，填入 `$history`。
- `goal`/`criteria` 直接来自当前要判定的目标对象。
- 渲染整个过程被包在 `try/except` 里——因为 `render()` 用的是 `Template.substitute`，模板占位符和调用参数一旦不匹配会抛 `KeyError`，而"判定器永不抛异常"是这个方法对外的契约（因为判定是并发执行的，一个 worker 抛出未捕获异常会破坏整个循环）；渲染失败时会被当作一次"判定失败"事件正常降级处理并记入 `Verdict`（`done=False`），而不是让异常向上传播丢失整局数据。
- 渲染成功后调用判定模型 `self._judge_llm.complete(prompt)`，返回结果按 `judge_success.md` 要求的 `{"done": bool, "why": str}` 格式解析成 `Verdict`。

### 5.5 小结：一次完整回合中模板的先后关系

1. **感知**：`perceive_screen.md`（+模拟器内存地形）→ 结构化 `facts`。
2. **决策**：`decide_action.md`（+ `BUTTON_HELP`/`REPEAT_HINT`/`MAP_HINT` 等组装出的 `$actions`/`$facts` 等）→ 模型输出一条**按键链**（`sequence`）。**这一版只有按键一类动作**，整条链交给 world 一次执行完、**只在链尾感知一次**，然后进入下一帧感知。
3. **判定**：`judge_success.md` 独立判断**栈顶**目标是否已经完成（不依赖决策阶段的推理过程，只看事实证据）；判定为 `done=true` 时目标出栈，栈空即任务完成。
4. **重试**：决策或判定阶段任一次输出不合法，追加 `retry_note.md` 内容在原 prompt 末尾重新请求，同一 prompt 前缀保持不变以复用缓存。
5. **蒸馏**（一局结束后，只发生一次）：`episode_summary.md` 把整局的关键步骤压成一条
   跨局摘要记忆，落进 `EpisodeMemory`，供**以后别的局**按场景检索回来。它不在每步的
   回路里，所以容易被忘掉——但它和上面四份走的是同一条加载路径、同样进 manifest。

所有渲染动作最终都经过 `PromptTemplate.render()`（即 `string.Template.substitute()`），因此修改任一 `.md` 模板文件时必须同步核对：新增/删除的 `$xxx` 占位符是否和上述各调用点传入的关键字参数集合完全一致，否则会在运行期直接抛出异常（决策/判定阶段有各自的重试或降级机制兜底，但异常本身仍会被记录为一次失败，不会被吞掉）。

---

## 六、`tests/test_prompts.py`：挡住 prompt 和代码之间的漂移

prompt 是最常改的一类文件，而它和代码之间有两处**约定但不检查**的耦合：

    模板里的 $占位符       ↔  调用方传的关键字实参
    perceive_screen.md    ↔  schemas 里的 SCENE_FIELDS / EXAMPLES

两处漂了都不会报错，只会让模型收到一份和事实不符的说明——而那种错误在日志上看起来是
"模型又答错了"。这个文件测三件事：

1. **`prompts/` 目录和 `CALLERS` 表一一对应**。新加或删掉一份 `.md` 而不登记，测试当场红。
2. **每份模板的 `$占位符` 和调用方实参双向吻合**。漏传会在 `substitute` 那里当场
   `KeyError`（那是刻意的），而**多传不报错**——只是模板里少了一段内容，没人会发现，
   所以两个方向都测。
3. **`perceive_screen.md` 的字段清单和六段 JSON 样例**分别等于 `describe_scene_fields()`
   和 `json_output_examples()` 的输出。样例按解析后的 dict 比而不是逐字比：缩进、键序
   这类差异不该让测试变红，内容不一样才该红。

`CALLERS` 那张表是**手写**的，就是"调用方的契约"。从代码里自动扒 `render(...)` 的实参
等于让两边用同一个来源，那就什么都测不出来了——这是这个文件唯一不能"优化"的地方。

**这道锁曾经只是一句话。** `schemas/observation.py` 里 `describe_scene_fields()` /
`json_output_examples()` 的注释一直写着"漂移由 `tests/test_prompts.py` 挡"，
而那个文件是 **0 字节的空文件**。后果有两层：那两个渲染函数因此零调用方、看起来像死代码；
而 prompt 和 `SCENE_FIELDS` 真漂了也没有任何人知道。**声称存在的锁不存在，比没有锁更糟**
——没有锁的时候人还会自己核对。补上这个文件的同时实测了一遍：当前没有存量漂移。
