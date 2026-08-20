"""探针之五：证明存档 / 读档真的可用，而且可复现。

## 为什么要证明，而不是"试试看能不能读上"

你的 A/B 实验（有记忆 vs 无记忆）全押在一个前提上：
**两组从逐字节相同的状态起跑。** 起点不同，两组的差异就说明不了任何事。

"读上了、画面对"只证明了没崩，没证明状态一致。所以这里查三件事，
一件比一件强：

    1. 读档后画面 = 存档时画面        —— 最基本
    2. 读档后 RAM  = 存档时 RAM        —— 画面一样不代表内存一样
    3. 同一存档跑同一动作序列两次，结果逐字节相同 —— **这才是实验要的那条**

第 3 条是真正的判据。前两条过了第 3 条也可能不过（比如模拟器里有没被存进
state 的隐藏状态），而第 3 条过了，A/B 对比才站得住。

    python -m probe.state_check                 # 默认 assets/rom
    python -m probe.state_check assets/rom
"""

from __future__ import annotations

import hashlib
import io
import sys

from pyboy import PyBoy

# 存档时机的采样地址：地图 ID / 徽章位图 / 坐标 / 队伍数（红版）
WATCH_ADDRS = [0xD35E, 0xD356, 0xD361, 0xD362, 0xD163]

SEQUENCE = ["a", "a", "start", "down", "a", "b", "up", "a"]


def screen_hash(pyboy: PyBoy) -> str:
    return hashlib.md5(pyboy.screen.ndarray.tobytes()).hexdigest()[:12]


def ram_hash(pyboy: PyBoy) -> str:
    """整个工作 RAM 的哈希（0xC000-0xDFFF，8KB）。

    比只看那几个采样地址严得多：任何被存进 state 的内存差异都会暴露。
    """
    data = bytes(pyboy.memory[0xC000:0xE000])
    return hashlib.md5(data).hexdigest()[:12]


def watched(pyboy: PyBoy) -> dict[str, int]:
    return {hex(a): pyboy.memory[a] for a in WATCH_ADDRS}


def run_sequence(pyboy: PyBoy, seq: list[str]) -> None:
    for name in seq:
        pyboy.button(name, delay=10)
        pyboy.tick(30)


def main() -> None:
    rom = sys.argv[1] if len(sys.argv) > 1 else "assets/rom"
    pyboy = PyBoy(rom, window="null")   # 无头：本探针不需要人看
    pyboy.set_emulation_speed(0)

    ok = True
    try:
        # 先跑一段，离开开机画面，进入一个有内容的状态
        pyboy.tick(600)
        run_sequence(pyboy, ["start", "a", "a"])

        saved_screen, saved_ram, saved_watch = screen_hash(pyboy), ram_hash(pyboy), watched(pyboy)
        buf = io.BytesIO()
        pyboy.save_state(buf)
        print(f"存档完成：{buf.tell()} 字节")
        print(f"  画面 {saved_screen}   RAM {saved_ram}")
        print(f"  采样 {saved_watch}\n")

        # 把状态搅乱
        run_sequence(pyboy, SEQUENCE)
        moved_screen = screen_hash(pyboy)
        print(f"跑了 {len(SEQUENCE)} 个动作后：画面 {moved_screen}")
        if moved_screen == saved_screen:
            print("  ⚠ 画面没变，这段动作没有真的改变状态，后面的检查会失去意义")

        # ---- 检查 1、2：读档回到存档点 ----
        buf.seek(0)
        pyboy.load_state(buf)
        pyboy.tick(1)

        back_screen, back_ram, back_watch = screen_hash(pyboy), ram_hash(pyboy), watched(pyboy)
        print("\n读档后：")
        print(f"  画面 {back_screen}   {'✓ 一致' if back_screen == saved_screen else '✗ 不一致'}")
        print(f"  RAM  {back_ram}   {'✓ 一致' if back_ram == saved_ram else '✗ 不一致'}")
        print(f"  采样 {back_watch}   {'✓ 一致' if back_watch == saved_watch else '✗ 不一致'}")
        ok &= back_screen == saved_screen and back_ram == saved_ram

        # ---- 检查 3：同起点跑同序列两次，结果必须相同 ----
        results = []
        for _ in range(2):
            buf.seek(0)
            pyboy.load_state(buf)
            pyboy.tick(1)
            run_sequence(pyboy, SEQUENCE)
            results.append((screen_hash(pyboy), ram_hash(pyboy)))

        same = results[0] == results[1]
        print("\n同一存档跑同一序列两次：")
        print(f"  第一次 画面 {results[0][0]}  RAM {results[0][1]}")
        print(f"  第二次 画面 {results[1][0]}  RAM {results[1][1]}")
        print(f"  {'✓ 逐字节相同' if same else '✗ 不同 —— 存在未被 state 捕获的隐藏状态'}")
        ok &= same
    finally:
        pyboy.stop()

    print("\n" + "=" * 52)
    if ok:
        print("三项全过。存档可用，且从同一存档出发是确定性的。")
        print("→ A/B 实验的前提成立：两组可以从逐字节相同的起点跑。")
    else:
        print("有检查未通过。**在修好之前不要跑 A/B 实验**——")
        print("  起点不一致的话，两组的差异说明不了任何事。")
        sys.exit(1)


if __name__ == "__main__":
    main()
