"""用命令行驱动游戏，游戏在你打字时照常运行。

实测：`pyboy.button()`（程序调用）有效，SDL 窗口的键盘输入无效。
agent 走的是前者，所以项目不受影响；但人要采截图还是得能操作游戏。

## 为什么要开线程

上一版在主循环里直接 `input()`，而 `input()` 阻塞期间模拟器不 tick——
窗口冻住、不重绘，看起来像卡死。

所以拆成两个线程：

    主线程    只有它碰 pyboy：一直 tick，顺便从队列里取命令执行
    读入线程  只做一件事：input() 读一行，塞进队列

**PyBoy 不是线程安全的**，所以严格保持"只有主线程碰它"。
线程之间只通过 `queue.Queue` 传字符串，不共享任何模拟器对象。

    python -m probe.play                 # 默认 assets/rom
    python -m probe.play assets/rom

命令：
    a / b / up / down / left / right / start / select   按键，可带次数：up 5
    shot [名字]        截图存进 screenshots/
    save [路径]        存档（默认 assets/rom.state）
    load [路径]        读档
    fast / slow        切不限速 / 实时
    hash               打印当前画面哈希
    h                  重看帮助
    q                  退出
"""

from __future__ import annotations

import hashlib
import pathlib
import queue
import sys
import threading

from pyboy import PyBoy

BUTTONS = {"a", "b", "up", "down", "left", "right", "start", "select"}
SHOT_DIR = pathlib.Path("screenshots")
HELP = __doc__.split("命令：")[1]


def frame_hash(pyboy: PyBoy) -> str:
    return hashlib.md5(pyboy.screen.ndarray.tobytes()).hexdigest()[:8]


def reader(q: queue.Queue[str]) -> None:
    """后台线程：只读字符串，不碰 pyboy。"""
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            q.put("q")
            return
        q.put(line.strip())


def default_state_path(pyboy: PyBoy) -> pathlib.Path:
    return pathlib.Path(str(pyboy.gamerom) + ".state")


def handle(pyboy: PyBoy, raw: str) -> bool:
    """在主线程里执行一条命令。返回 False 表示要退出。

    命令里的等待一律用 tick 实现，所以执行期间游戏照常推进，窗口不会冻。
    """
    if not raw:
        return True

    word, *rest = raw.split()
    arg = " ".join(rest)

    if word in {"q", "quit", "exit"}:
        return False

    if word in {"h", "help"}:
        print(HELP)
    elif word in BUTTONS:
        times = int(arg) if arg.isdigit() else 1
        for _ in range(times):
            pyboy.button(word, delay=10)
            pyboy.tick(20)          # 给游戏时间反应；期间世界在走
        print(f"  按了 {times} 次 {word}   → {frame_hash(pyboy)}")
    elif word == "shot":
        SHOT_DIR.mkdir(exist_ok=True)
        path = SHOT_DIR / f"{arg or frame_hash(pyboy)}.png"
        pyboy.screen.image.save(path)
        print(f"  存好了：{path}")
    elif word == "save":
        path = pathlib.Path(arg) if arg else default_state_path(pyboy)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pyboy.save_state(f)
        print(f"  存档：{path}（{path.stat().st_size} 字节）")
    elif word == "load":
        path = pathlib.Path(arg) if arg else default_state_path(pyboy)
        if not path.is_file():
            print(f"  没有这个存档：{path}")
            print("  —— 先用 save 造一个。**读不到多半是因为它根本不存在。**")
        else:
            with open(path, "rb") as f:
                pyboy.load_state(f)
            pyboy.tick(1)           # 读档后要 tick 一次才会重绘
            print(f"  已读档：{path}   → {frame_hash(pyboy)}")
    elif word == "fast":
        pyboy.set_emulation_speed(0)
        print("  不限速")
    elif word == "slow":
        pyboy.set_emulation_speed(1)
        print("  实时")
    elif word == "hash":
        print(f"  {frame_hash(pyboy)}")
    else:
        print(f"  不认识 {word!r}，敲 h 看帮助")

    return True


def main() -> None:
    rom = sys.argv[1] if len(sys.argv) > 1 else "assets/rom"

    pyboy = PyBoy(rom, window="SDL2", scale=4)
    pyboy.set_emulation_speed(1)

    q: queue.Queue[str] = queue.Queue()
    threading.Thread(target=reader, args=(q,), daemon=True).start()

    print(HELP)
    print("游戏在你打字时照常运行。直接敲命令，回车执行。\n")

    try:
        while pyboy.tick(1):        # ← 主循环一直在走，这是关键
            try:
                raw = q.get_nowait()
            except queue.Empty:
                continue
            if not handle(pyboy, raw):
                break
    finally:
        pyboy.stop()


if __name__ == "__main__":
    main()
