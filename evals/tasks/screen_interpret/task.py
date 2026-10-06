"""screen_interpret：文本模型读真值解码观测，使用生产读屏规则。"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as
from pydantic import ValidationError

from evals.core.frames import load_frames
from evals.core.judged import judged_accuracy, judged_count
from evals.core.models import interpretation_model
from evals.data.screen_reading.schemas import ScreenAnswer, ScreenSample
from evals.tasks.screen_interpret.schemas import InterpretRecord
from pokemon_agent.direct.prompts import READ_SCREEN


@solver
def interpret_solver() -> Solver:
    """只把标好的观测送给文本模型；解析失败作为被测结果留痕。"""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        prompt = (
            f"{READ_SCREEN}\n\n真值解码观测：\n{state.input_text}\n\n"
            "只回 JSON：overlay、dialog_text、options、cursor、quantity。"
        )
        state.messages = [ChatMessageUser(content=prompt)]
        state = await generate(state)
        record = store_as(InterpretRecord)
        record.raw = state.output.completion
        try:
            record.answer = ScreenAnswer.model_validate_json(
                record.raw.strip().removeprefix("```json").removesuffix("```").strip()
            )
        except ValidationError as exc:
            record.failure = str(exc)
        return state

    return solve


@scorer(metrics=[judged_accuracy(), judged_count()])
def interpret_scorer() -> Scorer:
    """只核标注，模型解析失败判负；未标字段不比较。"""

    async def score(state: TaskState, target: Target) -> Score:
        frame = ScreenSample.model_validate(state.metadata["frame"])
        record = store_as(InterpretRecord)
        if record.answer is None:
            return Score(value="I", explanation=record.failure)
        wanted = frame.label.model_dump(include={"overlay", "dialog_text", "options", "cursor"})
        if frame.label.quantity is not None:
            wanted["quantity"] = frame.label.quantity
        wrong = [key for key, value in wanted.items() if getattr(record.answer, key) != value]
        return Score(value="I" if wrong else "C", explanation=", ".join(wrong))

    return score


@task
def screen_interpret(version: str = "v2", text_model: str | None = None) -> Task:
    """只收带独立真值观测的帧；缺观测时明确报错，防止拿预测当输入。"""
    frames = [f for f in load_frames(version) if f.interpret_input and f.label_checked]
    model = interpretation_model(text_model)
    if not frames:
        raise ValueError("screen_interpret 需要帧的 interpret_input（人工核过的真值解码观测）")
    return Task(
        dataset=[
            Sample(
                id=f.sample_id,
                input=f.interpret_input or "",
                metadata={"frame": f.model_dump(mode="json")},
            )
            for f in frames
        ],
        solver=interpret_solver(),
        scorer=interpret_scorer(),
        model=model,
    )
