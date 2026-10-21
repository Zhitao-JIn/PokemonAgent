## task 意外打断
仅本次允许 decision=interrupted：实际出现目标未预料的战斗、剧情或传送，且让该 task 此刻无法继续。
普通走错、按键无反应、尚未达成都不算；变化本身是目标时优先检查 achieved。
不能确认打断时判 continue。只有已知需上层调整且当前层不能解决时才判 blocked。
