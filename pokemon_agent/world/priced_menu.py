"""从完整商品框读取可见商品及价格，不以光标是否正在闪烁为前提。"""

from collections.abc import Callable


def read_priced_menu(
    tiles: list[list[int]], render_text: Callable[[list[int]], str]
) -> list[tuple[str, str]]:
    """返回完整价格列表；被数量框遮挡或只有残片时返回空表。

    前置条件：tiles 是18×20图块。仅在 MONEY 标题存在时识别商品框；
    不推测当前光标、被遮挡商品或屏外商品。
    """
    assert len(tiles) == 18 and all(len(row) == 20 for row in tiles)
    if not any("MONEY" in render_text(row) for row in tiles):
        return []
    for top, row in enumerate(tiles):
        for left, tile in enumerate(row):
            if tile != 0x79:
                continue
            right = next((c for c in range(left + 1, 20) if row[c] == 0x7B), None)
            if right is None or any(value != 0x7A for value in row[left + 1 : right]):
                continue
            items = _read_box(tiles, top, left, right, render_text)
            if len(items) >= 2:
                return items
    return []


def _read_box(
    tiles: list[list[int]],
    top: int,
    left: int,
    right: int,
    render_text: Callable[[list[int]], str],
) -> list[tuple[str, str]]:
    """只接受边界连续且每个商品均有完整价格的框，拒绝嵌套遮挡。"""
    items: list[tuple[str, str]] = []
    pending = ""
    for row in tiles[top + 1 :]:
        if row[left] == 0x7D and row[right] == 0x7E:
            return items if not pending else []
        if row[left] != 0x7C or row[right] != 0x7C:
            return []
        values = row[left + 1 : right]
        if any(value in range(0x79, 0x7F) for value in values):
            return []
        text = render_text(values).replace("▶", "").replace("▷", "").strip()
        if not text:
            continue
        if text.startswith("¥") and text[1:].strip().isdigit() and pending:
            items.append((pending, text))
            pending = ""
        elif any(character.isalpha() for character in text) and not pending:
            pending = text
        else:
            return []
    return []
