# 场景decoder修复记录（2026-10-07）

## 评测边界

本次以1045帧冻结v2样本及重标真值为固定输入，不修改真值、RAM、截图或存档。
统计scene、overlay、dialog_text、options、option_grid、option_details、cursor、cursor_cell、
has_cursor、quantity_box、in_battle、strict_dialog、screen共13字段。
排除at_start、covered_by_script、covered、业务接管视图和地形；不将脚本表现混入解码正确率。
基线、阶段一、阶段二报告均保存输入SHA256，比较前核对两份输入相同。
用户确认全量标注就是本次真值；默认读取全部已标值。结果不是独立留出集上的泛化结论。

## 阶段一：按布局修复菜单（CHANGELOG 400）

普通菜单提取器假定光标右侧同一行就是选项，并用连续边框限定范围。
队伍列表的箭头在名字下一行，命名键盘有多个单图块键，设置是横向选项，图鉴列表没有普通边框；
这些布局违反假定。增加布局识别，再让普通框选提取器处理未匹配场景；不按样本ID分支。

| 场景 | 基线选项错误/有选项帧 | 基线光标错误/有光标帧 | 修复原因及方式 |
|---|---:|---:|---|
| naming | 30/30 | 11/30 | 按实际五行键位读取特殊符号及重复键，箭头坐标定位；ED只在键盘解释，不改金钱字表 |
| battle_switch | 10/11 | 10/11 | 以等级行及下一行HP标签识别队伍，箭头映射到上一行名字 |
| party | 6/7 | 6/7 | 共用队伍布局，不借昵称RAM变量补造屏上选项 |
| start_menu | 7/20 | 7/20 | 设置只取实心箭头所在行并按实际列切开；图鉴读取左侧列表，保留未见条目占位 |
| bag | 4/20 | 4/20 | 共用队伍目标选择布局，保留其他普通背包菜单提取 |
| battle_menu | 1/33 | 1/33 | 道具目标页读取队伍布局；不改它的场景及脚本能力 |

典型证据：c-0039原来将Q解成Q R、44键只解26项；c-0866队伍选项和光标原为空；
p-option_screen原来把MEDIUM SLOW合成一个选项；p-battle_use_on_which遗漏BULBASAUR目标。
修复后上述场景的选项和光标分歧均为零，其他统计字段没有新增失败。
option_details原58处错误主要是选项数不对导致空附注列表长度错误，不是58处价格读错。

阶段一整帧全对：976/1045 → 1034/1045；剩余11帧都为scene分歧。

## 阶段二：过场及无箭头战斗菜单（CHANGELOG 401）

- 6帧transition被判walk：旧逻辑只识别全0x7F白屏。加入无文字且地图碰撞表未载入的证据；
  对地图变量残留的开场画像，要求独立7×7画像布局及其余区域全空白，不能把普通地图黑边算过场。
  例：c-0002为全黑图块，c-0015只显示开场画像。
- 5帧battle_menu被判battle：旧逻辑需要实心或空心箭头。战斗状态下新增完整背包大框、
  招式框边界作为证据。c-0241空框、c-0252部分招式列表仍能识别为菜单；不补造未显示的光标与选项。

阶段二整帧全对：1034/1045 → 1045/1045；13字段没有分歧、没有回退。
阶段二完成时保留3帧at_start分歧，随后按用户要求在阶段三修复；排除统计不等于排除修复。

## 阶段三：初态判定与恢复路径（CHANGELOG 402）

c-0242、p-battle_menu_pkmn、p-battle_menu_item是完整战斗主菜单，但光标不在FIGHT。
at_start从任意主菜单光标收紧为完整四选项且光标在FIGHT，与此前独立真值一致。
同步修复reset_menu：已在主菜单时通过up/left归位，子菜单继续按B退回；不按A选择动作。
恢复走原ScriptRun的稳定等待和步骤记录，确保该判据可以被实际消费而不会仅按B耗尽预算。
加入3帧判定与RUN/PKMN/ITEM/FIGHT四种恢复起点回归；普通地图内存替身补齐碰撞表已载入值。
81个相关测试通过，1045帧四组全部适用真值诊断零分歧；13字段基线仍为1045/1045。
单独结果保存在eval_results/labeling_1007/decoder_stage3_start.json；统计范围不加入at_start等字段。

## 前后字段结果

| 字段 | 基线错误帧 | 修复后错误帧 |
|---|---:|---:|
| scene | 11 | 0 |
| options | 58 | 0 |
| option_grid | 58 | 0 |
| option_details | 58 | 0 |
| cursor | 39 | 0 |
| cursor_cell | 38 | 0 |
| screen | 30 | 0 |
| 其余6字段 | 0 | 0 |

有选项子集：111/169（65.68%）→169/169；有光标子集：128/167（76.65%）→167/167。
这是同一批用于定位问题的帧上的修复结果。规则依赖英文红版固定界面布局，未验证其他版本、
不同布局、未收录遮挡情况；本次也未新增模拟器执行验证，操作成功率仍不能由字段匹配率推出。

## 可复查产物与验证

### Inspect实跑（CHANGELOG 403）

通过inspect_ai.eval运行真实decode task、solver、scorer和metric，三种范围各1045样本，全部success且零sample error。
全部参考13字段：各1045/1045，整帧1045/1045；全部参考四组：scene/screen/takeover各1045/1045，terrain为1032/1032。
默认已审范围仍全部通过，但分母仅scene=7、screen=53、takeover=8、terrain=2；不能把默认运行的100%当全量审核覆盖率。
13个地图未加载帧的terrain为空，记N而不进入地形分母。新增缺标分母回归验证通过，原评测文件11个测试全部通过。
日志：eval_results/labeling_1007/inspect_decoder/*.eval；汇总：eval_results/labeling_1007/inspect_decoder_summary_1007.json。
上述403条三种审核范围为历史运行；404条后已删除审核过滤及include_unreviewed参数。
现在复跑通用基线：`python -m evals run decode -T baseline_only=true --log-dir eval_results/labeling_1007/inspect_decoder`。（2026-10-12 注：decode 将迁到 B 类，通用基线由 `python -m evals.single_state.decode` 的逐字段汇总取代，`baseline_only` 开关随之取消，见 `docs/eval/eval-split-spec.md`。）
完整诊断移除baseline_only参数，默认直接使用全部真值，均使用none模型。
删除reviewed、reviewed_groups、reviewed_fields只改变元数据，逐项验证全部期望值不变，51条用户审阅意见保留。
新默认运行日志位于eval_results/labeling_1007/inspect_decoder_no_reviewed，汇总为inspect_no_reviewed_summary.json。

- 原始基线：eval_results/labeling_1007/baseline_generic_1007.json。
- 阶段一：eval_results/labeling_1007/decoder_stage1_layouts.json。
- 阶段二：eval_results/labeling_1007/decoder_stage2_scenes.json。
- 最终复跑：eval_results/labeling_1007/decoder_final_1007.json。
- 报告包含逐字段失败ID、按场景分母、有内容子集、实际/期望差异及fixed/regressed列表。
- 重跑：python -m scripts.decoder_baseline --output <新的报告路径> --previous <前序报告路径>。（2026-10-12 注：该脚本将随 decode 迁移删除，逐字段统计由新入口取代，见 `docs/eval/eval-split-spec.md`。）
- 扩充现有测试的代表帧回归，覆盖名字与HP行错位、横向设置、道具目标、开场画像及无箭头菜单。
- 阶段二62个测试通过，阶段三扩大到81个读屏、脚本策略与执行、脚本流、动作、MCP和感知测试通过。
- 审阅页重新生成，完整四组诊断现为零分歧；原72帧差异归档保留。
- 不新增测试文件、不调用真实模型、不提交或推送。

## 2026-10-08 真值修补后复修

按用户批准的审计与补丁清单，713 条操作逐条核对后应用到 490 帧。原值备份与缺 before 的旧预检保留，补齐后通过的报告为 `eval_results/labeling_1007/patch_preflight_completed_1008.json`。没有重新标注、采集 WRAM 或调用真实模型。

修复顺序为 A/B/B2/D、C、E、F、H、I、J、K、L、M，逐项编号 409–418；真值修补为 408。地形使用隐藏位与地图格位，换图适用性共用 ROM 生成的静态 tileset 表；命名、空招式、末项 CANCEL、擦除动画、标题、能力页/空菜单、covered 和槽位/编号渲染按批准判据实现。生产换图帧省略地点与地形，保留当前截图和读数；完整规则见 world SPEC。

| 验收 | 真值修补后、decoder 修复前 | 修复后 |
|---|---|---|
| 13 字段整帧 | 962/1045 | 1045/1045 |
| scene 错误帧 | 23 | 0 |
| options / option_grid / option_details 错误帧 | 各 18 | 各 0 |
| overlay 错误帧 | 2 | 0 |
| screen 错误帧 | 50 | 0 |
| 完整 scene/screen/takeover 诊断 | 仍有差异 | 各 1045/1045 |
| 完整 terrain 诊断 | 地形与适用性待修复 | 1019/1019；26 帧 N |
| 覆盖检查 | 换图中间帧被误报缺字段 | 无缺字段，仅 c-0109 两项 unresolved |

83 个基线失败帧全部修复，所有字段 regressed 为空。修复前基线 `decoder_after_truth_patch_1008.json`、最终基线 `decoder_final_1008.json`、代码整理后的复验 `decoder_verified_1008.json`；四组报告 `decoder_groups_verified_1008.json`；Inspect none 模型实跑日志 `inspect_decoder_1008/*.eval`；覆盖检查 `coverage_final_1008.json`，均位于 `eval_results/labeling_1007/`。

现有测试增加每项代表帧、背景商店/菜单防回退、两条生产路径省略混合地点、7/10 字符命名长度及无框数字 9 的用例。测试仍按仓库 .gitignore 保留本地；不新增测试文件。world 自持检查同步已迁移的门面目录与指定 world MCP 服务适配器，三项均通过；ruff 排除独立 langfuse 检出目录与临时 pytest 输出后全仓库 lint/format 干净。本轮按 AGENTS 编号分步提交，未推送。

最终 196 个相关测试全部通过，JUnit 为 `eval_results/labeling_1007/tests_final_1008.xml`。独立重放批准操作验证修改仅限补丁字段，修补前基线的 129 个错误字段位置恰好等于清单中涉及基线的操作；冻结样本哈希不变。证据汇总为 `eval_results/labeling_1007/completion_report_1008.json`，包含基线变化、四组分母、coverage、测试与实际 Inspect 日志路径。

局限：同一批帧用于定位和验收，不能作为留出集泛化结论。没有模拟器实测；后续应验证走到原幽灵格、输入十字母昵称、进出门。小写键盘、异常状态/三只以上队伍、非空 PC 箱、忘招列表等未覆盖场景仍按审计第六节保留。
