"""人的命令只翻译为 hub 类型化调用，解析错误不会变成一次答复。"""

import shlex

from pydantic import ValidationError

from pokemon_agent.schemas.harness import AuditVerdict
from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.schemas.reviewer.interaction import AuditAnswer, InjectAnswer, SubmitAck

from ..view.render import text_without_frames
from .ports import CommandHub
from .query_commands import CommandParseError, CommandParser, parse_query, query_help, query_schemas

_CONTROL_HELP = (
    "ctx [--section 名]\nhistory [-n 10]\nsay <原文>\nok\noverturn <理由>\n"
    "ask-ai <原文>\nhelp [命令]"
)


class Commands:
    """本对象无问的状态；每次调用都显式提供 seq，由 hub 验证是否仍有效。"""

    def __init__(self, hub: CommandHub) -> None:
        self._hub = hub

    async def execute(self, seq: int, line: str) -> ViewAnswer:
        """执行一行命令；查询、答复与历史都只走 hub 端口。"""
        split = line.lstrip().split(maxsplit=1)
        if not split:
            return ViewAnswer(ok=False, text="请输入命令，用 help 查看用法")
        name, body = split[0], split[1] if len(split) == 2 else ""
        try:
            if name in {"say", "overturn", "ask-ai"}:
                return self._text_command(seq, name, body)
            arguments = shlex.split(body)
            if name in query_schemas():
                return await self._hub.query(seq, parse_query(name, arguments))
            return self._control(seq, name, arguments)
        except (CommandParseError, ValidationError, ValueError) as exc:
            return ViewAnswer(ok=False, text=text_without_frames(f"命令错误：{exc}"))

    def _text_command(self, seq: int, name: str, body: str) -> ViewAnswer:
        """自由正文保持引号和内部空格；空白不是有效的意见或推翻理由。"""
        if not body.strip():
            return ViewAnswer(ok=False, text="正文不能为空")
        if name == "say":
            ack = self._hub.submit(seq, InjectAnswer(text=body), "human")
        elif name == "overturn":
            ack = self._hub.submit(
                seq, AuditAnswer(verdict=AuditVerdict.OVERTURN, note=body), "human"
            )
        else:
            ack = self._hub.discuss(seq, body)
        return _answer(ack)

    def _control(self, seq: int, name: str, arguments: list[str]) -> ViewAnswer:
        """非查询命令解析后直接调用对应 hub 方法。"""
        if name == "help":
            if len(arguments) > 1:
                raise CommandParseError("help 最多接受一个命令名")
            topic = arguments[0] if arguments else None
            if topic is None:
                return ViewAnswer(ok=True, text=query_help() + "\n" + _CONTROL_HELP)
            if topic in query_schemas():
                return ViewAnswer(ok=True, text=query_help(topic))
            for line in _CONTROL_HELP.splitlines():
                if line.split()[0] == topic:
                    return ViewAnswer(ok=True, text=line)
            raise CommandParseError(f"未知命令：{topic}")
        if name == "ctx":
            parser = CommandParser(prog="ctx", add_help=False)
            parser.add_argument("--section")
            return self._hub.context(seq, parser.parse_args(arguments).section)
        if name == "history":
            return self._history(arguments)
        if name == "ok" and not arguments:
            ask = self._hub.current(seq)
            if ask is None:
                return ViewAnswer(ok=False, text="该问已了结")
            answer = InjectAnswer() if ask.kind == "inject" else AuditAnswer()
            return _answer(self._hub.submit(seq, answer, "human"))
        raise CommandParseError(f"未知命令或多余参数：{name}，用 help 查看用法")

    def _history(self, arguments: list[str]) -> ViewAnswer:
        """历史只展示摘要，不借助命令层缓存过去的问题。"""
        parser = CommandParser(prog="history", add_help=False)
        parser.add_argument("-n", type=int, default=10)
        n = parser.parse_args(arguments).n
        if n < 1:
            raise CommandParseError("history -n 必须为正数")
        items = self._hub.history(n)
        lines = [f"history：{len(items)} 条"]
        lines += [text_without_frames(item.model_dump(mode="json")) for item in items]
        return ViewAnswer(ok=True, text="\n".join(lines))


def _answer(ack: SubmitAck) -> ViewAnswer:
    """只转换返回形状，不重做 hub 的提交决策。"""
    return ViewAnswer(ok=ack.ok, text=ack.text)
