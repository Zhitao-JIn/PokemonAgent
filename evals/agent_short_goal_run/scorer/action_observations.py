"""Pair actual executions with observed states without crossing another action boundary."""

from pydantic import BaseModel, ConfigDict

from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import ActCallContent, SenseFrameContent

from .stream import RunStream


class ActionObservation(BaseModel):
    """Observed action boundary; missing states remain explicit."""

    model_config = ConfigDict(frozen=True)
    event: ParsedEvent
    before: SenseFrameContent | None
    after: SenseFrameContent | None


def action_observations(stream: RunStream) -> list[ActionObservation]:
    """Pair ordered act_call events with their nearest same-task frames.

    Caller provides one ordered branch. Unobserved tails and task changes never fabricate
    after states; absence is returned as None. Scripts expose endpoints, not internal paths.
    """
    result: list[ActionObservation] = []
    before: ParsedEvent | None = None
    pending: ParsedEvent | None = None
    for event in stream.events:
        if event.kind == "act_call":
            assert isinstance(event.content, ActCallContent)
            if pending is not None:
                result.append(_observation(pending, before, None))
                before = None
            pending = event
        elif event.kind == "sense_frame":
            if pending is not None:
                result.append(_observation(pending, before, event))
                pending = None
            before = event
    if pending is not None:
        result.append(_observation(pending, before, None))
    return result


def _observation(
    action: ParsedEvent, before: ParsedEvent | None, after: ParsedEvent | None
) -> ActionObservation:
    """Require matching task coordinates on both sides of an execution."""

    def state(event: ParsedEvent | None) -> SenseFrameContent | None:
        if event is None or (event.meta.episode_id, event.meta.task_id) != (
            action.meta.episode_id,
            action.meta.task_id,
        ):
            return None
        assert isinstance(event.content, SenseFrameContent)
        return event.content

    return ActionObservation(event=action, before=state(before), after=state(after))
