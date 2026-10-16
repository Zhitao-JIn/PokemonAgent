# brain 测试线观察台账（统一编号）

状态：2026-10-16 创建，裁决依据用户「按推荐」。本台账取代各 spec「已知观察」一节里的零散编号；各 spec 不改，凡与本台账冲突处以本台账为准。
编号规则：原编号保留；O7、O8 在不同 spec 里各被用过两次，这里加后缀区分（`-json`、`-reflect`、`-errors`）。

## 一、修（由「brain 观察修复」任务一次处理，每条配回归测试）

| 编号 | 来源 spec | 问题 | 裁决 |
|---|---|---|---|
| O1 | judge_verify | `verify` 里 `{"positive": "false"}`（字符串）被 `bool("false")` 判成正样本 | `positive` 存在但不是真正的布尔值 → 整份输出按 `ParseFailure` 处理；缺 `positive` 键仍按负样本（现行为不变） |
| O2 | judge_verify | `verdicts` 不是列表（如 `"xyz"`）时不抛，全部补成负样本 | 抛 `ParseFailure` |
| O3 | judge_verify | 重复 `index` 谁覆盖谁没写明 | 文档写明「后出现的覆盖先出现的」（现行为），并补一条测试钉住 |
| O9 | domain | `Task.max_steps` 描述写「> 0」，实际接受 0 与 -5 | 加 `gt=0` |
| O10 | domain | `ModelCall` 文档写「不可变值语义」，实际可赋值 | 改成 frozen（仅 brain 里的那一份） |
| O11 | domain | `Action` 的「恰好一种形状」用 assert，`-O` 下空 `Action()` 被放行 | 改成显式异常（`ValueError`，由 pydantic 包成 `ValidationError`），消息不变 |
| O14 | providers | HTTP 429 被归 `ProviderRejected`，重试循环立即放弃 | 归 `ToolTimeout`（与 5xx 一样值得在预算内重试）；其余 4xx 不变 |
| O15 | providers | 型号名为空、温度越界用 assert，但它们来自装配点配置 | 改成 `ValueError`，**只改异常类型，消息不变**；范围仅限配置值（见任务书），调用方前置条件（空 prompt、空 images）仍是 assert |
| O16 | providers 第二步 | `describe()` 丢弃截断标记 | `VisionDescribeResp` 加 `truncated: bool = False`，`describe()` 填入；world 里的副本不改 |
| O17 | providers 第二步 | `pack_images_grid` 帧尺寸不一致时静默裁剪 | 加 assert：所有帧尺寸一致（帧来自我们自己的 world，属于调用方前置条件） |
| O18 | providers 第二步 | `pack_images_grid` 单张输入绕过 data-URI 校验 | 单张也过同一校验 |
| 杂项 | factory 验收 | ruff 的 `I001`（`pokemon_agent/trace/langfuse_support.py:140`）取决于仓库根目录有没有未跟踪的 `langfuse/` 目录 | `pyproject.toml` 的 `[tool.ruff.lint.isort]` 加 `known-third-party = ["langfuse"]` |

## 二、不改，只留档

| 编号 | 来源 spec | 内容 | 裁决 |
|---|---|---|---|
| O4 | judge_verify | `quality_score` 传字符串 `"0.7"` 被 pydantic 悄悄转成数字 | 库行为，不测不改 |
| O5 | plan | `max_push` / `max_tasks` 不校验上限 | 设计取舍（调用方判断） |
| O6 | plan | `updates[].index` 越界原样交回 | 设计取舍，已测「原样交回」 |
| O7-json | json_utils | 起点是文本里第一个 `{` 或 `[`，前缀里有无关括号会失败 | 设计取舍；留意重试率 |
| O8-json | json_utils | 围栏标签 ```` ```jsonl ```` 会剩下 `l` | 无实际场景 |
| O7-reflect | reflect | `""` 被拒、`" "` 被收下 | 与 docstring 一致，不当缺陷 |
| O8-errors | errors | 包根 `pokemon_agent.brain` 不导出异常 | 未裁决：是否有意，等用户定 |
| 其他 | domain | `ScriptCall(args={"x": True})` 被存成整数 `1` | 库行为（联合类型的强转），不改 |
| O13 | factory / providers | 「`provider_for` 不校验温度」 | **已撤回**：基类构造里有 `assert 0.0 <= temperature <= 2.0`；O15 把它改成 `ValueError` |

## 三、单独立项

| 编号 | 来源 spec | 内容 |
|---|---|---|
| O12 | factory | `brain/vision_factory.py` 位于 brain 里，却依赖 `pokemon_agent.world`，与「brain 可整体拷走」冲突。要决定搬出 brain 还是改 docstring。属架构任务，不进本批修复。 |

## 四、被本批修复取代的已落地 spec 条目

修复落地后，以下已提交的 spec 描述的是「修复前」的行为，以本台账为准：
- `brain-providers-http-spec.md`：探针表与契约 13 里「HTTP 429 → `ProviderRejected`」（O14）；契约 1、2 与探针表里「构造期越界/空型号名 → `AssertionError`」（O15）；「不测」一节的 O14/O15 条目。
- `brain-factory-spec.md`、`brain-wiring-spec.md`：凡写「`AssertionError`」且对象是型号名或温度的地方（O15）。
- `brain-providers-multimodal-spec.md`：探针表「`finish_reason="length"` 不暴露」「帧尺寸各异」「单张绕过校验」三处，以及「已知观察」O16–O17（O16/O17/O18）。
- `brain-schemas-spec.md`：`VisionDescribeResp` 的字段集合与默认值多了 `truncated`（O16）。
- `brain-domain-spec.md`：O9–O11 三条的「待定」（已裁决）。
