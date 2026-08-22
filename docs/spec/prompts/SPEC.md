# Pokemon Agent — `prompts/` 模块技术规格

本文档描述 `pokemon_agent/prompts/` 目录下所有文件的职责、数据流与占位符契约，供修改任一 prompt 之前核对：改一个 `.md` 文件时，必须知道它被谁 `render()`、传的是哪些关键字参数，否则 `Template.substitute` 会直接抛 `KeyError`（详见下文）。

## 目录清单

```
prompts/
├── __init__.py          # PromptTemplate / load / load_sections / load_nested_sections
├── game_hints.py         # BUTTON_HELP / MAP_HINT / REPEAT_HINT（供 tools/game_tools.py 用）
├── brain_hints.py        # INTENT_HELP / retry_note()（供 brain/brain.py 用）
├── perceive_screen.md    # 感知：把一帧画面解析成结构化 JSON
├── inspect_focus.md      # 细看：对同一帧画面回答一个具体问题
├── decide_action.md      # 决策：大脑的 ReAct 主 prompt
├── judge_success.md      # 判定：独立判定目标是否完成
├── button_help.md         # 按键说明素材（按 overlay 分类）
├── intent_help.md         # intent 说明素材（按 intent 分类）
├── map_hint.md             # 地图（walk_map）读法说明素材
├── repeat_hint.md          # 连按（times）用法说明素材
└── retry_note.md           # 重试时追加的纠正块素材
```

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

调用方：`brain_hints.py` 用它加载 `intent_help.md`（切成 `press` / `push_goal` / `inspect` 三段）。

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

### 2.3 `REPEAT_HINT: str`

```python
REPEAT_HINT = load("repeat_hint").text
```

来源是 `repeat_hint.md`，**直接取 `.text`，不调用 `.render()`**——即这份内容里没有需要按调用方参数动态填充的占位符，是一段固定文字。

**投放方式**：不是写进 `decide_action.md` 模板本身，而是通过 `ActionSpace.note` 字段随动作空间一起下发给大脑。设计理由：这段说明属于**动作接口的一部分**而不是 prompt 文字的一部分——模型能不能用 `times` 参数连按，取决于工具层（`game_tools.py` / `ActionSpace`）认不认这个字段，和 prompt 怎么描述无关；如果工具层某次没有开放 `times`，这段说明也应当同步消失，而不是写死在模板里继续误导模型去用一个用不了的字段。

另有实现细节：必须放进 `ActionSpace.note`，而不是 `descriptions`——因为渲染 prompt 时只遍历 `space.names` 去渲染各按键的 `descriptions`，塞进 `descriptions` 字典里但没有对应键名的额外条目永远不会被渲染进最终 prompt，等于白写。

内容设计理由（docstring 详述）：实测发现模型已经在推理里把正确路径算出来了（例如 `(4,4)→left→(3,4)→left→(2,4)→down→(2,5)`），却仍然只执行第一步。原因不是不会用 `times`，而是"没有使用它的理由"——只说"可以连按"是一句许可，许可本身不会改变行为。所以 `repeat_hint.md` 给出三样东西：**代价**（每一步都要额外花一次感知调用）、**规则**（把路径开头方向相同的一段合并成一次 `times`）、**例子**（`left, left, down` → 选 `left` 且 `times=2`）。其中例子被认为最关键，因为它把抽象规则落在了模型自己刚刚推理出的那种路径形式上。同时也明确写了"什么时候不该连按"（目标格是未知的 `?`，或预期中途会触发对话/遭遇战），避免在一处收紧行为的同时在另一处过度放开。

---

## 三、`brain_hints.py`：决策 prompt 用的 intent 说明与重试提示

模块 docstring 定位与 `game_hints.py` 一致：内容都在 `.md` 里，本文件只做**组装**——`INTENT_HELP` 需要按 `Intent`（来自 `schemas.action`）分类，`retry_note()` 需要在渲染结果前面拼接两个换行符，这两件"怎么拼接"的逻辑不该留在 `brain/brain.py` 里，因为那个模块该管"怎么做决策"，不该同时管"这段说明文字怎么拼出来"。

### 3.1 `INTENT_HELP: dict[Intent, str]`

```python
_INTENT_SECTIONS = load_sections("intent_help")
INTENT_HELP = {
    Intent.PRESS: _INTENT_SECTIONS["press"],
    Intent.PUSH_GOAL: _INTENT_SECTIONS["push_goal"],
    Intent.INSPECT: _INTENT_SECTIONS["inspect"],
}
```

来源是 `intent_help.md`，按 `##` 切成 `press` / `push_goal` / `inspect` 三段，分别对应大脑一轮决策可选的三类 intent。

设计理由：和 `BUTTON_HELP` 一样，这是**接口的一部分**而不是 prompt 模板固定写死的一部分——大脑这一轮能做哪几类事由 `ActionSpace.intents` 在运行时决定，说明文字必须跟着实际下发的那几类走。如果直接写死在 `decide_action.md` 模板里，一旦某种场景下屏蔽掉了一类 intent，说明文字却还在，模型就会去选一个实际用不了的选项。

`decide_action.md` 里用法：`"\n".join(f"- \`{i.value}\`：{INTENT_HELP[i]}" for i in space.intents)`，即只渲染当前 `ActionSpace` 实际开放的那几类 intent 的说明，动态拼进 `$intents` 占位符。

内容要点（`press` 一段特意点出）："这是唯一会改变世界的一类，也是唯一不可逆的"——`push_goal` 和 `inspect` 选错了只是浪费一轮调用，但 `press` 按错键可能需要玩家/模型再走十步才能纠正回来。三种 intent 代价不对称，所以说明里要让模型明确知道这一点。

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

### 4.2 `inspect_focus.md` —— 细看：对同一帧回答一个具体问题

**用途**：当大脑选择 `intent: inspect` 时使用，让视觉模型针对**同一帧画面**回答一个具体、狭窄的问题（游戏不推进）。

**占位符**：`$focus`（要回答的具体问题）、`$known_map`（同一张 100% 准确的地形图）、`$legend`（地形图例文字）。

**内容结构概要**：
- 说明模型已经"掌握"的信息：一张 10 列 × 9 行、来自模拟器内存的地图，地形/门/招牌/人的位置不需要模型判断。
- 提醒图上的全局坐标 `y=..` 和画面上叠的红色网格坐标（`0`-`9`）不是同一套，需要按第一行给出的 x/y 范围换算；**换算不出来就直接说看不出来**，不要硬凑。
- "怎么回答"：只回答问的那一件事，用一两句话；看得出来就具体描述（颜色/形状/文字/相对位置）；看不出来就直说看不出来；如果视觉观感和地图矛盾，以地图为准，但要说明视觉上看到的样子（给了一个门/装饰冲突的例子）。
- **明确禁止**：不要输出 JSON，不要分点，不要复述问题——这是一段纯自由文本回答，和其他几个模板（要求 JSON 输出）形成对照。

### 4.3 `decide_action.md` —— 决策：大脑的 ReAct 主 prompt

**用途**：大脑每一轮做决策时使用的核心 prompt，要求模型按 ReAct 方式推理并输出下一步动作。是整个系统里占位符最多、结构最复杂的模板。

**占位符**：`$goals`（目标栈渲染结果，栈顶在最上）、`$summary`（当前状态摘要）、`$facts`（已知事实列表）、`$memories`（相关记忆）、`$intents`（当前开放的 intent 说明，来自 `INTENT_HELP` 按 `space.intents` 动态拼出）、`$actions`（可用按键列表及说明，来自 `space.names`/`space.descriptions`，若 `space.note` 存在则追加在后面）、`$max_rationale`（`rationale` 字段最多允许几条论据）。

**内容结构概要**：
- 目标栈规则：只需要完成栈顶那一条，完成后自动出栈。
- 三类可选 intent（`press`/`push_goal`/`inspect`）的说明由 `$intents` 动态填入。
- 可用按键列表由 `$actions` 动态填入，仅当 `intent=press` 时可选。
- 输出格式：只输出一个 JSON 对象；根据 `intent` 决定填哪些字段，给出三种 intent 各自的完整 JSON 示例（`press` 带 `action`/`args.times`；`push_goal` 带 `goal`/`criteria`；`inspect` 带 `focus`）。
- "各字段的要求"逐项细化：
  - `thought`：仅用于记录，不进入后续决策。
  - `rationale`：1 到 `$max_rationale` 条，要求写成"以后还能验证真假"的具体依据（例如"地上有药水而我手上没有"），而不是主观判断（"我觉得这样比较好"）；因为这些内容会被存入记忆，未来在相似状态下被检索复用。
  - `args.times`（仅 `press`）：连按次数 1-8，**intent 为 press 时该字段必须出现**，默认 `"1"`；只有"沿直线走几格"是正当用法；`a` 键永远只能是 1（会被强制夹到 1），因为对话是逐句出现的，连按会吞掉中间的关键文字。
  - `goal`（`push_goal`）：必须是"里程碑"而不是"路径点"——达成时画面要明显不同（进门/对话/换图），"往右走两格"不算子目标，直接按键即可；拆子目标本身有成本，它会一直挂在栈上，每一步都要为它多花一次判定调用。
  - `criteria`（`push_goal`）：必须**只看一帧画面**就能判真假；判定的人看不到 `thought`/`rationale`，也**看不到 `walk_map` 和 `landmarks`**，只能拿到 `where`/`map_id`/`scene`/对话框文字/`overview`；位置一律写成 `x=.. y=..`，不要写 `(6,4)` 括号对，也不要提 `walk_map`。
  - `focus`（`inspect`）：必须是一个具体新问题，不能是笼统的"再看看"。

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

### 4.6 `intent_help.md` —— intent 说明素材（按 intent 分类）

**用途**：被 `brain_hints.py` 用 `load_sections` 解析为 `INTENT_HELP` 字典，供 `decide_action.md` 的 `$intents` 段动态拼接。

**占位符**：无（纯静态文本，按 `##` 一层结构组织）。

**结构**：三个 `##` 段：
- `press`：唯一会推动游戏世界、也是唯一不可逆的一类操作。
- `push_goal`：把栈顶目标拆出一个更近、更容易验证的子目标，必须同时给出判据；强调子目标是"里程碑不是路径点"，位置写法要求（`x=.. y=..`，不要括号对、不要行列描述、不要提 `walk_map`）；并给出一条具体指引——遇到 `known_objects` 里还没互动过的门/招牌/人时，先拆一个"够到它"的子目标，具体按哪个键、试哪个朝向不用现猜（那部分已经在 `known_objects` 的"试过/还剩几种"记录里算好了）。
- `inspect`：对同一帧再问一个具体问题，游戏不推进；强调问题必须是新的，问"再看看"得不到新内容、只会白花一轮。

（与 4.3 节中 `decide_action.md` 输出示例的三种 intent 一一对应。）

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

### 4.8 `repeat_hint.md` —— 连按（times）用法说明素材

**用途**：被 `game_hints.py` 加载为 `REPEAT_HINT`（不经过 `.render()`，直接用 `.text`），随 `ActionSpace.note` 下发，说明如何合理使用 `args.times` 参数连续按同一个键。

**占位符**：无（固定文本）。

**内容结构概要**：说明 `times` 最大为 8；强调每一步都要花一次感知调用的代价，把一条直线拆成多步走等于把同一段路的成本成倍放大，还看不到任何新信息；给出规则——先在 `walk_map` 上把路径规划到转弯处，把开头同方向的一段合并成一次 `times`；给出两个具体例子（`left, left, down` → 选 `left` 且 `times=2`；`up, right` → `times=1`）；`N` 的取值方法是直接在 `walk_map` 上沿该方向数连续的 `.`，数到 `#`、`?` 或要转弯处为止；给出唯一该主动放弃连按的情形：目标格是 `?`，或预期中途会触发对话/遭遇战。

### 4.9 `retry_note.md` —— 重试时追加的纠正块素材

**用途**：被 `brain_hints.py` 的 `retry_note()` 函数渲染，在大脑一次输出不合法时追加在原 prompt 末尾，构成第二/第三次重试请求。

**占位符**：`$attempt`（第几次尝试）、`$reason`（不合法的原因）、`$raw`（上一次模型的原始输出）。

**内容结构概要**：以 `---` 分隔线开头（配合 `retry_note()` 在拼接前加的两个换行，形成与上文原 prompt 的视觉分隔）；指出这是第 `$attempt` 次尝试、原因是 `$reason`、并把上次的原始输出 `$raw` 贴出来；要求"别再输出同样的东西"，只输出一个 JSON 对象；针对一种常见失败原因（"不在 action space 里"）给出具体指导——这一帧当前只有"可用按键"里列出的那几个键能按，通常是因为画面被对话框/选择框挡住了，模型原本的目标本身没有错，只是这一帧推不动，应先按可用键里能清除阻挡的那个键，目标继续留在栈上，等画面恢复后再继续做。

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

### 5.2 细看阶段 —— `inspect_focus.md` 被 inspect 流程使用

`pyboy_world.py` 第 382-383 行左右（`inspect()` 方法内）：

```python
terrain = read_terrain(self._pyboy.memory)
prompt = self._inspect_prompt.render(
    focus=focus, known_map=terrain.render(), legend=terrain_legend()
)
r = self._vision.describe(png, prompt)
```

触发路径：大脑在 `decide_action.md` 的响应里选择 `intent: inspect` 并给出 `focus` 文字后，`brain.py`/上层调度会调用 `world.inspect(focus)`，这里再一次读取当前地形（保证和大脑看到的是同一帧的数据），把 `focus`、`known_map`、`legend` 三者填入 `inspect_focus` 模板，连同当前截图一起发给视觉模型，得到的自由文本回答会作为这一轮"细看"的结果返回给大脑（不产生新的动作，游戏不推进）。

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
    intents="\n".join(f"- `{i.value}`：{INTENT_HELP[i]}" for i in space.intents),
    summary=obs.summary,
    facts=facts,
    memories=recalled,
    actions=actions,
    max_rationale=MAX_RATIONALE,
)
```

- `goals` 由 `_render_goals()` 把目标栈倒序渲染成文本（栈顶显示在最上面，因为模型是从上往下读 prompt 的）。
- `intents` 只遍历当前 `space.intents`（实际开放的 intent 集合），从 `INTENT_HELP`（来自 `intent_help.md`）里取对应说明拼接——这就是为什么 `INTENT_HELP` 要按 `Intent` 枚举做成 dict：只渲染当前实际可选的那几类。
- `actions` 遍历 `space.names`，从 `space.descriptions` 取每个按键的说明；若 `space.note` 非空（即 `REPEAT_HINT` 等按键接口层面的补充说明），追加在末尾。这里的 `descriptions` 具体内容来源于 `BUTTON_HELP`（按当前 `Overlay` 索引出的按键说明字典），由更上层的调用逻辑（`tools/game_tools.py` 的 `get_action_space`）构造 `ActionSpace` 时填入。
- 渲染出的完整 prompt 连同截图（或不带截图，取决于 `decide_action` 是否需要视觉输入——从模板内容本身看它只依赖文本占位符）交给决策模型，模型按 `decide_action.md` 里的输出格式约定返回 JSON（`intent`/`action`/`args`/`goal`/`criteria`/`focus` 等字段视 `intent` 而定）。
- 重试：若这次响应解析失败或不满足契约（如选了 action space 之外的键），调用方会调用 `brain_hints.retry_note(attempt, reason, raw)`，把结果追加在**同一份原 prompt 之后**再次请求，直到成功或达到重试上限。

### 5.4 判定阶段 —— `judge_success.md` 被 `brain.py` 的判定逻辑使用

`brain.py` 约 270-300 行（`judge`/`Verdict.call` 相关逻辑）：

```python
rendered = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items() if k not in JUDGE_BLIND) or obs.summary
past = "\n\n".join(m.render(reason=False) for m in history)
prompt = self._judge_prompt.render(
    goal=goal.goal, criteria=goal.criteria, observation=rendered,
    history=past or "（这是第一步，之前什么都没发生）",
)
completion = self._judge_llm.complete(prompt)
```

- `JUDGE_BLIND` 用于从 `obs.facts` 中过滤掉判定器不应看到的字段（对应 `judge_success.md` 里"你手里没有地图，这是故意的"一节所述——`walk_map`/`landmarks` 不应出现在 `$observation` 里）。
- `history` 由多条历史记录（各自 `render(reason=False)`，即渲染时不带模型的推理/理由，只保留发生过的事实）拼接而成，若是第一步则给出固定占位说明文字，填入 `$history`。
- `goal`/`criteria` 直接来自当前要判定的目标对象。
- 渲染整个过程被包在 `try/except` 里——因为 `render()` 用的是 `Template.substitute`，模板占位符和调用参数一旦不匹配会抛 `KeyError`，而"判定器永不抛异常"是这个方法对外的契约（因为判定是并发执行的，一个 worker 抛出未捕获异常会破坏整个循环）；渲染失败时会被当作一次"判定失败"事件正常降级处理并记入 `Verdict`（`done=False`），而不是让异常向上传播丢失整局数据。
- 渲染成功后调用判定模型 `self._judge_llm.complete(prompt)`，返回结果按 `judge_success.md` 要求的 `{"done": bool, "why": str}` 格式解析成 `Verdict`。

### 5.5 小结：一次完整回合中模板的先后关系

1. **感知**：`perceive_screen.md`（+模拟器内存地形）→ 结构化 `facts`。
2. **决策**：`decide_action.md`（+ `BUTTON_HELP`/`INTENT_HELP`/`REPEAT_HINT`/`MAP_HINT` 等组装出的 `$actions`/`$intents`/`$facts` 等）→ 模型输出 `intent`。
   - 若 `intent=press`：直接执行按键，进入下一帧感知。
   - 若 `intent=push_goal`：压入新目标，下一轮从该目标开始决策，同时该目标后续每帧都会被判定阶段检查。
   - 若 `intent=inspect`：调用 `inspect_focus.md`（同一帧，游戏不动），把回答返回给大脑作为下一轮决策的参考。
3. **判定**：每当有目标在栈上，`judge_success.md` 独立判断该目标是否已经完成（不依赖决策阶段的推理过程，只看事实证据）；判定为 `done=true` 时目标出栈。
4. **重试**：决策或判定阶段任一次输出不合法，追加 `retry_note.md` 内容在原 prompt 末尾重新请求，同一 prompt 前缀保持不变以复用缓存。

所有渲染动作最终都经过 `PromptTemplate.render()`（即 `string.Template.substitute()`），因此修改任一 `.md` 模板文件时必须同步核对：新增/删除的 `$xxx` 占位符是否和上述各调用点传入的关键字参数集合完全一致，否则会在运行期直接抛出异常（决策/判定阶段有各自的重试或降级机制兜底，但异常本身仍会被记录为一次失败，不会被吞掉）。
