"""ViewQuery schema 派生命令参数与 help，查询种类只注册一次。"""

import argparse
from typing import Any

from pydantic import TypeAdapter

from pokemon_agent.schemas.reviewer import ViewQuery


class CommandParseError(ValueError):
    """用户命令不合法，返回提示而不退出进程。"""


class CommandParser(argparse.ArgumentParser):
    """禁用 argparse 的进程退出与直接 stderr 输出。"""

    def error(self, message: str) -> None:
        """把参数失败交给命令门面展示。"""
        raise CommandParseError(message)


def query_schemas() -> dict[str, dict[str, Any]]:
    """从联合 schema 的 discriminator 映射获取每个命令，不另建种类清单。"""
    schema = TypeAdapter(ViewQuery).json_schema()
    result: dict[str, dict[str, Any]] = {}
    for tool, ref in schema["discriminator"]["mapping"].items():
        name = tool.removeprefix("read_").replace("_", "-")
        result[name] = schema["$defs"][ref.rsplit("/", 1)[-1]]
    return result


def query_parser(command: str) -> CommandParser:
    """字段名派生标准长选项；保留短别名、帧位置参数与 recall 文本的既定语法。"""
    schemas = query_schemas()
    if command not in schemas:
        raise CommandParseError(f"未知查询：{command}")
    model = schemas[command]
    parser = CommandParser(prog=command, description=model.get("description"), add_help=False)
    for name, field in model["properties"].items():
        if name == "tool":
            continue
        if name == "conditions":
            _hint_arguments(parser, field)
        elif command == "frame" and name in {"episode_id", "step"}:
            parser.add_argument(name, nargs="?")
        elif name == "query":
            parser.add_argument(name, nargs="*", default=[])
        elif "enum" in field:
            group = parser.add_mutually_exclusive_group()
            group.add_argument(f"--{name}", choices=field["enum"], default=argparse.SUPPRESS)
            for choice in field["enum"]:
                group.add_argument(
                    f"--{choice}",
                    dest=name,
                    action="store_const",
                    const=choice,
                    default=argparse.SUPPRESS,
                )
        else:
            parser.add_argument(
                *_options(name), dest=name, default=argparse.SUPPRESS, help=_field_help(field)
            )
    return parser


def parse_query(command: str, arguments: list[str]) -> ViewQuery:
    """参数值交给唯一的 Pydantic schema 校验，条件选项合并成 conditions。"""
    values = vars(query_parser(command).parse_args(arguments))
    conditions = {
        name.removeprefix("hint_"): values.pop(name)
        for name in list(values)
        if name.startswith("hint_")
    }
    if "query" in values:
        values["query"] = " ".join(values["query"])
    if conditions:
        values["conditions"] = conditions
    values["tool"] = query_schemas()[command]["properties"]["tool"]["const"]
    return TypeAdapter(ViewQuery).validate_python(values)


def query_help(command: str | None = None) -> str:
    """help 与参数解析来自同一份 schema；新查询变体自动出现。"""
    if command is not None:
        return query_parser(command).format_help()
    return "\n".join(query_parser(name).format_help() for name in query_schemas())


def _options(name: str) -> list[str]:
    """规范字段名转长选项，并提供既定 CLI 的简写。"""
    options = ["--" + name.replace("_", "-")]
    if name.endswith("_id"):
        options.append("--" + name.removesuffix("_id").replace("_", "-"))
    if name in {"last_n", "limit"}:
        options.append("-n")
    return options


def _hint_arguments(parser: CommandParser, field: dict[str, Any]) -> None:
    """hint 键来自 dict 的 Literal 键 schema，未知键不会生成选项。"""
    for key in field["propertyNames"]["enum"]:
        parser.add_argument(*_options(key), dest=f"hint_{key}", default=argparse.SUPPRESS)


def _field_help(field: dict[str, Any]) -> str:
    """把模型的描述、默认值及体量界限显示在人与 AI 共用的帮助里。"""
    parts = [str(field[key]) for key in ("description", "default") if key in field]
    parts += [f"{key}={field[key]}" for key in ("minimum", "maximum") if key in field]
    return "; ".join(parts)
