"""通过 Pydantic AI 调用 DeepSeek，工具只暴露当前问的只读查询。"""

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable
from importlib.resources import files
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic_ai import (
    Agent,
    AgentRunResult,
    BinaryContent,
    RunContext,
    UsageLimits,
    capture_run_messages,
)
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from pokemon_agent.schemas.reviewer import (
    BrainFramesQuery,
    FrameQuery,
    RecallQuery,
    TraceQuery,
    ViewAnswer,
    ViewQuery,
)
from pokemon_agent.schemas.reviewer.interaction import (
    Ask,
    AuditAnswer,
    InjectAnswer,
    ReviewProposal,
)

logger = logging.getLogger(__name__)
QueryPort = Callable[[int, ViewQuery], Awaitable[ViewAnswer]]


class _AiInjectAnswer(BaseModel):
    """AI 插话提案必须带有可供人判断的实际内容。"""

    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


AnswerType = type[AuditAnswer] | type[_AiInjectAnswer]


class AiSeat:
    """每问临时建立 agent；模型标识、密钥与查询端口均由装配方传入。"""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        query: QueryPort,
        max_tool_calls: int,
        turn_budget_s: float,
    ) -> None:
        self._model = OpenAIChatModel(
            model_name, provider=OpenAIProvider(base_url=base_url, api_key=api_key)
        )
        self._query = query
        self._max_tool_calls = max_tool_calls
        self._turn_budget_s = turn_budget_s

    async def run_turn(self, ask: Ask, human_note: str = "") -> ReviewProposal | None:
        """返回与问匹配的结构化建议；模型失败、超时或预算耗尽返回 None。"""
        try:
            return await asyncio.wait_for(self._run(ask, human_note), self._turn_budget_s)
        except asyncio.CancelledError:
            raise
        except (TimeoutError, UnexpectedModelBehavior, UsageLimitExceeded) as exc:
            logger.warning("AI reviewer 未能形成提案：%s", exc)
            return None
        except Exception:
            logger.exception("AI reviewer 发生未预期错误")
            return None

    async def _run(self, ask: Ask, human_note: str) -> ReviewProposal:
        """生成类型匹配的提交工具，并把查询调用转交 hub 验证。"""
        answer_type: AnswerType = AuditAnswer if ask.kind == "audit" else _AiInjectAnswer
        instructions = _instructions(ask, human_note)
        agent = _agent(self._model, answer_type, instructions)

        async def read(ctx: RunContext[int], query: ViewQuery) -> ViewAnswer:
            return await self._query(ctx.deps, query)

        _register_tools(agent, read)
        with capture_run_messages() as messages:
            try:
                result = await agent.run(
                    "依据当前复核材料完成判断。需要证据时先调用只读查询，再通过匹配的提交工具给出结论。",
                    deps=ask.seq,
                    usage_limits=UsageLimits(tool_calls_limit=self._max_tool_calls),
                )
            except UsageLimitExceeded:
                result = await _forced_submit(self._model, answer_type, instructions, messages)
        answer = (
            result.output
            if isinstance(result.output, AuditAnswer)
            else InjectAnswer(text=result.output.text)
        )
        return ReviewProposal(answer=answer)


def _agent(model: OpenAIChatModel, answer_type: AnswerType, instructions: str) -> Agent:
    """构造 Chat Completions agent，清单强制函数工具或提交出口之一。"""
    tools = ["read_trace", "recall", "read_frame", "read_brain_frames", "final_result"]
    return Agent(
        model,
        deps_type=int,
        output_type=answer_type,
        retries=2,
        model_settings={
            "extra_body": {"thinking": {"type": "disabled"}},
            "tool_choice": tools,
        },
        instructions=instructions,
    )


def _register_tools(agent: Agent, read: Callable[..., Awaitable[ViewAnswer]]) -> None:
    """按查询联合类型注册只读工具；图片以多模态工具结果回传。"""

    @agent.tool
    async def read_trace(ctx: RunContext[int], query: TraceQuery) -> str:
        """读取本问对应 run 的 trace 账，可按局、task、节点与账名过滤。"""
        return (await read(ctx, query)).text

    @agent.tool
    async def recall(ctx: RunContext[int], query: RecallQuery) -> str:
        """只读查询跨 run 的记忆记录。"""
        return (await read(ctx, query)).text

    @agent.tool
    async def read_frame(
        ctx: RunContext[int], query: FrameQuery
    ) -> str | list[str | BinaryContent]:
        """读取某步或最新画面；可用时以图片内容回传模型。"""
        answer = await read(ctx, query)
        return [answer.text, *(_binary_content(frame) for frame in answer.images)]

    @agent.tool
    async def read_brain_frames(
        ctx: RunContext[int], query: BrainFramesQuery
    ) -> str | list[str | BinaryContent]:
        """读取大脑本次输入实际看到的帧，可按页查看。"""
        answer = await read(ctx, query)
        return [answer.text, *(_binary_content(frame) for frame in answer.images)]


async def _forced_submit(
    model: OpenAIChatModel,
    answer_type: AnswerType,
    instructions: str,
    messages: list[ModelMessage],
) -> AgentRunResult[AuditAnswer | InjectAnswer]:
    """查询额度耗尽后，保留已有证据并只开放结论出口。"""
    agent = Agent(
        model,
        output_type=answer_type,
        retries=2,
        model_settings={
            "extra_body": {"thinking": {"type": "disabled"}},
            "tool_choice": ["final_result"],
        },
        instructions=instructions,
    )
    return await agent.run(
        "查询预算已用完。根据已有对话立即调用提交工具给出结论。",
        message_history=messages,
        usage_limits=UsageLimits(tool_calls_limit=1),
    )


def _instructions(ask: Ask, human_note: str) -> str:
    """渲染提案与完整文字快照，不复制规则到素材。"""
    req = ask.request
    context = json.dumps(
        _without_images(req.context.model_dump(mode="json")), ensure_ascii=False, indent=2
    )
    rules = (
        files("pokemon_agent.reviewer.seats.ai")
        .joinpath("prompts/system.md")
        .read_text(encoding="utf-8")
    )
    if ask.kind == "audit":
        proposal = req.outcome.model_dump_json()
    else:
        proposal = (
            req.form.model_dump_json() if hasattr(req.form, "model_dump_json") else str(req.form)
        )
    question = req.prompt if ask.kind == "inject" else "请复核已达成结论"
    return (
        rules + "\n"
        f"问题类型：{ask.kind}\n复核问题：{question}\n既有提案：{proposal}\n"
        f"复核快照：\n{context}\n"
        f"人工补充：{human_note or '无'}"
    )


def _binary_content(data_uri: str) -> BinaryContent:
    """把已校验的图片 data URI 转为 provider 无关的二进制内容。"""
    header, separator, payload = data_uri.partition(",")
    if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
        raise ValueError("画面不是 base64 图片 data URI")
    media_type = header[5:-7]
    return BinaryContent(data=base64.b64decode(payload, validate=True), media_type=media_type)


def _without_images(value: object) -> object:
    """保留结构与文本，递归移除快照中的 data URI。"""
    if isinstance(value, str):
        return "[frame omitted]" if value.startswith("data:image/") else value
    if isinstance(value, list):
        return [_without_images(item) for item in value]
    if isinstance(value, dict):
        return {key: _without_images(item) for key, item in value.items()}
    return value
