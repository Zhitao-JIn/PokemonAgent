# RAG 金标集 v1 起草表（待用户勾选）

> 用途：RAG 检索评估的金标数据集（inspect-ai Dataset 形态）。
> **判定原则**：一条 query 的金标 = 回答该 query 所代表的情境**必须**读到的知识条目（核心 1~3 条）；
> 召回了一点用没有的条目不算命中。勾选 = 确认该条样本进入 v1 数据集，并可修改金标列。
> 勾完后转 `dataset/v1/samples.json`（input=query，target=source 列表）。
> 起草：2026-09-28，来源 = 历史 read_knowledge 账 2 个独特 query（legacy 0916）+ 12 条知识条目反向构造。

| # | 类型 | query（agent 检索输入） | 提议金标（source） | 起草理由 | 勾 |
|---|---|---|---|---|---|
| 1 | 真实 | scene:field overlay:none 你在野外。 map:12 目标：在草丛里一直走，直到撞上一只野生宝可梦 | wild_encounters.md；movement_and_obstacles.md | 草丛遭遇条件 + 移动是核心；历史 refs 里混入的 battle_confirmation/dialogue 是**噪声**（战斗还没发生），正是要暴露的误召回 | ☐ |
| 2 | 真实 | scene:field overlay:none 你在野外。 map:12 目标：打开主菜单：按 start 键，让屏幕上出现菜单窗口 | menu_and_choices.md；battle_confirmation.md | 菜单操作核心；battle_confirmation 存疑（开菜单≠战斗）——**历史 refs 实测包含它**，请裁决是否算噪声 | ☐ |
| 3 | 构造 | 目标：确认现在是不是进入了战斗（画面出现野生宝可梦名字或战斗菜单） | battle_confirmation.md | 该条知识的直接语义 | ☐ |
| 4 | 构造 | scene:battle overlay:battle 目标：战斗菜单里想逃跑，FIGHT/PKMN/ITEM/RUN 怎么选 | battle_actions.md | 分支语义直接对应 | ☐ |
| 5 | 构造 | 目标：战斗中想切换宝可梦或用道具，菜单分支怎么操作 | battle_actions.md | 同一条知识的第二情境 | ☐ |
| 6 | 构造 | 目标：在商店里买一个精灵球 | shop_purchase.md；items_and_pickups.md | 购买流程核心；拾取条目存疑（买≠捡），请裁决 | ☐ |
| 7 | 构造 | overlay:choice 目标：屏幕上出现了选项列表，怎么移动光标并确认 | menu_and_choices.md | choice overlay 直接对应 | ☐ |
| 8 | 构造 | 目标：走进一栋建筑，先弄清这是宝可梦中心还是商店 | pokemon_center_and_shop.md | 该条知识直接语义（进建筑先确认） | ☐ |
| 9 | 构造 | 目标：跟面前的 NPC 说话 | dialogue_interaction.md | **真实失败案例**（0915 跟 NPC 说话那局：按 a 的语义没说清） | ☐ |
| 10 | 构造 | 目标：抓一只野生宝可梦 | catching_pokemon.md；battle_actions.md | 捕捉流程核心；战斗分支相关 | ☐ |
| 11 | 构造 | 目标：捡起地面上的道具 | items_and_pickups.md | 拾取语义直接对应 | ☐ |
| 12 | 构造 | 目标：穿过这扇门去隔壁房间 | doors_and_warps.md | 门/map_id 变化直接对应 | ☐ |
| 13 | 构造 | 目标：一直往东走，但按了方向键画面没动 | movement_and_obstacles.md | 撞墙判断直接对应 | ☐ |
| 14 | 构造 | 目标：去宝可梦中心给宝可梦恢复 HP | pokemon_center.md；pokemon_center_and_shop.md | 治疗流程 + 建筑确认两条都相关 | ☐ |
| 15 | 构造（负例对照） | 目标：在野外走路，看看能不能碰到宝可梦 | wild_encounters.md | 只考遭遇条件本身，**不该**召回 battle/catch 全家——测精确率侧 | ☐ |
| 16 | 构造（负例对照） | overlay:none 目标：确认当前在室内还是室外 | 无（应空命中或仅 movement） | 库里没有"室内外判断"专条——**应命中为空或极小**，测"库没有时不硬凑" | ☐ |

**统计**：真实 2 / 构造 12 / 负例对照 2，共 16 条。金标涉及的 source 覆盖 12 条知识中的 12/12。
