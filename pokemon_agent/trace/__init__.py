"""trace 的具体实现——存储/推流（`store.py`）与 payload 组装（`utils.py`）。

`interfaces/trace.py` 里的 `TracePort` 协议本身极简，三个方法（`append`/
`replay`/`sse`），刻意不认识任何领域类型。这个包放的是围绕它的两件具体的事，
而且**故意不合并成一个类**：

- `store.MockTrace` —— `TracePort` 的一个具体实现：`append` 落盘（内存列表）、
  `replay` 历史拉取、`sse` 推流（现在打印到控制台，以后推给浏览器）。
  它只认识 `EventType`/`Source`/`payload: dict[str, str]` 这些 trace 自己的类型。
- `utils` —— 一组纯函数，把领域对象（`Observation`/`Action`/`Goal`/
  `ModelCall`……）组装成 `append()` 能直接展开调用的参数元组。不认识
  `TracePort`，不做任何 I/O，可以脱离 trace 单独单元测试。

`Harness` 依赖裸的 `TracePort`（不是某个包装类）：它自己调 `append()`，
但组装 payload 这件事全部委托给 `trace_utils` 里的纯函数——`harness.py`
里因此没有任何 `dict[str, str]` 字面量。
"""
