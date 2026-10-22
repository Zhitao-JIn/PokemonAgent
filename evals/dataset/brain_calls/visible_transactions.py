"""数量框以原屏幕为准；避免菜单解码保留旧列表导致错误负标签。"""

import re

from pokemon_agent.world import TaskObservation

CRITERIA: frozenset[str] = frozenset(
    {
        "options 变成购买数量或 YES / NO，不再是商品名",
        "屏幕出现购买数量确认框或 YES / NO 确认选项",
    }
)


def transaction_truth(current: TaskObservation, criterion: str) -> tuple[bool, str] | None:
    """明确购买数量目标；原屏幕数量与金额同现，或 YES/NO 活跃选项即可定真。"""
    if criterion not in CRITERIA or not str(current.scene).startswith("shop"):
        return None
    facts = current.facts
    quantity = bool(re.search(r"[×x]\s*\d+\s*[¥￥]\s*\d+", facts.screen))
    yes_no = {"YES", "NO"} <= set(facts.options)
    if quantity or yes_no:
        return True, "purchase_confirmation_screen"
    if not facts.screen:
        return None
    return False, "purchase_confirmation_screen"


def catch_result_truth(current: TaskObservation, criterion: str) -> tuple[bool, str] | None:
    """本批已见的投球结算话语也是结果，不把括号里的例子误当穷举。"""
    if criterion not in (
        "对话框里出现投球结果文字（如 All right! ... was caught! / Darn! The POKéMON broke free!）",
        "屏幕出现投球结果文字，如 All right! ... was caught! 或 Darn! The POKéMON broke free!",
    ):
        return None
    text = current.facts.dialog_text
    if any(
        phrase in text
        for phrase in (
            "Aww! It appeared to be caught!",
            "was caught!",
            "broke free!",
        )
    ):
        return True, "catch_result_text"
    return None
