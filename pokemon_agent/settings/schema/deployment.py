"""落盘与外部服务相关的小段：run / trace / paths / services / debug。

密钥（各家 API Key、Langfuse 连接信息）不在这里，仍只在 `.env`。
"""

from typing import Literal

from pydantic import Field

from .base import Section


class RunSection(Section):
    """本次 run 的身份：`run_id` 区分 trace 切片，`branch` 是执行线名（未经恢复为 main）。"""

    run_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)


class TraceSection(Section):
    """trace 后端：`local` 一条事件一个 JSON；`langfuse` 本机自托管服务。"""

    backend: Literal["local", "langfuse"]


class PathsSection(Section):
    """落盘根目录。相对路径按**仓库根**解析（不跟启动目录走）。

    `runs_root` 是其余各项的基准；`config_snapshot` 存每次 run 的生效配置快照。
    """

    runs_root: str = Field(min_length=1)
    trace: str = Field(min_length=1)
    memory: str = Field(min_length=1)
    config_snapshot: str = Field(min_length=1)


class ServicesSection(Section):
    """MCP 服务地址（base，不含 `/mcp`）；None 表示未配，装配时由 tool 层报错。"""

    memory_server_url: str | None = Field(min_length=1)
    world_server_url: str | None = Field(min_length=1)


class DebugSection(Section):
    """调试开关；`vision_dump_dir` 非空时把送进视觉模型的图写到该目录。"""

    vision_dump_dir: str | None = Field(min_length=1)
