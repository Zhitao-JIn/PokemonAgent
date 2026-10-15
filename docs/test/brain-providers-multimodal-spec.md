# brain/providers 第二步（多模态发图、静默丢图检测、网格拼图）测试 spec

状态：已确认（2026-10-15）。上位文档：`docs/test/brain-test-intent.md` 第 9 节；第一步见 `docs/test/brain-providers-http-spec.md`（已落地，提交 `d4391c5`）。
探针基线：`84fd4a4` 的干净导出（生产代码与 `d4391c5` 相同）。

## 被测对象

`pokemon_agent/brain/providers.py` 中带图的那一半，只通过**公开面**：
- 三个厂商类的 `describe(VisionDescribeReq, *, timeout_s=None) -> VisionDescribeResp`；
- 构造参数 `token_floor`（`QwenProvider` / `ArkProvider` / `DeepSeekProvider` 都有）；
- 模块级公开函数 `image_grid_dims(n)`、`pack_images_grid(images)`，常量 `IMAGE_TOKEN_FLOOR`（从 `pokemon_agent.brain.providers` 导入；它们没有从 `brain` 包根导出，不要去改出口）；
- `ImageNotDelivered`（`pokemon_agent.brain.errors`）的公开属性 `input_tokens`、`floor`。
不碰：`_send_multimodal`、`_prepare_images`、`_png_bytes`、`_dump`、`_floor`、`_dump_seq` 等带下划线的东西。

## 怎么观察

- 沿用第一步的共享替身 `tests/_doubles/http.py`（`FakeUrlopen`、`ok_body`）。`ok_body(prompt_tokens=…)` 控制「服务端报回来的输入 token 数」，这是静默丢图检测的唯一输入。
- 造帧：需要一个能按颜色、尺寸造**合法 PNG data URI**（`data:image/png;base64,…`）的小函数。先看 `tests/_doubles/` 里有没有现成的公开函数能做到；没有就新建 `tests/_doubles/frames.py`（一个函数 `solid_frame(color, size=(160, 144)) -> str`，用 PIL，不超过约 20 行）。
- 每个测试开头照第一步的做法清掉四个 key 环境变量再设需要的。
- 网格图的断言通过解码返回的 data URI 看像素（PIL），不要比对 base64 全文。

## 探针（真实代码，输入→实际输出，三家各跑过）

### 请求形状

| 输入 | 实际 |
|---|---|
| `describe(images=[f1], prompt="Q")`（三家） | 请求体 `messages[0].content` 为 `[{"type":"text","text":"Q"}, {"type":"image_url","image_url":{"url": f1}}]`——**文字块在最前，图在后**；图的 `url` 是帧字符串**原样透传** |
| Qwen / DeepSeek，3 张图 | 一个文字块 + 3 个 `image_url`，顺序与 `req.images` 一致，每个 `url` 原样等于对应的帧 |
| Qwen，帧不是 data URI（如 `"not-a-uri"`） | 不校验，原样透传（校验只发生在需要解码的地方） |
| Ark，1 张图 | 与另两家一致，原样透传 |
| Ark，3 张图（或 4 张） | **只有 1 个 `image_url`**，内容是网格图（不再等于任何一张原帧） |
| Ark，多张图里有非 data URI 的帧 | `AssertionError`，消息含 `帧不是 data URI 格式` |
| `describe(timeout_s=3.5)` | `urlopen` 收到 3.5；`timeout_s=0` → `ValueError`（消息 `timeout_s must be positive`），请求之前抛 |
| prompt 为空串 | `AssertionError`，消息含 `empty prompt`，替身调用次数 0 |
| `images=[]` | 在 `VisionDescribeReq` 构造时就 `ValidationError`（那是 schemas 目录的事，本步不测） |

### 响应映射

| 响应体 | 实际 |
|---|---|
| 完整 usage（`prompt_tokens=1000`、`completion_tokens=3`、`cached_tokens=4`、`reasoning_tokens=2`） | `VisionDescribeResp(text, input_tokens=1000, output_tokens=3, cached_tokens=4, reasoning_tokens=2)` |
| `finish_reason="length"` | **不暴露**：`VisionDescribeResp` 没有截断字段，`describe` 丢弃了它（见观察 O16） |
| `content` 为空串 / `None` / 纯空白 | `EmptyCompletion` |

### 静默丢图检测（floor）

判据：服务端报回的 `prompt_tokens < floor` → `ImageNotDelivered(input_tokens, floor)`；`floor = token_floor × 实际发出去的图片数`；`token_floor` 缺省 `IMAGE_TOKEN_FLOOR = 100`。

| 厂商 / 张数 | 报回 `prompt_tokens` | 实际 |
|---|---|---|
| Qwen，1 张 | 99 / 100 | 抛（`floor=100`）/ 通过 |
| Qwen，3 张 | 299 / 300 | 抛（`floor=300`）/ 通过 |
| Qwen，4 张 | 100 | 抛（`floor=400`；单张的门槛放过它，四张不放） |
| DeepSeek | 与 Qwen 相同 | 与 Qwen 相同 |
| Ark，4 张 | 99 / 100 | 抛（`floor=100`）/ 通过——**Ark 发出去的永远是 1 张图，门槛不随输入张数放大** |
| `token_floor=50` 的 Qwen，1 张，报回 50 | | 通过 |
| 抛出的异常 | | `input_tokens`、`floor` 属性等于上面的数；消息含 `silently dropped` |

### 网格拼图

| 输入 | 实际 |
|---|---|
| `image_grid_dims(n)`，n=1..7 | `(1,3)`、`(1,3)`、`(1,3)`、`(2,3)`、`(2,3)`、`(2,3)`、`(3,3)`——列数固定 3，行数 `ceil(n/3)`（n=0 返回 `(0,3)`，不钉） |
| `pack_images_grid([])` | `AssertionError`，消息含 `got no images` |
| `pack_images_grid([f])`（1 张） | 返回的就是 `f` 本身（同一字符串） |
| `pack_images_grid` 的帧不是 data URI | `AssertionError`，消息含 `帧不是 data URI 格式` |
| 4 张 160×144 | 返回 data URI（`data:image/png;base64,` 开头）；解码后 PNG 尺寸 **488×292**（`3×160 + 2×4` 宽，`2×144 + 4` 高）；行优先摆放：4 张纯色帧的中心像素依次落在 `(10,10)`、`(174,10)`、`(338,10)`、`(10,158)`；帧间隔是 4 像素黑线（如 `(161,10)`、`(10,145)` 是黑）；没有帧的空格子是黑色 |
| 2 张 / 3 张 160×144 | 尺寸都是 488×144（宽度永远按 3 列算，不足 3 张时右边留黑） |
| 7 张 160×144 | 488×440 |
| 尺寸各异的帧 | 画布按**第一张**的尺寸算，其余不缩放直接贴（见观察 O17，不钉） |

## 要钉的契约（测试清单）

文件 `tests/brain/providers/test_provider_describe.py`
1. 请求体：文字块在最前，其后是按 `req.images` 顺序排列的 `image_url` 块，`url` 原样透传（Qwen、DeepSeek 各用 1 张与 3 张，参数化）；请求落在 `base_url + /chat/completions`，带 Bearer（每家一条即可，细节第一步已钉）。
2. 响应映射：文本、`input_tokens`、`output_tokens`、`cached_tokens`、`reasoning_tokens` 四个数落到 `VisionDescribeResp`（三家参数化）。
3. 空 prompt 在发请求之前被拒（`AssertionError`），替身调用次数 0。
4. 空正文（空串、`None`、纯空白，参数化）→ `EmptyCompletion`。
5. `timeout_s` 只覆盖这一次（`urlopen` 收到它，下一次回到构造时的值）；`timeout_s` 为 0 → `ValueError` 且替身调用次数 0。
6. 失败分类与 `complete` 走同一条路：HTTP 401 → `ProviderRejected`、503 → `ToolTimeout`，各一条，且一次调用一个请求。
7. 思考开关：`describe` 不带 `thinking` 覆盖，请求体里的思考字段由构造时的 `thinking` 决定（构造时开则开、缺省则关；Qwen 一家一对即可）。

文件 `tests/brain/providers/test_provider_image_floor.py`
8. 门槛边界：Qwen 与 DeepSeek，1 张图报回 99 抛、100 过；3 张图 299 抛、300 过（参数化）。
9. 门槛随**实际发出的**图片数放大：Qwen 4 张图、报回 100 → 抛，且异常的 `floor` 为 400。
10. Ark 的门槛不随输入张数放大：4 张输入、报回 99 抛、100 过（`floor` 为 100）。
11. 自定义 `token_floor`：`token_floor=50` 时报回 50 通过、49 抛（Qwen 一条即可）。
12. `ImageNotDelivered` 携带 `input_tokens` 与 `floor`，消息含 `silently dropped`。
13. 缺省 `token_floor` 等于 `IMAGE_TOKEN_FLOOR`（用 1 张图、报回 `IMAGE_TOKEN_FLOOR - 1` 抛，来观察缺省，而不是读私有属性）。

文件 `tests/brain/providers/test_image_grid.py`
14. `image_grid_dims`：n=1..7 的行列数（参数化）。
15. `pack_images_grid`：空列表 `AssertionError`；单张原样返回；非 data URI 帧 `AssertionError`。
16. `pack_images_grid` 的版面：4 张 → 488×292；2、3 张 → 488×144；7 张 → 488×440；行优先顺序（像素颜色）；4 像素黑色分隔；空格子为黑；返回值是可解码的 PNG data URI。
17. Ark 的 `describe`：多张输入 → 请求体里**恰好 1 个** `image_url`，且它解码后尺寸等于 `pack_images_grid` 的结果尺寸；单张输入 → 原样透传。
18. Ark 多帧里有非 data URI 的帧 → `AssertionError`，且替身调用次数 0。
19. Qwen / DeepSeek 多张输入**不**拼网格：`image_url` 数量等于输入张数，`url` 原样（与契约 1 同源，这里只钉「不拼」）。

预期约 45–60 条（参数化展开后计）。

## 不测

- `VISION_DUMP_DIR` 落盘调试：环境变量在 import 时读取，测它要重载模块、会改动类对象的身份，收益太低；它是排查工具，出错被静默吞掉。
- 帧尺寸各异（O17）与 `describe` 丢弃截断标记（O16）：见下，只记录。
- `VisionDescribeReq` 的构造期校验（`images=[]`）：schemas 目录。
- 第一步已钉的内容（构造、思考字段形状、HTTP 分类细节、`provider_for`）。
- 私有方法与属性一律不碰。

## 已知观察（不写测试，由我与用户裁决；编号接第一步的 O13–O15）

- O16：`describe()` 解包时把截断标记丢弃（`_cut` 未使用）。视觉链路（judge/verify/summarize）里模型输出被 `max_tokens` 截断时，调用方无从得知，只会在后续解析时表现为 JSON 不完整。要不要在 `VisionDescribeResp` 上加 `truncated`，待定。
- O17：`pack_images_grid` 以第一张的尺寸定画布，其余帧不缩放直接贴；若帧尺寸不一致，较大的帧被裁掉、较小的留黑，不报错。当前所有帧都是 160×144，实际不会触发；待定要不要加断言。

## 测试风格

用法示范：Arrange / Act / Assert 以空行分段，句子式测试名；不用 `unittest.mock`；唯一替身是共享的 `FakeUrlopen`；没有 `__init__.py`。

## 破坏验证（必做，各一次，做完立即还原，每次确认 `git diff pokemon_agent/` 为空）

- (a) `_send_multimodal` 里 `floor = self._floor * len(images)` 改成 `floor = self._floor`：契约 8 的 3 张用例与契约 9 必须失败。
- (b) `image_grid_dims` 里 `cols = 3` 改成 `cols = 4`：契约 14、16 必须失败。
- (c) 把 `_send_multimodal` 里的内容顺序改成「图在前、文字在后」：契约 1 必须失败。
- (d) `ArkProvider._prepare_images` 改成 `return list(images)`（不拼网格）：契约 17 必须失败。
- (e) `pack_images_grid` 里 `sep = 4` 改成 `sep = 0`：契约 16 的尺寸与分隔线用例必须失败。
- (f) `describe` 里 `cached_tokens=n_cached` 改成 `cached_tokens=0`：契约 2 必须失败。

## 停止条件

- 实际行为与上面探针表不符；
- 需要改 `pokemon_agent/` 才能让测试通过；
- 需要 `unittest.mock` / `MagicMock`，或需要访问带下划线的私有属性才能观察；
- 站位不是 `tests/brain-unit` 的 `d4391c5` 或其后代。
