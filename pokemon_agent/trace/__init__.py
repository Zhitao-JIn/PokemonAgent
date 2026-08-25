"""trace 包：事件流的实现与它的周边。

    store.py    `TracePort` 的实现：追加写、落盘、控制台推流
    utils.py    payload 组装的纯函数——**不认识 TracePort，不做任何 I/O**
    index.py    episode 的全局索引：保证 id 唯一、清理跑了一半的局
    browser.py  把事件推给浏览器的那个小服务

`utils.py` 单独拎出来是因为"这一步该不该记"和"记的话该长什么样"是两件事：
前者是 Harness 的调度判断，后者是纯翻译。拆开之后组装逻辑可以脱离 `TracePort`
单测——给一个 `ModelCall` 断言吐出来的元组长什么样，不需要造假实现。
"""

from .index import EpisodeIndex
