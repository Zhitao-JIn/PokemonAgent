"""商店与护士现场逐段审阅；不把错误上游目标的无解强塞为动作 gold。"""

from typing import Literal

Decision = tuple[Literal["labelled", "invalid_task", "unjudgeable"], list[str], str]


def merchant(number: int) -> Decision:
    """只覆盖新审阅项；已存在的纯坐标标签另行保留其来源。"""
    if number in {2, 31, 43, 54}:
        return (
            "labelled",
            ["a"],
            "当前已面向任务要求的互动方向，先进行一次探测；不能由 N 标记假定商人身份。",
        )
    if number in {3, 4, 32, 33, 42, 44, 45, 55, 56}:
        return (
            "labelled",
            ["a"],
            "当前对话尚未结束，按当前能力说明单次 a 推进；本次不自动重新开启下一轮。",
        )
    if 5 <= number <= 13 or 34 <= number <= 41 or 57 <= number <= 60:
        return (
            "unjudgeable",
            [],
            (
                "本任务可见历史已完成一轮普通/售罄对话并关闭，未见 BUY/SE"
                "LL/QUIT；当前任务仍要求同一对象开启菜单，输入不能证明哪"
                "一个动作可达成。排除无依据 a 循环 gold，需上游重规划。"
            ),
        )
    if 16 <= number <= 25:
        return (
            "invalid_task",
            [],
            (
                "目标将(3,7)门格 D 写成店员；当前地图无该位置 NPC。先修正"
                "人物身份/目标，不能把面向门重复 a 当商人互动。"
            ),
        )
    if 27 <= number <= 30:
        return (
            "labelled",
            ["up"],
            "当前北邻是空地，人物已在(5,5)；上移接近人物再交互，不按旧坐标对空 a。",
        )
    if 46 <= number <= 51:
        return (
            "invalid_task",
            [],
            ("要求站到(5,4)，但本次 walk_map 显示该格 #；绕开移动 NPC 也不能把墙格变成站位。"),
        )
    if number == 53:
        return "labelled", ["up"], "当前朝 east，本任务要求先朝 north；朝北转身不等于已经打开商店。"
    raise ValueError(f"unreviewed merchant choose {number}")


def nurse(number: int, overlay: str) -> Decision:
    """可关闭错误对话再转向；出口触发未知时不猜测成功动作。"""
    if number <= 10:
        return (
            "invalid_task",
            [],
            (
                "任务要求站(3,2)朝北，当前可见 row2 全为 # 柜台；应修正为"
                "柜台外互动，而非给穿墙动作。"
            ),
        )
    if number == 12 or number == 18:
        return (
            "labelled",
            ["up"],
            ("当前(3,3)朝 east 且无对话；本任务要求 north，先转向柜台，不能再向东打开顾客对话。"),
        )
    if 13 <= number <= 23:
        if overlay != "dialog":
            raise ValueError("reviewed dialogue state changed")
        return (
            "labelled",
            ["a"],
            (
                "当前是错误方向 NPC 的中心介绍；先单次推进/关闭，之后重新"
                "朝北调查，不能将该介绍当治疗证据。"
            ),
        )
    if 24 <= number <= 27:
        return (
            "labelled",
            ["down"],
            (
                "本次任务只给到出门目标；南侧路径通往(3,7)，可以先沿可走"
                "地面接近，不能导入不可见的上层治疗意图。"
            ),
        )
    return nurse_exit(number)


def nurse_exit(number: int) -> Decision:
    """区分可见接近门格与未被证实的传送触发。"""
    if number == 36:
        return (
            "labelled",
            ["right"],
            "当前(3,7)，东邻 D 为本任务指定(4,7)，先到指定门格；不宣称必定已发生传送。",
        )
    if number == 48:
        return (
            "labelled",
            ["left"],
            "当前(4,7)，西邻 D 为本次指定(3,7)，按 left 一格；本任务仅要求该坐标。",
        )
    if number == 42:
        return "labelled", ["left"], "当前(5,7)，西邻 D 为本次指定(4,7)，先接近门格。"
    if 28 <= number <= 47 or 49 <= number <= 52:
        return (
            "unjudgeable",
            [],
            (
                "已在门格附近但仍地图41；本次可见输入不能确定改变地图的触"
                "发方向/条件。a、横移无变化的历史不能反推另一个动作必然成"
                "功；不建立门口反复 a 的 gold，待补可验证出口机制或修订任"
                "务。"
            ),
        )
    raise ValueError(f"unreviewed nurse choose {number}")
