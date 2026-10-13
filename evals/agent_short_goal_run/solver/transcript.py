"""把类型化执行线回放进 Inspect，保留原时间、正文与截图。"""

from datetime import UTC, datetime

from inspect_ai.event import InfoEvent, ModelEvent, SpanBeginEvent, SpanEndEvent, ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model import (
    ChatMessageUser,
    ContentImage,
    ContentText,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._model_call import ModelCall
from pydantic import JsonValue

from evals.agent_short_goal_run.scorer.stream import RunStream
from pokemon_agent.direct.trace.parse import MODEL_CALL_KINDS, ParsedEvent

MODEL_LINKS: dict[str, str] = {
    "sense_call": "vision_model",
    "choose_call": "text_model",
    "plan_call": "plan_model",
    "decompose_call": "plan_model",
    "judge_call": "judge_model",
    "verify_call": "verify_model",
    "summarize_episode_call": "verify_model",
    "summarize_task_call": "verify_model",
}
SPAN_OPEN: dict[str, str] = {f"{level}_start": level for level in ("run", "episode", "task")}
SPAN_CLOSE: dict[str, str] = {
    f"{level}_{ending}": level
    for level in ("run", "episode", "task")
    for ending in ("end", "error")
}


def _timestamp(value: float) -> datetime:
    """把账本秒数转为 UTC，不使用当前时间。"""
    return datetime.fromtimestamp(value, UTC)


def _metadata(event: ParsedEvent) -> dict[str, str]:
    """所有派生事件携带同一账本定位信息。"""
    return {"kind": event.kind, "type": event.type, "trace_uuid": event.uuid}


def _payload(event: ParsedEvent) -> dict[str, JsonValue]:
    """完整保留类型化账本的标签与正文，不筛去图或额外字段。"""
    return {
        "type": event.type,
        "meta": event.meta.model_dump(mode="json", exclude_unset=True),
        "content": event.content.model_dump(mode="json", exclude_unset=True),
    }


def _info(event: ParsedEvent, parent: str | None) -> None:
    """追加一条原时间的信息账。"""
    transcript()._event(
        InfoEvent(
            uuid=event.uuid,
            source=event.kind,
            data=_payload(event),
            timestamp=_timestamp(event.started_at),
            span_id=parent,
            metadata=_metadata(event),
        )
    )


def _end_span(event: ParsedEvent, stack: list[tuple[str, str]]) -> None:
    """关闭栈顶；调用方保证栈非空，派生 uuid 不与正文事件冲突。"""
    assert stack, "cannot close an empty span stack"
    _, identifier = stack.pop()
    transcript()._event(
        SpanEndEvent(
            uuid=f"{event.uuid}:end:{identifier}",
            id=identifier,
            timestamp=_timestamp(event.ended_at),
            span_id=stack[-1][1] if stack else None,
            metadata=_metadata(event),
        )
    )


def _span(event: ParsedEvent, stack: list[tuple[str, str]]) -> int:
    """起止账保留正文；结束只关闭存在的对应层及其内层。"""
    parent = stack[-1][1] if stack else None
    if event.kind in SPAN_OPEN:
        level = SPAN_OPEN[event.kind]
        identifier = getattr(event.meta, f"{level}_id")
        transcript()._event(
            SpanBeginEvent(
                uuid=f"{event.uuid}:begin",
                id=event.uuid,
                parent_id=parent,
                type=level,
                name=f"{level} {identifier}",
                timestamp=_timestamp(event.started_at),
                span_id=parent,
                metadata=_metadata(event),
            )
        )
        stack.append((level, event.uuid))
        _info(event, event.uuid)
        return 2
    _info(event, parent)
    level = SPAN_CLOSE[event.kind]
    levels = [item[0] for item in stack]
    if level not in levels:
        return 1
    count = 1
    target = len(levels) - 1 - levels[::-1].index(level)
    while len(stack) > target:
        _end_span(event, stack)
        count += 1
    return count


def _model_output(event: ParsedEvent, model: str) -> ModelOutput:
    """从类型化调用账组装输出与全部用量。"""
    content = event.content.model_dump(mode="json")
    output = ModelOutput.from_content(model=model, content=str(content.get("raw", "")))
    output.usage = ModelUsage(
        input_tokens=content["input_tokens"],
        output_tokens=content["output_tokens"],
        total_tokens=content["input_tokens"] + content["output_tokens"],
        input_tokens_cache_read=content["cached_tokens"],
        reasoning_tokens=content["reasoning_tokens"],
    )
    return output


def _model(event: ParsedEvent, parent: str | None, models: dict[str, str]) -> None:
    """回放一次模型尝试，保留用量、错误、图片与完整请求。"""
    content = event.content.model_dump(mode="json")
    model = models.get(MODEL_LINKS.get(event.kind, ""), event.kind)
    images = content.get("images") or []
    if isinstance(images, str):
        import ast

        images = ast.literal_eval(images)
    raw = str(content.get("raw", ""))
    transcript()._event(
        ModelEvent(
            uuid=event.uuid,
            model=model,
            role=event.kind,
            input=[
                ChatMessageUser(
                    content=[
                        ContentText(text=str(content.get("prompt", ""))),
                        *[ContentImage(image=image) for image in images],
                    ]
                )
            ],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
            output=_model_output(event, model),
            error=(str(content["error"]) or "model call failed") if not content["ok"] else None,
            call=ModelCall(request=_payload(event), response={"raw": raw}),
            timestamp=_timestamp(event.started_at),
            completed=_timestamp(event.ended_at),
            working_time=event.ended_at - event.started_at,
            span_id=parent,
            metadata=_metadata(event),
        )
    )


def _tool(event: ParsedEvent, parent: str | None) -> None:
    """回放动作和记忆调用，正文作为完整 JSON 结果。"""
    transcript()._event(
        ToolEvent(
            uuid=event.uuid,
            id=event.uuid,
            function=event.kind,
            arguments={"meta": event.meta.model_dump(mode="json", exclude_unset=True)},
            result=event.content.model_dump_json(exclude_unset=True),
            timestamp=_timestamp(event.started_at),
            completed=_timestamp(event.ended_at),
            working_time=event.ended_at - event.started_at,
            span_id=parent,
            metadata=_metadata(event),
        )
    )


def replay_into_transcript(stream: RunStream, models: dict[str, str]) -> int:
    """每样本只调用一次；追加原时序账并返回事件数，坏载荷直接抛出。

    保留每次完整模型请求，结束后恢复 Inspect 原本的模型 API 日志策略。
    """
    current = transcript()
    previous = current._log_model_api
    current._log_model_api = True
    try:
        return _replay(stream, models)
    finally:
        current._log_model_api = previous


def _replay(stream: RunStream, models: dict[str, str]) -> int:
    """按执行线顺序追加并返回事件数；调用方保证每样本只回放一次。

    未配对的结束只记正文，未收口的 span 在最后一条账的结束时刻关闭。
    失败：坏图片载荷或 Inspect 接口不兼容直接抛出，不静默漏账。
    """
    stack: list[tuple[str, str]] = []
    count = 0
    for event in stream.events:
        parent = stack[-1][1] if stack else None
        if event.kind in SPAN_OPEN or event.kind in SPAN_CLOSE:
            count += _span(event, stack)
            continue
        if event.kind in MODEL_CALL_KINDS:
            _model(event, parent, models)
        elif event.kind in {
            "act_call",
            "press_key",
            "run_macro",
            "get_action_space",
        } or event.kind.startswith(("read_", "write_")):
            _tool(event, parent)
        else:
            _info(event, parent)
        count += 1
    while stack:
        _end_span(stream.events[-1], stack)
        count += 1
    return count
