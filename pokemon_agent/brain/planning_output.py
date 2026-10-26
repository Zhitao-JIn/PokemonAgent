"""Convert model budget amounts to the internal budget shape without guessing units."""

from typing import Literal


def normalize_budget_amounts(
    raw: dict[str, object], unit: Literal["tasks", "actions"]
) -> tuple[dict[str, object], list[str]]:
    """Inject the capability's fixed unit into positive integer budgets.

    Caller guarantees unit matches the capability. Invalid external values remain unchanged
    for normal schema validation; existing explicit objects remain subject to that validation.
    Returns a copy and ledger annotations; never mutates the decoded model output.
    """
    assert unit in {"tasks", "actions"}
    items = raw.get("new_items")
    if not isinstance(items, list):
        return raw, []
    normalized: list[object] = []
    annotations: list[str] = []
    for index, item in enumerate(items):
        budget = item.get("budget") if isinstance(item, dict) else None
        if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0:
            normalized.append({**item, "budget": {"limit": budget, "unit": unit}})
            annotations.append(f"new_items[{index}].budget: limit={budget}, unit={unit}")
        else:
            normalized.append(item)
    return {**raw, "new_items": normalized}, annotations
