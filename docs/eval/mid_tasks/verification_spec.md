# spec —— 中期任务的模拟器核实与 oracle（只做实验，不入库）

> 依据：`docs/eval/mid_tasks/intent.md` 第五、五点五、六节。本任务是**实验**：在模拟器里核实 M1–M5 设计里写着"未验证"的前提，并为每条任务跑出确定性 oracle。**不提交、不改任何已跟踪文件**；全部产物放 `experiment/mid_verify/`（该目录被忽略，不入库）。
> 工作位置：主仓库 `D:\Users\GummiGu\PycharmProjects\Pokemon_Agent`，用它的虚拟环境 `.venv\Scripts\python.exe`；可以启动模拟器（这正是本任务的目的），不调用真实模型。
> 后续：核实结果交给设计侧，据此改写 intent、冻结 episode 目标表，再另案建中期数据集版本（派生存档此时才入库）。

## 一、通用做法

1. 脚本仿照已有的 `experiment/probe_settle.py` 起 `PyBoyWorld` 与 `WorldConsoleAdapter`；起点存档在 `evals/agent_short_goal_run/dataset/v20261021_retest5/states/`：M1、M2、M5 用 `knowledge_pokemon_center_enter.state`，M3 用 `knowledge_catch_weaken_target.state`，M4 用 `knowledge_shop_interaction.state`。
2. oracle 用项目里**已有的世界脚本**写（先在 `pokemon_agent/world/scripts/` 与 `mcp_servers/world_server.py` 里看有哪些脚本与按键接口，如走到某格、对 NPC 说话、推进对话、买东西、使用物品等），按"一个决策一步"计数：记 `oracle_steps`（脚本调用 + 单键各算一步）与脚本内部实际按键总数两个数；自然 episode 边界按 intent 里写的地图切换点记录每段步数。
3. 每个结论都要有证据：逐字的对话文字（解码屏幕文字）、地图号与坐标、背包与队伍的 RAM 读数前后对比；"没发生"也要写出你看了哪一帧、看了什么。
4. 有随机性的地方（遇敌、伤害）重复多次：用不同的空转帧数（如开局先空转 0、7、13、29、53 帧）取样，每个设置至少 5 次，报分布，不要只报一次。
5. 预检：核实前先确认存档能加载、`WorldConsoleAdapter.read()` 正常；跑不起来就停下汇报，不要自行替代。
6. 判据要求：oracle 通关后，用 intent 里写的机械判据逻辑（在你的实验脚本里用 RAM 读数独立实现一遍）判定通过；判不过就说明哪一步不满足，不要改判据。

## 二、要核实的事项（对应 intent 第六节 1–7）

**V1 包裹自动触发（M1）**：从 `knowledge_pokemon_center_enter.state`（地图 1 (20,26)）走到商店门 (29,19) 进地图 42，是否自动进入店员托付对话？逐字记录台词（应点明 PROF. OAK 与 PALLET TOWN）；按几下键对话结束；背包是否出现 item 70（OAK's PARCEL）；过程中的地图号变化与步数；对话期间主角位置。再从同一起点换一条先与店员 (0,5) 附近的柜台交互的路径，核实包裹事件是否仍只触发一次。
**V2 研究所交付（M1）**：带着包裹走 42→1→12→0→40：记录每次换图的步数与坐标、Route 1（地图 12）的随机遭遇次数与处理方式（你的 oracle 遇敌时怎么办：逃跑还是战斗，各自多少步）、进地图 40 后包裹**何时**从背包移除、过场长度、是否需要主动走到 Oak 面前交互；重复运行得到总步数的分布；给出 `oracle_steps` 与三个自然 episode 的边界步数。
**V3 顾客台词与店员事件（M4）**：从 `knowledge_shop_interaction.state` 与两位顾客各对话一次，逐字记录各说了什么、哪位在哪个坐标说的；顾客有一位沿 x=5 来回走，记录走动周期并给出稳定对话的做法；在 (3,5) 与店员首次对话是否仍触发包裹事件；打开 BUY 列表，逐项记录商品名与价格（与 `shop_layouts.json` 对照）。
**V4 中毒（M5）**：派生存档：把第二只宝可梦（Pidgey）的状态字节改写为中毒（0x08），保存到 `experiment/mid_verify/states/`，记录被改的 RAM 地址与改前改后值；加载后核实队伍菜单是否显示 PSN；从背包使用 ANTIDOTE 是否确实把它治成 ok，使用 POTION 是否**不**治中毒；在 M5 的路线（地图 1→42）上中毒伤害使 Pidgey（15 HP）每 4 步掉 1 HP 的实际表现，走完去商店再回来是否会倒下，记录路线上的 HP 轨迹。
**V5 抓捕与治疗（M3）**：派生存档：把 Bulbasaur 的 HP 改为最大值的一半，保存并记录改动的 RAM；从 `knowledge_catch_weaken_target.state` 起：对手的等级与最大 HP（读 RAM）；用 Tackle 打一击的伤害分布（至少 20 次采样，用不同空转帧数）；投精灵球的捕获成功率分布（至少 20 次）；捕获后的起名询问用什么方式拒绝（给出按键序列与屏幕文字）；回城路径（地图 12→1→41）上的随机遭遇次数与步数；队伍治疗后满血的判定。
**V6 M2 的 oracle**：派生存档：把首只宝可梦 HP 改为一半（记录 RAM 改动并保存）；跑通"治疗→买 2 个精灵球→回到起点 (1,20,26)"：记录钱与球的变化（应为钱 −400、球 +2）、每段步数与自然 episode 边界。
**V7 估算对照**：把你测得的换图次数、移动步数、对话与菜单按键数，与 intent 里每条任务"必要下限（估算）"逐条对照，写出偏差；给出建议的 `max_steps` 与 run 预算取值依据（不要自己定，只给数据）。

## 三、产物

1. `experiment/mid_verify/`：脚本、`results.json`（结构化：每个事项的结论、证据、分布）、`report.md`（人读版）、`states/`（派生存档，附 sha256 与改动的 RAM 地址表）。
2. 汇报：一张总表（V1–V7 各"成立 / 不成立 / 无法判断"与一句话证据）；每个**不成立**的前提单独写：现象、证据、对哪个任务的什么设计有影响、你建议的最小调整（只描述，不要自己改 intent）；五条 oracle 的 `oracle_steps`、内部按键数与自然 episode 边界；派生存档清单。

## 四、规则与停止条件

- 不提交、不 `git add`、不改任何已跟踪文件（含 `docs/`、`evals/`、`pokemon_agent/`）；只写 `experiment/mid_verify/`。不调用真实模型。
- 遇到：存档加载失败、需要改 `pokemon_agent/` 下代码才能继续、某个前提不成立且后续事项依赖它、怀疑模拟器行为与预期不符而无法解释——停下汇报，不要硬凑 oracle，不要为了让 oracle 通过去改判据或改起点。
- 不做：不设计新任务，不改变 M1–M5 的目标与判据文字，不建数据集版本。
