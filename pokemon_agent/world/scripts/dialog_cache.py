"""脚本的对话增量采集，不参与流程分叉。"""


class DialogCache:
    """对话增量缓存（§3.5 写侧主动增量）：已见行集合，reset/load_state 清空。

    `ingest` 返回**本帧新增**文本（不在已见集合里的行），并就地更新集合——
    消费方按序直接拼接各事件 `text` 即完整对话，无需 diff。
    """

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.deltas: list[str] = []
        """每次 `ingest` 的增量文本，按发生顺序（P6 起脚本的对话载荷从这取——
        events[] 已交给判定层统一产出，不再兼职对话记录）。"""

    def reset(self) -> None:
        self.seen.clear()
        self.deltas.clear()

    def ingest(self, dialog_text: str) -> str:
        lines = [line for line in dialog_text.splitlines() if line.strip()]
        new = [line for line in lines if line not in self.seen]
        self.seen.update(lines)
        delta = "\n".join(new)
        if delta:
            self.deltas.append(delta)
        return delta
