# Prompt CP2：增量观测字段

world 的 TaskPerceived / MCP perceive_task 同时返回旧文本与新结构化数据。

| 位置 | 字段 | 语义 |
|---|---|---|
| facts | neighbor_cells | up / down / left / right 对应的地形字符 |
| facts | cells | TerrainMap 原始格子，未取得地图时为空列表 |
| facts | option_grid | 选项的行列排布 |
| facts | cursor_cell | 光标的零起点行列，未取得时为 null |
| facts | option_annotations | 按选项顺序排列的附注原文 |
| facts | battle_status | mine / foe 的名字、等级、当前及最大 HP、异常状态；非战斗为 null |
| facts | terrain_visible | 本帧旧投影是否显示 walk_map，避免有菜单时额外展开地图 |
| observation | observation_flags | no_text / incomplete_menu / missing_takeover / transition |

旧 where、neighbors、walk_map、option_layout、option_details、my_*、foe_*、status 与 observation_notes 均保留，旧渲染保持原样。ActMemory 中使用独立的同构快照；新字段默认空值，使已有记录仍可读取。

历史文本适配只存在于 tests/prompt/legacy_adapter.py。位置、地形、四邻、选项与战斗状态通过旧渲染器逐字段往返验证，不能逐字还原时显式拒绝。历史地图中心的 @ 作为可见标记保留，不推断被主角遮挡的地形。

为保留冻结历史请求的精确序列化形状，未显式赋值的增量 Facts 字段不写入旧请求；新 perceive_task 生产者显式填写全部新增字段。历史 TaskObservation 未携带增量字段时不额外写 observation_flags，读取时仍可按现有事实计算。旧 ActMemory 未提供 observation_flags 时也不增写。状态 schema 指纹因新增结构化字段变化，旧 checkpoint 的现有 schema 校验仍会拒绝不同指纹，未增加兼容绕过。
