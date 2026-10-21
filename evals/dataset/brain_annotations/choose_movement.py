"""按当前可见地图核验路径首键；仅目标门格可走入 D。"""

import re

from evals.dataset.brain_choose.build.prelabel import walking_keys


def route(walk_map: str, x: int, y: int, target: tuple[int, int]) -> list[str]:
    """把目标门格作为可进入终点，其余门保持障碍；未知或不可达返回空。"""
    lines: list[str] = []
    for line in walk_map.splitlines():
        match = re.fullmatch(r"y=(-?\d+)\s+(\S+)\s+\(x=(-?\d+)\.\.(-?\d+)\)", line)
        if match:
            row, cells, left, right = match.groups()
            column = target[0] - int(left)
            if int(row) == target[1] and 0 <= column < len(cells) and cells[column] == "D":
                cells = cells[:column] + "." + cells[column + 1 :]
            line = f"y={row} {cells} (x={left}..{right})"
        lines.append(line)
    return walking_keys("\n".join(lines), (x, y), f"x={target[0]} y={target[1]}")
