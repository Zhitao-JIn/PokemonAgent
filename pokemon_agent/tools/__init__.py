"""工具层 —— harness 和其他模块之间的那一层：harness 组装 req，tool 做处理。

四个 tool，各对接一个模块：
- `brain_tool.py`（`BrainToolPort`）对接 brain——req 翻译成 brain 原生输入；
- `trace/`（`TraceToolPort`）对接 trace——按 `TraceKind` 渲染 payload 再落盘。
  收成一个包（D8-③）：`__init__.py` 分派器 + `render.py` 每种账的 payload
  （payload 字段格式是跨模块契约，观测台前端按字段名渲染，变更权在本层）
  + `model_calls.py` 一次交互的批量账；
- `game_tools.py`（`GameToolPort`）对接 world；
- `memory_tool.py`（`MemoryToolPort`）对接 memory。

（`checkpoint_tool.py` 已在步 5b 解散：存档不再是外面递进来的一根 Port，
而是 `harness/episode/episode_state.py` 的 `EpisodeCheckpoint` 自己落盘。）

分工约定：harness 只负责组装 req（挑字段、声明 kind），tool 对 req 做处理
（不用改就原样转发），模块只返回自己该返回的，tool 把返回处理成新的 resp
——harness 拿到的 resp 形状由 tool 负责，不随模块内部形状漂移。

**本文件是统一出口，但只导出实现；四张协议住在 `tools/interface/`**：

```python
from pokemon_agent.tools.interface import GameToolPort   # 消费方（harness）
from pokemon_agent.tools import GameTools                # 装配点（build.py）
```

**为什么分家**：`tools/__init__.py` 是"进这一层的门"，任何人
`import pokemon_agent.tools.interface` 都会先跑完它。出口一旦同时导出协议和
实现，harness 只想拿一张协议，也得把五个插件全请来——"换 mock 不改 harness"
这句承诺在类型上早就成立（类型注解里只有 Protocol），在 **import 这一层**没成立。
搬完实测：拿协议从 146 个 `pokemon_agent` 模块降到与信封侧同量级。理由、
验收与迁移顺序见 `docs/spec/tools/PLAN_tool_interface.md`。

**四个实现全部懒加载。** 跟 `world/__init__.py` 对 `PyBoyWorld`、
`brain/__init__.py` 对 `Brain` 同一个道理，只是这里的重依赖不是 PyBoy，而是
"四个插件各自的整条链"（`trace.store`、`memory` 包、`prompts`、`world`…）。
`__getattr__` 把四个名字改成按需导入，`from pokemon_agent.tools import GameTools`
用起来和之前一模一样，只是不再是包初始化时就全量加载。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .brain_tool import BrainTool
    from .game_tools import GameTools
    from .memory_tool import MemoryTool
    from .trace import TraceTool

__all__ = [
    "BrainTool",
    "GameTools",
    "MemoryTool",
    "TraceTool",
]

_LAZY: dict[str, tuple[str, str]] = {
    "BrainTool": (".brain_tool", "BrainTool"),
    "GameTools": (".game_tools", "GameTools"),
    "MemoryTool": (".memory_tool", "MemoryTool"),
    "TraceTool": (".trace", "TraceTool"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
