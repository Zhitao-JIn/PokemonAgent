"""探针之四：反复按同一个键，看它到底生不生效。

    python -m probe.input_check                    # 默认按 a
    python -m probe.input_check assets/rom 10 a    # ROM / 准备秒数 / 按键

跑起来之后：

  1. **前 10 秒是你的**。用键盘把游戏调到一个静止且可交互的画面
     （站在地图上不动最好）。⚠ **别按空格** —— 它是不限速开关，
     按一次就一直加速，不会自己恢复。
  2. 之后脚本每 2 秒按一次这个键，逐次报告画面变没变。
     Ctrl+C 结束。

## 判据

不能简单看「画面变了没有」：动画期间不按也变，静止画面按了也可能不变。
所以每次按键前后都先**等画面稳定**：

    等稳定 → 记哈希 → 按键 → 等稳定 → 比较

等不到稳定就报「无法判定」，不猜。

这个「等稳定」正是 harness 将来要用的规则：动作之后不要固定 tick N 帧，
等世界安定——动画期间既采不到有效状态，按键也会被游戏丢弃。
"""

from __future__ import annotations

import hashlib
import sys

from pyboy import PyBoy

STABLE_FRAMES = 12    # 连续这么多帧不变，认为世界安定了
STABLE_TIMEOUT = 300  # 最多等这么多帧；等不到就是持续动画
INTERVAL = 2          # 两次按键之间隔多久（秒）


def frame_hash(pyboy: PyBoy) -> str:
    return hashlib.md5(pyboy.screen.ndarray.tobytes()).hexdigest()[:8]


def real_seconds(pyboy: PyBoy, seconds: float) -> bool:
    """真的过 `seconds` 秒。返回是否还在运行。

    **必须一帧一帧 tick。** PyBoy 的 `tick(count)` 是「连跑 count 帧、
    最后只限速一次」——`tick(60)` 花的是 ~17ms 而不是 1 秒。
    """
    return all(pyboy.tick(1) for _ in range(int(60 * seconds)))


def tick_until_stable(pyboy: PyBoy) -> tuple[bool, str, int]:
    """推进到画面稳定。返回 (是否稳定, 哈希, 等了多少帧)。"""
    last = frame_hash(pyboy)
    same = 0
    for waited in range(1, STABLE_TIMEOUT + 1):
        if not pyboy.tick(1):
            return False, last, waited
        now = frame_hash(pyboy)
        same = same + 1 if now == last else 0
        last = now
        if same >= STABLE_FRAMES:
            return True, now, waited
    return False, last, STABLE_TIMEOUT


def your_turn(pyboy: PyBoy, seconds: int) -> None:
    print(f"=== 现在是你的 {seconds} 秒 ===")
    print("把游戏调到一个**静止且可交互**的画面（站在地图上不动最好）。")
    print("⚠ 别按空格 —— 它是不限速开关，按一次就一直加速，不会自己恢复。\n")

    for left in range(seconds, 0, -1):
        print(f"  还剩 {left} 秒…", end="\r", flush=True)
        real_seconds(pyboy, 1)
    print("  时间到，开始测试。      \n")

    # 万一准备期间碰到空格，强制拨回实时，免得后面整段在另一个时间尺度上跑
    pyboy.set_emulation_speed(1)


def main() -> None:
    rom = sys.argv[1] if len(sys.argv) > 1 else "assets/rom"
    prep = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    button = sys.argv[3] if len(sys.argv) > 3 else "a"

    pyboy = PyBoy(rom, window="SDL2", scale=4)
    pyboy.set_emulation_speed(1)

    changed = unchanged = unknown = 0
    try:
        your_turn(pyboy, prep)
        print(f"=== 每 {INTERVAL} 秒按一次 {button!r}，Ctrl+C 结束 ===\n")

        n = 0
        while True:
            n += 1
            stable, before, w1 = tick_until_stable(pyboy)
            if not stable:
                unknown += 1
                print(f"  #{n:<3} 画面一直在动，无法判定 ?   （等了 {w1} 帧）")
            else:
                pyboy.button(button, delay=10)
                pyboy.tick(1)
                _, after, w2 = tick_until_stable(pyboy)
                if after != before:
                    changed += 1
                    print(f"  #{n:<3} 画面变了 ✓   {before} → {after}   （按后等 {w2} 帧）")
                else:
                    unchanged += 1
                    print(f"  #{n:<3} 没变化 ✗     {before}            （按后等 {w2} 帧）")

            if not real_seconds(pyboy, INTERVAL):
                break
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        pyboy.stop()

    print("\n" + "=" * 46)
    print(f"变了 {changed} 次 / 没变 {unchanged} 次 / 无法判定 {unknown} 次")
    if changed:
        print(f"→ `pyboy.button({button!r})` 有效。agent 走的就是这条路。")
    elif unknown and not unchanged:
        print("→ 画面始终在动，一次都没测成。停在静止画面上再试。")
    else:
        print("→ 一次都没生效。如果你停在地图上，A 至少该能和面前的东西互动；")
        print("  停在菜单里，A 该能选中。检查模拟器是不是被 P 暂停了。")


if __name__ == "__main__":
    main()
