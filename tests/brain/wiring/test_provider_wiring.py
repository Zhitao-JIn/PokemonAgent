"""四个 provider 槽位对六个方法的可用性矩阵，与「四个都给时各走各的」。

`Brain.__init__` 的装配规则本身就是契约：`decide_llm` 只服务 `choose`，`judge_llm`
只服务 `judge`，`verify_llm` 只服务 `verify` + `summarize`，`plan_llm` 只服务
`plan` + `decompose`；其中只有 `verify_llm` / `plan_llm` 缺省时回退 `judge_llm`，
`decide_llm` / `judge_llm` 永不回退。各方法目录已钉住入口 assert 文案与单项回退，
本文件不重复，只钉这张矩阵与「各走各的、不串线」。只经六个公开方法测，不读私有属性。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _doubles.llm import ScriptedJudge, text_reply

from pokemon_agent.brain.brain import Brain

# 方法名 → (拿一个 `Brain` 调该方法、忽略返回值，该方法的最小合法回复文本)。
CALLS: dict[str, tuple[Callable[[Brain], object], str]] = {
    "choose": (lambda brain: brain.choose(prompt="p", keys=["up"]), '{"action": "up"}'),
    "judge": (lambda brain: brain.judge(prompt="p", goal="g", history=[]), '{"done": true}'),
    "verify": (
        lambda brain: brain.verify(prompt="p", entries=["e"], goal="g", knowledge="k"),
        '[{"index": 0, "positive": true, "why": "w"}]',
    ),
    "summarize": (
        lambda brain: brain.summarize(
            prompt="p", goal="g", history=["h"], success=True, steps=1, max_steps=2
        ),
        '{"summary": "s", "quality_score": 0.5, "quality_rationale": "q"}',
    ),
    "plan": (
        lambda brain: brain.plan(prompt="p", goal_stack=[], history=[], max_push=1),
        "{}",
    ),
    "decompose": (
        lambda brain: brain.decompose(prompt="p", goal="g", context=[], max_tasks=1),
        '{"tasks": [{"goal": "a", "success_criteria": "s", "max_steps": 1}]}',
    ),
}

SLOTS = ("decide_llm", "judge_llm", "verify_llm", "plan_llm")
METHODS = ("choose", "judge", "verify", "summarize", "plan", "decompose")

# 只给某一个槽位、其余缺省时，六个方法里哪些可用（True）、哪些触发入口 AssertionError。
MATRIX: dict[str, dict[str, bool]] = {
    "decide_llm": {
        "choose": True,
        "judge": False,
        "verify": False,
        "summarize": False,
        "plan": False,
        "decompose": False,
    },
    "judge_llm": {
        "choose": False,
        "judge": True,
        "verify": True,
        "summarize": True,
        "plan": True,
        "decompose": True,
    },
    "verify_llm": {
        "choose": False,
        "judge": False,
        "verify": True,
        "summarize": True,
        "plan": False,
        "decompose": False,
    },
    "plan_llm": {
        "choose": False,
        "judge": False,
        "verify": False,
        "summarize": False,
        "plan": True,
        "decompose": True,
    },
}

_MATRIX_CASES = [(slot, method, MATRIX[slot][method]) for slot in SLOTS for method in METHODS]
_MATRIX_IDS = [f"{slot}-{method}" for slot in SLOTS for method in METHODS]


@pytest.mark.parametrize(("slot", "method", "available"), _MATRIX_CASES, ids=_MATRIX_IDS)
def test_a_method_is_available_only_through_the_provider_slots_that_serve_it(
    slot: str, method: str, available: bool
) -> None:
    call, reply_text = CALLS[method]

    provider = ScriptedJudge(text_reply(reply_text))
    brain = Brain(**{slot: provider})

    if available:
        call(brain)
        assert len(provider.requests) == 1
    else:
        with pytest.raises(AssertionError):
            call(brain)


def test_each_method_uses_its_own_provider_when_all_four_are_given() -> None:
    d = ScriptedJudge(text_reply('{"action": "up"}'))
    j = ScriptedJudge(text_reply('{"done": true}'))
    v = ScriptedJudge(
        text_reply('[{"index": 0, "positive": true, "why": "w"}]'),
        text_reply('{"summary": "s", "quality_score": 0.5, "quality_rationale": "q"}'),
    )
    p = ScriptedJudge(
        text_reply("{}"),
        text_reply('{"tasks": [{"goal": "a", "success_criteria": "s", "max_steps": 1}]}'),
    )
    brain = Brain(decide_llm=d, judge_llm=j, verify_llm=v, plan_llm=p)

    brain.choose(prompt="p", keys=["up"])
    brain.judge(prompt="p", goal="g", history=[])
    brain.verify(prompt="p", entries=["e"], goal="g", knowledge="k")
    brain.summarize(prompt="p", goal="g", history=["h"], success=True, steps=1, max_steps=2)
    brain.plan(prompt="p", goal_stack=[], history=[], max_push=1)
    brain.decompose(prompt="p", goal="g", context=[], max_tasks=1)

    assert len(d.requests) == 1
    assert len(j.requests) == 1
    assert len(v.requests) == 2
    assert len(p.requests) == 2
