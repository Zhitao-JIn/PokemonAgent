# intent —— 删除视觉感知档：全层统一用内存观测

> 流程位置：**intent.md（本文）** → spec.md → plan.md → PR → production
> 状态：**v2，已确认**（第五节各项已答复；下一步见 `remove-vision-spec.md`）
> 起草：2026-10-13
> 关联：`docs/perceive/spec.md`、`docs/perceive/plan.md`（视觉与机械解码的历史设计）、`docs/eval/eval-split-intent.md`（评测分类）
> 性质：**生产代码改动**，不是评测改动。评测侧只受牵连，不作为主体。

---

## 一、一句话意图

把"调视觉模型读屏"这一整档感知删掉：run 层和 episode 层每圈取帧，也改用 task 层已在用的**只读内存、不调模型**的观测，world 的 MCP 服务端不再有 prompt，也不再依赖视觉模型。

## 二、为什么做

1. **机械解码已经能替代读屏。** task 层早就只用内存观测（`perceive_task`：不调模型、不会失败）。`decode` 评测在 1045 个冻结帧、23 个字段上与独立真值全部一致，覆盖场合、对话文字、选项、光标、地形、选单视图。视觉读屏这条链路原本要解决的问题，大部分已经有了确定性的答案。
2. **同一件事现在有两套实现。** 取帧有两个入口：`perceive_task`（内存）和 `perceive_once`（视觉）。两条链路的观测内容、失败语义、账本各不相同，每改一处都要想两遍。
3. **视觉档带来额外的成本和脆弱性。**
   - 每圈一次模型调用，慢且贵；
   - 视觉输出不确定，同一画面可能读出不同的结果；
   - 重试耗尽后，run 层会让**整个 run 作废**（已知代价）；
   - 为此 world 里带着一份 prompt（`world/prompts/perceive_screen.md`）和一套 provider 接线，破坏了"world 是确定性的世界层"这条边界；
   - 配置里要维护一个 `vision_model`，评测里要单独维护一个 `episode_vision_read`。
4. **删除比继续维护两套更省。** 视觉档的价值只剩解码覆盖不到的画面；在不确定哪些画面覆盖不到之前，先盘点，再决定是否补解码器，比长期留着一条昂贵的兜底更干净。

## 三、做什么（范围）

**删除：**
- world 的 `perceive_once` 工具、视觉读屏的实现与 prompt、`VisionProvider` 协议及其错误类型；
- MCP 服务端的 `perceive_once` tool 与服务端启动参数里的视觉模型；
- 接线里的视觉 provider 工厂、`GameTools.perceive_with_retry` 及其重试与异常翻译；
- harness 里围绕视觉档的取帧入口、`sense_call` 账与对应的 `TraceKind`；
- 配置里的 `vision_model`；
- 评测里的 `episode_vision_read`（刚迁完的 B 类任务）及其注册、配置、测试。

**改动：**
- run 层、episode 层的 `sense` 节点改为取内存观测（与 task 层同一档），拆解与判定读到的是这一帧的内存解码结果；
- 相关的观测类型、渲染、账本字段按此收敛（具体见 spec）；
- 文档、测试同步。

## 四、不做什么

- **不动各节点把截图交给模型看的能力。** 决策、判定、验证等节点现在会把记忆里的前后帧作为图片发给文本或判定模型；这是模型的多模态输入，不是"视觉感知档"。删除视觉档时，brain 侧的 `describe()` 等图片通道不能被连带删掉（`JudgeProvider` 等借用了同一个协议名，spec 里要拆开）。
- **不改解码器本身。** 解码覆盖不到的画面，要补解码器是另一项工作，不在本次。
- **不改 task 层**，它本来就是内存观测。
- **不在本次重做 agent 评测的数据与口径。**

## 五、已确认的事项

1. **解码覆盖缺口：基本不存在**，唯一例外是视觉才写的 `overview`（整幅画面的一句话布局描述）。结论：直接删，不先补解码器；`overview` 随视觉档一起删（字段、校验、渲染条目），旧记忆里已存的 `overview` 保持可读。
2. **观测类型：** run/episode 的 `sense` 直接换成 `TaskObservation`。spec 已逐项核过依赖：`perceived`/`BLIND_NOTE`（会在每个 prompt 顶上多出"没做视觉感知"一行，须取消）、`Facts.scene`（知识检索用它判断"场景变了要重查"，内存档下它只有战斗/空，须换键）、状态类型标注（子类被声明为基类会丢字段，须改标注）。
3. **旧账兼容：** 保留 `TraceKind.sense_call` 枚举值与解析/渲染，只停止产出。
4. **端到端验证：** 删除前、后各跑一次 `agent_short_goal_run` 做对比；真实模型费用由你逐次确认。
5. **其他"vision"字样：** `agent_reviewer` 等处与本感知档无关（spec 里逐项核对并列出）；brain 的 `describe()` 图片通道保留。

## 六、影响面（初步）

| 层 | 内容 |
|---|---|
| world | `perceive_once`、`visual_perception`、`perceive_frame` 里的读屏部分、`prompts/perceive_screen.md`、`VisionProvider`、`PerceptionAttemptFailed` |
| MCP | 服务端 `perceive_once` tool、`world_server_cli` 的视觉模型参数、`WorldMcpTool.perceive_once` |
| 接线 | `brain/vision_factory.py`、`build.py` 里的视觉部分、`GameTools.perceive_with_retry`、`direct/prompts` 里对 `perceive_screen` 的说明 |
| harness | `sensing.perceive_once`、episode/run 的 `sense` 节点、感知账 |
| 账本 | `sense_call` 与相关 `TraceKind`、trace 解析与渲染 |
| 配置 | `evals/config.json` 与 `runconfig` 的 `vision_model`、各处 `--vision-model` 参数 |
| 评测 | 删 `episode_vision_read`；`registry` 由六项变五项；`agent_short_goal_run` 受牵连需重测 |
| 测试与文档 | 约六个本地测试文件，及 `docs/` 下约三十份提到视觉档的文档（历史文档只加标注） |

## 七、风险

- **解码覆盖不到的画面读不出来**（第五节第 1 点）；这是本次最大的未知。
- **拆解与判定的行为会变。** 它们读的是同一档观测的另一种文字化结果，端到端成功率可能升也可能降，需要实测。
- **图片通道被误删。** 视觉档与 brain 的多模态通道共用过协议名，拆分不当会误伤判定器、验证器。
- **旧 trace 无法渲染。** 若删掉 `TraceKind`，旧账读取会出错。
- **与进行中的工作冲突。** 同一批文件（如 `mcpclient/game_tools.py`）正被"掩码只由 world 给出"（CHANGELOG 442）改动，应先提交那一项再开始本项。

## 八、成功的样子

- world 的 MCP 服务端没有 prompt，也不依赖任何模型；
- 仓库里只剩一种取帧方式（内存观测），run、episode、task 三层一致；
- 配置里没有 `vision_model`，评测注册表五项，`episode_vision_read` 不再存在；
- 全量测试通过；`agent_short_goal_run` 在新观测下可跑完，并有前后对比的数字；
- 旧 trace 仍能读取。
