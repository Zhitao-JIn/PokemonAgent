"""运行上下文的单调截止点；与 brain、world 实现无关，可注入假时钟。"""

import math
import time
from collections.abc import Callable, Sequence

from pokemon_agent.errors import BudgetExhausted
from pokemon_agent.schemas.harness import ModelCall


class Deadline:
    """一次 run 的时间预算；请求必须保留收尾时间，不足则不发送。"""

    def __init__(
        self,
        wall_clock_s: float,
        reserve_s: float,
        min_request_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """前置条件：正总时长超过非负预留，最小有用时长为正。"""
        assert math.isfinite(wall_clock_s) and wall_clock_s > reserve_s >= 0
        assert math.isfinite(min_request_s) and min_request_s > 0
        self._clock = clock
        self._wall_clock_s = wall_clock_s
        self._reserve_s = reserve_s
        self._min_request_s = min_request_s
        self.start()

    def start(self, remaining_s: float | None = None) -> None:
        """在 run 真正进图时重新设截止点，装配与加载存档不消耗执行预算。"""
        self._end = self._clock() + (
            self._wall_clock_s if remaining_s is None else min(self._wall_clock_s, remaining_s)
        )

    def cap_remaining(self, remaining_s: float | None) -> None:
        """恢复内层检查点时只收紧截止点，不能把上层旧快照当作新增时间。"""
        if remaining_s is not None:
            self._end = min(self._end, self._clock() + remaining_s)

    def remaining(self) -> float:
        """返回非负剩余秒数；不使用系统墙钟。"""
        return max(0.0, self._end - self._clock())

    def allowed(
        self,
        limit_s: float,
        source: str,
        calls: Sequence[ModelCall] = (),
        *,
        delay_s: float = 0,
    ) -> float:
        """扣掉收尾预留与拟等待退避，低于最小有用时长则抛 BudgetExhausted。"""
        assert limit_s > 0 and delay_s >= 0
        allowed = min(limit_s, self.remaining() - self._reserve_s - delay_s)
        if allowed < self._min_request_s:
            raise BudgetExhausted(source, calls)
        return allowed
