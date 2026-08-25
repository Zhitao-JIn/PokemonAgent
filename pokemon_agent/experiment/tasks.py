"""可重复的短程/长程实验任务定义。"""

from __future__ import annotations

from pokemon_agent.schemas.task import Task
from pydantic import BaseModel, Field


class TaskChain(BaseModel):
    """按顺序执行的一组任务；链内任务共享同一个已装配的游戏世界。"""

    chain_id: str = Field(description="实验任务链标识")
    tasks: list[Task] = Field(min_length=1, description="按执行顺序排列的子任务")
    initial_state_hint: str = Field(default="", description="任务链起始状态说明")

    @property
    def initial_task(self) -> Task:
        """返回决定任务链初始存档的第一个子任务。"""
        assert self.tasks, "task chain must contain at least one task"
        return self.tasks[0]


def knowledge_recall_tasks(max_steps: int = 15) -> list[TaskChain]:
    """返回 knowledge 召回实验任务链；单任务统一表示为单节点链。"""
    cases = (
        ("wild_encounter", "在草丛中连续行走，直到确认遇到一只野生宝可梦",
         "画面出现战斗场景、野生宝可梦名称或明确遭遇提示", "野外草丛边缘，scene=field overlay=none"),
        ("door_transition", "从建筑外绕到入口，进入建筑并确认已经切换到室内地图",
         "map_id 或 scene 发生明确变化，且画面显示室内地点", "野外建筑门口，scene=field overlay=none"),
        ("npc_dialogue", "从附近位置走到 NPC 前，完成一次对话并确认出现对话文字",
         "画面出现 NPC 对话框文字", "NPC 正前方一格，scene=field 或 indoor overlay=none"),
        ("movement_obstacle", "识别前方阻挡，改变路线并到达阻挡后的可通行区域",
         "连续两次观测显示位置或场景已离开阻挡区域", "墙或树前一格，scene=field overlay=none"),
        ("dialogue_advance", "逐句推进至少三段对话，直到对话框关闭并确认回到可行动画面",
         "对话文字出现过且最终 overlay 不再是 dialog", "对话框已打开，scene=indoor overlay=dialog"),
        ("choice_confirm", "读取当前选项，移动光标后选择确认并观察结果",
         "选择框消失并出现选择后的明确画面或文字", "选项框已打开，overlay=choice"),
        ("menu_open", "从野外位置打开菜单，浏览至少一个菜单项后返回野外",
         "scene=menu 且出现菜单标题或选项", "野外静止画面，scene=field overlay=none"),
        ("shop_interaction", "走到商店店员处，完成进店对话并确认商店选项出现",
         "scene=shop 且出现商品或金钱信息", "商店 NPC 前方一格，scene=indoor overlay=none"),
        ("battle_action_menu", "确认战斗开始，读取行动菜单并移动光标后回到行动菜单",
         "scene=battle 且出现可用战斗选项", "战斗选择画面，scene=battle overlay=choice"),
        ("battle_fight_menu", "从战斗行动菜单选择战斗，读取招式列表并返回行动选择",
         "画面出现可用招式或 PP 信息", "战斗行动菜单，scene=battle overlay=choice"),
        ("battle_move_select", "选择一个可用招式，确认招式执行后重新读取战斗状态",
         "招式选择框关闭并出现招式执行或伤害文字", "招式列表，scene=battle overlay=choice"),
        ("battle_pokemon_switch", "在战斗中打开宝可梦列表，移动到另一只可行动宝可梦并确认切换",
         "画面出现宝可梦列表或切换结果文字", "战斗行动菜单，至少有两只可用宝可梦"),
        ("battle_item_use", "在战斗中打开道具袋，浏览道具并确认一个可用道具",
         "画面出现道具列表或道具使用结果", "战斗行动菜单，scene=battle overlay=choice"),
        ("battle_run_attempt", "在野生战斗中读取行动菜单，尝试逃跑并根据结果决定下一步",
         "战斗结束并回到野外，或出现逃跑失败文字", "野生战斗行动菜单，scene=battle overlay=choice"),
        ("shop_open_buy_menu", "进入商店并完成店员对话，选择购买后确认商品列表出现",
         "画面出现商品列表和价格", "商店 NPC 对话结束后的菜单，scene=shop overlay=choice"),
        ("shop_select_item", "在商品列表中浏览至少两个商品，选择一个并进入购买确认",
         "商品被选中并出现购买数量或确认选项", "商店商品列表，scene=shop overlay=choice"),
        ("shop_confirm_purchase", "浏览商品、选择一个买得起的商品并确认购买成功",
         "出现购买成功文字，且金钱或物品数量发生变化", "商品确认选项，金钱足够"),
        ("shop_cancel_purchase", "选择商品进入购买确认，取消购买并返回商品列表后退出商店",
         "购买确认框关闭且仍停留在商店菜单", "购买确认选项，scene=shop overlay=choice"),
        ("catch_weaken_target", "在野生战斗中选择合适行动，削弱目标但不要将其击倒",
         "目标 HP 明显降低且战斗仍在继续", "野生战斗刚开始，目标 HP 较高，自身有可控伤害招式"),
        ("catch_throw_ball", "在野生战斗中打开背包，选择精灵球并尝试捕捉目标",
         "出现捕捉动画、捕捉成功或捕捉失败的明确结果", "野生战斗中，背包至少有一枚精灵球"),
        ("catch_confirm_success", "确认一次捕捉结果，并根据结果回到可继续行动的状态",
         "出现捕捉成功文字或明确的捕捉失败文字", "精灵球结算动画或结果文字出现"),
        ("pokemon_center_enter", "从宝可梦中心外进入中心并完成前台对话",
         "出现宝可梦中心内部或护士对话文字", "宝可梦中心门外 3–6 步"),
        ("pokemon_center_heal", "将受伤的宝可梦交给护士治疗并确认恢复完成",
         "出现治疗完成文字，或队伍 HP 恢复的明确证据", "宝可梦中心护士前，队伍至少一只受伤"),
        ("pokemon_center_leave", "完成治疗后离开宝可梦中心并确认回到野外",
         "scene 从 indoor 变为 field，或出现中心外地图证据", "治疗完成后的宝可梦中心内部"),
    )
    available_state_tasks = {
        "knowledge_wild_encounter", "knowledge_door_transition", "knowledge_npc_dialogue",
        "knowledge_movement_obstacle", "knowledge_dialogue_advance",
        "knowledge_battle_action_menu", "knowledge_battle_fight_menu",
        "knowledge_battle_move_select", "knowledge_battle_pokemon_switch",
        "knowledge_battle_item_use", "knowledge_battle_run_attempt",
        "knowledge_shop_open_buy_menu", "knowledge_shop_select_item",
        "knowledge_shop_confirm_purchase", "knowledge_shop_cancel_purchase",
        "knowledge_catch_weaken_target", "knowledge_catch_throw_ball",
        "knowledge_pokemon_center_enter", "knowledge_pokemon_center_heal",
        "knowledge_pokemon_center_leave",
    }
    tasks = [
        Task(task_id=f"knowledge_{name}", goal=goal,
             success_criteria=criteria, max_steps=max_steps,
             initial_state_hint=state_hint)
        for name, goal, criteria, state_hint in cases
        if f"knowledge_{name}" in available_state_tasks
    ]
    task_by_id = {task.task_id: task for task in tasks}
    chain_specs = (
        ("knowledge_encounter_and_battle", (
            "knowledge_wild_encounter", "knowledge_battle_action_menu",
        )),
        ("knowledge_shop_purchase_flow", (
            "knowledge_shop_open_buy_menu", "knowledge_shop_select_item",
            "knowledge_shop_confirm_purchase",
        )),
        ("knowledge_pokemon_center_flow", (
            "knowledge_pokemon_center_enter", "knowledge_pokemon_center_heal",
            "knowledge_pokemon_center_leave",
        )),
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


def episodic_recall_tasks(max_steps: int = 80) -> list[Task]:
    """需要跨局摘要经验的长程任务；先失败积累轨迹，再重复同一目标测召回。"""
    goal = "从当前起点穿过野外路线并进入下一个城镇"
    return [
        Task(task_id=f"episodic_route_trial_{index}", goal=goal,
             success_criteria="画面出现下一个城镇的直接证据", max_steps=max_steps)
        for index in range(1, 4)
    ]
