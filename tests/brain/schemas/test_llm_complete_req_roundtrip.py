"""`LlmCompleteReq.prompt` 必须真的在字段表里——**一次真机事故的回归钉**。

0915 129 收编 images 时曾把整个 `prompt` 字段连着删掉：Pydantic 对未声明的
字段默认**忽略**，`LlmCompleteReq(prompt=…)` 构造"成功"但 prompt 静默丢失，
直到真机 `provider.complete()` 里 `req.prompt` 才炸 AttributeError——而当时
108 个测试全绿，因为测试用的 FakeProvider 都不摸 `req.prompt`。

所以这里的 FakeProvider **故意像真 provider 一样读 `req.prompt`**：
字段丢了，这两条测试当场红，不用等真机。
"""

from __future__ import annotations

from pokemon_agent.brain import Brain
from pokemon_agent.brain.schemas import LlmCompleteReq, LlmCompleteResp


def test_llm_complete_req_carries_prompt() -> None:
    # Arrange / Act
    req = LlmCompleteReq(prompt="完整 prompt 文本")

    # Assert：字段真的存在且逐字保留（不是被 Pydantic 静默吞掉的未知字段）
    assert "prompt" in LlmCompleteReq.model_fields
    assert req.prompt == "完整 prompt 文本"


def test_brain_choose_roundtrip_reaches_prompt_via_provider() -> None:
    class PromptReadingProvider:
        """像真 provider 一样摸 `req.prompt`——字段丢了这条 assert 就炸。"""

        multimodal = False

        def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
            assert req.prompt == "怎么选", f"prompt 丢了，req 只有 {set(req.model_fields)}"
            return LlmCompleteResp(
                text='{"action":"up"}',
                prompt_tokens=1,
                completion_tokens=1,
            )

    # Arrange
    brain = Brain(decide_llm=PromptReadingProvider(), judge_llm=PromptReadingProvider())

    # Act
    result = brain.choose(prompt="怎么选", keys=["up"])

    # Assert
    assert result.action.describe() == "up"
