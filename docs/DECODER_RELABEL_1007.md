# 全量重标结果（2026-10-07）

按用户最新裁决重新读取1045帧冻结RAM、ROM及固定名称表，覆盖scene、screen、takeover、terrain所有适用字段。
这次不是只给旧候选打补丁：场合、菜单文字与物理位置、业务视图和地形全部重新计算。
旧值只用于前后比较、保留未变字段的既有审核资格；decoder在候选定稿后才单独运行。
本次没有人工逐帧批准所有值，也没有调用模型。全量独立参考标注仍需用户复核。

## 最新标注规则

- 战斗队伍选择统一为battle_switch，不按HP区分主动换人与倒下换人；视图只有队伍。
- 命名键盘按冻结图块的固定物理格抄录，5行分别9、9、8、9、9项；最后的结束键记ED，框外lower case不算选项。
- 命名光标按实际实心箭头右侧的键定位，不从旧cursor或名字输入历史推断；保持价格/数量附注的输出契约，无附注的项为空字符串。
- 无箭头的完整商品框仍标商品、排布和价格；有遮挡时不补造完整列表，没有实心箭头时不猜光标。
- 战斗招式空位“-”独立占一行，重复“-”按各自物理位置记录，不能定位到第一次出现的同名文本。
- 子菜单只取实心箭头所在框，不能从背景列表取同名CANCEL；排布从上往下、从左往右。
- battle_menu初态须有完整四选项、无空心箭头，并且实心光标在FIGHT。PKMN/ITEM/RUN光标不是归一化后的入口。
- c-0002、c-0006、c-0007、c-0008、c-0015、c-0049保留用户明确裁决transition；其他场合从当前缓冲重新判断。
- 截图仅作辅助，不覆盖滞后的冻结RAM答案。c-0241空框仍为battle_menu、at_start=false，不把尚未画出的FIGHT光标补出来。

## 与上一版不同的35帧

| 数量 | 修正 |
|---:|---|
| 30 | 命名结束键¥改ED，删除框外lower case选项，排布修正为五行，整屏参考同步显示ED |
| 1 | c-0875：GUST、SAND-ATTACK、-、-四行，不把重复“-”并到上一行 |
| 1 | p-pc_deposit_sub：DEPOSIT、STATS、CANCEL按当前子菜单顺序，光标格修正为[0,0] |
| 3 | c-0242、p-battle_menu_pkmn、p-battle_menu_item的光标不在FIGHT，at_start改false |

其余1010帧的四组期望重新计算后未变；所有1045行更新标注来源及复核说明。
改变字段的旧审核资格撤回，未变的已审字段按原粒度保留，绝不连带批准新增或修订字段。
51帧用户意见保留，原始两份导出及历次快照归档，旧浏览器记录兼容迁移并撤回修订组通过。

## 复核材料与结果

真值：`evals/data/frames/truth.jsonl`。本地证据位于`eval_results/labeling_1007/full_truth/`：

- `relabel_all.py`、`menu_reference.py`、`scene_reference.py`：本次重标入口、独立菜单及场合规则。
- `raw_material.py`、`screen_reference.py`（只用字表渲染与对话抄录）、`business.py`、`terrain_reference.py`：字节、视图与地形参考。
- `relabel_evidence.jsonl`：1045帧WRAM指纹、屏幕图块及地形格证据。
- `relabel_changes.json`：35帧逐字段前后值；`truth_before_relabel_all.jsonl`保留旧快照。

结构检查：1045个唯一ID，所有适用字段无缺项；菜单选项/附注等长，排布展平与选项一致，
光标格对应实际选项，整屏非空参考保留18行。terrain在13帧未加载地图时不适用。
候选定稿后运行decoder，72帧仍存在差异，其中包括命名页语义与切分、战斗重绘和入口归一化。
这些差异没有反写成decoder答案，也不能据此宣布decoder已全部修好。
