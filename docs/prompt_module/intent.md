# intent —— prompt 模块：为 brain 集中拼装、版本化管理全部 prompt

> 流程位置：**intent.md**（已确认） → spec → plan → 落码
> 关联：`pokemon_agent/direct/prompts/`、`pokemon_agent/direct/brain_tool.py`、
> `pokemon_agent/schemas/memory/datastore/*.py`、`pokemon_agent/world/interface/domain/*.py`、
> `pokemon_agent/mcpclient/action_space.py`、`pokemon_agent/settings/`、`AGENTS.md` 第二/四/六节
> 本文只写最终意图；字段、函数、数值与实施顺序归 spec 与 `migration-order.md`。

---

## 一、一句话意图

新建一个只为 brain 服务的 **prompt 模块**：一个任务一个子模块，每个版本是「一个 md + 一个拼装函数 + 一份元数据」，由**注册表**唯一决定当前生效版本，**网关**是模块唯一的出口。所有给模型看的措辞，包括现在散落在记忆对象、world 对象和模块级常量里的，全部收进这个模块并随版本迭代。

## 二、为什么这样做（现状证据）

1. **措辞散在五处，改一句话要跳多个包。** 除了 `direct/prompts/`（15 份 md + 11 个装配 `.py`），还有：`schemas/memory` 里 13 处 `render` / `index_line` / `render_sequence`；`world` 里约 19 处 `render` / `signature` / `terrain_legend`；`mcpclient/action_space.py` 把 `BUTTON_HELP` / `MAP_HINT` / `REPEAT_HINT` 塞进 `ActionSpace`；reviewer 另有一份。
2. **world 在产出数据时就已经渲染成文字。** `task_perception.py` 把 `where`、`neighbors`、`walk_map`、`option_layout`、`option_details`、`my_*` / `foe_*`、`status`、`observation_notes` 直接填成字符串。措辞在数据里，prompt 的版本管不到它。`knowledge_query.py` 甚至把 `obs.status` 这句措辞拼进了知识检索的 query。
3. **没有版本标识。** 项目文档把 prompt 定义为「实验变量」，但 `ModelCall` 只存 prompt 全文，settings 里没有 prompt 配置；换了哪一版、哪一版跑的哪次调用，只能靠 git 考古。
4. **常量与导入期副作用。** `MAP_HINT`、`BUTTON_HELP`、`READ_SCREEN` 在模块导入时就被算好；`direct/prompts/__init__.py` 里 `append_human_note` 必须写在子模块 import 之前，只为躲循环 import。
5. **共用片段挂在最先写它的模块上。** `judge_success` 向 `decompose.py` 借 `task_table_lines`、向 `run_plan.py` 借 `goals_lines`；同一段「读屏幕」说明被两个模板共用，却没有独立归属。
6. **范例与数据格式耦合。** `decide_action.py` 里手写的读图范例必须照着 `TerrainMap.render()` 的格式写，两边在不同包、不同版本节奏，必然漂移。
7. **有冻结副本。** `evals/common/legacy_requests/` 下复制了一份 judge 的 prompt 装配与模板，目的只是固定旧行为；有了版本机制，这类副本不再需要。
8. **依赖方向不对。** `direct/prompts` 依赖 world、schemas、记忆数据形状与 brain 的 `Goal`；`harness` 还直接 import 它的 `object_render`。

## 三、目标形态

```
prompt/                         # 暂名；独立模块，pokemon_agent.* 依赖为零（仅标准库 + pydantic）
├── gateway                     # 唯一出口：render(task, params) -> RenderedPrompt
├── registry                    # 加载并校验注册表；task -> 当前版本
├── 注册表数据文件（默认随包）     # 纯数据；路径可由配置指向别处
└── <任务>/                      # 一个任务一个子模块
    ├── 入参契约                  # 任务级：该任务接受哪些字段（版本间不变）
    └── <版本>/
        ├── prompt.md            # 本版全部文本，片段在同一个 md 里分段
        ├── 拼装函数              # 把入参嵌进 md；选段、排版、组合
        └── 元数据                # 版本号、改动理由、内容 hash
```

- **最小单元** = 一个版本目录（一个 md、一个拼装函数、一份元数据）。
- **网关**返回 `RenderedPrompt`：文本，加上 `(任务, 版本, hash)`。`BrainTool` 把后三项写进每次尝试的 `ModelCall.payload`，因此每次模型调用都可追溯到具体版本；不改 `ModelCall` 模型。brain 方言那份 `ModelCall` 不动（brain 只收到字符串）。
- **注册表**是当前版本的唯一真源。路径写在 `AppConfig` 里，`build_real` 只递这个裸字段给 `BrainTool.build()`，由它造出网关；网关作为依赖注入，不做模块级单例。
- **不设 `version=` 参数。** 要固定历史版本（eval、replay），换一份注册表文件即可。

## 四、规则

1. **唯一出口。** 模块外不允许 import 任何具体任务或版本；只能经网关。机械守卫：静态扫描全仓 import。
2. **措辞全部归模块。** `BrainTool` 只把原始对象转成入参字段（目标、坐标、按键名、记忆各字段……），**不传任何已渲染的文字**。凡是「改措辞等于改 prompt」的渲染，一律在模块内完成。
3. **入参契约归任务、不归版本。** 每个任务声明自己的入参模型（Pydantic，允许与 world、memory 的同构形状各存一份，即既有的「冗余类对象」规则）。同一任务的各版本共享这份契约，因此换版本不需要改 `BrainTool`；要改契约等于改任务边界，走正常的代码改动。
4. **没有模块级字符串常量。** `MAP_HINT`、`BUTTON_HELP`、`REPEAT_HINT`、`READ_SCREEN` 这类全部消失：静态文本在 md 里，动态部分（图例、overlay 对应的按键说明）由拼装函数在渲染时选取和嵌入。
5. **措辞只在 md，函数只有逻辑；hash 覆盖版本目录。** 标签、前缀、提示句（如「当时看到：」「做了」「之后变成：」「位置」「四邻」）都写在 md 里，重复出现的行用 md 中带占位符的小段模板表达，函数负责循环、选段、去重、对齐，不含中文措辞。一个版本的 hash 覆盖 md 与拼装函数源文件（元数据中的 hash 字段除外），因为逻辑改动同样改变输出。网关加载时校验：注册版本存在、hash 一致、入参契约存在，不满足即启动失败，不兜底。
6. **共用片段是独立单元。** 「读屏幕」说明、人类插话、上一次判定行这类被多个任务共用的片段，各自是一个单元（md + 函数 + 元数据），由任务的拼装函数经网关组合，不再挂在某个任务名下。
7. **`decide_action` 一个 md。** 按键与脚本同时开放，原来的「仅脚本」分支作废；`button_help`（按 overlay 分三段）、`map_hint`、`repeat_hint`、`retry_note` 并入同一个 md 的分段，读图范例也搬进 md。
8. **第一版逐字复刻现状。** 迁移不改任何措辞；措辞调整在迁移完成后以新版本的形式单独做。

## 五、上游数据随之改动（意图的一部分）

**world：从渲染文本改为字段，渲染延后到使用点。**

| 字段 | 现状 | 改为 |
|---|---|---|
| `Facts.where` | `PlaceInWorld.render()` 文本 | 删除，用已有的 `Observation.place` |
| `Facts.neighbors` | 一行文本 | 结构化四邻（方向 → 地形字符） |
| `Facts.walk_map` | 带行号与行尾 x 范围的文本 | 地形格 `cells`，行号、行尾范围由模块按 `place` 算出 |
| `option_layout`、`option_details` | 动态字符串字段 | 结构化选项排布（网格、光标格、附注列表） |
| `my_*`、`foe_*` | 压成字符串（含 `当前/最大` HP） | 结构化 `BattleStatus` |
| `Observation.status` | world 拼的一句话 | 删除 |
| `observation_notes` | world 产出中文句子 | 结构化标志，措辞归模块 |
| `takeover` 及其 9 个视图类 | 已是结构化，另带 `render` | 保留结构，`render` 迁入模块 |

保留在 world 的有：`screen`（RAM 字符缓冲的解码结果，属于数据）、`TERRAIN_MEANING`（符号含义表，属于 world 知识；图例的排版迁入模块）、`landmarks` 等本来就结构化的字段。

**记忆对象：只剩字段。** `ActMemory` / `TaskMemory` / `EpisodeMemory` / `RunMemory` / `KnowledgeRecord` 的 `render`、`index_line`，以及 `render_sequence` 的去重渲染，全部迁入模块。检索走的是 `summary` / `markdown` 原始字段（已核实 `memory/recall.py`），不受影响。`ActMemory` 内的 world 快照副本同步改字段。

**动作空间：** `ActionSpace` 不再携带 `descriptions`（按键说明）、`note`（连按提示）、`map_note` 这类 prompt 文本；动作契约只保留结构。

**知识检索 query：** 不再拼 `obs.status`；由 `scene`、`overlay`、`map_id` 与目标拼成。检索行为会随之变化，属于有意的改动。

**harness：** 不再 import prompt 渲染；`known_objects` 这类原来在 harness 里渲染好的素材，改为传原始事件，由模块渲染。

**旧记忆：** `memory/` 下现有的旧记忆文件直接删除，不写任何兼容逻辑。

## 六、明确不做

- reviewer 的 prompt（`reviewer/seats/ai/prompts/system.md`）：本次不动，保持自管。
- 运行时热更新、按流量路由版本、A/B 分流：不做；版本由注册表静态决定。
- `version=` 调用参数：不做。
- 迁移期间的措辞优化：不做。
- world 的 RAM 解码（`screen_text.render_screen` 等把内存读成屏幕文字的逻辑）：不动，它是数据解码。
- `ActionEntry.description` 与 `ScriptParam.description`（world 在脚本定义处手写的说明文字）：留在 world 原地，随脚本定义维护，因为它描述的是脚本的真实行为；`decide_action` 只负责围绕它们的排版与分组措辞。

## 七、死代码清理（意图的一部分）

必须随改动同步清除，不留兼容壳：

- `direct/prompts/` 整个包（模板、装配函数、`load` / `load_nested_sections` / `append_human_note`）。
- `BUTTON_HELP`、`MAP_HINT`、`REPEAT_HINT`、`READ_SCREEN` 及 `ActionSpace` 上对应的文本字段。
- 记忆对象与 world 对象上的 `render` / `index_line` / `signature` / `render_sequence` / `render_neighbors` / `render_layout` / `render_details`，以及它们所服务的旧字符串字段。
- `evals/common/legacy_requests/` 中仅为冻结 prompt 行为而存在的副本。
- `test_facts_dual_copy_parity` 保证的是「两份渲染一致」，渲染统一后需改写其意图。

**范围判据**：只清「本次意图使之失效」与已核实的陈旧项；每项先查读方，读方清零才删；清理与引起它的那步同提交。历史记录（`CHANGELOG.md`、`changelog/`）不改。

## 八、验收（机械可验）

1. 模块外对 prompt 具体任务或版本的 import 为零，只存在对网关的 import。
2. 模块对 `pokemon_agent.*` 的依赖为零（AST 守卫，同 `check_world_self_contained.py` 的做法）。
3. 全仓无模块级 prompt 字符串常量：`MAP_HINT` / `BUTTON_HELP` / `REPEAT_HINT` / `READ_SCREEN` 零残留。
4. **对拍**：对同一批固化的真实输入，迁移后网关的输出与迁移前逐字节一致。
5. 每次模型调用的账（`ModelCall.payload`）带有 `(任务, 版本, hash)`；只改注册表文件即可切换版本，无需改代码。
6. world 返回值中不再有任何给模型看的措辞字段；记忆对象与 world 对象上无 `render` / `index_line`。
7. 注册表校验失败（版本缺失、hash 不符）时启动即抛，且有测试覆盖。
8. 全量测试与 ruff 通过。

## 九、需在 spec 阶段落实的前提

1. 逐任务的入参契约清单（九类调用加共用片段，含 `decide_action` 的重试那一段是否单列为任务）。
2. 元数据格式、hash 的计算规则与注册表格式。
3. 版本标识写进 `ModelCall.payload` 后，trace 内容往返与 Langfuse 映射是否受影响。
4. `ActionSpace` 瘦身对 MCP 契约、`docs/mcp/` 和 `test_world_mcp_contract.py` 的影响。
5. decode eval 真值数据集（`evals/dataset/` 中带 `where` / `walk_map` / `neighbors` 的约 26–29 个文件）如何迁移；`choose_review` 改读 `cells`；`agent_short_goal_run` 里读 `option_details` 的规则。
6. `trace/render.py` 对 `status` 的使用，以及 reviewer 为界面渲染 `index_line` 需要的自管实现。
7. 对拍样本的来源与固化方式。
8. 与并行分支的文件交集（尤其 world 线）与合并顺序。

## 十、已确认的决定

1. 共用片段是独立单元（第四节第 6 条）。
2. 标签措辞写在 md 里，函数只含逻辑（第四节第 5 条）。
3. 入参契约归任务、版本间不变（第四节第 3 条）。
4. 模块暂名并定位为顶层独立模块 `pokemon_agent/prompt/`（与将被删除的 `direct/prompts/` 区分开）。
5. 脚本与参数上由 world 手写的 `description` 留在 world 原地（第六节）。
6. 旧记忆直接删除，不写兼容逻辑（第五节）。
7. world 返回由渲染文本改为字段，渲染延后到使用点（第五节）。

## 十一、与既有设计的关系

- 延续既有铁律：prompt 是规则、入参是素材，同一东西不两处传；模块各自只暴露一个 Port，边界收裸字段；装配点只递裸字段，工厂住 tool 层。
- 与 reviewer 独立：reviewer 的 prompt 与渲染自管，本项目不依赖也不修改其实现；`reviewer/hub/context.py` 目前用记忆对象的 `index_line()` 给界面渲染，迁移时改为 reviewer 自己渲染。
- brain-scope 与统一配置已合入主线，本项目建立在其请求形状与 `AppConfig` 之上。
