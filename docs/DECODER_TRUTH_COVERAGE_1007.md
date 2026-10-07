# Decoder 全字段标注（2026-10-07）

当前口径：全量标注直接作为真值；reviewed及组/字段审核标记已删除，网页审阅意见不控制计分。以下旧审核说明保留为标注过程记录。
最新版本已按用户裁决重新标注全部1045帧，35帧修正，细则和前后值说明见
`docs/DECODER_RELABEL_1007.md`；下文是字段覆盖说明，不代表人工审核全部完成。

统一 1045 帧已逐帧补齐所有适用的 decoder 输出字段，不再只标代表帧或字段子集。
这是完整的独立参考标注，新增字段尚未由用户审核；覆盖率不等于准确率，也不等于审核完成。

| 输出组 | 对应真值 | 已标帧数 |
|---|---|---:|
| scene | scene、covered_by_script、at_start | 每个字段 1045 |
| screen | dialog_text、options、cursor、option_grid、cursor_cell、option_details、covered、has_cursor、quantity_box、strict_dialog、screen、in_battle、overlay | 每个字段 1045 |
| takeover | view（包含全部业务子字段） | 1045 |
| terrain | map_id、where、facing、walk_map、neighbors | 每个字段 1032 |

13 帧的冻结 RAM 尚未加载地图，decoder 的 terrain 输出为空对象，因此没有这五个适用字段。
普通场合的 view 明确标为 null；无光标、无选项、无对话等分别有空字符串、空列表或 null 期望。
这些表示内容不存在，区别于漏标。terrain 空组继续记 NOANSWER，不计入地形准确率分母。

## 接管视图的子字段

view 使用完整对象标注，评分会比较整个对象，包括列表次序、长度及每个成员的全部字段。
覆盖检查递归检查 schema 声明字段，不能靠 Pydantic 默认值替缺失标注补键。

| kind | 全部字段（包含 kind） |
|---|---|
| naming | kind、target、typed |
| shop_items | kind、items、money、bag |
| battle_menu | kind、mine、foe、trainer、party、bag |
| battle_switch | kind、party |
| bag | kind、bag、party |
| party | kind、party |
| pc | kind、items、bag、box、box_number、party |
| learn_move | kind、pokemon、new_move、moves |

items 的商店成员为 name/price，PC 道具与 bag 成员为 name/quantity；box 成员为 name/level。
mine、foe、party 成员为 name/level/hp/max_hp/status/active/moves，moves 成员为 name/pp。
对手 moves 明确为空，因为该输出契约不提供对手招式。

## 标注依据与边界

保留此前独立场合及文字标注，其余字段由独立参考程序读取原始冻结 WRAM、ROM 和固定名称表。
参考程序不导入 classify_scene/read_screen_text/takeover_view/read_terrain，也不读取 solver 产物。
先生成候选文件，再单独运行 decoder 诊断差异；诊断结果不反写真值。
整屏字符串使用参考字表及 HUD 图块格式；菜单排布依据物理行列，数量/价格附注限定在选项所在框中。

参考标注仍可能有与生产实现共有的地址或游戏规则理解错误。因此新增字段保持未审，
参考程序与字节证据用于复核，并不声称独立人工审核了每帧的每个值。
covered 按其屏幕切分契约标注，与 scene.covered_by_script 不是同一含义。

地形的 90 格参考依据当前 wTileMap、碰撞表、台阶、门牌及精灵表计算。
菜单盖住地图时，这里核对的是 decoder 所读取的当前图块缓冲投影，
不能把相符结果解释为遮挡下真实地图已恢复，更不能证明脚本执行成功。

两帧边界裁决也保留为待审标注：c-0419、c-0440 当前 RAM 中完整菜单文字和实心光标尚未形成，
按当前可观察缓冲标为 transition，covered_by_script=false、at_start=null。
不利用前后帧继承菜单所属。c-0440 的截图与 RAM 不同步，RAM 输出评分以冻结 RAM 为准。

p-option_screen 原先 options 包含所有设置框；现按“实心光标所在框”的契约修正为
FAST/MEDIUM/SLOW，其旧 options 审核资格撤回，其他未改的已审核键保留。
另将 p-shop_confirm、p-pc_withdrew 的 overlay 从 dialog 修正为 choice：
冻结图块中有数量框，即使没有实心光标也属于 choice；这两个旧 overlay 键的审核资格撤回。
三项修正前后值单列于 `existing_field_changes.json`，不修改旧 label 或视觉任务输入。

## 文件与检查

唯一真值文件：`evals/data/frames/truth.jsonl`。原始样本不改，预标 label 不作 decode 答案。

本地复核材料位于 `eval_results/labeling_1007/full_truth/`：

- `truth_before_full.jsonl`：扩标前备份。
- `raw_material.py`、`screen_reference.py`、`business.py`、`terrain_reference.py`、`annotate_all.py`：参考标注程序。
- `evidence.jsonl`：每帧原始字节、图块、地形格与 WRAM 哈希。
- `coverage.json`：逐字段数量、适用性、未决项、文件哈希与参考程序 import 清单。
- `decoder_disagreements.json`：定稿候选与被测输出的差异，72 帧至少一个字段不同，不能据此直接归因给 decoder。
- `existing_field_changes.json`：此前已标字段的三项修正及原审核状态。

运行 `python -m evals.data.frames.coverage` 可重新检查所有顶层字段和非空视图的嵌套字段。
本次结果：1045 行，未记账字段 0，未决字段 0；25 个已有相关测试通过，
`ruff check evals pokemon_agent tests` 与变更文件 format 检查通过。

## 审核与评分

reviewed_fields 只保留扩标前已经审核且值没有改变的键，新字段不连带获批。
去重后默认正式评分为 scene 8 帧、screen 53 帧、takeover 8 帧、terrain 2 帧的已审字段。
原接管组已审的 scene 和 screen_contains 移到场合与文字组；新增完整字段不连带获批。
接管组仅保留 view，旧点路径审核从完整对象按路径投影，不重复存储相同业务字段。
include_unreviewed 仅用于候选诊断，不把未审结果宣称为正式准确率。

组内所有已标键相等才是 C，任一个不同是 I，无标注组是 N；准确率为 C/(C+I)。
view=null 也要求实际输出存在 view 这个键，缺键不能冒充 null 获得通过分。
