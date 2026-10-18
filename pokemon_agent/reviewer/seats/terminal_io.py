"""阻塞 readline 的可取消异步适配；daemon 线程不阻止 Ctrl-C 后进程退出。"""

import asyncio
import threading
from collections.abc import AsyncIterator, Callable


class StdinLines:
    """readline 由入口注入；只把读出的行投递回事件循环，不在线程里修改 hub。"""

    def __init__(self, readline: Callable[[], str]) -> None:
        self._readline = readline
        self._queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def __aiter__(self) -> AsyncIterator[str]:
        """首次消费才开始读终端，构造本身不抢占 stdin。"""
        if self._thread is None:
            self._loop = asyncio.get_running_loop()
            self._thread = threading.Thread(target=self._read, daemon=True, name="reviewer-stdin")
            self._thread.start()
        return self

    async def __anext__(self) -> str:
        """EOF 正常结束，读失败沿原异常传播，不能误当作人的答复。"""
        value = await self._queue.get()
        if value is None:
            raise StopAsyncIteration
        if isinstance(value, BaseException):
            raise value
        return value

    def _read(self) -> None:
        """阻塞读取只发生在 daemon 线程，退出后不再投递已经迟到的行。"""
        try:
            for line in iter(self._readline, ""):
                if self._stop.is_set():
                    break
                self._feed(line.rstrip("\r\n"))
        except BaseException as exc:
            self._feed(exc)
        finally:
            self._feed(None)

    def _feed(self, value: str | BaseException | None) -> None:
        """事件循环退出与阻塞 readline 返回可能同时发生，关闭后不再排队。"""
        if not self._stop.is_set() and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, value)
            except RuntimeError:
                if not self._loop.is_closed():
                    raise

    def close(self) -> None:
        """幂等结束输入消费；无法打断 OS readline 的线程仍为 daemon。"""
        if not self._stop.is_set():
            self._feed(None)
            self._stop.set()
