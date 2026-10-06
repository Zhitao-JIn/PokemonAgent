"""部署配置（env）读取：`.env` 的极简加载 + 只读访问。

**本文件只管 env，不管 knob**。实验旋钮（重试预算、召回条数……）住在
`config.py`——那里改的是"这一轮实验想试什么"，这里改的是"这台机器/这个服务在
哪"。两者的生命周期不同，混在一起会让"这次实验的配置"无法从代码复现。

**为什么自己解析而不用 python-dotenv**：仓库的 `.env` 只有 `KEY=VALUE`
（带引号、空行、`#` 注释），为解析它引一个包不值当；更重要的是**加载时机要
显式**——装配点（`build.py::build_real`）与 server 入口各调一次
`load_env_file()`，不要"import 模块就改全局 os.environ"的隐式副作用
（那会让测试顺序影响装配结果）。

**优先级**：真实环境变量 > `.env` 文件（`override=False` 缺省）。CI / 容器里
注入的真变量不该被盘上的文件盖掉。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_FILE_NAME = ".env"
""".env 文件名（固定；只在仓库根找一层）。"""


def _parse_line(line: str) -> tuple[str, str] | None:
    """把一行 `KEY=VALUE` 解析成元组；注释 / 空行 / 无 `=` 的行返回 None。"""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    # 成对引号（`KEY="value"` / `KEY='value'`）剥掉——只剥一层，内容里的引号保留
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value


def load_env_file(
    path: str | Path | None = None,
    *,
    override: bool = False,
) -> Path | None:
    """把 `.env` 的条目读进 `os.environ`；返回实际读的文件（没找到返回 None）。

    `path`：缺省按**仓库根**找（本文件的上上级目录），与"起跑脚本在哪个目录
    启动"无关——env 是部署配置，跟着仓库走，不跟着 cwd 走。

    `override`：False（缺省）时已有同名环境变量**不动**（真变量优先）；
    True 时以文件为准（只有"想让盘上的文件接管"的场景才开，目前没有）。

    后置条件：返回非 None 时，文件里的每个 `KEY=VALUE` 都在 `os.environ` 里可见
    （`override=False` 且键已存在时保留原值）。
    """
    if path is not None:
        target = Path(path)
    else:
        target = Path(__file__).resolve().parent.parent / ENV_FILE_NAME
    if not target.is_file():
        return None
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if not override and key in os.environ:
            continue
        os.environ[key] = value
    return target


def env_str(name: str, default: str | None = None) -> str | None:
    """读一个 env 变量：空串与纯空白**视同未配**（返回 default）。

    判据：`.env` 里留一行 `MCP_MEMORY_SERVER_URL=` 是"我预留了这项但没填"，
    不是"地址是空串"——按空串往下走会在 httpx 那里炸出一个看不懂的错。
    """
    value = os.getenv(name, "").strip()
    return value or default
