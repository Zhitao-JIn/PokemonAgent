"""可重复的短程/长程实验任务定义。

# goal 和 criteria 怎么写

**临时规范，写在这里是因为新任务都加在这个文件里，照着上下文的例子写最省事。**
稳定之后应该挪进 `docs/spec/`。

下面每一条都是撞出来的，不是推演的。judge 的处境要先记住：它只看得到
**当前这一帧** + 本局最近 3 步的快照，看不到 `walk_map`/`landmarks`/跨局记忆，
拿不到决策者的任何说辞，而且**默认判 false**（判错成"完成"的代价远大于判错成
"没完成"）。所有规则都是这个处境的推论。

## 1. goal 的最后一句，必须就是 criteria 描述的那一帧

两者是同一个终局的两种说法：goal 给人读，criteria 给 judge 核对。

**实测**：`battle_move_select` 的 goal 写「选择一个可用招式，确认招式执行后
**重新读取战斗状态**」，criteria 写「招式选择框关闭并出现招式执行或伤害文字」。
判据其实满足过三次（`But, it failed!` / `Critical hit!` /
`Enemy RATTATA fainted!`），judge 每次都判 false，理由是"不是招式执行后的
**战斗状态重读画面**"——那句话不在 criteria 里，**是它从 goal 的字面抠出来的**。
goal 里一旦有 criteria 覆盖不到的东西，judge 就会去找它的证据。

## 2. 不写过程动词

`确认` `读取` `观察` `浏览` `尝试` `根据结果决定` ——这些都是**动作**，
画面上永远不会有它们的证据。judge 找不到就判 false，而且会自己发明替代判据
（上面那局它开始要求出现 `used TACKLE` 那行字，而按 `a` 推进对话时它早翻过去了）。

写**终点的样子**，不写到达终点的过程。「绕过障碍」→「走到 y >= 14」；
「确认招式执行」→「对话框里出现伤害文字」。

## 3. criteria 要能在单帧上机械核对

用 `facts` 里的字段名和字面值：`map_id 仍是 12 且 y >= 14`、
`overlay 不再是 dialog`、`scene=shop`。judge 的 prompt 明确教它
「判据提到位置就直接读 `where` 那一行」——你给它字段名，它就不用去猜。

**criteria 不能是残句。** 写成 `"x或y坐标"` 这种残句，judge 无法比对任何
东西，只好回退去照 goal 的字面找证据——成功率恒为 0，而且看不出原因。

## 4. 分清判据问的是**事件**还是**状态**

- **事件**（说过话、看过招牌、打出过招式）：问的是发生过没有，证据可能在前几步
  的快照里，judge 有 3 步历史可查。
- **状态**（在哪张地图、室内还是野外、身上有什么）：只看当前这一帧，历史不算数。

同一条 criteria 里混着两类，judge 会拿错的那套规则去核对。

## 5. goal 和 criteria 不能指向互斥的两帧

`menu_open`：goal 要「浏览菜单后**返回野外**」，criteria 要 `scene=menu`——
终帧不可能同时是野外和菜单。`shop_cancel_purchase` 同理（goal 要"退出商店"，
criteria 要"仍停留在商店菜单"）。这类任务**无论 agent 做什么都不可能成功**，
而症状和"太难"完全一样。写完自问一句：满足 criteria 的那一帧，
放进 goal 的叙述里说得通吗？

## 6. 别把计数写进判据

「逐句推进**至少三段**对话」「浏览**至少两个**商品」——judge 只有 3 步历史，
数不了，只能猜。要计数就换成一个终局状态：对话推完的样子是
「历史里出现过对话文字，且这一帧 overlay 不再是 dialog」。

## 7. 判据锚在绝对值上时，前提是初始存档确定

`movement_obstacle` 的 `map_id 仍是 12 且 y >= 14` 建立在"每局都从
`x=9 y=12` 开局"之上。存档漂了判据就跟着坏，而且不报错。
锚绝对坐标之前先确认 `experiment_states/` 里那个 `.state` 是钉死的。

## 8. 不要求 judge 做归属推断

「`dialog_text` 是**护士**说的话」「`options` 是**队伍里**的宝可梦名字」——
judge 手里只有文字本身，**没有说话人、没有队伍名单**，它没有任何办法确认归属。
按「拿不准一律 false」，这类判据的成功率恒为 0，而症状和"太难"一模一样。

`pokemon_center_enter` 就栽在这上面：判据要「dialog_text 是护士说的话」，
而护士的台词 `Welcome to our POKéMON CENTER!` 不带说话人前缀，
agent 明明已经对上话，judge 稳定判 false。
（母亲那条能判，是因为 Gen1 里她的台词真的带 `MOM:` 前缀——那是巧合，不是写法。）

要么**引台词原文**（`We hope to see you again!`），
要么**换成内存里读得到的状态量**（`map_id` 变了、`scene` 是 indoor），
要么**给一组字面例子**让它做字符串比对（`options` 是道具名，如 `POTION` / `ANTIDOTE`）。

## 9. 引用的字段必须在**那个 scene 下真的存在**

`facts` 是按 scene 装的（见 `world/screen_state.py` 的 `ScreenState.fields`）：
`my_hp` / `foe_hp` 只在 `scene=battle` 有，`money` / `items` 只在 `scene=shop` 有。
判据里写一个当前 scene 根本不会出现的字段，等于没写。

判据引用的字段必须在当前 scene 读得到——`scene=indoor`（治疗发生的地方）
永远读不到 `my_hp`，写「或 `my_hp` 回到满值」等于没写。另外 `facts` 是**扁平的**，
键就是 `money`、`items`，没有 `fields` 这一层，判据里也不要这么写。

## 自查清单

写完一条新任务，逐条过一遍：

1. goal 的最后一句和 criteria 说的是同一帧吗？
2. goal 里还有 `确认`/`读取`/`观察`/`浏览`/`尝试` 吗？
3. criteria 里的每个词，judge 能在这一帧的 `facts` 里找到对应吗？
4. 这条判据问的是事件还是状态，两类混了吗？
5. criteria 那一帧，放进 goal 的叙述里说得通吗？
6. 有没有 judge 数不出来的数量词？
7. 有没有要 judge 判断"这是谁说的""这是谁的名字"的地方？
8. 引用的字段，在这条判据对应的那个 scene 下真的会出现吗？
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.domain import TaskForHarness


class TaskChain(BaseModel):
    """按顺序执行的一组任务；链内任务共享同一个已装配的游戏世界。"""

    chain_id: str = Field(description="实验任务链标识")
    tasks: list[TaskForHarness] = Field(min_length=1, description="按执行顺序排列的子任务")
    initial_state_hint: str = Field(default="", description="任务链起始状态说明")

    @property
    def initial_task(self) -> TaskForHarness:
        """返回决定任务链初始存档的第一个子任务。"""
        assert self.tasks, "task chain must contain at least one task"
        return self.tasks[0]


def knowledge_recall_tasks(max_steps: int = 15) -> list[TaskChain]:
    """返回 knowledge 召回实验任务链；单任务统一表示为单节点链。"""
    cases = (
        (
            "wild_encounter",
            "在草丛里一直走，直到撞上一只野生宝可梦",
            "scene 是 battle，或对话框里出现 `WILD ... appeared!`",
            "野外草丛边缘，scene=field overlay=none",
        ),
        (
            "door_transition",
            "绕到建筑门口，走进去",
            "scene 是 indoor",
            "野外建筑门口，scene=field overlay=none",
        ),
        (
            "npc_dialogue",
            "走到 NPC 面前按 a，让他说话",
            "overlay 是 dialog，且 dialog_text 非空",
            "NPC 正前方一格，scene=field 或 indoor overlay=none",
        ),
        (
            "movement_obstacle",
            "你在地图 12 的 x=9 y=12，正南方 y=13 这一整行被挡住了。绕过它，走到 y=14 或更南的地方",
            "where 那一行显示 map_id 仍是 12 且 y >= 14",
            "地图12 x=9 y=12，正南是墙，scene=field overlay=none",
        ),
        (
            "dialogue_advance",
            "把对话一句一句按完，直到对话框消失",
            "历史里出现过 dialog_text，且这一帧 overlay 不是 dialog",
            "对话框已打开，scene=indoor overlay=dialog",
        ),
        (
            "choice_confirm",
            "在选择框里把光标移到某一项，按 a 选中它",
            "这一帧 overlay 不再是 choice，且 overlay 变成 dialog 或 scene 和历史里那几步不同",
            "选项框已打开，overlay=choice",
        ),
        (
            "menu_open",
            "在野外按 start 打开主菜单",
            "scene 是 menu，且 options 非空",
            "野外静止画面，scene=field overlay=none",
        ),
        (
            "shop_interaction",
            "在商店里找到店员，隔着柜台跟他说话，直到 BUY / SELL / QUIT 出现",
            "overlay 是 choice，且 options 是 BUY / SELL / QUIT",
            "商店内地板上（地图42 x=3 y=5），店员在柜台里，店里另有两个顾客",
        ),
        (
            "battle_action_menu",
            "在战斗行动菜单里把光标移到 RUN",
            "scene 是 battle、overlay 是 choice，且 cursor 是 RUN",
            "战斗选择画面，scene=battle overlay=choice",
        ),
        (
            "battle_fight_menu",
            "在行动菜单里选 FIGHT，打开招式列表",
            "overlay 是 choice，且 options 是招式名（不再是 FIGHT / PKMN / ITEM / RUN）",
            "战斗行动菜单，scene=battle overlay=choice",
        ),
        (
            "battle_move_select",
            "在招式列表里选一个招式，按 a 把它打出去",
            "对话框里出现招式执行的结果文字（如 Critical hit! / It's super effective! / But, it failed! / Enemy ... fainted!），或对手 HP 挡位下降",
            "招式列表，scene=battle overlay=choice",
        ),
        (
            "battle_pokemon_switch",
            "在战斗中打开宝可梦列表",
            "overlay 是 choice，且 options 不再是 FIGHT / PKMN / ITEM / RUN，而是宝可梦名字",
            "战斗行动菜单，至少有两只可用宝可梦",
        ),
        (
            "battle_item_use",
            "在战斗中打开道具袋",
            "overlay 是 choice，且 options 是道具名（如 POKé BALL / POTION / ANTIDOTE）",
            "战斗行动菜单，scene=battle overlay=choice",
        ),
        (
            "battle_run_attempt",
            "在野生战斗里选 RUN 逃跑",
            "scene 变回 field，或对话框里出现逃跑失败文字（如 Can't escape!）",
            "野生战斗行动菜单，scene=battle overlay=choice",
        ),
        (
            "shop_open_buy_menu",
            "在商店里选 BUY，打开商品列表",
            "scene 是 shop，且 options 是商品名（如 POKé BALL / POTION / ANTIDOTE）",
            "商店 NPC 对话结束后的菜单，scene=shop overlay=choice",
        ),
        (
            "shop_select_item",
            "在商品列表里选中一个商品，按 a 进入购买确认",
            "options 变成购买数量或 YES / NO，不再是商品名",
            "商店商品列表，scene=shop overlay=choice",
        ),
        (
            "shop_confirm_purchase",
            "买下一个买得起的商品",
            "对话框里出现购买成功文字（如 Here you are! Thank you!）",
            "商品确认选项，金钱足够",
        ),
        (
            "shop_cancel_purchase",
            "在购买确认里选 NO 取消，退回商品列表",
            "scene 是 shop，且 options 又是商品名（如 POKé BALL / POTION），确认框已经不在",
            "购买确认选项，scene=shop overlay=choice",
        ),
        (
            "catch_weaken_target",
            "打对手一下，让它掉血",
            "foe_hp 的挡位比历史里那几步低",
            "野生战斗刚开始，目标 HP 较高，自身有可控伤害招式",
        ),
        (
            "catch_throw_ball",
            "在战斗中打开背包，选精灵球扔出去",
            "对话框里出现投球结果文字（如 All right! ... was caught! / Darn! The POKéMON broke free!）",
            "野生战斗中，背包至少有一枚精灵球",
        ),
        (
            "catch_confirm_success",
            "把捕捉结算的文字按完，回到可行动画面",
            "历史里出现过捕捉结果文字，且这一帧 overlay 不是 dialog",
            "精灵球结算动画或结果文字出现",
        ),
        (
            "pokemon_center_enter",
            "走进宝可梦中心",
            "scene 是 indoor，且 map_id 和历史里门外那几步不同（已经换过一次图）",
            "宝可梦中心门外 3–6 步",
        ),
        (
            "pokemon_center_heal",
            "让护士把队伍治好",
            "对话框里出现治疗完成文字（如 We hope to see you again!）",
            "宝可梦中心护士前，队伍至少一只受伤",
        ),
    )
    available_state_tasks = {
        "knowledge_wild_encounter",
        "knowledge_door_transition",
        "knowledge_npc_dialogue",
        "knowledge_movement_obstacle",
        "knowledge_dialogue_advance",
        "knowledge_battle_action_menu",
        "knowledge_battle_fight_menu",
        "knowledge_battle_move_select",
        "knowledge_battle_pokemon_switch",
        "knowledge_battle_item_use",
        "knowledge_battle_run_attempt",
        "knowledge_shop_interaction",
        "knowledge_shop_open_buy_menu",
        "knowledge_shop_select_item",
        "knowledge_shop_confirm_purchase",
        "knowledge_shop_cancel_purchase",
        "knowledge_catch_weaken_target",
        "knowledge_catch_throw_ball",
        "knowledge_pokemon_center_enter",
        "knowledge_pokemon_center_heal",
    }
    tasks = [
        TaskForHarness(
            task_id=f"knowledge_{name}",
            goal=goal,
            success_criteria=criteria,
            max_steps=max_steps,
            initial_state_hint=state_hint,
        )
        for name, goal, criteria, state_hint in cases
        if f"knowledge_{name}" in available_state_tasks
    ]
    task_by_id = {task.task_id: task for task in tasks}
    chain_specs = (
        (
            "knowledge_encounter_and_battle",
            (
                "knowledge_wild_encounter",
                "knowledge_battle_action_menu",
            ),
        ),
        (
            "knowledge_shop_purchase_flow",
            (
                "knowledge_shop_open_buy_menu",
                "knowledge_shop_select_item",
                "knowledge_shop_confirm_purchase",
            ),
        ),
        (
            "knowledge_pokemon_center_flow",
            (
                "knowledge_pokemon_center_enter",
                "knowledge_pokemon_center_heal",
            ),
        ),
    )
    chains = [
        TaskChain(chain_id=chain_id, tasks=[task_by_id[task_id] for task_id in task_ids])
        for chain_id, task_ids in chain_specs
        if all(task_id in task_by_id for task_id in task_ids)
    ]
    chains.extend(
        TaskChain(chain_id=task.task_id, tasks=[task], initial_state_hint=task.initial_state_hint)
        for task in tasks
    )
    return chains
