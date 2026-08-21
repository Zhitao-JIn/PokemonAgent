# Pokémon Agent —— Provider 层技术规格

本文档描述 `pokemon_agent` 中与模型供应商相关的四个文件：两个接口定义
（`interfaces/llm.py`、`interfaces/vision.py`）、一个具体实现
（`providers/dashscope.py`）、以及视觉预处理管线（`vision/preprocess.py`）。
内容严格按源码整理，不引入源码之外的推测；凡引用的设计动机均来自源码内的中文注释。

---

## 1. `interfaces/llm.py`：`LLMProvider` 与 `Completion`

### 1.1 模块存在的意义

文档字符串明确：**代码里任何地方都不许直连模型 SDK**（引用 `CLAUDE.md` 第六节的规定）。
当前唯一实现是 `providers.dashscope.QwenText`，换模型时只需改动"装配处"的一行代码，
不动调用方代码。

### 1.2 `Completion`（`pydantic.BaseModel`）

一次文本补全的结果。字段：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `text` | `str` | 必填 | 补全出的原始文本，可能是任意字符串（包括不合法 JSON）。 |
| `prompt_tokens` | `int` | `0` | 输入 token 数。 |
| `completion_tokens` | `int` | `0` | 输出 token 数。 |
| `truncated` | `bool` | `False` | 输出是否被 `max_tokens` 截断。 |

**为什么把 token 数放进返回值**：让成本统计能在调用点就地产生 trace，而不需要让
LLM 实现和成本模块相互认识对方。

**`truncated` 字段的设计理由（源码原文要点）**：
- 必须由 provider 给出，不能让调用方靠 `completion_tokens == 某个整数` 去猜——
  那是巧合，不是判据。
- 值得单开一个字段的原因：截断在下游表现为"JSON 少了个右括号"，与"模型不会写 JSON"
  长得一模一样，但**修法完全相反**——前者要调大 `max_tokens` 或让模型少说，
  后者要改 prompt 或上约束解码。如果混进同一类 `ParseFailure`，统计里就永远看不见这个区分。

### 1.3 `LLMProvider`（`Protocol`，`@runtime_checkable`）

"把 prompt 变成文本的东西"，故意做得很薄。

**方法**：

```python
def complete(self, prompt: str) -> Completion: ...
```

- 前置条件：`prompt` 非空。
- 后置条件：返回的 `text` 可能是任意字符串（包括不合法 JSON）——解析失败是预期内的
  运行时情况，由调用方处理，本方法不为格式负责。
- 失败语义：底层不可用时**必须抛异常**，不能返回空 `Completion`。
  "调不通"和"调通了但输出没用"必须能被调用方区分开。

**故意不放进这个接口的东西及原因**：

- **重试**：属于调用方的策略（大脑要按解析失败重试，并把重试次数计入 trace），
  不是 provider 的职责。
- **结构化输出 / 约束解码**：原型期用 "Pydantic 解析 + 重试" 代替；真正上约束解码时
  应当给接口**加一个新方法**，而不是改动 `complete` 现有方法的语义。
- **对话历史**：大脑是无状态的（项目铁律 1），历史由调用方每次组装完整后传入，
  `LLMProvider` 不持有任何会话状态。

---

## 2. `interfaces/vision.py`：`VisionProvider` 与 `VisionCompletion`

### 2.1 为什么视觉和文本要拆成两个 Protocol（不并入 `LLMProvider`）

源码给出四条理由，"任何一条单独都够"：

1. **大脑不该有看图的能力。** `Observation` 的 docstring 写死"原始画面不进这里"；
   若 `LLMProvider` 长出图片参数，大脑手里就多了一个不该有的口子。
2. **两条链路会选不同的模型。** 感知每一步都要调用、任务简单（在枚举内分类、
   按 schema 填字段），应选最便宜的档位；决策需要真正的推理。拆成两个 Port
   才能分别选型、分别换供应商。
3. **项目自己定过规矩。** `LLMProvider` 的 docstring 已写明"真上约束解码时应当加
   新方法而不是改语义"——加图片属于同类情况，而且分量更重。
4. **计费结构本身就是这么分的。** 决策走有资源包抵扣的文本模型，感知走带免费额度的
   廉价视觉模型。

`VisionProvider` 和 `LLMProvider` 一样做得很薄：只负责"图片进、文本出"。
**分类、schema 填充、类型判定都不在这里**——那些属于感知层的职责，换模型不应该
牵动它们。

### 2.2 `VisionCompletion`（`pydantic.BaseModel`）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `text` | `str` | 必填 | 视觉补全的原始文本。 |
| `input_tokens` | `int` | `0` | 输入 token 数。 |
| `output_tokens` | `int` | `0` | 输出 token 数。 |

**`input_tokens` 不是可选的记账信息，它是正确性的证据**：当网关静默丢弃图片时，
这个数会塌回纯文本的量级，因此可以据此判断图片是否真的被模型消费。详见下方
`describe()` 的契约说明。

### 2.3 `VisionProvider`（`Protocol`，`@runtime_checkable`）

"把「一张图 + 一段提示」变成文本。"

**方法**：

```python
def describe(self, image_png: bytes, prompt: str) -> VisionCompletion: ...
```

- 前置条件：`image_png` 非空、`prompt` 非空。
- 后置条件：返回的 `text` 可能是任意字符串（包括不合法 JSON）——解析是调用方的事，
  本方法不为格式负责，与 `LLMProvider.complete` 保持一致。
- 失败语义：底层不可用时抛异常，不返回空结果。

**⚠️ 实现方必须校验图片确实被消费了（核心契约）**：

源码中记录了一个实测到的真实故障模式——DashScope 的 **Anthropic 兼容端点**
会**接受**带图请求、**不报任何错**、返回一段读起来完全合理的描述，而图片根本没有
传到模型，描述内容是模型凭空编造的。

判据必须是 **token 数**而非回答内容：一张 2.4KB 的 PNG 真被处理时，输入 token
至少是几百的量级；而实测在静默丢图的情况下，输入 token 却只比纯文本多了提示词的
那十几个。

这被称为"最危险的一类失败"：不报错，只幻觉。如果不做校验，会得到一个"完全正常
工作"的 agent，但每一步观测都是假的，等到基线实验和 A/B 测试跑完才发现全部数据作废。

校验的具体形式由实现方决定（"token 下界"是最便宜的一种实现方式），但**一旦判定
图片未送达，必须抛出 `ImageNotDelivered`，绝不能静默继续**。

---

## 3. `providers/dashscope.py`：DashScope 实现

### 3.1 模块定位

**全项目只有这个文件直连模型服务**（同样引用 `CLAUDE.md` 第六节）。换供应商的方式是
新增一个同级文件，再改装配处一行，其余代码不动。

文件内含两个类，分别实现两个 Port，使用不同的模型——源码明确这是**计费结构决定的**，
不是设计洁癖：

| 类 | 实现的 Port | 默认模型 | 选型理由 |
|---|---|---|---|
| `QwenText` | `LLMProvider` | `qwen-plus` | 有资源包抵扣（非思考模式，输入 ≤128K） |
| `QwenVision` | `VisionProvider` | `qwen3-vl-plus` | flash 档读不出格子级的几何精度（详见 CHANGELOG，本文件未展开） |

**走 OpenAI 兼容端点，而非 Anthropic 兼容端点**：源码明确后者实测会"静默丢弃图片"
（即触发 `ImageNotDelivered` 所要防范的那类故障）。

**依赖策略**：只用标准库（`urllib`），不引入第三方 HTTP 依赖——理由是"两个 POST
而已，不值得为它加一个 requirement"。

### 3.2 `_DashScopeBase`：共用的鉴权与 POST 基类

#### 构造函数

```python
def __init__(
    self,
    model: str,
    *,
    temperature: float,
    max_tokens: int = 1024,
    base_url: str | None = None,
    timeout: int = 90,
    max_attempts: int = 3,
) -> None
```

参数说明：

- `model`：模型名，非空（断言）。
- `temperature`：**没有默认值，必须由子类显式给出**。源码原文：走服务端默认值
  等于把一个影响全部实验结果的变量交给别人管，而那个值是什么、会不会变，
  "你我都不知道"。范围断言 `0.0 <= temperature <= 2.0`。
- `max_tokens`：默认 `1024`（基类默认值，两个子类各自会覆盖）。
- `base_url`：优先取传入值，其次环境变量 `DASHSCOPE_BASE_URL`，最后回退到
  `_DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"`；末尾的
  `/` 会被去掉。
- `timeout`：单次请求超时秒数，默认 `90`。
- `max_attempts`：网络层重试次数上限，默认 `3`，断言 `>= 1`。

**鉴权 key 的读取**：从环境变量 `DASHSCOPE_API_KEY` 读取，取不到则退回
`ANTHROPIC_AUTH_TOKEN`；两者都没有则在构造函数中直接抛出 `RuntimeError`。
源码强调 key **只从环境变量读，任何情况下都不落盘、不进日志**。

#### `_post(content: list[dict] | str) -> dict`

向 `{base_url}/chat/completions` 发起一次 POST，请求体为：

```json
{
  "model": "...",
  "temperature": ...,
  "max_tokens": ...,
  "messages": [{"role": "user", "content": <content>}]
}
```

`content` 既可以是纯字符串（文本请求），也可以是一个 `list[dict]`
（图文混合请求，见 `QwenVision.describe`）。

**重试逻辑（本文件唯一具备重试机制的地方）**：

- **重试动机**：该端点在国内、用户在德国，跨境 TLS 偶发断连
  （`UNEXPECTED_EOF_WHILE_READING`）是常态，尤其是带图的大请求。不重试的话，
  一次网络抖动就会让整个 episode 崩掉，导致几小时的实验白跑。
- **只重试网络层错误，不重试 HTTP 错误**：
  - 捕获 `urllib.error.HTTPError`（4xx/5xx）时，**立即**抛出
    `RuntimeError(f"DashScope HTTP {e.code}: {body}")`，不重试。理由：
    4xx/5xx 是服务端的明确答复（型号不对、没权限、超限等），重试改变不了
    任何结果，只会把钱和时间烧两遍。错误体截取前 500 字符。
  - 捕获 `(urllib.error.URLError, TimeoutError, ConnectionError, OSError)`
    时视为网络层失败，按指数退避重试：`0.5 * 2 ** (attempt - 1)` 秒，
    即 0.5s、1s、2s……直到达到 `max_attempts`。
  - 重试次数耗尽后，抛出
    `RuntimeError(f"DashScope 网络层失败，{max_attempts} 次重试后放弃：{type}: {msg}")`。
- 这一区分直接服务于 `LLMProvider.complete` 的契约："调不通"必须和
  "调通了但输出没用"能被调用方区分开——HTTP 错误立即抛出正是这个契约的体现。

#### `config() -> dict[str, str]`

自报配置，用于写入 run manifest：`model`、`temperature`、`max_tokens`、`base_url`。
**不含 key**——源码强调 key 永远不进任何会被写出去的东西。理由：实验可复现的前提是
配置被记下来，而不是"当时应该是默认值吧"。

#### `_unpack(resp: dict) -> tuple[str, int, int, bool]`（静态方法）

将 DashScope 原始 JSON 响应解析为 `(text, prompt_tokens, completion_tokens, truncated)`：

- `text`：`resp["choices"][0]["message"]["content"]`（缺失则为空字符串）。
- `truncated`：判据是 `choices[0]["finish_reason"] == "length"`，**不用**
  `completion_tokens == max_tokens` 作判据。理由：后者是巧合（正好写满也可能是
  自然结束），前者是服务端给出的明确答复。
- `prompt_tokens` / `completion_tokens`：来自 `resp["usage"]`，缺失则为 0。

### 3.3 `QwenText`：`LLMProvider` 的实现（决策链路）

#### 构造函数

```python
def __init__(
    self,
    model: str = "qwen-plus",
    *,
    temperature: float = 0.7,
    max_tokens: int = 25600,
    **kw: object,
) -> None
```

**`temperature` 默认非零（0.7）的理由**：大脑（`ReActBrain.choose()`）的重试策略
以此为前提——解析失败后用**完全相同的 prompt** 再问一次；若温度为 0，第二次会得到
同样的坏输出，重试就成了纯浪费。源码强调 0.7 是"一个起点不是结论"——它会进
manifest，所以任何一批实验都说得清用的是多少。

**`max_tokens` 默认值 25600 的实测依据（源码原文要点）**：

- `Action.thought` 字段刻意不设上限，因为它的长度就是模型这一步"算力"的体现。
- 实测：`max_tokens=1024` 时出现过一次 `completion_tokens` 正好等于 1024 的
  `ParseFailure`——JSON 是被**切断**的，不是**写错**的。那次调用烧了 23 秒和
  一整笔 token，产出为零，而错误信息却指向"模型不会写 JSON"这个错误的方向。
- 3072 同样不够：实测单步 `thought` 达到过 2235 token，离上限只剩八百，
  而那还只是模型在"和自己的记忆吵架"的情况下——真正需要长推理的局面尚未出现。
- **这是上限不是预算**：只有模型自己想说这么多时才会花掉；判定那条链路
  （感知）每次只输出二三十个 token，抬高上限对它没有任何影响。真正控制成本的是
  `max_steps` 和 prompt 长度，不是这个数。
- 25600 不是结论，是"当前观测下的余量"，同样会进 manifest。
- **注意**：各家模型对 `max_tokens` 有自己的硬上限（`qwen-plus` 一档通常是
  8192），超过会被 API 直接拒绝——被拒时应通过 `--max-tokens` 调低，而不是
  改动这里的默认值。

#### `complete(self, prompt: str) -> Completion`

```python
assert prompt, "complete() got an empty prompt"
text, n_in, n_out, cut = self._unpack(self._post(prompt))
return Completion(text=text, prompt_tokens=n_in, completion_tokens=n_out, truncated=cut)
```

即：断言非空 → 以纯字符串形式 POST → `_unpack` 解析 → 直接映射进 `Completion`
的四个字段。不做任何格式校验（符合 `LLMProvider.complete` 契约）。

### 3.4 `QwenVision`：`VisionProvider` 的实现（感知链路）

#### 构造函数

```python
def __init__(
    self,
    model: str = "qwen3-vl-plus",
    *,
    temperature: float = 0.0,
    token_floor: int = IMAGE_TOKEN_FLOOR,   # = 100
    preprocess: tuple[ImageFilter, ...] = (),
    **kw: object,
) -> None
```

**`temperature` 钉死为 0 的理由**：感知是"抽取"不是"创作"。同一张图两次读出不同
结果是纯噪声，而这个噪声会污染全部下游数字——状态抽象准确率、state key 的稳定性、
"机制三"的 value 回填；后两者直接建立在"同一状态映射到同一 key"这个前提上，
读不稳这个前提就不成立了。源码指出，这正是把感知和决策拆成两个 Port 的又一条
理由：**两条链路对随机性的需求是相反的**。

**`preprocess` 参数（预处理器元组）**：

- 为什么以"注入"方式而非写死在类里：预处理和"问什么问题"是配对的关系
  （叠了网格之后才谈得上"第 3 行第 4 列那格"），这一对还要随实验多轮一起更换。
  注入的话，换预处理不需要碰这个类。
- 为什么放在 provider 层而不是 world 层：world 的职责是交出"这一帧的真实画面"，
  网格只是给模型看的辅助线，不属于画面本身。存证、replay、未来切换 CV 通道
  用的都应当是原图。
- 默认空元组：不传就是不改图，行为与预处理机制引入之前完全一致。

`IMAGE_TOKEN_FLOOR = 100`：模块级常量，作为 `token_floor` 的默认值。注释：
一张 160×144 的 GB 截图真被当图处理时，输入至少是这个量级；实测静默丢图时输入会
塌到 30 上下（相当于纯提示词的量），两者相差一个数量级，所以这个阈值取在哪都行，
不需要精调。

#### `config() -> dict[str, str]`

在基类 `config()` 的基础上，追加预处理链信息：

```python
cfg["preprocess"] = " -> ".join(
    f.config().get("filter", type(f).__name__) for f in self._preprocess
) or "none"
```

并逐个把每个过滤器的 `config()` 键值对以 `preprocess.{i}.{k}` 的形式展开写入。
**为什么必须补**：叠不叠网格会显著改变感知准确率，如果 manifest 里没有记录，
两批数字摆在一起就没人说得清差异是模型带来的还是网格带来的。

#### `describe(self, image_png: bytes, prompt: str) -> VisionCompletion`

```python
assert image_png, "describe() got an empty image"
assert prompt, "describe() got an empty prompt"

b64 = base64.b64encode(apply_all(image_png, self._preprocess)).decode()
text, n_in, n_out, _cut = self._unpack(self._post([
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    {"type": "text", "text": prompt},
]))

if n_in < self._floor:
    raise ImageNotDelivered(n_in, self._floor)

return VisionCompletion(text=text, input_tokens=n_in, output_tokens=n_out)
```

流程：

1. 断言 `image_png`、`prompt` 均非空。
2. 先用 `apply_all` 跑完预处理链（`self._preprocess`），再对结果做 base64 编码。
3. 以图文混合内容（`image_url` + `text` 两个 part）调用 `_post`。
4. 用 `_unpack` 解析响应，得到文本与输入/输出 token 数（`truncated` 字段本方法
   不使用，用 `_cut` 变量名丢弃）。
5. **关键校验**：若 `n_in < self._floor`（默认 100），抛出 `ImageNotDelivered(n_in, self._floor)`。
   源码原注："这一行是整个感知链路最重要的一行：没有它，丢图会表现为'一切正常'。"
   这正是对 `VisionProvider.describe` 契约中"实现方必须校验图片确实被消费了"这一
   要求的具体落实。
6. 校验通过后返回 `VisionCompletion(text=text, input_tokens=n_in, output_tokens=n_out)`。

---

## 4. `vision/preprocess.py`：图像预处理管线

### 4.1 模块定位与设计动机

"图像预处理插件——送进视觉模型之前，先把图片改一改。"

**为什么做成插件而不是写死在 provider 里**：预处理和"问什么问题"是一对——问
"north 是什么"时叠网格毫无意义，问"第 3 行第 4 列那格能不能走"时网格却是必需的。
这一对将来还要一起换好几轮。做成注入式插件后，换预处理不需要动 `QwenVision`，
也不需要动 world；并且它会进 manifest（见各自的 `config()`），因此任何一批数字都
说得清是在哪种预处理配置下跑出来的——源码强调"这一点比代码整洁重要得多：预处理换了
没记，前后两批准确率就没法比"。

### 4.2 契约

```
ImageFilter(png_bytes) -> png_bytes
```

进出都是 PNG 字节，**不是 PIL 对象**。理由：若传 PIL 对象，会让 provider 和 world
两层都被迫依赖 Pillow，而它们本来只是在传递"一张图"这件事。多做几次解码/编码的开销
（一张 160×144 的图，亚毫秒级）换掉一个跨三层的依赖，是划算的。

### 4.3 模块级常量

- `GB_SCREEN = (160, 144)`：Game Boy 屏幕尺寸。注释明确"写在这里是给断言用的，
  不是给缩放用的"。
- `METATILE = 16`：宝可梦野外地图一格的像素边长。Game Boy 硬件 tile 是 8×8，
  但红版野外地图的一格是 2×2 个硬件 tile，即 16×16；走一步 = 移动一格 = 画面
  平移 16 像素。网格要对齐的是这个尺度，不是 8。

### 4.4 `ImageFilter`（`Protocol`，`@runtime_checkable`）

方法：

```python
def __call__(self, png: bytes) -> bytes: ...
def config(self) -> dict[str, str]: ...
```

实现方必须满足的约束（源码原文）：

- **除自身实现细节外必须幂等**：同样的输入永远给出同样的输出（不允许有随机、
  不允许有时间依赖）。理由：感知链路的 temperature 已经钉死为 0，如果预处理再
  引入随机性，前面为消除噪声所做的努力就前功尽弃。
- `config()` 必须完整到"照着它能复现这次处理"，且不含任何密钥。

### 4.5 `GridOverlay`：叠加网格线的实现

在画面上叠加 16×16 的网格，并在**画面之外**的白边上标出行列号。

#### 构造函数

```python
def __init__(
    self,
    *,
    cell: int = METATILE,
    origin: tuple[int, int] = (0, 0),
    color: tuple[int, int, int] = (255, 0, 0),
    alpha: float = 0.45,
    margin: int = 14,
    labels: bool = True,
) -> None
```

参数：

| 参数 | 含义 |
|---|---|
| `cell` | 网格间距（像素），默认等于 `METATILE=16`。 |
| `origin` | 网格相对屏幕左上角的偏移 `(ox, oy)`。 |
| `color` | 网格线颜色，默认红色 `(255, 0, 0)`。 |
| `alpha` | 网格线透明度，`[0, 1]`。 |
| `margin` | 画面外白边宽度（像素），仅当 `labels=True` 时才实际生效为非零值。 |
| `labels` | 是否在白边上绘制行列号。 |

断言（前置条件）：

- `cell > 0`
- `0.0 <= alpha <= 1.0`
- `0 <= origin[0] < cell and 0 <= origin[1] < cell`（origin 必须落在一格之内）
- `not labels or margin >= 12`（若要画标签，`margin` 至少为 12；理由：小于这个
  数字放不下一个两位数标签，标签会被裁掉，属于"画了但没用"）

**关于标签放置位置的设计理由**：在不放大画面的前提下（用户决定：游戏像素保持
1:1），画面内没有任何地方能放下可辨认的数字——一个字符最少需要 6×11 像素，
而一格才 16×16，数字会盖掉半格内容，等于用一个假信息换一个标签。加白边不动
游戏像素一个点——源码强调"它不是放大，是加画框"。

**关于网格线为何采用半透明**：1 像素的实线会吃掉每格 1/16 的宽度，而障碍物
（栅栏、断崖边缘）恰恰是靠那几个边缘像素辨认的。按 `alpha` 与底下像素混合，
线看得见，底下内容也还在。`alpha` 之所以可调，是因为"线要多显眼"这件事只能靠
实测确定，它会进 manifest。

**关于 `origin` 的假设性质**：地图滚动时，格子边界不一定落在屏幕原点上。
`origin` 就是网格相对屏幕左上角的偏移。源码明确警告：**默认 `(0, 0)` 是一个
假设，不是事实**——要拿真实截图验证过才能当作结论；如果验不过，就应当把它做成
从画面上实测出来的量，而不是写死的常量。

#### `__call__(self, png: bytes) -> bytes`

- 前置条件：`png` 非空且能被解码。
- 处理流程：
  1. 将输入解码为 RGB 图像 `src`，尺寸 `(w, h)`。
  2. 新建一张 `(w+m, h+m)` 的白色画布 `canvas`（`m` 为 `margin`），把 `src`
     贴在偏移 `(m, m)` 处——即左边和上边各加一条白边。
  3. 根据 `origin` 与 `cell` 计算网格线的 x/y 坐标列表 `xs`、`ys`。
  4. 用 `_line_mask` 生成一张只在网格线像素处有非零值（`alpha*255`）的灰度蒙版，
     再用 `Image.composite` 把纯色网格线图层按该蒙版混合进画布。
     **为什么不直接用半透明画笔逐条线画**：那样交叉点会被混合两次、颜色明显更深，
     模型看到的就会是一张带规律性暗点的图——纯属自己制造的干扰信息。
  5. 若 `labels=True`，调用 `_draw_labels` 在白边上写行列号。
  6. 编码为 PNG bytes 返回。
- 后置条件：输出尺寸 = 原尺寸 + `margin`（左和上各加一条），**游戏像素本身不缩放**。

`_draw_labels`：列号写在上边框，行号写在左边框，均从 0 开始编号——源码强调
"和 prompt 里的说法必须一致"。使用 `ImageFont.load_default()` 默认字体。

`_line_mask(size, xs, ys, m, w, h, alpha)`：单独抽出的静态辅助函数，生成一张
灰度（`"L"`模式）蒙版，只在网格线所在像素填入 `alpha*255` 的灰度值，其余位置为 0。
之所以单独抽出，是因为"这是唯一会改动游戏像素的地方，值得能被单独看、单独测"。

#### `config(self) -> dict[str, str]`

```python
{
    "filter": "grid_overlay",
    "cell": str(self._cell),
    "origin": f"{ox},{oy}",
    "color": "r,g,b",
    "alpha": str(self._alpha),
    "margin": str(self._margin),
    "labels": str(self._labels),
}
```

源码强调：进 manifest 是必须的，"网格参数变了，感知准确率就不可比"，所以一个
字段都不能少。

### 4.6 `apply_all(png: bytes, filters: tuple[ImageFilter, ...]) -> bytes`

按顺序依次执行一串过滤器；空元组时原样返回输入。

```python
def apply_all(png: bytes, filters: tuple[ImageFilter, ...]) -> bytes:
    for f in filters:
        png = f(png)
        assert png, f"{type(f).__name__} returned an empty image"
    return png
```

每一步执行后断言输出非空。使用 `tuple` 而非 `set` 是有意为之——**顺序具有语义**
（"先叠网格再画标记 ≠ 反过来"）。

此函数被 `QwenVision.describe`（`providers/dashscope.py`）直接调用，
在图片被 base64 编码、发往 DashScope 之前，先对其应用整条预处理链。

---

## 5. 两个文件间的调用关系小结

```
QwenVision.describe(image_png, prompt)
    │
    ├─ apply_all(image_png, self._preprocess)   # vision/preprocess.py
    │      → 依次执行 tuple 中的 ImageFilter（例如 GridOverlay）
    │
    ├─ base64 编码 → 组装图文混合 content → self._post(content)
    │
    ├─ self._unpack(resp) → (text, n_in, n_out, _cut)
    │
    ├─ 若 n_in < self._floor(=100): raise ImageNotDelivered(n_in, self._floor)
    │
    └─ 返回 VisionCompletion(text=text, input_tokens=n_in, output_tokens=n_out)
```

对于集成新的模型供应商而言，需要实现的最小契约是：

1. 一个满足 `LLMProvider` Protocol 的类，其 `complete(prompt) -> Completion`
   在失败时抛异常、成功时如实回报 `truncated`；
2. 一个满足 `VisionProvider` Protocol 的类，其 `describe(image_png, prompt) -> VisionCompletion`
   必须自行校验图片确实被模型消费（不能仅凭"接口调用成功、无异常"来判定），
   校验失败时抛出 `ImageNotDelivered`；
3. 若要复用现有的 `ImageFilter` 预处理插件体系（如 `GridOverlay`），新 provider
   的构造函数应当同样接受一个 `preprocess: tuple[ImageFilter, ...]` 参数，
   并在 `describe` 内部于编码发送前调用 `apply_all`。
