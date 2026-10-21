"""严格解析独立评分；格式失败有限纠正，未知和低分都不重试。"""

import json
from collections.abc import Callable
from typing import Generic, TypeVar

from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageUser
from pydantic import BaseModel, Field, ValidationError

from pokemon_agent.config import EVAL_GRADER_FORMAT_ATTEMPTS

from .review_port import ReviewProvider

Review = TypeVar("Review", bound=BaseModel)


class ReviewAttempt(BaseModel):
    """每次原始评分和格式问题；成功也记一条。"""

    raw: str
    error: str = ""


class ReviewResult(BaseModel, Generic[Review]):
    """有效评分或格式耗尽；历史不能因重试覆盖。"""

    review: Review | None = None
    value: float | str | None = None
    attempts: list[ReviewAttempt] = Field(default_factory=list)

    @property
    def raw(self) -> str:
        """最后一次原始文本。"""
        return self.attempts[-1].raw


async def generate_review(
    provider: ReviewProvider,
    messages: list[ChatMessage],
    schema: type[Review],
    evaluate: Callable[[Review], float | str],
    *,
    max_attempts: int = EVAL_GRADER_FORMAT_ATTEMPTS,
) -> ReviewResult[Review]:
    """只修复结构/维度对齐失败；调用方保证正预算，传输错误直接上抛。"""
    assert max_attempts > 0
    conversation = list(messages)
    result = ReviewResult[Review]()
    for _ in range(max_attempts):
        output = await provider.generate(list(conversation))
        attempt = ReviewAttempt(raw=output.completion)
        result.attempts.append(attempt)
        try:
            review = schema.model_validate_json(
                output.completion.strip().removeprefix("```json").removesuffix("```").strip()
            )
            value = evaluate(review)
        except (ValidationError, ValueError) as error:
            attempt.error = str(error)
            conversation += [
                ChatMessageAssistant(content=output.completion),
                ChatMessageUser(content=_correction(schema, attempt.error)),
            ]
        else:
            result.review, result.value = review, value
            return result
    return result


def _correction(schema: type[BaseModel], error: str) -> str:
    """纠错只提供输出契约，不新增评分事实或暗示分数。"""
    return (
        "上一次评分格式未通过严格校验。请只修正格式，仍按原始证据独立评分；"
        "不得因重试而改成高分，不得把此反馈当成现场事实。未知仍可填 null。\n"
        f"校验错误：{error}\n仅返回符合以下 JSON Schema 的 JSON，维度须与原量表完整对应：\n"
        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )
